"""Parallel table node — fans out per-table pipelines concurrently.

Replaces the sequential execute → classify → diagnose → rca chain with a
single node that runs the full mini-pipeline for each table in parallel.

With N tables, this means table B starts executing against the warehouse
while table A's failures are already being diagnosed by the LLM — giving
roughly N× throughput improvement over the sequential approach.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ...adapters.llm.base import LLMAdapter
from ...adapters.llm.pricing import cost_usd
from ...adapters.warehouse.base import WarehouseAdapter
from ...rules.schema import DataQualityRule, RuleFailure, Severity
from ..lineage.openlineage import LineageGraph
from ..state import AegisState, Diagnosis
from .classify import _heuristic_severity, _triage_one
from .diagnose import _diagnose_one
from .rca import _build_lineage_context, _rca_one

_SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]


async def _run_table_pipeline(
    table: str,
    rules: list[DataQualityRule],
    warehouse: WarehouseAdapter,
    llm: LLMAdapter | None,
    lineage: LineageGraph,
    run_id: str,
) -> dict[str, Any]:
    """Execute the full mini-pipeline for one table and return partial results."""

    # ── execute ──────────────────────────────────────────────────────────
    results = list(await asyncio.gather(*[warehouse.execute_rule(r) for r in rules]))
    failures = [
        RuleFailure(rule=rule, result=result)
        for rule, result in zip(rules, results)
        if not result.passed
    ]

    if not failures:
        return {
            "results": results,
            "failures": [],
            "triaged": [],
            "diagnoses": [],
            "rca_results": [],
            "in_tokens": 0,
            "out_tokens": 0,
        }

    # ── classify ─────────────────────────────────────────────────────────
    if llm is not None:
        triaged: list[tuple[RuleFailure, str]] = list(
            await asyncio.gather(*[_triage_one(f, llm, run_id) for f in failures])
        )
    else:
        triaged = [(f, _heuristic_severity(f)) for f in failures]

    # ── diagnose ─────────────────────────────────────────────────────────
    diagnoses: list[Diagnosis] = []
    total_in, total_out = 0, 0

    if llm is not None:
        diag_outcomes = list(
            await asyncio.gather(*[_diagnose_one(f, llm, run_id) for f in failures])
        )
        for diag, in_tok, out_tok in diag_outcomes:
            diagnoses.append(diag)
            total_in += in_tok
            total_out += out_tok

    # ── rca ──────────────────────────────────────────────────────────────
    rca_results = []

    if llm is not None and diagnoses:
        diag_map = {d["failure_id"]: d for d in diagnoses}

        async def _maybe_rca(failure: RuleFailure):
            rid = failure.rule.metadata.id
            diag = diag_map.get(rid)
            if diag is None:
                return None
            tbl = failure.rule.spec_scope.table
            hints = failure.rule.diagnosis.lineage_hints
            upstream, _ = _build_lineage_context(tbl, hints, lineage)
            checked = failure.result.row_count_checked
            failed = failure.result.row_count_failed
            rate = (failed / checked) if checked > 0 else 0.0
            return await _rca_one(
                failure_id=rid,
                table=tbl,
                diagnosis=diag,
                failure_rate=rate,
                upstream_tables=upstream,
                llm=llm,
                run_id=run_id,
            )

        outcomes = await asyncio.gather(*[_maybe_rca(f) for f in failures])
        rca_results = [r for r in outcomes if r is not None]

    return {
        "results": results,
        "failures": failures,
        "triaged": triaged,
        "diagnoses": diagnoses,
        "rca_results": rca_results,
        "in_tokens": total_in,
        "out_tokens": total_out,
    }


async def parallel_table_node(
    state: AegisState,
    warehouse: WarehouseAdapter,
    llm: LLMAdapter | None,
    lineage: LineageGraph,
) -> AegisState:
    """Fan out one mini-pipeline per table and merge results into state."""

    rule_map = {r.metadata.id: r for r in state["rules"]}
    ordered = [rule_map[rid] for rid in state["plan"] if rid in rule_map]

    # Group rules by table, preserving plan order within each group
    table_groups: dict[str, list[DataQualityRule]] = {}
    for rule in ordered:
        table_groups.setdefault(rule.spec_scope.table, []).append(rule)

    # Run all table pipelines concurrently
    per_table = await asyncio.gather(
        *[
            _run_table_pipeline(table, rules, warehouse, llm, lineage, state["run_id"])
            for table, rules in table_groups.items()
        ]
    )

    # Merge results
    all_results = []
    all_failures = []
    classified: dict[str, list[RuleFailure]] = {}
    all_diagnoses: list[Diagnosis] = []
    all_rca = []
    total_in, total_out = 0, 0

    for chunk in per_table:
        all_results.extend(chunk["results"])
        all_failures.extend(chunk["failures"])
        for failure, sev in chunk["triaged"]:
            # Validate severity string
            if sev not in {s.value for s in Severity}:
                sev = str(failure.rule.metadata.severity)
            classified.setdefault(sev, []).append(failure)
        all_diagnoses.extend(chunk["diagnoses"])
        all_rca.extend(chunk["rca_results"])
        total_in += chunk["in_tokens"]
        total_out += chunk["out_tokens"]

    # Preserve severity ordering in classified dict
    classified = {k: classified[k] for k in _SEVERITY_ORDER if k in classified}

    cost = cost_usd(getattr(llm, "_model", None), total_in, total_out)

    state["rule_results"] = all_results
    state["failures"] = all_failures
    state["classified_failures"] = classified
    state["diagnoses"] = all_diagnoses
    state["rca_results"] = all_rca
    state["cost_total_usd"] = state.get("cost_total_usd", 0.0) + cost
    state["tokens_total"] = state.get("tokens_total", 0) + total_in + total_out

    return state
