"""Classify node — groups failures by severity and escalates when blast radius warrants it."""

from __future__ import annotations

import time

from ...adapters.llm.base import LLMAdapter
from ...adapters.llm.pricing import cost_usd
from ...audit.logger import log_decision
from ...rules.schema import RuleFailure, Severity
from ..state import AegisState

SYSTEM_PROMPT = """You are a senior data quality engineer performing severity triage.
Given a rule failure, decide if its severity should be escalated based on the blast radius
(how many rows failed vs total rows checked).

Rules for escalation:
- If failure rate >= 50% and current severity is 'medium' or lower → escalate to 'high'
- If failure rate >= 80% and current severity is 'high' or lower → escalate to 'critical'
- If the failure affects a primary key or foreign key column → escalate to 'critical' regardless
- Otherwise → keep the declared severity

Respond with ONLY one word: the final severity level.
Valid values: critical, high, medium, low, info"""


def _failure_rate(failure: RuleFailure) -> float:
    checked = failure.result.row_count_checked
    if checked == 0:
        return 0.0
    return failure.result.row_count_failed / checked


def _rule_type_str(failure: RuleFailure) -> str:
    return str(failure.rule.spec_logic.type)


async def _triage_one(
    failure: RuleFailure, llm: LLMAdapter, run_id: str
) -> tuple[RuleFailure, str]:
    """Ask LLM to triage severity; return (failure, final_severity_str)."""
    rate = _failure_rate(failure)
    rule = failure.rule
    result = failure.result

    user_msg = (
        f"Rule ID: {rule.metadata.id}\n"
        f"Rule type: {_rule_type_str(failure)}\n"
        f"Declared severity: {rule.metadata.severity}\n"
        f"Rows checked: {result.row_count_checked}\n"
        f"Rows failed: {result.row_count_failed}\n"
        f"Failure rate: {rate:.1%}\n"
        f"Columns: {rule.spec_scope.columns or []}\n"
        f"Description: {rule.metadata.description or 'N/A'}"
    )

    t0 = time.monotonic()
    text, in_tok, out_tok = await llm.complete(SYSTEM_PROMPT, user_msg, max_tokens=16)
    duration_ms = (time.monotonic() - t0) * 1000

    severity_str = text.strip().lower().split()[0] if text.strip() else str(rule.metadata.severity)
    if severity_str not in {s.value for s in Severity}:
        severity_str = str(rule.metadata.severity)

    cost = cost_usd(getattr(llm, "_model", None), in_tok, out_tok)
    await log_decision(
        run_id=run_id,
        step="classify",
        input_summary=user_msg[:500],
        output_summary=f"severity={severity_str}",
        model=getattr(llm, "_model", None),
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
        duration_ms=duration_ms,
    )

    return failure, severity_str


def _heuristic_severity(failure: RuleFailure) -> str:
    """Offline severity escalation based on failure rate alone."""
    declared = str(failure.rule.metadata.severity)
    rate = _failure_rate(failure)
    rule_type = _rule_type_str(failure)

    if rule_type in ("not_null", "unique", "foreign_key", "composite_unique"):
        return "critical"
    if rate >= 0.80 and declared not in ("critical",):
        return "critical"
    if rate >= 0.50 and declared in ("medium", "low", "info"):
        return "high"
    return declared


async def classify_node(state: AegisState, llm: LLMAdapter | None) -> AegisState:
    """Triage failures by severity. Uses LLM when available, heuristics otherwise."""
    failures = state["failures"]
    if not failures:
        state["classified_failures"] = {}
        return state

    triaged: list[tuple[RuleFailure, str]] = []

    if llm is not None:
        import asyncio

        tasks = [_triage_one(f, llm, state["run_id"]) for f in failures]
        triaged = list(await asyncio.gather(*tasks))
    else:
        triaged = [(f, _heuristic_severity(f)) for f in failures]

    classified: dict[str, list[RuleFailure]] = {}
    for failure, sev in triaged:
        classified.setdefault(sev, []).append(failure)

    _SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]
    classified = {k: classified[k] for k in _SEVERITY_ORDER if k in classified}

    state["classified_failures"] = classified
    return state
