"""Full-text search over audit decisions using SQLite FTS5."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from ..memory.store import DB_PATH, _connect


async def _ensure_fts_table(db: aiosqlite.Connection) -> None:
    """Create FTS5 virtual table and keep it in sync via triggers."""
    # Regular (non-content) FTS5 table — owns its own index
    await db.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts
        USING fts5(run_id, step, input_summary, output_summary)
        """
    )
    # Sentinel so we only backfill existing rows once per database
    await db.execute("CREATE TABLE IF NOT EXISTS _fts_seeded (v INTEGER PRIMARY KEY)")
    await db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS decisions_ai
        AFTER INSERT ON decisions BEGIN
            INSERT INTO decisions_fts(rowid, run_id, step, input_summary, output_summary)
            VALUES (new.id, new.run_id, new.step, new.input_summary, new.output_summary);
        END
        """
    )
    await db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS decisions_ad
        AFTER DELETE ON decisions BEGIN
            DELETE FROM decisions_fts WHERE rowid = old.id;
        END
        """
    )
    # Backfill rows that existed before the FTS table was created.
    # INSERT OR IGNORE is the atomic gate — only the connection that actually
    # inserts the sentinel row (changes() = 1) performs the backfill, preventing
    # duplicate FTS entries when multiple coroutines call this concurrently.
    await db.execute("INSERT OR IGNORE INTO _fts_seeded VALUES (1)")
    cursor = await db.execute("SELECT changes()")
    row = await cursor.fetchone()
    if row and row[0] == 1:
        await db.execute(
            """
            INSERT INTO decisions_fts(rowid, run_id, step, input_summary, output_summary)
            SELECT id, run_id, step, input_summary, output_summary FROM decisions
            """
        )
        await db.commit()


async def rebuild_fts_index(db_path: Path = DB_PATH) -> int:
    """Rebuild the FTS index from the decisions table. Returns number of rows indexed."""
    if not db_path.exists():
        return 0
    async with _connect(db_path) as db:
        await _ensure_fts_table(db)
        # Full rebuild: clear and repopulate from decisions
        await db.execute("DELETE FROM decisions_fts")
        await db.execute(
            """
            INSERT INTO decisions_fts(rowid, run_id, step, input_summary, output_summary)
            SELECT id, run_id, step, input_summary, output_summary FROM decisions
            """
        )
        await db.commit()
        cursor = await db.execute("SELECT COUNT(*) FROM decisions_fts")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def search_decisions(
    query: str,
    *,
    db_path: Path = DB_PATH,
    limit: int = 20,
    run_id: str | None = None,
) -> list[dict]:
    """Full-text search over decision audit trail.

    Args:
        query: FTS5 match expression (e.g. "ETL bug", "root cause nulls")
        db_path: Path to audit SQLite database
        limit: Maximum number of results
        run_id: If set, restrict search to a specific run

    Returns:
        List of decision dicts matching the query, ordered by rank.
    """
    if not db_path.exists():
        return []
    async with _connect(db_path) as db:
        await _ensure_fts_table(db)
        db.row_factory = aiosqlite.Row
        if run_id:
            cursor = await db.execute(
                """
                SELECT d.* FROM decisions d
                JOIN decisions_fts f ON d.id = f.rowid
                WHERE decisions_fts MATCH ? AND d.run_id = ?
                ORDER BY rank LIMIT ?
                """,
                (query, run_id, limit),
            )
        else:
            cursor = await db.execute(
                """
                SELECT d.* FROM decisions d
                JOIN decisions_fts f ON d.id = f.rowid
                WHERE decisions_fts MATCH ?
                ORDER BY rank LIMIT ?
                """,
                (query, limit),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
