"""Tests for audit logger and trajectory export."""

from __future__ import annotations

import pytest

from thota_dq.audit.logger import get_decisions, log_decision
from thota_dq.audit.trajectory import export_json, export_sharegpt


@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "test_history.db"


@pytest.mark.asyncio
async def test_log_and_retrieve_decision(tmp_db):
    await log_decision(
        run_id="run-001",
        step="diagnose",
        input_summary="rule: orders_not_null",
        output_summary="EXPLANATION: Null order_id found",
        model="claude-haiku-4-5-20251001",
        input_tokens=120,
        output_tokens=45,
        cost_usd=0.000276,
        duration_ms=310.5,
        db_path=tmp_db,
    )

    decisions = await get_decisions("run-001", tmp_db)
    assert len(decisions) == 1
    d = decisions[0]
    assert d["run_id"] == "run-001"
    assert d["step"] == "diagnose"
    assert d["model"] == "claude-haiku-4-5-20251001"
    assert d["input_tokens"] == 120
    assert d["output_tokens"] == 45
    assert abs(d["cost_usd"] - 0.000276) < 1e-9
    assert abs(d["duration_ms"] - 310.5) < 0.01
    assert "orders_not_null" in d["input_summary"]


@pytest.mark.asyncio
async def test_multiple_decisions_ordered(tmp_db):
    for i in range(3):
        await log_decision(
            run_id="run-002",
            step=f"step_{i}",
            input_summary=f"input {i}",
            output_summary=f"output {i}",
            db_path=tmp_db,
        )

    decisions = await get_decisions("run-002", tmp_db)
    assert len(decisions) == 3
    assert [d["step"] for d in decisions] == ["step_0", "step_1", "step_2"]


@pytest.mark.asyncio
async def test_decisions_isolated_by_run_id(tmp_db):
    await log_decision(run_id="run-A", step="diagnose", db_path=tmp_db)
    await log_decision(run_id="run-B", step="report", db_path=tmp_db)

    a = await get_decisions("run-A", tmp_db)
    b = await get_decisions("run-B", tmp_db)
    assert len(a) == 1 and a[0]["step"] == "diagnose"
    assert len(b) == 1 and b[0]["step"] == "report"


@pytest.mark.asyncio
async def test_get_decisions_missing_db(tmp_path):
    missing = tmp_path / "nonexistent.db"
    result = await get_decisions("run-xyz", missing)
    assert result == []


@pytest.mark.asyncio
async def test_input_summary_truncated(tmp_db):
    long_input = "x" * 5000
    await log_decision(run_id="run-003", step="diagnose", input_summary=long_input, db_path=tmp_db)
    decisions = await get_decisions("run-003", tmp_db)
    assert len(decisions[0]["input_summary"]) <= 2000


@pytest.mark.asyncio
async def test_non_llm_decision_no_model(tmp_db):
    await log_decision(
        run_id="run-004",
        step="report",
        input_summary="rules=5 passed=4 failed=1",
        output_summary="pass_rate=80.0%",
        db_path=tmp_db,
    )
    decisions = await get_decisions("run-004", tmp_db)
    assert decisions[0]["model"] is None


@pytest.mark.asyncio
async def test_export_json(tmp_db):
    await log_decision(run_id="run-005", step="diagnose", input_summary="a", output_summary="b", model="m", db_path=tmp_db)
    result = await export_json("run-005", tmp_db)
    assert isinstance(result, list)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_export_sharegpt_structure(tmp_db):
    await log_decision(run_id="run-006", step="diagnose", input_summary="question", output_summary="answer", model="claude", db_path=tmp_db)
    await log_decision(run_id="run-006", step="report", input_summary="summary", output_summary="done", db_path=tmp_db)

    result = await export_sharegpt("run-006", tmp_db)
    assert result["id"] == "run-006"
    assert "conversations" in result
    assert result["metadata"]["llm_decisions"] == 1
    assert result["metadata"]["total_decisions"] == 2

    # LLM step → human + gpt turns; non-LLM step → system turn
    roles = [c["from"] for c in result["conversations"]]
    assert "human" in roles
    assert "gpt" in roles
    assert "system" in roles


@pytest.mark.asyncio
async def test_export_sharegpt_empty_run(tmp_db):
    result = await export_sharegpt("run-missing", tmp_db)
    assert result["conversations"] == []
    assert result["metadata"]["total_decisions"] == 0
