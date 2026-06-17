"""Diagnose node — uses LLM to explain each rule failure."""

from __future__ import annotations

import asyncio
import time

from ...adapters.llm.base import LLMAdapter
from ...adapters.llm.pricing import cost_usd
from ...audit.logger import log_decision
from ..state import AegisState, Diagnosis

SYSTEM_PROMPT = """You are a senior data engineer performing data quality diagnosis.
Given a failed data quality rule, explain:
1. What the failure means in plain English
2. The most likely root cause
3. A concrete next step to investigate or fix it

Be concise (3-5 sentences total). Output in this exact format:
EXPLANATION: <one sentence>
LIKELY_CAUSE: <one sentence>
SUGGESTED_ACTION: <one sentence>"""


async def _diagnose_one(failure, llm: LLMAdapter, run_id: str) -> tuple[Diagnosis, int, int]:
    """Diagnose a single failure. Extracted for use in parallel_table_node."""
    rule = failure.rule
    result = failure.result
    sample_str = str(result.failure_sample[:3]) if result.failure_sample else "No sample available"

    user_msg = f"""Rule: {rule.metadata.id}
Table: {rule.spec_scope.table}
Rule type: {rule.spec_logic.type}
Expression: {rule.spec_logic.expression or rule.spec_logic.query or "N/A"}
Rows checked: {result.row_count_checked}
Rows failed: {result.row_count_failed}
Failure sample: {sample_str}
Common causes hint: {", ".join(rule.diagnosis.common_causes) if rule.diagnosis.common_causes else "None provided"}
Error: {result.error or "None"}"""

    t0 = time.monotonic()
    text, in_tok, out_tok = await llm.complete(SYSTEM_PROMPT, user_msg, max_tokens=512)
    duration_ms = (time.monotonic() - t0) * 1000

    lines = {
        line.split(": ", 1)[0]: line.split(": ", 1)[1]
        for line in text.strip().splitlines()
        if ": " in line
    }

    diag: Diagnosis = {
        "failure_id": rule.metadata.id,
        "explanation": lines.get("EXPLANATION", text[:200]),
        "likely_cause": lines.get("LIKELY_CAUSE", "Unknown"),
        "suggested_action": lines.get("SUGGESTED_ACTION", "Investigate manually"),
    }

    decision_cost = cost_usd(getattr(llm, "_model", None), in_tok, out_tok)
    await log_decision(
        run_id=run_id,
        step="diagnose",
        input_summary=f"[{rule.metadata.id}] {user_msg[:500]}",
        output_summary=text[:500],
        model=getattr(llm, "_model", None),
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=decision_cost,
        duration_ms=duration_ms,
    )

    return diag, in_tok, out_tok


async def diagnose_node(state: AegisState, llm: LLMAdapter | None) -> AegisState:
    """Diagnose each failure using the LLM. Skips gracefully if llm is None."""
    if not state["failures"] or llm is None:
        state["diagnoses"] = []
        return state

    tasks = [_diagnose_one(f, llm, state["run_id"]) for f in state["failures"]]
    outcomes = await asyncio.gather(*tasks)

    diagnoses: list[Diagnosis] = []
    total_in, total_out = 0, 0
    for diag, in_tok, out_tok in outcomes:
        diagnoses.append(diag)
        total_in += in_tok
        total_out += out_tok

    cost = cost_usd(getattr(llm, "_model", None), total_in, total_out)

    state["diagnoses"] = diagnoses
    state["cost_total_usd"] = state.get("cost_total_usd", 0.0) + cost
    state["tokens_total"] = state.get("tokens_total", 0) + total_in + total_out
    return state
