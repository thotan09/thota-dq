"""Tests for the RCA node and OpenLineage loader."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from thota_dq.core.lineage.openlineage import (
    LineageGraph,
    lineage_from_hints,
    load_lineage,
    upstream_chain,
)
from thota_dq.core.nodes.rca import rca_node
from thota_dq.rules.schema import DataQualityRule, RuleFailure, RuleResult

# --- OpenLineage loader ---

def _ol_event(inputs: list[str], outputs: list[str]) -> dict:
    return {
        "eventType": "COMPLETE",
        "inputs": [{"namespace": "db", "name": n} for n in inputs],
        "outputs": [{"namespace": "db", "name": n} for n in outputs],
    }


def test_load_lineage_single_event(tmp_path: Path):
    event = _ol_event(["raw_orders"], ["stg_orders"])
    p = tmp_path / "lineage.json"
    p.write_text(json.dumps(event))
    graph = load_lineage(p)
    assert "db.stg_orders" in graph
    assert "db.raw_orders" in graph["db.stg_orders"]


def test_load_lineage_list_of_events(tmp_path: Path):
    events = [
        _ol_event(["raw_orders"], ["stg_orders"]),
        _ol_event(["stg_orders"], ["fct_orders"]),
    ]
    p = tmp_path / "lineage.json"
    p.write_text(json.dumps(events))
    graph = load_lineage(p)
    assert "db.stg_orders" in graph["db.fct_orders"]
    assert "db.raw_orders" in graph["db.stg_orders"]


def test_load_lineage_deduplicates_upstreams(tmp_path: Path):
    events = [
        _ol_event(["raw_orders"], ["stg_orders"]),
        _ol_event(["raw_orders"], ["stg_orders"]),
    ]
    p = tmp_path / "lineage.json"
    p.write_text(json.dumps(events))
    graph = load_lineage(p)
    assert graph["db.stg_orders"].count("db.raw_orders") == 1


def test_load_lineage_empty_list(tmp_path: Path):
    p = tmp_path / "lineage.json"
    p.write_text("[]")
    graph = load_lineage(p)
    assert graph == {}


def test_lineage_from_hints():
    hints = {"upstream_tables": ["raw_orders", "dim_customers"]}
    graph = lineage_from_hints(hints)
    assert graph["__hints__"] == ["raw_orders", "dim_customers"]


def test_lineage_from_hints_empty():
    graph = lineage_from_hints({})
    assert graph["__hints__"] == []


# --- upstream_chain ---

def test_upstream_chain_direct():
    graph: LineageGraph = {"stg_orders": ["raw_orders"]}
    chain = upstream_chain("stg_orders", graph, depth=3)
    assert chain == ["raw_orders"]


def test_upstream_chain_multi_hop():
    graph: LineageGraph = {
        "fct_orders": ["stg_orders"],
        "stg_orders": ["raw_orders"],
    }
    chain = upstream_chain("fct_orders", graph, depth=3)
    assert "stg_orders" in chain
    assert "raw_orders" in chain


def test_upstream_chain_depth_limit():
    graph: LineageGraph = {
        "d": ["c"],
        "c": ["b"],
        "b": ["a"],
    }
    chain = upstream_chain("d", graph, depth=1)
    assert chain == ["c"]
    assert "b" not in chain


def test_upstream_chain_no_lineage():
    chain = upstream_chain("orphan_table", {}, depth=3)
    assert chain == []


def test_upstream_chain_no_cycles():
    graph: LineageGraph = {
        "a": ["b"],
        "b": ["a"],
    }
    chain = upstream_chain("a", graph, depth=5)
    assert chain.count("b") == 1


# --- rca_node ---

def _make_failure(rule_id: str, table: str, rows_checked: int = 100,
                  rows_failed: int = 10, upstream: list[str] | None = None) -> RuleFailure:
    rule = DataQualityRule.model_validate({
        "apiVersion": "thota_dq.dev/v1",
        "kind": "DataQualityRule",
        "metadata": {"id": rule_id, "severity": "high"},
        "scope": {"table": table},
        "logic": {"type": "sql_expression", "expression": "revenue >= 0"},
        "diagnosis": {
            "common_causes": ["ETL bug"],
            "lineage_hints": {"upstream_tables": upstream or []},
        },
    })
    result = RuleResult(
        rule_id=rule_id,
        passed=False,
        row_count_checked=rows_checked,
        row_count_failed=rows_failed,
    )
    return RuleFailure(rule=rule, result=result)


def _make_state(failures, diagnoses=None):
    return {
        "run_id": "test-run",
        "failures": failures,
        "diagnoses": diagnoses or [],
        "rca_results": [],
        "cost_total_usd": 0.0,
        "tokens_total": 0,
    }


@pytest.mark.asyncio
async def test_rca_node_no_llm_skips():
    failures = [_make_failure("r1", "orders")]
    diagnoses = [{"failure_id": "r1", "explanation": "x", "likely_cause": "y", "suggested_action": "z"}]
    state = _make_state(failures, diagnoses)
    result = await rca_node(state, llm=None)
    assert result["rca_results"] == []


@pytest.mark.asyncio
async def test_rca_node_no_failures_skips():
    state = _make_state([])
    llm = MagicMock()
    result = await rca_node(state, llm=llm)
    assert result["rca_results"] == []


@pytest.mark.asyncio
async def test_rca_node_no_diagnoses_skips():
    failures = [_make_failure("r1", "orders")]
    state = _make_state(failures, diagnoses=[])
    llm = MagicMock()
    result = await rca_node(state, llm=llm)
    assert result["rca_results"] == []


@pytest.mark.asyncio
async def test_rca_node_calls_llm_per_failure():
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=(
        "ROOT_CAUSE: Stale ETL job\nORIGIN: raw_orders\nPROPAGATION: Nulls flowed down\nFIX: Rerun pipeline",
        20, 50,
    ))
    llm._model = "test-model"

    failures = [_make_failure("r1", "orders", upstream=["raw_orders"])]
    diagnoses = [{"failure_id": "r1", "explanation": "Null revenues", "likely_cause": "ETL bug", "suggested_action": "Check pipeline"}]
    state = _make_state(failures, diagnoses)
    result = await rca_node(state, llm=llm)

    assert len(result["rca_results"]) == 1
    rca = result["rca_results"][0]
    assert rca["failure_id"] == "r1"
    assert rca["root_cause"] == "Stale ETL job"
    assert rca["origin"] == "raw_orders"
    assert rca["fix"] == "Rerun pipeline"
    assert "raw_orders" in rca["upstream_tables"]
    llm.complete.assert_called_once()


@pytest.mark.asyncio
async def test_rca_node_uses_lineage_graph():
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=("ROOT_CAUSE: x\nORIGIN: raw\nPROPAGATION: y\nFIX: z", 10, 10))
    llm._model = "test-model"

    graph: LineageGraph = {"orders": ["stg_orders", "raw_orders"]}
    failures = [_make_failure("r1", "orders")]
    diagnoses = [{"failure_id": "r1", "explanation": "x", "likely_cause": "y", "suggested_action": "z"}]
    state = _make_state(failures, diagnoses)
    result = await rca_node(state, llm=llm, lineage_graph=graph)

    rca = result["rca_results"][0]
    assert "stg_orders" in rca["upstream_tables"]
    assert rca["lineage_depth"] >= 1


@pytest.mark.asyncio
async def test_rca_node_invalid_llm_response_uses_defaults():
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=("some random text with no structured output", 5, 5))
    llm._model = "test-model"

    failures = [_make_failure("r1", "orders")]
    diagnoses = [{"failure_id": "r1", "explanation": "x", "likely_cause": "y", "suggested_action": "z"}]
    state = _make_state(failures, diagnoses)
    result = await rca_node(state, llm=llm)

    rca = result["rca_results"][0]
    assert rca["root_cause"] == "Unable to determine"
    assert rca["origin"] == "Unknown"


@pytest.mark.asyncio
async def test_rca_node_multiple_failures():
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=("ROOT_CAUSE: x\nORIGIN: y\nPROPAGATION: z\nFIX: w", 10, 10))
    llm._model = "test-model"

    failures = [
        _make_failure("r1", "orders"),
        _make_failure("r2", "customers"),
    ]
    diagnoses = [
        {"failure_id": "r1", "explanation": "a", "likely_cause": "b", "suggested_action": "c"},
        {"failure_id": "r2", "explanation": "d", "likely_cause": "e", "suggested_action": "f"},
    ]
    state = _make_state(failures, diagnoses)
    result = await rca_node(state, llm=llm)

    assert len(result["rca_results"]) == 2
    assert llm.complete.call_count == 2
