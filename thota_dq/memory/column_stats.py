"""Column-level statistical history — used by learned_threshold rules."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from .store import DB_PATH

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS column_stats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    table_name  TEXT NOT NULL,
    column_name TEXT NOT NULL,
    row_count   INTEGER,
    mean_val    REAL,
    stddev_val  REAL,
    min_val     REAL,
    max_val     REAL
)
"""


async def init_column_stats(path: Path = DB_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as db:
        await db.execute(_CREATE_TABLE)
        await db.commit()


async def save_column_stats(
    run_id: str,
    table: str,
    column: str,
    row_count: int,
    mean_val: float,
    stddev_val: float,
    min_val: float,
    max_val: float,
    path: Path = DB_PATH,
) -> None:
    """Persist per-column stats for a completed run."""
    await init_column_stats(path)
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "INSERT INTO column_stats "
            "(run_id, timestamp, table_name, column_name, row_count, mean_val, stddev_val, min_val, max_val) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                datetime.now(UTC).isoformat(),
                table,
                column,
                row_count,
                mean_val,
                stddev_val,
                min_val,
                max_val,
            ),
        )
        await db.commit()


def load_column_history_sync(
    table: str,
    column: str,
    limit: int = 90,
    path: Path | None = None,
) -> list[float]:
    """Synchronous load of historical mean_vals (newest first, up to *limit* rows).

    Designed for use inside thread executors where async is unavailable.
    Returns an empty list when no history exists yet.
    """
    import thota_dq.memory.column_stats as _self
    actual_path = path if path is not None else _self.DB_PATH
    path = actual_path  # rebind for the rest of the function
    if not path.exists():
        return []
    try:
        con = sqlite3.connect(path)
        try:
            cur = con.execute(
                "SELECT mean_val FROM column_stats "
                "WHERE table_name=? AND column_name=? "
                "ORDER BY timestamp DESC LIMIT ?",
                (table, column, limit),
            )
            return [row[0] for row in cur.fetchall() if row[0] is not None]
        except sqlite3.OperationalError:
            # Table not yet created
            return []
        finally:
            con.close()
    except Exception:
        return []
