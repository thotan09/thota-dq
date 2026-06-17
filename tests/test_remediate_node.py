"""Tests for the remediation proposal node."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from thota_dq.core.nodes.remediate import _parse_response, remediate_node
from thota_dq.rules.schema import DataQualityRule, RuleFailure, RuleResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GOOD_LLM_RESPONSE = (
    "SQL: UPDATE orders SET order_id = uuid() WHERE order_id IS NULL\n"
    "CONFIDENCE: medium\n"
    "CAVEAT: Verify uuid() is available in your warehouse before running.",
    100,
    50,
)


def _make_failure(
    rule_id: str,
    table: str = "orders",
    rule_type: str = "not_null",
    proposal_strategy: str = "llm_simple",
) -> RuleFailure:
    rule = DataQualityRule.model_validate({
        "apiVersion": "thota_dq.dev/v1",
        "kind": "DataQualityRule",
        "metadata": {"id": rule_id, "severity": "high"},
        "scope": {"table": table},
        "logic": {"type": rule_type},
        "remediation": {"proposal_strategy": proposal_strategy},
    })
    result = RuleResult(
        rule_id=rule_id,
        passed=False,
        row_count_checked=100,
        row_count_failed=10,
    )
    return RuleFailure(rule=rule, result=result)


def _make_state(
    failures: list[RuleFailure],
    diagnoses: list[dict] | None = None,
    rca_results: list[dict] | None = None,
) -> dict:
    return {
        "run_id": "test-run-remediate",
        "failures": failures,
        "diagnoses": diagnoses or [],
        "rca_results": rca_results or [],
        "remediation_proposals": [],
        "cost_total_usd": 0.0,
        "tokens_total": 0,
    }


def _mock_llm(response=_GOOD_LLM_RESPONSE):
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=response)
    llm._model = "test-model"
    return llm


# ---------------------------------------------------------------------------
# Unit tests for _parse_response
# ---------------------------------------------------------------------------

def test_parse_response_valid():
    text = (
        "SQL: UPDATE orders SET status = 'fixed' WHERE status IS NULL\n"
        "CONFIDENCE: high\n"
        "CAVEAT: Check that status column allows NULLs first."
    )
    sql, confidence, caveat = _parse_response(text)
    assert sql == "UPDATE orders SET status = 'fixed' WHERE status IS NULL"
    assert confidence == "high"
    assert caveat == "Check that status column allows NULLs first."


def test_parse_response_missing_confidence_defaults_low():
    text = "SQL: DELETE FROM orders WHERE id IS NULL\nCAVEAT: Be careful."
    _, confidence, _ = _parse_response(text)
    assert confidence == "low"


def test_parse_response_invalid_confidence_defaults_low():
    text = "SQL: UPDATE t SET x=1\nCONFIDENCE: very high\nCAVEAT: None."
    _, confidence, _ = _parse_response(text)
    assert confidence == "low"


def test_parse_response_missing_sql_returns_comment():
    text = "CONFIDENCE: medium\nCAVEAT: Review carefully."
    sql, _, _ = _parse_response(text)
    assert sql.startswith("-- Could not generate SQL")


def test_parse_response_missing_caveat_returns_default():
    text = "SQL: UPDATE t SET x=1\nCONFIDENCE: high"
    _, _, caveat = _parse_response(text)
    assert caveat == "Review carefully before executing."


def test_parse_response_all_confidence_values():
    for level in ("high", "medium", "low"):
        text = f"SQL: SELECT 1\nCONFIDENCE: {level}\nCAVEAT: ok."
        _, confidence, _ = _parse_response(text)
        assert confidence == level


# ---------------------------------------------------------------------------
# Async node tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remediate_no_llm_returns_empty():
    failures = [_make_failure("r1")]
    diagnoses = [{"failure_id": "r1", "explanation": "x", "likely_cause": "y", "suggested_action": "z"}]
    state = _make_state(failures, diagnoses)
    result = await remediate_node(state, llm=None)
    assert result["remediation_proposals"] == []


@pytest.mark.asyncio
async def test_remediate_generates_proposal():
    llm = _mock_llm()
    failures = [_make_failure("r1")]
    diagnoses = [{"failure_id": "r1", "explanation": "NULLs detected", "likely_cause": "ETL gap", "suggested_action": "Fill NULLs"}]
    state = _make_state(failures, diagnoses)

    result = await remediate_node(state, llm=llm)

    proposals = result["remediation_proposals"]
    assert len(proposals) == 1
    p = proposals[0]
    assert p["failure_id"] == "r1"
    assert p["table"] == "orders"
    assert p["rule_type"] == "not_null"
    assert "UPDATE orders" in p["proposed_sql"]
    assert p["confidence"] == "medium"
    assert "uuid()" in p["caveat"]
    llm.complete.assert_called_once()


@pytest.mark.asyncio
async def test_remediate_skips_none_strategy():
    llm = _mock_llm()
    failures = [_make_failure("r1", proposal_strategy="none")]
    diagnoses = [{"failure_id": "r1", "explanation": "x", "likely_cause": "y", "suggested_action": "z"}]
    state = _make_state(failures, diagnoses)

    result = await remediate_node(state, llm=llm)

    assert result["remediation_proposals"] == []
    llm.complete.assert_not_called()


@pytest.mark.asyncio
async def test_remediate_skips_undiagnosed_failure():
    llm = _mock_llm()
    failures = [_make_failure("r1")]
    # No diagnoses — r1 has no diagnosis entry
    state = _make_state(failures, diagnoses=[])

    result = await remediate_node(state, llm=llm)

    assert result["remediation_proposals"] == []
    llm.complete.assert_not_called()


@pytest.mark.asyncio
async def test_remediate_multiple_failures():
    llm = _mock_llm()
    failures = [
        _make_failure("r1", table="orders"),
        _make_failure("r2", table="customers"),
    ]
    diagnoses = [
        {"failure_id": "r1", "explanation": "a", "likely_cause": "b", "suggested_action": "c"},
        {"failure_id": "r2", "explanation": "d", "likely_cause": "e", "suggested_action": "f"},
    ]
    state = _make_state(failures, diagnoses)

    result = await remediate_node(state, llm=llm)

    proposals = result["remediation_proposals"]
    assert len(proposals) == 2
    assert llm.complete.call_count == 2
    ids = {p["failure_id"] for p in proposals}
    assert ids == {"r1", "r2"}


@pytest.mark.asyncio
async def test_remediate_llm_error_handled():
    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    llm._model = "test-model"

    failures = [_make_failure("r1")]
    diagnoses = [{"failure_id": "r1", "explanation": "x", "likely_cause": "y", "suggested_action": "z"}]
    state = _make_state(failures, diagnoses)

    result = await remediate_node(state, llm=llm)

    proposals = result["remediation_proposals"]
    assert len(proposals) == 1
    p = proposals[0]
    assert p["confidence"] == "low"
    assert "LLM error" in p["proposed_sql"] or p["proposed_sql"].startswith("--")


@pytest.mark.asyncio
async def test_remediate_includes_rca_context():
    """Verify RCA data is passed into the LLM user prompt when available."""
    llm = _mock_llm()
    failures = [_make_failure("r1")]
    diagnoses = [{"failure_id": "r1", "explanation": "x", "likely_cause": "y", "suggested_action": "z"}]
    rca_results = [{"failure_id": "r1", "root_cause": "Stale ETL", "origin": "raw_orders", "fix": "Rerun job"}]
    state = _make_state(failures, diagnoses, rca_results)

    result = await remediate_node(state, llm=llm)

    # Should still produce a proposal; the RCA data was available
    assert len(result["remediation_proposals"]) == 1
    call_args = llm.complete.call_args
    user_prompt = call_args[0][1]  # positional arg: (system, user, ...)
    assert "Stale ETL" in user_prompt


@pytest.mark.asyncio
async def test_remediate_proposal_in_report():
    """End-to-end: proposals are placed in state['remediation_proposals']."""
    llm = _mock_llm()
    failures = [_make_failure("r1")]
    diagnoses = [{"failure_id": "r1", "explanation": "Nulls", "likely_cause": "ETL", "suggested_action": "Fix"}]
    state = _make_state(failures, diagnoses)

    result = await remediate_node(state, llm=llm)

    assert "remediation_proposals" in result
    proposals = result["remediation_proposals"]
    assert len(proposals) == 1
    assert proposals[0]["failure_id"] == "r1"
    assert proposals[0]["proposed_sql"]
    assert proposals[0]["confidence"] in ("high", "medium", "low")
    assert proposals[0]["caveat"]


@pytest.mark.asyncio
async def test_remediate_strategy_llm_with_lineage_is_included():
    """Failures with llm_with_lineage strategy should still be remediated."""
    llm = _mock_llm()
    failures = [_make_failure("r1", proposal_strategy="llm_with_lineage")]
    diagnoses = [{"failure_id": "r1", "explanation": "x", "likely_cause": "y", "suggested_action": "z"}]
    state = _make_state(failures, diagnoses)

    result = await remediate_node(state, llm=llm)

    assert len(result["remediation_proposals"]) == 1


@pytest.mark.asyncio
async def test_remediate_no_failures_returns_empty():
    llm = _mock_llm()
    state = _make_state(failures=[], diagnoses=[])

    result = await remediate_node(state, llm=llm)

    assert result["remediation_proposals"] == []
    llm.complete.assert_not_called()


@pytest.mark.asyncio
async def test_remediate_mixed_strategies():
    """One failure with 'none', one with 'llm_simple' — only the latter gets a proposal."""
    llm = _mock_llm()
    failures = [
        _make_failure("r1", proposal_strategy="none"),
        _make_failure("r2", proposal_strategy="llm_simple"),
    ]
    diagnoses = [
        {"failure_id": "r1", "explanation": "a", "likely_cause": "b", "suggested_action": "c"},
        {"failure_id": "r2", "explanation": "d", "likely_cause": "e", "suggested_action": "f"},
    ]
    state = _make_state(failures, diagnoses)

    result = await remediate_node(state, llm=llm)

    proposals = result["remediation_proposals"]
    assert len(proposals) == 1
    assert proposals[0]["failure_id"] == "r2"
    llm.complete.assert_called_once()
