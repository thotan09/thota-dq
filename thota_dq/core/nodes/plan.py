"""Plan node — creates an ordered execution plan from loaded rules."""

from __future__ import annotations

from ..state import AegisState

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


async def plan_node(state: AegisState) -> AegisState:
    """Order rules: CRITICAL first, then by severity, then alphabetically."""
    sorted_rules = sorted(
        state["rules"],
        key=lambda r: (
            _SEVERITY_ORDER.get(r.metadata.severity.value, 99),
            r.metadata.id,
        ),
    )
    state["plan"] = [r.metadata.id for r in sorted_rules]
    return state
