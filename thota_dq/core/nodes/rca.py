"""RCA node — multi-hop root cause analysis using lineage context."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ...adapters.llm.base import LLMAdapter
from ...adapters.llm.pricing import cost_usd
from ...audit.logger import log_decision
from ..lineage.openlineage import LineageGraph, upstream_chain
from ..state import AegisState

SYSTEM_PROMPT = """You are a senior data platform engineer performing root cause analysis (RCA)
on a data quality failure. You have access to lineage information showing which upstream
tables and pipelines feed the failing table.

Analyse the failure chain and identify:
1. The most likely root cause in the upstream pipeline
2. Which upstream table or job is the probable origin
3. How the failure propagated to the failing table
4. Specific steps to confirm and fix the root cause

Output in this exact format:
ROOT_CAUSE: <one sentence — the underlying cause>
ORIGIN: <upstream table or job name>
PROPAGATION: <one sentence — how the issue flowed downstream>
FIX: <one concrete action>"""


class RCAResult(dict):
    """Typed dict for an RCA result (extends dict for JSON serialisability)."""


def _build_lineage_context(
    table: str,
    rule_lineage_hints: dict[str, list[str]],
    graph: LineageGraph,
) -> tuple[list[str], int]:
    """Return (upstream_tables, lineage_depth) for a given table."""
    # Merge graph-derived lineage with rule-level hints
    chain = upstream_chain(table, graph, depth=3)
    hints = rule_lineage_hints.get("upstream_tables", [])
    merged = list(dict.fromkeys(chain + [h for h in hints if h not in chain]))
    return merged, len(merged)


async def _rca_one(
    failure_id: str,
    table: str,
    diagnosis: dict[str, Any],
    failure_rate: float,
    upstream_tables: list[str],
    llm: LLMAdapter,
    run_id: str,
) -> RCAResult:
    lineage_str = (
        " → ".join(upstream_tables) + f" → {table}"
        if upstream_tables
        else f"(no lineage available) → {table}"
    )

    user_msg = (
        f"Failing table: {table}\n"
        f"Rule ID: {failure_id}\n"
        f"Failure rate: {failure_rate:.1%}\n"
        f"Diagnosis summary: {diagnosis.get('explanation', 'N/A')}\n"
        f"Likely cause (from diagnosis): {diagnosis.get('likely_cause', 'N/A')}\n"
        f"Lineage chain: {lineage_str}\n"
        f"Upstream tables: {upstream_tables or ['none identified']}"
    )

    t0 = time.monotonic()
    text, in_tok, out_tok = await llm.complete(SYSTEM_PROMPT, user_msg, max_tokens=300)
    duration_ms = (time.monotonic() - t0) * 1000

    lines = {
        line.split(": ", 1)[0]: line.split(": ", 1)[1]
        for line in text.strip().splitlines()
        if ": " in line
    }

    result: RCAResult = RCAResult(
        {
            "failure_id": failure_id,
            "table": table,
            "upstream_tables": upstream_tables,
            "lineage_depth": len(upstream_tables),
            "root_cause": lines.get("ROOT_CAUSE", "Unable to determine"),
            "origin": lines.get("ORIGIN", "Unknown"),
            "propagation": lines.get("PROPAGATION", "Unknown"),
            "fix": lines.get("FIX", "Investigate manually"),
        }
    )

    cost = cost_usd(getattr(llm, "_model", None), in_tok, out_tok)
    await log_decision(
        run_id=run_id,
        step="rca",
        input_summary=user_msg[:500],
        output_summary=text[:300],
        model=getattr(llm, "_model", None),
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
        duration_ms=duration_ms,
    )

    return result


async def rca_node(
    state: AegisState,
    llm: LLMAdapter | None,
    lineage_graph: LineageGraph | None = None,
) -> AegisState:
    """Run RCA for each diagnosed failure. Skips gracefully if no LLM or no failures."""
    failures = state["failures"]
    diagnoses = state.get("diagnoses", [])

    if not failures or not diagnoses or llm is None:
        state["rca_results"] = []
        return state

    graph: LineageGraph = lineage_graph or {}
    diag_map = {d["failure_id"]: d for d in diagnoses}

    async def _run_one(failure) -> RCAResult | None:
        rid = failure.rule.metadata.id
        diag = diag_map.get(rid)
        if diag is None:
            return None

        table = failure.rule.spec_scope.table
        hints = failure.rule.diagnosis.lineage_hints
        upstream, _ = _build_lineage_context(table, hints, graph)

        checked = failure.result.row_count_checked
        failed = failure.result.row_count_failed
        rate = (failed / checked) if checked > 0 else 0.0

        return await _rca_one(
            failure_id=rid,
            table=table,
            diagnosis=diag,
            failure_rate=rate,
            upstream_tables=upstream,
            llm=llm,
            run_id=state["run_id"],
        )

    outcomes = await asyncio.gather(*[_run_one(f) for f in failures])
    rca_results = [r for r in outcomes if r is not None]

    total_cost = sum(
        cost_usd(getattr(llm, "_model", None), r.get("_in_tok", 0), r.get("_out_tok", 0))
        for r in rca_results
    )

    state["rca_results"] = rca_results
    state["cost_total_usd"] = state.get("cost_total_usd", 0.0) + total_cost
    return state
