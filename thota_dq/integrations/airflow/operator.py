"""Airflow operator that runs Thota DQ validation as a task."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from airflow.exceptions import AirflowException
from airflow.models.baseoperator import BaseOperator

from thota_dq.adapters.warehouse.factory import build_adapter
from thota_dq.core.agent import AegisAgent
from thota_dq.rules.parser import load_rules


class AegisOperator(BaseOperator):
    """Airflow operator that runs Thota DQ validation as a task.

    Parameters
    ----------
    rules_path:
        Path to the YAML rules file. Supports Jinja templating.
    warehouse:
        Warehouse type: ``duckdb``, ``bigquery``, ``athena``, ``databricks``,
        or ``postgres``. Defaults to ``duckdb``.
    connection_params:
        Warehouse connection kwargs as a JSON string or dict. Falls back to
        environment variables when omitted (e.g. ``DUCKDB_PATH``, ``BQ_PROJECT``).
        Supports Jinja templating when passed as a string.
    db_path:
        Shortcut for DuckDB — equivalent to passing
        ``connection_params='{"path": "<db_path>"}'``. Ignored when
        ``warehouse`` is not ``duckdb``. Kept for backward compatibility.
    llm_provider:
        Which LLM backend to use: ``anthropic``, ``openai``, ``ollama``, or
        ``none`` to disable LLM-assisted diagnosis.
    llm_model:
        Optional model override passed to the selected LLM adapter.
    ollama_host:
        Base URL for a locally running Ollama instance.
    fail_on_failure:
        When ``True`` (default), raise :class:`AirflowException` if the DQ
        report contains any failed rules.
    xcom_key:
        XCom key under which the serialised report dict is pushed.
    run_id:
        Explicit run identifier.  Defaults to Airflow's ``context["run_id"]``
        when not provided.  Supports Jinja templating.
    """

    template_fields = ("rules_path", "connection_params", "db_path", "run_id")

    def __init__(
        self,
        *,
        rules_path: str,
        warehouse: str = "duckdb",
        connection_params: str | dict[str, Any] | None = None,
        db_path: str = ":memory:",
        llm_provider: str = "anthropic",
        llm_model: str | None = None,
        ollama_host: str = "http://localhost:11434",
        fail_on_failure: bool = True,
        xcom_key: str = "aegis_report",
        run_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.rules_path = rules_path
        self.warehouse = warehouse
        self.connection_params = connection_params
        self.db_path = db_path
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self.ollama_host = ollama_host
        self.fail_on_failure = fail_on_failure
        self.xcom_key = xcom_key
        self.run_id = run_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_warehouse_adapter(self):
        """Construct the warehouse adapter via the shared factory."""
        wh = self.warehouse.lower()

        # db_path shortcut: DuckDB users don't need to know connection_params
        if wh == "duckdb" and self.connection_params is None:
            return build_adapter("duckdb", {"path": self.db_path})

        # Normalise connection_params — may arrive as a Jinja-rendered string
        params = self.connection_params
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except json.JSONDecodeError as exc:
                raise AirflowException(f"connection_params is not valid JSON: {exc}") from exc

        try:
            return build_adapter(wh, params)
        except ValueError as exc:
            raise AirflowException(str(exc)) from exc

    def _build_llm_adapter(self):
        """Construct the LLM adapter based on *llm_provider*."""
        provider = self.llm_provider.lower()

        if provider == "none":
            return None

        from thota_dq.adapters.llm.retry import RetryingLLMAdapter

        if provider == "anthropic":
            from thota_dq.adapters.llm.anthropic import AnthropicAdapter

            kwargs: dict[str, Any] = {}
            if self.llm_model:
                kwargs["model"] = self.llm_model
            return RetryingLLMAdapter(AnthropicAdapter(**kwargs))

        if provider == "openai":
            from thota_dq.adapters.llm.openai import OpenAIAdapter

            kwargs = {}
            if self.llm_model:
                kwargs["model"] = self.llm_model
            return RetryingLLMAdapter(OpenAIAdapter(**kwargs))

        if provider == "ollama":
            from thota_dq.adapters.llm.ollama import OllamaAdapter

            kwargs = {"base_url": self.ollama_host}
            if self.llm_model:
                kwargs["model"] = self.llm_model
            return RetryingLLMAdapter(OllamaAdapter(**kwargs))

        if provider == "bedrock":
            from thota_dq.adapters.llm.bedrock import BedrockAdapter

            kwargs = {}
            if self.llm_model:
                kwargs["model"] = self.llm_model
            return RetryingLLMAdapter(BedrockAdapter(**kwargs))

        raise AirflowException(
            f"Unknown llm_provider {self.llm_provider!r}. "
            "Choose one of: anthropic, openai, ollama, bedrock, none."
        )

    # ------------------------------------------------------------------
    # Main execution
    # ------------------------------------------------------------------

    def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        effective_run_id: str = self.run_id or context.get("run_id") or ""

        self.log.info(
            "AegisOperator starting — rules=%s warehouse=%s run_id=%s",
            self.rules_path,
            self.warehouse,
            effective_run_id,
        )

        llm_adapter = self._build_llm_adapter()
        warehouse_adapter = self._build_warehouse_adapter()

        rules = load_rules(Path(self.rules_path))
        self.log.info("Loaded %d rule(s) from %s", len(rules), self.rules_path)

        agent = AegisAgent(
            warehouse_adapter=warehouse_adapter,
            llm_adapter=llm_adapter,
        )
        state = asyncio.run(
            agent.run(rules, triggered_by="airflow", run_id=effective_run_id or None)
        )

        report: dict[str, Any] = state.get("report", {})

        context["ti"].xcom_push(key=self.xcom_key, value=report)
        self.log.info("Pushed report to XCom key %r", self.xcom_key)

        if self.fail_on_failure:
            failed_count: int = report.get("summary", {}).get("failed", 0)
            if failed_count > 0:
                raise AirflowException(
                    f"Thota DQ validation found {failed_count} failed rule(s). "
                    f"See XCom key {self.xcom_key!r} for the full report."
                )

        return report
