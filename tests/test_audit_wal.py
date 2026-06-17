"""Tests for audit DB WAL mode and concurrent write safety."""

from __future__ import annotations

import asyncio

import pytest

from thota_dq.audit.logger import get_decisions, log_decision
from thota_dq.memory.store import _connect, save_run


@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "test_wal.db"


@pytest.mark.asyncio
async def test_wal_mode_enabled(tmp_db):
    """Database should be opened in WAL journal mode."""
    async with _connect(tmp_db) as db:
        cursor = await db.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()
    assert row[0] == "wal"


@pytest.mark.asyncio
async def test_concurrent_log_decisions_no_race(tmp_db):
    """Multiple concurrent writers should all succeed without SQLITE_BUSY errors."""
    n = 20
    await asyncio.gather(
        *[
            log_decision(
                run_id="run-concurrent",
                step=f"step_{i}",
                input_summary=f"input {i}",
                output_summary=f"output {i}",
                db_path=tmp_db,
            )
            for i in range(n)
        ]
    )
    decisions = await get_decisions("run-concurrent", tmp_db)
    assert len(decisions) == n


@pytest.mark.asyncio
async def test_concurrent_save_runs_no_race(tmp_db):
    """Concurrent save_run calls should not raise."""
    reports = [
        {
            "run_id": f"run-{i}",
            "timestamp": "2026-05-14T00:00:00+00:00",
            "triggered_by": "test",
            "summary": {"total_rules": 5, "passed": 4, "failed": 1},
            "cost_usd": 0.001 * i,
        }
        for i in range(10)
    ]
    await asyncio.gather(*[save_run(r, tmp_db) for r in reports])

    async with _connect(tmp_db) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM runs")
        row = await cursor.fetchone()
    assert row[0] == 10


@pytest.mark.asyncio
async def test_decisions_survive_concurrent_mixed_ops(tmp_db):
    """Interleaved reads and writes should return consistent results."""
    # Pre-initialize so WAL mode is already set before concurrent access
    await log_decision(run_id="_init", step="_init", db_path=tmp_db)

    async def _write(i: int):
        await log_decision(
            run_id="run-mix",
            step=f"step_{i}",
            db_path=tmp_db,
        )

    async def _read():
        return await get_decisions("run-mix", tmp_db)

    # Interleave 5 writes and 5 reads
    tasks = []
    for i in range(5):
        tasks.append(_write(i))
        tasks.append(_read())
    await asyncio.gather(*tasks)

    # All writes must have landed
    final = await get_decisions("run-mix", tmp_db)
    assert len(final) == 5
