"""Aegis REST API — FastAPI application.

Requires: pip install thota-dq[rest]

Start with:
    thota-dq serve                          # DuckDB :memory:, no LLM
    thota-dq serve --db data.db --port 8000
    uvicorn thota_dq.server.app:create_app --factory --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Response

from .models import (
    HealthResponse,
    RunDetail,
    RunRequest,
    RunStatus,
    RunSummary,
    SearchResult,
)

# In-memory run state — survives only for the lifetime of the process.
# Completed run reports are also persisted to the SQLite audit DB via save_run().
_runs: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def create_app(
    warehouse_adapter=None,
    llm_adapter=None,
) -> FastAPI:
    """Factory that wires adapters into the app.  Called by the CLI and tests."""

    from thota_dq import __version__

    app = FastAPI(
        title="Thota DQ",
        description="Agentic data quality — validate, diagnose, and explain data failures.",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ------------------------------------------------------------------
    # Background run executor
    # ------------------------------------------------------------------

    async def _execute_run(run_id: str, rules_yaml: str, triggered_by: str) -> None:
        _runs[run_id]["status"] = RunStatus.RUNNING
        try:
            import tempfile
            from pathlib import Path

            from thota_dq.adapters.warehouse.duckdb import DuckDBAdapter
            from thota_dq.core.agent import AegisAgent
            from thota_dq.memory.store import save_run
            from thota_dq.rules.parser import load_rules

            wa = warehouse_adapter or DuckDBAdapter()

            with tempfile.NamedTemporaryFile(
                suffix=".yaml", mode="w", delete=False
            ) as f:
                f.write(rules_yaml)
                tmp_path = Path(f.name)

            try:
                rules = load_rules(tmp_path)
            finally:
                tmp_path.unlink(missing_ok=True)

            agent = AegisAgent(warehouse_adapter=wa, llm_adapter=llm_adapter)
            final_state = await agent.run(rules, triggered_by=triggered_by, run_id=run_id)
            report = final_state["report"]
            await save_run(report)

            _runs[run_id]["status"] = RunStatus.DONE
            _runs[run_id]["report"] = report
        except Exception as exc:
            _runs[run_id]["status"] = RunStatus.FAILED
            _runs[run_id]["error"] = str(exc)

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @app.get("/v1/health", response_model=HealthResponse, tags=["meta"])
    async def health() -> HealthResponse:
        """Liveness check."""
        return HealthResponse(version=__version__)

    @app.post("/v1/runs", response_model=RunSummary, status_code=202, tags=["runs"])
    async def create_run(
        body: RunRequest,
        background_tasks: BackgroundTasks,
    ) -> RunSummary:
        """Submit a rules YAML and start a validation run asynchronously.

        Returns immediately with a `run_id`.  Poll `GET /v1/runs/{run_id}` for results.
        """
        run_id = str(uuid.uuid4())
        created_at = _now()
        _runs[run_id] = {
            "run_id": run_id,
            "status": RunStatus.QUEUED,
            "triggered_by": body.triggered_by,
            "created_at": created_at,
            "report": None,
            "error": None,
        }
        background_tasks.add_task(
            _execute_run, run_id, body.rules_yaml, body.triggered_by
        )
        return RunSummary(
            run_id=run_id,
            status=RunStatus.QUEUED,
            triggered_by=body.triggered_by,
            created_at=created_at,
        )

    @app.get("/v1/runs", response_model=list[RunSummary], tags=["runs"])
    async def list_runs(limit: int = Query(20, ge=1, le=200)) -> list[RunSummary]:
        """List recent runs, newest first."""
        items = sorted(_runs.values(), key=lambda r: r["created_at"], reverse=True)
        return [
            RunSummary(
                run_id=r["run_id"],
                status=r["status"],
                triggered_by=r["triggered_by"],
                created_at=r["created_at"],
            )
            for r in items[:limit]
        ]

    @app.get("/v1/runs/{run_id}", response_model=RunDetail, tags=["runs"])
    async def get_run(run_id: str) -> RunDetail:
        """Get full details and report for a run."""
        r = _runs.get(run_id)
        if r is None:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        return RunDetail(**r)

    @app.delete("/v1/runs/{run_id}", status_code=204, response_class=Response, tags=["runs"])
    async def delete_run(run_id: str) -> Response:
        """Remove a run from the in-memory store."""
        if run_id not in _runs:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        del _runs[run_id]
        return Response(status_code=204)

    @app.get("/v1/runs/{run_id}/trajectory", tags=["runs"])
    async def get_trajectory(run_id: str) -> list[dict]:
        """Return the LLM decision trail for a completed run."""
        from thota_dq.audit.logger import get_decisions
        decisions = await get_decisions(run_id)
        return decisions

    @app.get("/v1/search", response_model=list[SearchResult], tags=["search"])
    async def search(
        q: str = Query(..., description="Full-text search query"),
        limit: int = Query(20, ge=1, le=100),
    ) -> list[SearchResult]:
        """Full-text search across all audit decision records."""
        from thota_dq.audit.search import search_decisions
        hits = await search_decisions(q, limit=limit)
        return [
            SearchResult(
                run_id=h.get("run_id", ""),
                step=h.get("step", ""),
                input_summary=h.get("input_summary", ""),
                output_summary=h.get("output_summary", ""),
                model=h.get("model"),
                cost_usd=h.get("cost_usd", 0.0),
            )
            for h in hits
        ]

    return app
