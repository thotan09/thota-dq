"""Reconcile node — summarises source-vs-target comparison results."""

from __future__ import annotations

from ...rules.schema import RuleType
from ..state import AegisState

_RECONCILE_TYPES = {
    RuleType.RECONCILE_ROW_COUNT,
    RuleType.RECONCILE_COLUMN_SUM,
    RuleType.RECONCILE_KEY_MATCH,
}


async def reconcile_node(state: AegisState) -> AegisState:
    """Build a reconciliation summary from any reconcile_* rule results."""
    recon_results = [
        r for r in state["rule_results"]
        if any(
            rule.metadata.id == r.rule_id and rule.spec_logic.type in _RECONCILE_TYPES
            for rule in state["rules"]
        )
    ]

    if not recon_results:
        state["reconciliation_summary"] = {}
        return state

    rule_map = {r.metadata.id: r for r in state["rules"]}

    pairs: dict[str, dict] = {}
    for result in recon_results:
        rule = rule_map.get(result.rule_id)
        if rule is None:
            continue
        src = rule.spec_logic.source_table or "unknown"
        tgt = rule.spec_scope.table
        pair_key = f"{src} → {tgt}"
        if pair_key not in pairs:
            pairs[pair_key] = {
                "source_table": src,
                "target_table": tgt,
                "checks": [],
                "passed": True,
            }
        check = {
            "rule_id": result.rule_id,
            "check_type": str(rule.spec_logic.type),
            "passed": result.passed,
            "rows_checked": result.row_count_checked,
            "discrepancy": result.failure_sample[0] if result.failure_sample else None,
        }
        pairs[pair_key]["checks"].append(check)
        if not result.passed:
            pairs[pair_key]["passed"] = False

    state["reconciliation_summary"] = {
        "pairs_checked": len(pairs),
        "pairs_passed": sum(1 for p in pairs.values() if p["passed"]),
        "pairs_failed": sum(1 for p in pairs.values() if not p["passed"]),
        "details": list(pairs.values()),
    }
    return state
