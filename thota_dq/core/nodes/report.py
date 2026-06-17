"""Report node — builds a structured report dict from all results."""

from __future__ import annotations

from datetime import UTC, datetime

from ...audit.logger import log_decision
from ..state import AegisState


async def report_node(state: AegisState) -> AegisState:
    """Assemble final report from results and diagnoses."""
    total = len(state["rule_results"])
    passed = sum(1 for r in state["rule_results"] if r.passed)
    failed = total - passed

    diag_map = {d["failure_id"]: d for d in state.get("diagnoses", [])}

    # Build reverse map: rule_id → triaged severity (from classify node)
    triaged_severity: dict[str, str] = {}
    for sev, failures in state.get("classified_failures", {}).items():
        for f in failures:
            triaged_severity[f.rule.metadata.id] = sev

    failure_details = []
    for f in state["failures"]:
        rid = f.rule.metadata.id
        declared_sev = f.rule.metadata.severity.value
        effective_sev = triaged_severity.get(rid, declared_sev)
        detail: dict = {
            "rule_id": rid,
            "table": f.rule.spec_scope.table,
            "severity": declared_sev,
            "effective_severity": effective_sev,
            "escalated": effective_sev != declared_sev,
            "rows_failed": f.result.row_count_failed,
            "rows_checked": f.result.row_count_checked,
        }
        if f.result.error:
            detail["error"] = f.result.error
        if rid in diag_map:
            detail["diagnosis"] = diag_map[rid]
        failure_details.append(detail)

    severity_breakdown = {
        sev: len(failures)
        for sev, failures in state.get("classified_failures", {}).items()
    }

    report = {
        "run_id": state["run_id"],
        "timestamp": datetime.now(UTC).isoformat(),
        "triggered_by": state["triggered_by"],
        "summary": {
            "total_rules": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed / total * 100, 1) if total else 0.0,
            "severity_breakdown": severity_breakdown,
        },
        "failures": failure_details,
        "rca": state.get("rca_results") or [],
        "reconciliation": state.get("reconciliation_summary") or {},
        "remediation_proposals": state.get("remediation_proposals") or [],
        "cost_usd": round(state.get("cost_total_usd", 0.0), 6),
        "tokens_total": state.get("tokens_total", 0),
    }
    state["report"] = report

    await log_decision(
        run_id=state["run_id"],
        step="report",
        input_summary=f"rules={total} passed={passed} failed={failed}",
        output_summary=f"pass_rate={report['summary']['pass_rate']}% cost=${report['cost_usd']}",
    )
    return state
