"""Execute node — runs all rules through the warehouse adapter."""

from __future__ import annotations

import asyncio

from ...adapters.warehouse.base import WarehouseAdapter
from ...rules.schema import RuleFailure
from ..state import AegisState


async def execute_node(state: AegisState, adapter: WarehouseAdapter) -> AegisState:
    """Execute all planned rules concurrently and collect results."""
    rule_map = {r.metadata.id: r for r in state["rules"]}
    ordered = [rule_map[rid] for rid in state["plan"] if rid in rule_map]

    results = await asyncio.gather(*[adapter.execute_rule(r) for r in ordered])

    state["rule_results"] = list(results)
    state["failures"] = [
        RuleFailure(rule=rule, result=result)
        for rule, result in zip(ordered, results)
        if not result.passed
    ]
    return state
