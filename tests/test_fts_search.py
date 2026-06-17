"""Tests for FTS5 full-text search over audit decisions."""

from __future__ import annotations

from pathlib import Path

import pytest

from thota_dq.audit.logger import log_decision
from thota_dq.audit.search import rebuild_fts_index, search_decisions

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed(
    run_id: str,
    db_path: Path,
    step: str = "diagnose",
    input_summary: str = "some input",
    output_summary: str = "some output",
    model: str = "claude-haiku-4-5",
) -> None:
    await log_decision(
        run_id=run_id,
        step=step,
        input_summary=input_summary,
        output_summary=output_summary,
        model=model,
        db_path=db_path,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_finds_matching_decisions(tmp_path: Path):
    db = tmp_path / "audit.db"
    await _seed(
        "run-1",
        db,
        input_summary="ETL pipeline ingestion",
        output_summary="Found null values in order_id column",
    )
    await _seed(
        "run-2",
        db,
        input_summary="schema validation",
        output_summary="All checks passed successfully",
    )

    results = await search_decisions("null", db_path=db)
    assert len(results) == 1
    assert results[0]["run_id"] == "run-1"


@pytest.mark.asyncio
async def test_search_empty_db_returns_empty(tmp_path: Path):
    db = tmp_path / "does_not_exist.db"
    results = await search_decisions("anything", db_path=db)
    assert results == []


@pytest.mark.asyncio
async def test_search_with_run_id_filter(tmp_path: Path):
    db = tmp_path / "audit.db"
    await _seed("run-A", db, output_summary="ETL bug caused missing rows")
    await _seed("run-B", db, output_summary="ETL bug found in ingestion step")

    # Both match "ETL", but filter to run-A only
    results = await search_decisions("ETL", db_path=db, run_id="run-A")
    assert len(results) == 1
    assert results[0]["run_id"] == "run-A"


@pytest.mark.asyncio
async def test_search_no_match_returns_empty(tmp_path: Path):
    db = tmp_path / "audit.db"
    await _seed("run-1", db, output_summary="Everything looks fine with the data")

    results = await search_decisions("xyzzy_nonexistent_term", db_path=db)
    assert results == []


@pytest.mark.asyncio
async def test_rebuild_fts_index(tmp_path: Path):
    db = tmp_path / "audit.db"

    # Seed rows BEFORE FTS table exists (triggers not yet created)
    # We do this by inserting directly through log_decision which doesn't create FTS
    await _seed("run-1", db, output_summary="diagnosis complete")
    await _seed("run-2", db, output_summary="root cause identified")

    # rebuild should index existing rows
    count = await rebuild_fts_index(db_path=db)
    assert count >= 2


@pytest.mark.asyncio
async def test_rebuild_fts_on_nonexistent_db_returns_zero(tmp_path: Path):
    db = tmp_path / "nonexistent.db"
    count = await rebuild_fts_index(db_path=db)
    assert count == 0


@pytest.mark.asyncio
async def test_search_limit_respected(tmp_path: Path):
    db = tmp_path / "audit.db"
    # Insert 5 rows all matching the same term
    for i in range(5):
        await _seed(f"run-{i}", db, output_summary=f"repeated keyword alpha occurrence {i}")

    results = await search_decisions("alpha", db_path=db, limit=3)
    assert len(results) <= 3


@pytest.mark.asyncio
async def test_search_returns_full_decision_fields(tmp_path: Path):
    db = tmp_path / "audit.db"
    await _seed(
        "run-xyz",
        db,
        step="rca",
        input_summary="lineage data for orders table",
        output_summary="root cause is upstream ETL failure",
        model="claude-sonnet-4-6",
    )

    results = await search_decisions("upstream", db_path=db)
    assert len(results) == 1
    r = results[0]
    assert r["run_id"] == "run-xyz"
    assert r["step"] == "rca"
    assert r["model"] == "claude-sonnet-4-6"
    assert "upstream" in r["output_summary"]


@pytest.mark.asyncio
async def test_search_matches_input_summary(tmp_path: Path):
    db = tmp_path / "audit.db"
    await _seed(
        "run-inp",
        db,
        input_summary="checking freshness constraint violation",
        output_summary="no issues found",
    )

    results = await search_decisions("freshness", db_path=db)
    assert len(results) == 1
    assert results[0]["run_id"] == "run-inp"


@pytest.mark.asyncio
async def test_search_run_id_filter_no_match(tmp_path: Path):
    db = tmp_path / "audit.db"
    await _seed("run-A", db, output_summary="data anomaly detected in pipeline")

    # run_id filter for a different run — should return empty
    results = await search_decisions("anomaly", db_path=db, run_id="run-B")
    assert results == []
