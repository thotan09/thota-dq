"""SQLite-backed rule version history."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

DB_PATH = Path.home() / ".thota_dq" / "history.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS rule_versions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id      TEXT NOT NULL,
    version      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'draft',
    yaml_content TEXT NOT NULL,
    generated_by TEXT,
    created_at   TEXT NOT NULL,
    UNIQUE(rule_id, version)
)
"""


async def init_db(path: Path | None = None) -> None:
    import thota_dq.memory.rule_versions as _self
    actual_path = path if path is not None else _self.DB_PATH
    actual_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(actual_path) as db:
        await db.execute(_CREATE_TABLE)
        await db.commit()


async def save_rule_version(
    rule_id: str,
    version: str,
    status: str,
    yaml_content: str,
    generated_by: str | None = None,
    path: Path | None = None,
) -> None:
    """Upsert a rule version record."""
    import thota_dq.memory.rule_versions as _self
    actual_path = path if path is not None else _self.DB_PATH
    await init_db(actual_path)
    async with aiosqlite.connect(actual_path) as db:
        await db.execute(
            """INSERT OR REPLACE INTO rule_versions
               (rule_id, version, status, yaml_content, generated_by, created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                rule_id, version, status, yaml_content,
                generated_by,
                datetime.now(UTC).isoformat(),
            ),
        )
        await db.commit()


def get_rule_versions_sync(rule_id: str, path: Path | None = None) -> list[dict]:
    """Return all versions for *rule_id*, newest first."""
    import thota_dq.memory.rule_versions as _self
    actual_path = path if path is not None else _self.DB_PATH
    if not actual_path.exists():
        return []
    conn = sqlite3.connect(actual_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT * FROM rule_versions WHERE rule_id=? ORDER BY created_at DESC",
            (rule_id,),
        )
        return [dict(row) for row in cur.fetchall()]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


async def promote_rule(
    rule_id: str,
    version: str,
    new_status: str,
    path: Path | None = None,
) -> bool:
    """Update the status of a specific rule version. Returns True if found."""
    import thota_dq.memory.rule_versions as _self
    actual_path = path if path is not None else _self.DB_PATH
    await init_db(actual_path)
    async with aiosqlite.connect(actual_path) as db:
        cur = await db.execute(
            "UPDATE rule_versions SET status=? WHERE rule_id=? AND version=?",
            (new_status, rule_id, version),
        )
        await db.commit()
        return cur.rowcount > 0
