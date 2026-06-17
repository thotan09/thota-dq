"""Tests for the parallel_table_node and the full agent with parallel execution."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from thota_dq.core.nodes.parallel import _run_table_pipeline, parallel_table_node
from thota_dq.rules.schema import DataQualityRule, RuleResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rule(rule_id: str, table: str, severity: str = "high") -> DataQualityRule:
    return DataQualityRule.model_validate({
        "apiVersion": "thota_dq.dev/v1",
        "kind": "DataQualityRule",
        "metadata": {"id": rule_id, "severity": severity},
        "scope": {"table": table, "columns": []},
        "logic": {"type": "row_count", "threshold": 1},
    })


def _make_pass_result(rule_id: str) -> RuleResult:
    return RuleResult(rule_id=rule_id, passed=True, row_count_checked=100)


def _make_fail_result(rule_id: str, failed: int = 10) -> RuleResult:
    return RuleResult(
        rule_id=rule_id, passed=False,
        row_count_checked=100, row_count_failed=failed,
    )


def _make_state(rules: list[DataQualityRule]) -> dict:
    return {
        "run_id": "test-run",
        "triggered_by": "test",
        "scope": {"tables": [], "rule_ids": None},
        "rules": rules,
        "plan": [r.metadata.id for r in rules],
        "rule_results": [],
        "failures": [],
        "classified_failures": {},
        "reconciliation_summary": {},
        "diagnoses": [],
        "rca_results": [],
        "remediation_proposals": [],
        "report": {},
        "trajectory": [],
        "cost_total_usd": 0.0,
        "tokens_total": 0,
        "error": None,
    }


def _make_warehouse(*results: RuleResult) -> MagicMock:
    wh = MagicMock()
    wh.execute_rule = AsyncMock(side_effect=list(results))
    return wh


# ---------------------------------------------------------------------------
# _run_table_pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_table_pipeline_all_pass_no_llm():
    rule = _make_rule("r1", "orders")
    wh = _make_warehouse(_make_pass_result("r1"))
    result = await _run_table_pipeline("orders", [rule], wh, None, {}, "run-1")
    assert len(result["results"]) == 1
    assert result["failures"] == []
    assert result["diagnoses"] == []
    assert result["rca_results"] == []


@pytest.mark.asyncio
async def test_run_table_pipeline_failure_no_llm():
    rule = _make_rule("r1", "orders")
    wh = _make_warehouse(_make_fail_result("r1", failed=20))
    result = await _run_table_pipeline("orders", [rule], wh, None, {}, "run-1")
    assert len(result["failures"]) == 1
    assert result["failures"][0].rule.metadata.id == "r1"
    assert len(result["triaged"]) == 1
    # heuristic triage: row_count with 20% failure → keep declared severity
    assert result["triaged"][0][1] == "high"
    assert result["diagnoses"] == []  # no LLM


@pytest.mark.asyncio
async def test_run_table_pipeline_multiple_rules():
    rules = [_make_rule(f"r{i}", "orders") for i in range(3)]
    results = [_make_pass_result(f"r{i}") for i in range(3)]
    wh = _make_warehouse(*results)
    out = await _run_table_pipeline("orders", rules, wh, None, {}, "run-1")
    assert len(out["results"]) == 3
    assert out["failures"] == []


# ---------------------------------------------------------------------------
# parallel_table_node — no LLM
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parallel_table_node_no_llm_all_pass():
    rules = [_make_rule("r1", "orders"), _make_rule("r2", "customers")]
    wh = MagicMock()
    wh.execute_rule = AsyncMock(side_effect=[
        _make_pass_result("r1"), _make_pass_result("r2")
    ])
    state = _make_state(rules)
    out = await parallel_table_node(state, wh, None, {})
    assert len(out["rule_results"]) == 2
    assert out["failures"] == []
    assert out["classified_failures"] == {}


@pytest.mark.asyncio
async def test_parallel_table_node_two_tables_fan_out():
    """Rules for two tables must both execute and appear in results."""
    rules = [
        _make_rule("orders_r1", "orders"),
        _make_rule("orders_r2", "orders"),
        _make_rule("customers_r1", "customers"),
    ]
    wh = MagicMock()
    wh.execute_rule = AsyncMock(side_effect=[
        _make_pass_result("orders_r1"),
        _make_fail_result("orders_r2", 5),
        _make_pass_result("customers_r1"),
    ])
    state = _make_state(rules)
    out = await parallel_table_node(state, wh, None, {})
    assert len(out["rule_results"]) == 3
    assert len(out["failures"]) == 1
    assert out["failures"][0].rule.metadata.id == "orders_r2"


@pytest.mark.asyncio
async def test_parallel_table_node_failures_classified():
    rules = [_make_rule("r1", "orders", severity="critical")]
    wh = _make_warehouse(_make_fail_result("r1", failed=90))
    state = _make_state(rules)
    out = await parallel_table_node(state, wh, None, {})
    assert "critical" in out["classified_failures"]


@pytest.mark.asyncio
async def test_parallel_table_node_populates_diagnoses_with_llm():
    rule = _make_rule("r1", "orders")
    wh = _make_warehouse(_make_fail_result("r1", failed=10))
    state = _make_state([rule])

    llm = MagicMock()
    llm.complete = AsyncMock(return_value=(
        "EXPLANATION: Test\nLIKELY_CAUSE: ETL\nSUGGESTED_ACTION: Re-run",
        100, 50,
    ))

    with patch("thota_dq.core.nodes.classify._triage_one",
               new=AsyncMock(return_value=(MagicMock(), "high"))), \
         patch("thota_dq.core.nodes.rca.log_decision", new=AsyncMock()), \
         patch("thota_dq.core.nodes.diagnose.log_decision", new=AsyncMock()), \
         patch("thota_dq.core.nodes.classify.log_decision", new=AsyncMock()):
        out = await parallel_table_node(state, wh, llm, {})

    assert len(out["diagnoses"]) == 1
    assert out["diagnoses"][0]["failure_id"] == "r1"


@pytest.mark.asyncio
async def test_parallel_table_node_cost_accumulated():
    rules = [_make_rule("r1", "orders")]
    wh = _make_warehouse(_make_fail_result("r1"))
    state = _make_state(rules)
    state["cost_total_usd"] = 0.001  # pre-existing cost

    llm = MagicMock()
    llm.complete = AsyncMock(return_value=("EXPLANATION: x\nLIKELY_CAUSE: y\nSUGGESTED_ACTION: z", 200, 100))

    with patch("thota_dq.core.nodes.classify._triage_one",
               new=AsyncMock(return_value=(MagicMock(), "high"))), \
         patch("thota_dq.core.nodes.rca.log_decision", new=AsyncMock()), \
         patch("thota_dq.core.nodes.diagnose.log_decision", new=AsyncMock()), \
         patch("thota_dq.core.nodes.classify.log_decision", new=AsyncMock()):
        out = await parallel_table_node(state, wh, llm, {})

    assert out["cost_total_usd"] > 0.001  # cost was added


@pytest.mark.asyncio
async def test_parallel_table_node_tokens_accumulated():
    rules = [_make_rule("r1", "orders")]
    wh = _make_warehouse(_make_fail_result("r1"))
    state = _make_state(rules)
    state["tokens_total"] = 0

    llm = MagicMock()
    llm.complete = AsyncMock(return_value=("EXPLANATION: x\nLIKELY_CAUSE: y\nSUGGESTED_ACTION: z", 150, 75))

    with patch("thota_dq.core.nodes.classify._triage_one",
               new=AsyncMock(return_value=(MagicMock(), "high"))), \
         patch("thota_dq.core.nodes.rca.log_decision", new=AsyncMock()), \
         patch("thota_dq.core.nodes.diagnose.log_decision", new=AsyncMock()), \
         patch("thota_dq.core.nodes.classify.log_decision", new=AsyncMock()):
        out = await parallel_table_node(state, wh, llm, {})

    assert out["tokens_total"] > 0


# ---------------------------------------------------------------------------
# Full agent integration (no LLM)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_parallel_pipeline_end_to_end():
    """Full agent.run() with parallel pipeline — no LLM, DuckDB in-memory."""
    from thota_dq.adapters.warehouse.duckdb import DuckDBAdapter
    from thota_dq.core.agent import AegisAgent

    adapter = DuckDBAdapter(":memory:")

    import asyncio as _asyncio
    loop = _asyncio.get_running_loop()

    def _setup():
        conn = adapter._get_conn()
        conn.execute("CREATE TABLE orders (id INT, rev FLOAT)")
        conn.execute("INSERT INTO orders VALUES (1, 100.0), (NULL, 50.0)")
        conn.execute("CREATE TABLE customers (cid INT)")
        conn.execute("INSERT INTO customers VALUES (1), (2), (3)")

    await loop.run_in_executor(adapter._executor, _setup)

    rules = [
        DataQualityRule.model_validate({
            "apiVersion": "thota_dq.dev/v1", "kind": "DataQualityRule",
            "metadata": {"id": "orders_not_null", "severity": "critical"},
            "scope": {"table": "orders", "columns": ["id"]},
            "logic": {"type": "not_null"},
        }),
        DataQualityRule.model_validate({
            "apiVersion": "thota_dq.dev/v1", "kind": "DataQualityRule",
            "metadata": {"id": "customers_count", "severity": "high"},
            "scope": {"table": "customers"},
            "logic": {"type": "row_count", "threshold": 2},
        }),
    ]

    agent = AegisAgent(warehouse_adapter=adapter, llm_adapter=None)
    final = await agent.run(rules, triggered_by="test")

    assert len(final["rule_results"]) == 2
    assert any(r.rule_id == "orders_not_null" and not r.passed for r in final["rule_results"])
    assert any(r.rule_id == "customers_count" and r.passed for r in final["rule_results"])
    assert final["report"]["summary"]["total_rules"] == 2
