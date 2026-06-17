"""Audit logger — persists every agent decision to SQLite."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from ..memory.store import DB_PATH, _connect, _schema_initialized


async def _ensure_decisions_table(db: aiosqlite.Connection, db_path: Path) -> None:
    """Create decisions table and index once per process per DB path."""
    if db_path in _schema_initialized:
        return
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS decisions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id       TEXT    NOT NULL,
            timestamp    TEXT    NOT NULL,
            step         TEXT    NOT NULL,
            input_summary  TEXT,
            output_summary TEXT,
            model        TEXT,
            input_tokens  INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cost_usd     REAL    DEFAULT 0.0,
            duration_ms  REAL    DEFAULT 0.0
        )
        """
    )
    await db.execute("CREATE INDEX IF NOT EXISTS idx_decisions_run_id ON decisions(run_id)")
    await db.commit()
    _schema_initialized.add(db_path)


async def log_decision(
    *,
    run_id: str,
    step: str,
    input_summary: str = "",
    output_summary: str = "",
    model: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    duration_ms: float = 0.0,
    db_path: Path = DB_PATH,
) -> None:
    """Persist one agent decision row. Creates the table on first call."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with _connect(db_path) as db:
        await _ensure_decisions_table(db, db_path)
        await db.execute(
            """
            INSERT INTO decisions
              (run_id, timestamp, step, input_summary, output_summary,
               model, input_tokens, output_tokens, cost_usd, duration_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                datetime.now(UTC).isoformat(),
                step,
                input_summary[:2000],  # guard against huge prompts
                output_summary[:2000],
                model,
                input_tokens,
                output_tokens,
                cost_usd,
                duration_ms,
            ),
        )
        await db.commit()


async def get_decisions(run_id: str, db_path: Path = DB_PATH) -> list[dict]:
    """Return all decisions for a given run_id, ordered by insertion time."""
    if not db_path.exists():
        return []
    async with _connect(db_path) as db:
        await _ensure_decisions_table(db, db_path)
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM decisions WHERE run_id = ? ORDER BY id",
            (run_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
