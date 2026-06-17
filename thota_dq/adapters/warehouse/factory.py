"""Warehouse adapter factory.

Maps a warehouse type string + connection params dict to the correct adapter
instance. Used by the MCP server, Airflow operator, and CLI — build once,
share everywhere.

Supported warehouse types:
  duckdb      — local or in-memory DuckDB
  bigquery    — Google BigQuery
  athena      — Amazon Athena
  databricks  — Databricks SQL warehouse
  postgres    — PostgreSQL (and Redshift via Postgres wire protocol)

Connection params are passed as keyword arguments to the adapter constructor.
Unrecognised keys are silently ignored so callers can pass a superset config.

Environment variable fallbacks are checked when a required param is absent,
letting users configure once in their shell / .env rather than per-call.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .base import WarehouseAdapter

# ── env var defaults per warehouse ───────────────────────────────────────────

_DUCKDB_DEFAULTS = {
    "path": lambda: os.environ.get("DUCKDB_PATH", ":memory:"),
}

_BIGQUERY_DEFAULTS = {
    "project": lambda: os.environ.get("BQ_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT"),
    "dataset": lambda: os.environ.get("BQ_DATASET"),
    "location": lambda: os.environ.get("BQ_LOCATION", "US"),
}

_ATHENA_DEFAULTS = {
    "s3_staging_dir": lambda: os.environ.get("ATHENA_S3_STAGING_DIR"),
    "region_name": lambda: os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
    "schema_name": lambda: os.environ.get("ATHENA_SCHEMA", "default"),
}

_DATABRICKS_DEFAULTS = {
    "server_hostname": lambda: os.environ.get("DATABRICKS_HOST"),
    "http_path": lambda: os.environ.get("DATABRICKS_HTTP_PATH"),
    "access_token": lambda: os.environ.get("DATABRICKS_TOKEN"),
}

_POSTGRES_DEFAULTS = {
    "dsn": lambda: os.environ.get("POSTGRES_DSN"),
    "host": lambda: os.environ.get("PGHOST", "localhost"),
    "port": lambda: int(os.environ.get("PGPORT", "5432")),
    "dbname": lambda: os.environ.get("PGDATABASE", "postgres"),
    "user": lambda: os.environ.get("PGUSER", "postgres"),
    "password": lambda: os.environ.get("PGPASSWORD", ""),
}


def _merge(params: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Fill missing keys from env-var default callables."""
    result = dict(params)
    for key, getter in defaults.items():
        if key not in result or result[key] is None:
            value = getter()
            if value is not None:
                result[key] = value
    return result


# ── public factory ────────────────────────────────────────────────────────────

_SUPPORTED = {"duckdb", "bigquery", "athena", "databricks", "postgres"}


def build_adapter(
    warehouse: str,
    connection_params: dict[str, Any] | str | None = None,
) -> WarehouseAdapter:
    """Build and return a warehouse adapter.

    Args:
        warehouse: One of "duckdb", "bigquery", "athena", "databricks", "postgres".
        connection_params: Dict of constructor kwargs, a JSON string encoding the
            same dict, or None to rely entirely on environment variable defaults.

    Raises:
        ValueError: If the warehouse type is not recognised.
        TypeError: If connection_params is not a dict, JSON string, or None.
    """
    wh = warehouse.lower().strip()
    if wh not in _SUPPORTED:
        raise ValueError(
            f"Unknown warehouse type {warehouse!r}. "
            f"Supported types: {', '.join(sorted(_SUPPORTED))}"
        )

    if connection_params is None:
        params: dict[str, Any] = {}
    elif isinstance(connection_params, str):
        try:
            params = json.loads(connection_params)
        except json.JSONDecodeError as exc:
            raise TypeError(
                f"connection_params must be a JSON object string or a dict, got invalid JSON: {exc}"
            ) from exc
    elif isinstance(connection_params, dict):
        params = dict(connection_params)
    else:
        raise TypeError(
            f"connection_params must be a dict, JSON string, or None — got {type(connection_params).__name__}"
        )

    if wh == "duckdb":
        from .duckdb import DuckDBAdapter

        p = _merge(params, _DUCKDB_DEFAULTS)
        return DuckDBAdapter(path=p.get("path", ":memory:"))

    if wh == "bigquery":
        p = _merge(params, _BIGQUERY_DEFAULTS)
        _require(p, ("project", "dataset"), warehouse)
        from .bigquery import BigQueryAdapter

        return BigQueryAdapter(
            project=p["project"],
            dataset=p["dataset"],
            location=p.get("location", "US"),
            credentials=p.get("credentials"),
        )

    if wh == "athena":
        p = _merge(params, _ATHENA_DEFAULTS)
        _require(p, ("s3_staging_dir", "region_name"), warehouse)
        from .athena import AthenaAdapter

        return AthenaAdapter(
            s3_staging_dir=p["s3_staging_dir"],
            region_name=p["region_name"],
            schema_name=p.get("schema_name", "default"),
            aws_access_key_id=p.get("aws_access_key_id"),
            aws_secret_access_key=p.get("aws_secret_access_key"),
            aws_session_token=p.get("aws_session_token"),
        )

    if wh == "databricks":
        p = _merge(params, _DATABRICKS_DEFAULTS)
        _require(p, ("server_hostname", "http_path", "access_token"), warehouse)
        from .databricks import DatabricksAdapter

        return DatabricksAdapter(
            server_hostname=p["server_hostname"],
            http_path=p["http_path"],
            access_token=p["access_token"],
            catalog=p.get("catalog"),
            schema=p.get("schema"),
            port=int(p.get("port", 443)),
        )

    if wh == "postgres":
        p = _merge(params, _POSTGRES_DEFAULTS)
        from .postgres import PostgresAdapter

        if p.get("dsn"):
            return PostgresAdapter(dsn=p["dsn"])
        _require(p, ("host", "dbname", "user"), warehouse)
        return PostgresAdapter(
            host=p.get("host", "localhost"),
            port=int(p.get("port", 5432)),
            dbname=p.get("dbname", "postgres"),
            user=p.get("user", "postgres"),
            password=p.get("password", ""),
            schema=p.get("schema", "public"),
        )

    raise ValueError(f"Unhandled warehouse type: {wh!r}")  # unreachable


def _require(params: dict[str, Any], keys: tuple[str, ...], warehouse: str) -> None:
    missing = [k for k in keys if not params.get(k)]
    if missing:
        raise ValueError(
            f"Missing required connection params for {warehouse!r}: {missing}. "
            f"Pass them in connection_params or set the corresponding environment variables."
        )
