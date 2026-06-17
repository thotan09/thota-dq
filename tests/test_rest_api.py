"""Tests for the Aegis REST API (FastAPI).

Uses httpx AsyncClient with ASGITransport — no real server process needed.
The AegisAgent is mocked so tests run offline with no warehouse or LLM.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from thota_dq.server.app import _runs, create_app
from thota_dq.server.models import RunStatus

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

RULES_YAML = """\
rules:
  - apiVersion: aegis.dev/v1
    kind: DataQualityRule
    metadata:
      id: test_rule
      severity: high
    scope:
      warehouse: duckdb
      table: orders
    logic:
      type: row_count
      threshold: 1
"""

MOCK_REPORT = {
    "run_id": "test-run",
    "summary": {"total_rules": 1, "passed": 1, "failed": 0, "pass_rate": 100.0},
    "failures": [],
    "cost_usd": 0.0,
}

MOCK_STATE = {
    "run_id": "test-run",
    "report": MOCK_REPORT,
    "rule_results": [],
    "failures": [],
    "classified_failures": {},
    "reconciliation_summary": {},
    "diagnoses": [],
    "rca_results": [],
    "remediation_proposals": [],
    "trajectory": [],
    "cost_total_usd": 0.0,
    "tokens_total": 0,
    "error": None,
}


@pytest.fixture(autouse=True)
def clear_runs():
    """Reset in-memory run store before each test."""
    _runs.clear()
    yield
    _runs.clear()


@pytest.fixture
def app():
    return create_app(warehouse_adapter=None, llm_adapter=None)


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert "version" in resp.json()


# ---------------------------------------------------------------------------
# POST /v1/runs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_run_returns_202(client):
    with patch("thota_dq.core.agent.AegisAgent") as MockAgent:
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=MOCK_STATE)
        MockAgent.return_value = mock_instance

        resp = await client.post(
            "/v1/runs", json={"rules_yaml": RULES_YAML, "triggered_by": "test"}
        )

    assert resp.status_code == 202
    body = resp.json()
    assert "run_id" in body
    assert body["status"] == RunStatus.QUEUED
    assert body["triggered_by"] == "test"


@pytest.mark.asyncio
async def test_create_run_stores_in_memory(client):
    with patch("thota_dq.core.agent.AegisAgent") as MockAgent:
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=MOCK_STATE)
        MockAgent.return_value = mock_instance

        resp = await client.post(
            "/v1/runs", json={"rules_yaml": RULES_YAML}
        )

    run_id = resp.json()["run_id"]
    assert run_id in _runs


@pytest.mark.asyncio
async def test_create_run_invalid_yaml_fails(client):
    with patch("thota_dq.core.agent.AegisAgent") as MockAgent:
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=MOCK_STATE)
        MockAgent.return_value = mock_instance

        resp = await client.post(
            "/v1/runs", json={"rules_yaml": "rules: [invalid: yaml: {{{"}
        )
        run_id = resp.json()["run_id"]
        # Give background task time to fail
        await asyncio.sleep(0.1)

    assert _runs[run_id]["status"] == RunStatus.FAILED


# ---------------------------------------------------------------------------
# GET /v1/runs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_runs_empty(client):
    resp = await client.get("/v1/runs")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_runs_returns_submitted(client):
    with patch("thota_dq.core.agent.AegisAgent") as MockAgent:
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=MOCK_STATE)
        MockAgent.return_value = mock_instance

        await client.post("/v1/runs", json={"rules_yaml": RULES_YAML})
        await client.post("/v1/runs", json={"rules_yaml": RULES_YAML})

    resp = await client.get("/v1/runs")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_list_runs_limit(client):
    for _ in range(5):
        _runs[str(id(_))] = {
            "run_id": str(id(_)), "status": RunStatus.DONE,
            "triggered_by": "test", "created_at": "2026-01-01T00:00:00+00:00",
            "report": None, "error": None,
        }

    resp = await client.get("/v1/runs?limit=3")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


# ---------------------------------------------------------------------------
# GET /v1/runs/{run_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_run_not_found(client):
    resp = await client.get("/v1/runs/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_run_returns_detail(client):
    _runs["abc"] = {
        "run_id": "abc", "status": RunStatus.DONE,
        "triggered_by": "api", "created_at": "2026-01-01T00:00:00+00:00",
        "report": MOCK_REPORT, "error": None,
    }
    resp = await client.get("/v1/runs/abc")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "abc"
    assert body["status"] == RunStatus.DONE
    assert body["report"]["summary"]["passed"] == 1


@pytest.mark.asyncio
async def test_get_run_failed_has_error(client):
    _runs["fail"] = {
        "run_id": "fail", "status": RunStatus.FAILED,
        "triggered_by": "api", "created_at": "2026-01-01T00:00:00+00:00",
        "report": None, "error": "connection refused",
    }
    resp = await client.get("/v1/runs/fail")
    assert resp.status_code == 200
    assert resp.json()["error"] == "connection refused"


# ---------------------------------------------------------------------------
# DELETE /v1/runs/{run_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_run(client):
    _runs["del"] = {
        "run_id": "del", "status": RunStatus.DONE,
        "triggered_by": "api", "created_at": "2026-01-01T00:00:00+00:00",
        "report": None, "error": None,
    }
    resp = await client.delete("/v1/runs/del")
    assert resp.status_code == 204
    assert "del" not in _runs


@pytest.mark.asyncio
async def test_delete_run_not_found(client):
    resp = await client.delete("/v1/runs/ghost")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /v1/runs/{run_id}/trajectory
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_trajectory(client):
    mock_decisions = [{"step": "diagnose", "model": "claude-haiku", "run_id": "xyz"}]
    with patch("thota_dq.audit.logger.get_decisions", new=AsyncMock(return_value=mock_decisions)):
        resp = await client.get("/v1/runs/xyz/trajectory")
    assert resp.status_code == 200
    assert resp.json()[0]["step"] == "diagnose"


# ---------------------------------------------------------------------------
# GET /v1/search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_returns_results(client):
    mock_hits = [
        {
            "run_id": "r1", "step": "diagnose",
            "input_summary": "null order_id", "output_summary": "ETL failure",
            "model": "claude-haiku", "cost_usd": 0.0001,
        }
    ]
    with patch("thota_dq.audit.search.search_decisions", new=AsyncMock(return_value=mock_hits)):
        resp = await client.get("/v1/search?q=null+order")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["step"] == "diagnose"


@pytest.mark.asyncio
async def test_search_missing_query_returns_422(client):
    resp = await client.get("/v1/search")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Background run completes to DONE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_completes_to_done(client):
    with patch("thota_dq.core.agent.AegisAgent") as MockAgent, \
         patch("thota_dq.memory.store.save_run", new=AsyncMock()):
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=MOCK_STATE)
        MockAgent.return_value = mock_instance

        resp = await client.post("/v1/runs", json={"rules_yaml": RULES_YAML})
        run_id = resp.json()["run_id"]

        # Wait for the background task to finish
        for _ in range(20):
            await asyncio.sleep(0.05)
            if _runs[run_id]["status"] != RunStatus.RUNNING:
                break

    assert _runs[run_id]["status"] == RunStatus.DONE
    assert _runs[run_id]["report"] is not None
