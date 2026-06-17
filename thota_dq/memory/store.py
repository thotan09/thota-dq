"""SQLite-backed run history store using aiosqlite."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

DB_PATH = Path.home() / ".thota_dq" / "history.db"

# Per-process cache: tracks which DB paths have had their schema initialized.
# Eliminates redundant DDL on every log_decision() call under parallel runs.
_schema_initialized: set[Path] = set()


@asynccontextmanager
async def _connect(path: Path) -> AsyncGenerator[aiosqlite.Connection, None]:
    """Open a WAL-mode connection with a busy timeout to handle concurrent writers."""
    async with aiosqlite.connect(path, timeout=30) as db:
        try:
            await db.execute("PRAGMA journal_mode=WAL")
        except Exception:
            # Another concurrent writer already set WAL mode; the file header
            # stores the mode so this connection will use WAL regardless.
            pass
        await db.execute("PRAGMA synchronous=NORMAL")
        yield db


async def _ensure_schema(db: aiosqlite.Connection, path: Path) -> None:
    """Create all tables once per process. Safe to call concurrently — DDL is idempotent."""
    if path in _schema_initialized:
        return
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id       TEXT PRIMARY KEY,
            timestamp    TEXT NOT NULL,
            triggered_by TEXT,
            total_rules  INTEGER,
            passed       INTEGER,
            failed       INTEGER,
            cost_usd     REAL,
            report_json  TEXT
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS decisions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id         TEXT    NOT NULL,
            timestamp      TEXT    NOT NULL,
            step           TEXT    NOT NULL,
            input_summary  TEXT,
            output_summary TEXT,
            model          TEXT,
            input_tokens   INTEGER DEFAULT 0,
            output_tokens  INTEGER DEFAULT 0,
            cost_usd       REAL    DEFAULT 0.0,
            duration_ms    REAL    DEFAULT 0.0
        )
        """
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_decisions_run_id ON decisions(run_id)"
    )
    await db.commit()
    _schema_initialized.add(path)


async def init_db(path: Path = DB_PATH) -> None:
    """Public API: ensure the history database and schema exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    async with _connect(path) as db:
        await _ensure_schema(db, path)


async def save_run(report: dict, path: Path = DB_PATH) -> None:
    """Persist a completed run report to the history database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    s = report.get("summary", {})
    async with _connect(path) as db:
        await _ensure_schema(db, path)
        await db.execute(
            "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?)",
            (
                report["run_id"],
                report.get("timestamp", datetime.now(UTC).isoformat()),
                report.get("triggered_by", "unknown"),
                s.get("total_rules", 0),
                s.get("passed", 0),
                s.get("failed", 0),
                report.get("cost_usd", 0.0),
                json.dumps(report),
            ),
        )
        await db.commit()
