"""Tests for the Aegis MCP server tools.

The mcp package is an optional dependency. This module stubs it in sys.modules
before importing server.py so the tests work without installing mcp.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Stub the mcp package before any import of the server module
# ---------------------------------------------------------------------------


def _install_mcp_mock() -> dict:
    """Stub the mcp package so we can test server.py without installing it."""
    mcp_mod = types.ModuleType("mcp")
    server_mod = types.ModuleType("mcp.server")
    fastmcp_mod = types.ModuleType("mcp.server.fastmcp")

    registered_tools: dict = {}

    class FakeFastMCP:
        def __init__(self, name: str, **kwargs):
            self.name = name

        def tool(self):
            def decorator(fn):
                registered_tools[fn.__name__] = fn
                return fn

            return decorator

        def run(self, **kwargs):
            pass

    fastmcp_mod.FastMCP = FakeFastMCP
    server_mod.fastmcp = fastmcp_mod
    mcp_mod.server = server_mod
    sys.modules["mcp"] = mcp_mod
    sys.modules["mcp.server"] = server_mod
    sys.modules["mcp.server.fastmcp"] = fastmcp_mod
    return registered_tools


_TOOLS = _install_mcp_mock()

# Now import the server module (mcp is already stubbed)
server_module = importlib.import_module("thota_dq.integrations.mcp.server")

# Grab direct references to each tool function
list_runs = server_module.list_runs
get_trajectory = server_module.get_trajectory
get_run_report = server_module.get_run_report
run_validation = server_module.run_validation
search_decisions = server_module.search_decisions
compare_reports = server_module.compare_reports
summarize_reports = server_module.summarize_reports
check_consistency = server_module.check_consistency


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMcpServerName:
    def test_mcp_server_name(self):
        """The FastMCP instance must be named 'thota-dq'."""
        assert server_module.mcp_server.name == "thota-dq"


class TestListRuns:
    async def test_list_runs_returns_json_array(self):
        """list_runs should return a JSON-encoded list."""
        mock_run_ids = ["run-1", "run-2", "run-3"]
        with patch(
            "thota_dq.integrations.mcp.server.list_run_ids",
            new=AsyncMock(return_value=mock_run_ids),
        ):
            result = await list_runs()
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert parsed == mock_run_ids

    async def test_list_runs_respects_limit(self):
        """list_runs(limit=5) should truncate a longer list to 5 items."""
        mock_run_ids = [f"run-{i}" for i in range(30)]
        with patch(
            "thota_dq.integrations.mcp.server.list_run_ids",
            new=AsyncMock(return_value=mock_run_ids),
        ):
            result = await list_runs(limit=5)
        parsed = json.loads(result)
        assert len(parsed) == 5
        assert parsed == mock_run_ids[:5]


class TestGetTrajectory:
    async def test_get_trajectory_no_decisions(self):
        """When get_decisions returns [], get_trajectory should return an error JSON."""
        with patch(
            "thota_dq.audit.logger.get_decisions",
            new=AsyncMock(return_value=[]),
        ):
            result = await get_trajectory("nonexistent-run")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "nonexistent-run" in parsed["error"]

    async def test_get_trajectory_with_decisions(self):
        """When decisions exist, get_trajectory should return a JSON array."""
        mock_decisions = [
            {"run_id": "run-abc", "step": "diagnose", "output_summary": "issue found"},
            {"run_id": "run-abc", "step": "rca", "output_summary": "root cause: ETL bug"},
        ]
        with patch(
            "thota_dq.audit.logger.get_decisions",
            new=AsyncMock(return_value=mock_decisions),
        ):
            result = await get_trajectory("run-abc")
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0]["step"] == "diagnose"


class TestGetRunReport:
    async def test_get_run_report_structure(self):
        """get_run_report should return JSON with an 'id' key."""
        mock_export = {
            "id": "run-xyz",
            "conversations": [],
            "metadata": {"source": "thota-dq", "total_decisions": 0, "llm_decisions": 0},
        }
        with patch(
            "thota_dq.integrations.mcp.server.export_sharegpt",
            new=AsyncMock(return_value=mock_export),
        ):
            result = await get_run_report("run-xyz")
        parsed = json.loads(result)
        assert "id" in parsed
        assert parsed["id"] == "run-xyz"


class TestRunValidation:
    async def test_run_validation_offline(self):
        """run_validation with no_llm=True should return JSON with 'run_id'."""
        mock_report = {
            "run_id": "test-run-001",
            "summary": {"total_rules": 1, "passed": 1, "failed": 0, "pass_rate": 100},
            "failures": [],
        }
        mock_state = {"report": mock_report}

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=mock_state)

        mock_rules = [MagicMock()]
        mock_warehouse = MagicMock()

        with (
            patch("thota_dq.rules.parser.load_rules", return_value=mock_rules),
            patch("thota_dq.adapters.warehouse.factory.build_adapter", return_value=mock_warehouse),
            patch("thota_dq.core.agent.AegisAgent", return_value=mock_agent),
        ):
            result = await run_validation(
                rules_path="/tmp/rules.yaml",
                warehouse="duckdb",
                connection_params='{"path": ":memory:"}',
                no_llm=True,
            )
        parsed = json.loads(result)
        assert "run_id" in parsed
        assert parsed["run_id"] == "test-run-001"

    async def test_run_validation_bigquery(self):
        """run_validation passes warehouse=bigquery and connection_params through factory."""
        mock_state = {"report": {"run_id": "bq-run", "summary": {}, "failures": []}}
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=mock_state)
        mock_warehouse = MagicMock()

        with (
            patch("thota_dq.rules.parser.load_rules", return_value=[]),
            patch(
                "thota_dq.adapters.warehouse.factory.build_adapter", return_value=mock_warehouse
            ) as mock_factory,
            patch("thota_dq.core.agent.AegisAgent", return_value=mock_agent),
        ):
            await run_validation(
                rules_path="/tmp/rules.yaml",
                warehouse="bigquery",
                connection_params='{"project": "my-proj", "dataset": "analytics"}',
                no_llm=True,
            )
        mock_factory.assert_called_once_with(
            "bigquery", '{"project": "my-proj", "dataset": "analytics"}'
        )


class TestSearchDecisions:
    async def test_search_decisions_returns_json(self):
        """search_decisions should return a JSON array of matching records."""
        mock_results = [
            {"run_id": "run-1", "step": "diagnose", "output_summary": "null ETL bug found"},
            {"run_id": "run-2", "step": "rca", "output_summary": "ETL pipeline failure"},
        ]
        with patch(
            "thota_dq.audit.search.search_decisions",
            new=AsyncMock(return_value=mock_results),
        ):
            result = await search_decisions(query="null ETL bug", limit=10)
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0]["run_id"] == "run-1"


_REPORT_A = {
    "run_id": "run-a",
    "timestamp": "2026-05-01T10:00:00+00:00",
    "triggered_by": "mcp",
    "summary": {
        "total_rules": 10,
        "passed": 8,
        "failed": 2,
        "pass_rate": 80.0,
        "severity_breakdown": {"critical": 1, "high": 1},
    },
    "failures": [
        {
            "rule_id": "rule_1",
            "table": "orders",
            "severity": "critical",
            "effective_severity": "critical",
            "rows_failed": 5,
            "rows_checked": 100,
        },
        {
            "rule_id": "rule_2",
            "table": "customers",
            "severity": "high",
            "effective_severity": "high",
            "rows_failed": 2,
            "rows_checked": 50,
        },
    ],
    "cost_usd": 0.001,
}

_REPORT_B = {
    "run_id": "run-b",
    "timestamp": "2026-05-02T10:00:00+00:00",
    "triggered_by": "mcp",
    "summary": {
        "total_rules": 10,
        "passed": 9,
        "failed": 1,
        "pass_rate": 90.0,
        "severity_breakdown": {"critical": 1},
    },
    "failures": [
        {
            "rule_id": "rule_1",
            "table": "orders",
            "severity": "critical",
            "effective_severity": "critical",
            "rows_failed": 3,
            "rows_checked": 100,
        },
    ],
    "cost_usd": 0.0008,
}


class TestCompareReports:
    async def test_compare_identifies_fix(self):
        """rule_2 passed in B but failed in A — should appear as a fix."""

        async def _load(run_id):
            return {"run-a": _REPORT_A, "run-b": _REPORT_B}.get(run_id)

        with patch("thota_dq.integrations.mcp.server._load_report", side_effect=_load):
            result = await compare_reports("run-a", "run-b")
        parsed = json.loads(result)
        assert "rule_2" in parsed["fixes"]
        assert parsed["regressions"] == []
        assert "rule_1" in parsed["persistent_failures"]

    async def test_compare_summary_delta(self):
        """Pass rate delta should be +10.0 (90 - 80)."""

        async def _load(run_id):
            return {"run-a": _REPORT_A, "run-b": _REPORT_B}.get(run_id)

        with patch("thota_dq.integrations.mcp.server._load_report", side_effect=_load):
            result = await compare_reports("run-a", "run-b")
        parsed = json.loads(result)
        assert parsed["summary_delta"]["pass_rate"] == 10.0
        assert parsed["summary_delta"]["failed_delta"] == -1

    async def test_compare_missing_run(self):
        """Missing run_id should return error JSON."""

        async def _load(run_id):
            return None

        with patch("thota_dq.integrations.mcp.server._load_report", side_effect=_load):
            result = await compare_reports("run-a", "run-b")
        parsed = json.loads(result)
        assert "error" in parsed


class TestSummarizeReports:
    async def test_summarize_single_run(self):
        """Summarizing one run returns a list with one entry."""

        async def _load(run_id):
            return _REPORT_A if run_id == "run-a" else None

        with patch("thota_dq.integrations.mcp.server._load_report", side_effect=_load):
            result = await summarize_reports(["run-a"])
        parsed = json.loads(result)
        assert parsed["total"] == 1
        assert parsed["runs"][0]["run_id"] == "run-a"
        assert parsed["runs"][0]["pass_rate"] == 80.0
        assert len(parsed["runs"][0]["top_failures"]) == 2

    async def test_summarize_missing_run(self):
        """Missing run_id should be reported as an error entry, not raise."""

        async def _load(run_id):
            return None

        with patch("thota_dq.integrations.mcp.server._load_report", side_effect=_load):
            result = await summarize_reports(["missing-run"])
        parsed = json.loads(result)
        assert parsed["total"] == 1
        assert "error" in parsed["runs"][0]

    async def test_summarize_multiple_runs(self):
        """Summarizing two runs returns two entries."""

        async def _load(run_id):
            return {"run-a": _REPORT_A, "run-b": _REPORT_B}.get(run_id)

        with patch("thota_dq.integrations.mcp.server._load_report", side_effect=_load):
            result = await summarize_reports(["run-a", "run-b"])
        parsed = json.loads(result)
        assert parsed["total"] == 2


class TestCheckConsistency:
    async def test_consistency_detects_flapping(self):
        """rule_2 failed in A but passed in B — it is a flapping rule."""

        async def _load(run_id):
            return {"run-a": _REPORT_A, "run-b": _REPORT_B}.get(run_id)

        with patch("thota_dq.integrations.mcp.server._load_report", side_effect=_load):
            result = await check_consistency("run-a", "run-b")
        parsed = json.loads(result)
        assert "rule_2" in parsed["flapping_rules"]
        assert "rule_1" in parsed["consistent_failures"]
        assert parsed["consistent"] is False

    async def test_consistency_perfect_match(self):
        """Two identical failure sets → consistent=True, score=100."""

        async def _load(run_id):
            return _REPORT_A

        with patch("thota_dq.integrations.mcp.server._load_report", side_effect=_load):
            result = await check_consistency("run-a", "run-a")
        parsed = json.loads(result)
        assert parsed["consistent"] is True
        assert parsed["consistency_score_pct"] == 100.0
        assert parsed["flapping_rules"] == []

    async def test_consistency_missing_run(self):
        """Missing run_id returns error JSON."""

        async def _load(run_id):
            return None

        with patch("thota_dq.integrations.mcp.server._load_report", side_effect=_load):
            result = await check_consistency("run-a", "run-b")
        parsed = json.loads(result)
        assert "error" in parsed
