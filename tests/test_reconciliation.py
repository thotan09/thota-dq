"""Tests for reconciliation rule types and the reconcile node."""

from __future__ import annotations

import pytest

from thota_dq.adapters.warehouse.duckdb import DuckDBAdapter
from thota_dq.core.nodes.reconcile import reconcile_node
from thota_dq.rules.schema import DataQualityRule, RuleResult


def _make_rule(rule_id: str, rule_type: str, table: str, source_table: str,
               columns: list[str] | None = None, tolerance_pct: float = 0.0) -> DataQualityRule:
    return DataQualityRule.model_validate({
        "apiVersion": "thota_dq.dev/v1",
        "kind": "DataQualityRule",
        "metadata": {"id": rule_id, "severity": "high"},
        "scope": {"table": table, "columns": columns or []},
        "logic": {"type": rule_type, "source_table": source_table, "tolerance_pct": tolerance_pct},
    })


def _seeded_adapter() -> DuckDBAdapter:
    adapter = DuckDBAdapter()
    conn = adapter._get_conn()
    conn.execute("CREATE TABLE src_orders (order_id INT, revenue FLOAT)")
    conn.execute("CREATE TABLE tgt_orders (order_id INT, revenue FLOAT)")
    conn.execute("INSERT INTO src_orders VALUES (1, 100.0), (2, 200.0), (3, 300.0)")
    conn.execute("INSERT INTO tgt_orders VALUES (1, 100.0), (2, 200.0), (3, 300.0)")
    return adapter


# --- reconcile_row_count ---

@pytest.mark.asyncio
async def test_reconcile_row_count_pass():
    adapter = _seeded_adapter()
    rule = _make_rule("r1", "reconcile_row_count", "tgt_orders", "src_orders")
    result = await adapter.execute_rule(rule)
    assert result.passed
    assert result.row_count_checked == 3


@pytest.mark.asyncio
async def test_reconcile_row_count_fail():
    adapter = _seeded_adapter()
    adapter._get_conn().execute("INSERT INTO tgt_orders VALUES (4, 400.0)")
    rule = _make_rule("r1", "reconcile_row_count", "tgt_orders", "src_orders")
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 1
    assert result.failure_sample[0]["source_rows"] == 3
    assert result.failure_sample[0]["target_rows"] == 4


@pytest.mark.asyncio
async def test_reconcile_row_count_within_tolerance():
    adapter = _seeded_adapter()
    adapter._get_conn().execute("INSERT INTO tgt_orders VALUES (4, 400.0)")
    # 1 extra row out of 3 source = 33% deviation; allow 50%
    rule = _make_rule("r1", "reconcile_row_count", "tgt_orders", "src_orders", tolerance_pct=50.0)
    result = await adapter.execute_rule(rule)
    assert result.passed


# --- reconcile_column_sum ---

@pytest.mark.asyncio
async def test_reconcile_column_sum_pass():
    adapter = _seeded_adapter()
    rule = _make_rule("r2", "reconcile_column_sum", "tgt_orders", "src_orders", columns=["revenue"])
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_reconcile_column_sum_fail():
    adapter = _seeded_adapter()
    adapter._get_conn().execute("UPDATE tgt_orders SET revenue = 999.0 WHERE order_id = 1")
    rule = _make_rule("r2", "reconcile_column_sum", "tgt_orders", "src_orders", columns=["revenue"])
    result = await adapter.execute_rule(rule)
    assert not result.passed
    sample = result.failure_sample[0]
    assert sample["source_sum"] == pytest.approx(600.0)
    assert sample["target_sum"] == pytest.approx(1499.0)


@pytest.mark.asyncio
async def test_reconcile_column_sum_within_tolerance():
    adapter = _seeded_adapter()
    adapter._get_conn().execute("UPDATE tgt_orders SET revenue = 101.0 WHERE order_id = 1")
    # 1/600 ≈ 0.17% deviation; allow 1%
    rule = _make_rule("r2", "reconcile_column_sum", "tgt_orders", "src_orders",
                      columns=["revenue"], tolerance_pct=1.0)
    result = await adapter.execute_rule(rule)
    assert result.passed


# --- reconcile_key_match ---

@pytest.mark.asyncio
async def test_reconcile_key_match_pass():
    adapter = _seeded_adapter()
    rule = _make_rule("r3", "reconcile_key_match", "tgt_orders", "src_orders", columns=["order_id"])
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_reconcile_key_match_missing_in_target():
    adapter = _seeded_adapter()
    adapter._get_conn().execute("DELETE FROM tgt_orders WHERE order_id = 2")
    rule = _make_rule("r3", "reconcile_key_match", "tgt_orders", "src_orders", columns=["order_id"])
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.failure_sample[0]["missing_in_target"] == 1
    assert result.failure_sample[0]["missing_in_source"] == 0


@pytest.mark.asyncio
async def test_reconcile_key_match_extra_in_target():
    adapter = _seeded_adapter()
    adapter._get_conn().execute("INSERT INTO tgt_orders VALUES (99, 0.0)")
    rule = _make_rule("r3", "reconcile_key_match", "tgt_orders", "src_orders", columns=["order_id"])
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.failure_sample[0]["missing_in_source"] == 1


# --- reconcile_node ---

def _make_state(rules, results):
    return {
        "run_id": "test-run",
        "rules": rules,
        "rule_results": results,
        "reconciliation_summary": {},
    }


@pytest.mark.asyncio
async def test_reconcile_node_no_recon_rules():
    rule = DataQualityRule.model_validate({
        "apiVersion": "thota_dq.dev/v1",
        "kind": "DataQualityRule",
        "metadata": {"id": "plain_rule"},
        "scope": {"table": "t"},
        "logic": {"type": "not_null"},
    })
    result = RuleResult(rule_id="plain_rule", passed=True)
    state = _make_state([rule], [result])
    out = await reconcile_node(state)
    assert out["reconciliation_summary"] == {}


@pytest.mark.asyncio
async def test_reconcile_node_summarises_pairs():
    rule = _make_rule("rc1", "reconcile_row_count", "tgt_orders", "src_orders")
    result = RuleResult(
        rule_id="rc1", passed=False,
        row_count_checked=3, row_count_failed=1,
        failure_sample=[{"source_rows": 3, "target_rows": 4}],
    )
    state = _make_state([rule], [result])
    out = await reconcile_node(state)
    summary = out["reconciliation_summary"]
    assert summary["pairs_checked"] == 1
    assert summary["pairs_failed"] == 1
    assert summary["pairs_passed"] == 0
    detail = summary["details"][0]
    assert detail["source_table"] == "src_orders"
    assert detail["target_table"] == "tgt_orders"
    assert detail["passed"] is False


@pytest.mark.asyncio
async def test_reconcile_node_multiple_checks_same_pair():
    rule1 = _make_rule("rc1", "reconcile_row_count", "tgt_orders", "src_orders")
    rule2 = _make_rule("rc2", "reconcile_column_sum", "tgt_orders", "src_orders", columns=["revenue"])
    results = [
        RuleResult(rule_id="rc1", passed=True, row_count_checked=3),
        RuleResult(rule_id="rc2", passed=True, row_count_checked=3),
    ]
    state = _make_state([rule1, rule2], results)
    out = await reconcile_node(state)
    summary = out["reconciliation_summary"]
    assert summary["pairs_checked"] == 1
    assert summary["pairs_passed"] == 1
    assert len(summary["details"][0]["checks"]) == 2


@pytest.mark.asyncio
async def test_reconcile_node_pair_fails_if_any_check_fails():
    rule1 = _make_rule("rc1", "reconcile_row_count", "tgt_orders", "src_orders")
    rule2 = _make_rule("rc2", "reconcile_column_sum", "tgt_orders", "src_orders", columns=["revenue"])
    results = [
        RuleResult(rule_id="rc1", passed=True, row_count_checked=3),
        RuleResult(rule_id="rc2", passed=False, row_count_checked=3,
                   failure_sample=[{"source_sum": 600.0, "target_sum": 700.0}]),
    ]
    state = _make_state([rule1, rule2], results)
    out = await reconcile_node(state)
    assert out["reconciliation_summary"]["pairs_failed"] == 1
