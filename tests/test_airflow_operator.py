"""Tests for the Airflow operator (fully mocked — no Airflow installation required)."""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Install minimal Airflow stubs before importing the operator so the real
# apache-airflow package is never required.
# ---------------------------------------------------------------------------


def _install_airflow_mock() -> None:
    """Inject lightweight airflow stubs into sys.modules."""

    class FakeBaseOperator:
        template_fields: tuple[str, ...] = ()

        def __init__(self, **kwargs):
            self.task_id = kwargs.get("task_id", "test_task")

        @property
        def log(self):
            import logging

            return logging.getLogger("thota_dq.test")

    class FakeAirflowException(Exception):
        pass

    airflow_mod = types.ModuleType("airflow")
    models_mod = types.ModuleType("airflow.models")
    baseop_mod = types.ModuleType("airflow.models.baseoperator")
    exc_mod = types.ModuleType("airflow.exceptions")

    baseop_mod.BaseOperator = FakeBaseOperator
    exc_mod.AirflowException = FakeAirflowException
    airflow_mod.models = models_mod
    models_mod.baseoperator = baseop_mod

    sys.modules.setdefault("airflow", airflow_mod)
    sys.modules.setdefault("airflow.models", models_mod)
    sys.modules.setdefault("airflow.models.baseoperator", baseop_mod)
    sys.modules.setdefault("airflow.exceptions", exc_mod)


_install_airflow_mock()

from thota_dq.integrations.airflow.operator import AegisOperator  # noqa: E402

_AirflowException = sys.modules["airflow.exceptions"].AirflowException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(failed: int = 0, passed: int = 1) -> dict:
    return {
        "run_id": "test-run-001",
        "report": {
            "summary": {
                "total": passed + failed,
                "passed": passed,
                "failed": failed,
            }
        },
    }


def _make_context(run_id: str = "airflow-run-xyz") -> dict:
    ti = MagicMock()
    return {"run_id": run_id, "ti": ti}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAegisOperator:
    def _make_operator(self, **kwargs) -> AegisOperator:
        defaults = dict(
            task_id="dq_check",
            rules_path="/tmp/rules.yaml",
            llm_provider="none",
        )
        defaults.update(kwargs)
        return AegisOperator(**defaults)

    def _execute(self, op, context, state):
        """Run op.execute with Agent + load_rules + build_adapter patched."""
        with (
            patch("thota_dq.integrations.airflow.operator.AegisAgent") as MockAgent,
            patch("thota_dq.integrations.airflow.operator.load_rules", return_value=[]),
            patch("thota_dq.integrations.airflow.operator.build_adapter") as mock_build,
        ):
            mock_build.return_value = MagicMock()
            instance = MockAgent.return_value
            instance.run = AsyncMock(return_value=state)
            result = op.execute(context)
        return result, MockAgent, mock_build

    # ------------------------------------------------------------------
    # template_fields
    # ------------------------------------------------------------------

    def test_template_fields(self):
        op = self._make_operator()
        assert "rules_path" in op.template_fields
        assert "connection_params" in op.template_fields
        assert "db_path" in op.template_fields
        assert "run_id" in op.template_fields

    # ------------------------------------------------------------------
    # Happy path — xcom push
    # ------------------------------------------------------------------

    def test_operator_runs_and_pushes_xcom(self):
        state = _make_state(failed=0, passed=3)
        context = _make_context()
        op = self._make_operator(fail_on_failure=True, xcom_key="my_report")
        result, _, _ = self._execute(op, context, state)
        context["ti"].xcom_push.assert_called_once_with(key="my_report", value=state["report"])
        assert result == state["report"]

    # ------------------------------------------------------------------
    # fail_on_failure=True raises when failures > 0
    # ------------------------------------------------------------------

    def test_fail_on_failure_raises(self):
        state = _make_state(failed=2, passed=1)
        context = _make_context()
        op = self._make_operator(fail_on_failure=True)
        with (
            patch("thota_dq.integrations.airflow.operator.AegisAgent") as MockAgent,
            patch("thota_dq.integrations.airflow.operator.load_rules", return_value=[]),
            patch("thota_dq.integrations.airflow.operator.build_adapter", return_value=MagicMock()),
        ):
            instance = MockAgent.return_value
            instance.run = AsyncMock(return_value=state)
            with pytest.raises(_AirflowException, match="2 failed rule"):
                op.execute(context)

    # ------------------------------------------------------------------
    # fail_on_failure=False — no exception even with failures
    # ------------------------------------------------------------------

    def test_no_fail_when_fail_on_failure_false(self):
        state = _make_state(failed=2, passed=1)
        context = _make_context()
        op = self._make_operator(fail_on_failure=False)
        result, _, _ = self._execute(op, context, state)
        assert result["summary"]["failed"] == 2

    # ------------------------------------------------------------------
    # Custom run_id is forwarded to agent.run
    # ------------------------------------------------------------------

    def test_custom_run_id_used(self):
        state = _make_state()
        context = _make_context(run_id="ctx-run-id")
        op = self._make_operator(run_id="custom-run-42")
        _, MockAgent, _ = self._execute(op, context, state)
        instance = MockAgent.return_value
        instance.run.assert_awaited_once()
        _, kwargs = instance.run.call_args
        assert kwargs.get("run_id") == "custom-run-42"

    # ------------------------------------------------------------------
    # run_id=None falls back to context["run_id"]
    # ------------------------------------------------------------------

    def test_run_id_falls_back_to_context(self):
        state = _make_state()
        context = _make_context(run_id="from-airflow-context")
        op = self._make_operator(run_id=None)
        _, MockAgent, _ = self._execute(op, context, state)
        instance = MockAgent.return_value
        instance.run.assert_awaited_once()
        _, kwargs = instance.run.call_args
        assert kwargs.get("run_id") == "from-airflow-context"

    # ------------------------------------------------------------------
    # llm_provider="none" passes llm_adapter=None to AegisAgent
    # ------------------------------------------------------------------

    def test_llm_none_provider(self):
        state = _make_state()
        context = _make_context()
        op = self._make_operator(llm_provider="none")
        _, MockAgent, _ = self._execute(op, context, state)
        MockAgent.assert_called_once()
        _, kwargs = MockAgent.call_args
        assert kwargs.get("llm_adapter") is None

    # ------------------------------------------------------------------
    # build_adapter called with correct warehouse + connection_params
    # ------------------------------------------------------------------

    def test_duckdb_default_uses_db_path(self):
        state = _make_state()
        context = _make_context()
        op = self._make_operator(warehouse="duckdb", db_path="/data/prod.duckdb")
        _, _, mock_build = self._execute(op, context, state)
        mock_build.assert_called_once_with("duckdb", {"path": "/data/prod.duckdb"})

    def test_bigquery_passes_connection_params_dict(self):
        state = _make_state()
        context = _make_context()
        params = {"project": "my-project", "dataset": "analytics"}
        op = self._make_operator(warehouse="bigquery", connection_params=params)
        _, _, mock_build = self._execute(op, context, state)
        mock_build.assert_called_once_with("bigquery", params)

    def test_connection_params_as_json_string(self):
        state = _make_state()
        context = _make_context()
        op = self._make_operator(
            warehouse="postgres",
            connection_params='{"dsn": "postgresql://user:pass@host/db"}',
        )
        _, _, mock_build = self._execute(op, context, state)
        mock_build.assert_called_once_with("postgres", {"dsn": "postgresql://user:pass@host/db"})

    def test_athena_connection_params(self):
        state = _make_state()
        context = _make_context()
        params = {"s3_staging_dir": "s3://bucket/athena/", "region_name": "us-east-1"}
        op = self._make_operator(warehouse="athena", connection_params=params)
        _, _, mock_build = self._execute(op, context, state)
        mock_build.assert_called_once_with("athena", params)

    def test_invalid_json_connection_params_raises(self):
        op = self._make_operator(
            warehouse="postgres",
            connection_params="not valid json",
        )
        context = _make_context()
        with patch("thota_dq.integrations.airflow.operator.load_rules", return_value=[]):
            with pytest.raises(_AirflowException, match="not valid JSON"):
                op.execute(context)

    def test_unknown_warehouse_raises(self):
        op = self._make_operator(warehouse="snowflake")
        context = _make_context()
        with patch("thota_dq.integrations.airflow.operator.load_rules", return_value=[]):
            with patch(
                "thota_dq.integrations.airflow.operator.build_adapter",
                side_effect=ValueError("Unknown warehouse type 'snowflake'"),
            ):
                with pytest.raises(_AirflowException, match="Unknown warehouse"):
                    op.execute(context)
