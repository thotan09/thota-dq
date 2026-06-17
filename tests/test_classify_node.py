"""Tests for the classify failures node."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from thota_dq.core.nodes.classify import _failure_rate, _heuristic_severity, classify_node
from thota_dq.rules.schema import DataQualityRule, RuleFailure, RuleResult


def _make_failure(
    rule_id: str,
    rule_type: str,
    severity: str,
    rows_checked: int,
    rows_failed: int,
    columns: list[str] | None = None,
) -> RuleFailure:
    rule = DataQualityRule.model_validate({
        "apiVersion": "thota_dq.dev/v1",
        "kind": "DataQualityRule",
        "metadata": {"id": rule_id, "severity": severity},
        "scope": {"table": "t", "columns": columns or []},
        "logic": {"type": rule_type},
    })
    result = RuleResult(
        rule_id=rule_id,
        passed=False,
        row_count_checked=rows_checked,
        row_count_failed=rows_failed,
    )
    return RuleFailure(rule=rule, result=result)


def _make_state(failures: list[RuleFailure]) -> dict:
    return {
        "run_id": "test-run",
        "failures": failures,
        "classified_failures": {},
        "cost_total_usd": 0.0,
        "tokens_total": 0,
    }


# --- _failure_rate ---

def test_failure_rate_normal():
    f = _make_failure("r", "not_null", "medium", 100, 25)
    assert _failure_rate(f) == pytest.approx(0.25)


def test_failure_rate_zero_rows():
    f = _make_failure("r", "not_null", "medium", 0, 0)
    assert _failure_rate(f) == 0.0


# --- _heuristic_severity ---

def test_heuristic_pk_types_always_critical():
    for rule_type in ("not_null", "unique", "foreign_key", "composite_unique"):
        f = _make_failure("r", rule_type, "low", 100, 1)
        assert _heuristic_severity(f) == "critical"


def test_heuristic_80pct_escalates_to_critical():
    f = _make_failure("r", "sql_expression", "high", 100, 85)
    assert _heuristic_severity(f) == "critical"


def test_heuristic_50pct_escalates_medium_to_high():
    f = _make_failure("r", "sql_expression", "medium", 100, 55)
    assert _heuristic_severity(f) == "high"


def test_heuristic_50pct_does_not_escalate_high():
    f = _make_failure("r", "sql_expression", "high", 100, 55)
    assert _heuristic_severity(f) == "high"


def test_heuristic_low_rate_keeps_declared():
    f = _make_failure("r", "sql_expression", "medium", 100, 10)
    assert _heuristic_severity(f) == "medium"


# --- classify_node (offline / no LLM) ---

@pytest.mark.asyncio
async def test_classify_no_failures():
    state = _make_state([])
    result = await classify_node(state, llm=None)
    assert result["classified_failures"] == {}


@pytest.mark.asyncio
async def test_classify_offline_groups_by_severity():
    failures = [
        _make_failure("r1", "sql_expression", "medium", 100, 10),  # stays medium
        _make_failure("r2", "sql_expression", "low", 100, 60),     # escalates to high
        _make_failure("r3", "not_null", "low", 100, 1),            # escalates to critical
    ]
    state = _make_state(failures)
    result = await classify_node(state, llm=None)
    cf = result["classified_failures"]

    assert "critical" in cf
    assert "high" in cf
    assert "medium" in cf
    assert cf["critical"][0].rule.metadata.id == "r3"
    assert cf["high"][0].rule.metadata.id == "r2"
    assert cf["medium"][0].rule.metadata.id == "r1"


@pytest.mark.asyncio
async def test_classify_offline_ordering():
    """classified_failures keys must follow critical→high→medium→low→info order."""
    failures = [
        _make_failure("r1", "sql_expression", "low", 100, 5),
        _make_failure("r2", "not_null", "low", 100, 1),
    ]
    state = _make_state(failures)
    result = await classify_node(state, llm=None)
    keys = list(result["classified_failures"].keys())
    assert keys.index("critical") < keys.index("low")


# --- classify_node (with LLM) ---

@pytest.mark.asyncio
async def test_classify_with_llm_uses_response():
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=("high", 10, 5))
    llm._model = "test-model"

    failures = [_make_failure("r1", "sql_expression", "medium", 100, 20)]
    state = _make_state(failures)
    result = await classify_node(state, llm=llm)

    assert "high" in result["classified_failures"]
    llm.complete.assert_called_once()


@pytest.mark.asyncio
async def test_classify_with_llm_invalid_response_falls_back():
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=("gibberish_value", 10, 5))
    llm._model = "test-model"

    failures = [_make_failure("r1", "sql_expression", "medium", 100, 20)]
    state = _make_state(failures)
    result = await classify_node(state, llm=llm)

    # Falls back to declared severity
    assert "medium" in result["classified_failures"]


@pytest.mark.asyncio
async def test_classify_with_llm_escalation_to_critical():
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=("critical", 10, 5))
    llm._model = "test-model"

    failures = [_make_failure("r1", "sql_expression", "low", 100, 5)]
    state = _make_state(failures)
    result = await classify_node(state, llm=llm)

    assert "critical" in result["classified_failures"]


# --- report integration: effective_severity and escalated fields ---

@pytest.mark.asyncio
async def test_classify_sets_state_for_report():
    failures = [
        _make_failure("escalated", "not_null", "low", 100, 1),
        _make_failure("unchanged", "sql_expression", "high", 100, 5),
    ]
    state = _make_state(failures)
    result = await classify_node(state, llm=None)

    cf = result["classified_failures"]
    assert any(f.rule.metadata.id == "escalated" for f in cf.get("critical", []))
    assert any(f.rule.metadata.id == "unchanged" for f in cf.get("high", []))
