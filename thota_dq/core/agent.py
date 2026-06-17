"""LangGraph orchestrator — wires plan → parallel_table → reconcile → report."""

from __future__ import annotations

import uuid

from langgraph.graph import END, StateGraph

from ..adapters.llm.anthropic import AnthropicAdapter
from ..adapters.llm.base import LLMAdapter
from ..adapters.llm.retry import RetryingLLMAdapter
from ..adapters.warehouse.base import WarehouseAdapter
from ..adapters.warehouse.duckdb import DuckDBAdapter
from ..rules.schema import DataQualityRule
from .lineage.openlineage import LineageGraph
from .nodes.parallel import parallel_table_node
from .nodes.plan import plan_node
from .nodes.reconcile import reconcile_node
from .nodes.remediate import remediate_node
from .nodes.report import report_node
from .state import AegisState

_UNSET = object()  # sentinel — distinguishes "not provided" from explicit None


class AegisAgent:
    """Agentic data quality orchestrator built on LangGraph.

    Pipeline (default — parallel):
        plan → parallel_table → reconcile → remediate → report

    parallel_table fans out per-table: each table runs
    execute → classify → diagnose → rca concurrently, so LLM calls for
    table A overlap with warehouse queries for table B.
    """

    def __init__(
        self,
        warehouse_adapter: WarehouseAdapter | None = None,
        llm_adapter: LLMAdapter | None = _UNSET,  # type: ignore[assignment]
        lineage_graph: LineageGraph | None = None,
    ):
        self._warehouse: WarehouseAdapter = warehouse_adapter or DuckDBAdapter()
        # If caller explicitly passes llm_adapter=None → no-LLM / offline mode.
        # If caller omits the argument → default to AnthropicAdapter.
        if llm_adapter is _UNSET:
            self._llm: LLMAdapter | None = RetryingLLMAdapter(AnthropicAdapter())
        else:
            self._llm = llm_adapter  # type: ignore[assignment]
        self._lineage: LineageGraph = lineage_graph or {}
        self._graph = self._build_graph()

    def _build_graph(self):
        builder: StateGraph = StateGraph(AegisState)

        warehouse = self._warehouse
        llm = self._llm
        lineage = self._lineage

        async def _parallel_table(state: AegisState) -> AegisState:
            return await parallel_table_node(state, warehouse, llm, lineage)

        async def _remediate(state: AegisState) -> AegisState:
            return await remediate_node(state, llm)

        builder.add_node("plan", plan_node)
        builder.add_node("parallel_table", _parallel_table)
        builder.add_node("reconcile", reconcile_node)
        builder.add_node("remediate", _remediate)
        builder.add_node("report", report_node)

        builder.set_entry_point("plan")
        builder.add_edge("plan", "parallel_table")
        builder.add_edge("parallel_table", "reconcile")
        builder.add_edge("reconcile", "remediate")
        builder.add_edge("remediate", "report")
        builder.add_edge("report", END)

        return builder.compile()

    async def run(
        self,
        rules: list[DataQualityRule],
        triggered_by: str = "cli",
        run_id: str | None = None,
    ) -> AegisState:
        """Run validation for the given rules and return the final state."""
        initial: AegisState = {
            "run_id": run_id or str(uuid.uuid4()),
            "triggered_by": triggered_by,
            "scope": {
                "tables": list({r.spec_scope.table for r in rules}),
                "rule_ids": None,
            },
            "rules": rules,
            "plan": [],
            "rule_results": [],
            "failures": [],
            "classified_failures": {},
            "reconciliation_summary": {},
            "diagnoses": [],
            "rca_results": [],
            "remediation_proposals": [],
            "report": {},
            "trajectory": [],
            "cost_total_usd": 0.0,
            "tokens_total": 0,
            "error": None,
        }
        return await self._graph.ainvoke(initial)
