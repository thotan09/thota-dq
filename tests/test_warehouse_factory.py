"""Tests for the warehouse adapter factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from thota_dq.adapters.warehouse.factory import build_adapter


class TestBuildAdapterDuckDB:
    def test_default_in_memory(self):
        adapter = build_adapter("duckdb")
        from thota_dq.adapters.warehouse.duckdb import DuckDBAdapter

        assert isinstance(adapter, DuckDBAdapter)

    def test_explicit_path(self):
        adapter = build_adapter("duckdb", {"path": ":memory:"})
        from thota_dq.adapters.warehouse.duckdb import DuckDBAdapter

        assert isinstance(adapter, DuckDBAdapter)

    def test_json_string_params(self):
        adapter = build_adapter("duckdb", '{"path": ":memory:"}')
        from thota_dq.adapters.warehouse.duckdb import DuckDBAdapter

        assert isinstance(adapter, DuckDBAdapter)

    def test_none_params(self):
        adapter = build_adapter("duckdb", None)
        from thota_dq.adapters.warehouse.duckdb import DuckDBAdapter

        assert isinstance(adapter, DuckDBAdapter)

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("DUCKDB_PATH", ":memory:")
        adapter = build_adapter("duckdb")
        from thota_dq.adapters.warehouse.duckdb import DuckDBAdapter

        assert isinstance(adapter, DuckDBAdapter)

    def test_case_insensitive(self):
        adapter = build_adapter("DuckDB")
        from thota_dq.adapters.warehouse.duckdb import DuckDBAdapter

        assert isinstance(adapter, DuckDBAdapter)


class TestBuildAdapterBigQuery:
    def test_requires_project_and_dataset(self):
        with pytest.raises(ValueError, match="dataset"):
            build_adapter("bigquery", {"project": "p"})  # missing dataset

    def test_requires_project(self):
        with pytest.raises(ValueError, match="project"):
            build_adapter("bigquery", {"dataset": "ds"})  # missing project

    def test_builds_with_params(self):
        mock_adapter = MagicMock()
        with patch("thota_dq.adapters.warehouse.bigquery.BigQueryAdapter", return_value=mock_adapter):
            adapter = build_adapter("bigquery", {"project": "my-proj", "dataset": "analytics"})
        assert adapter is mock_adapter

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("BQ_PROJECT", "env-project")
        monkeypatch.setenv("BQ_DATASET", "env-dataset")
        # Should not raise missing-param error
        mock_adapter = MagicMock()
        with patch("thota_dq.adapters.warehouse.bigquery.BigQueryAdapter", return_value=mock_adapter):
            adapter = build_adapter("bigquery")
        assert adapter is mock_adapter


class TestBuildAdapterAthena:
    def test_requires_s3_staging_dir(self):
        with pytest.raises(ValueError, match="s3_staging_dir"):
            build_adapter("athena", {"region_name": "us-east-1"})

    def test_requires_region(self):
        with pytest.raises(ValueError, match="region_name"):
            build_adapter("athena", {"s3_staging_dir": "s3://bucket/athena/"})

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("ATHENA_S3_STAGING_DIR", "s3://bucket/athena/")
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        mock_adapter = MagicMock()
        with patch("thota_dq.adapters.warehouse.athena.AthenaAdapter", return_value=mock_adapter):
            adapter = build_adapter("athena")
        assert adapter is mock_adapter


class TestBuildAdapterDatabricks:
    def test_requires_hostname_httppath_token(self):
        with pytest.raises(ValueError, match="server_hostname"):
            build_adapter("databricks", {"http_path": "/sql/...", "access_token": "dapi..."})

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("DATABRICKS_HOST", "abc.azuredatabricks.net")
        monkeypatch.setenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/abc")
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test-token")
        mock_adapter = MagicMock()
        with patch(
            "thota_dq.adapters.warehouse.databricks.DatabricksAdapter", return_value=mock_adapter
        ):
            adapter = build_adapter("databricks")
        assert adapter is mock_adapter


class TestBuildAdapterPostgres:
    def test_dsn_takes_precedence(self):
        mock_adapter = MagicMock()
        with patch(
            "thota_dq.adapters.warehouse.postgres.PostgresAdapter", return_value=mock_adapter
        ) as mock_cls:
            adapter = build_adapter("postgres", {"dsn": "postgresql://user:pass@host/db"})
        mock_cls.assert_called_once_with(dsn="postgresql://user:pass@host/db")
        assert adapter is mock_adapter

    def test_individual_params(self):
        mock_adapter = MagicMock()
        with patch("thota_dq.adapters.warehouse.postgres.PostgresAdapter", return_value=mock_adapter):
            adapter = build_adapter(
                "postgres",
                {"host": "localhost", "dbname": "mydb", "user": "alice", "password": "secret"},
            )
        assert adapter is mock_adapter

    def test_env_var_dsn_fallback(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_DSN", "postgresql://user:pass@host/db")
        mock_adapter = MagicMock()
        with patch("thota_dq.adapters.warehouse.postgres.PostgresAdapter", return_value=mock_adapter):
            adapter = build_adapter("postgres")
        assert adapter is mock_adapter


class TestBuildAdapterErrors:
    def test_unknown_warehouse(self):
        with pytest.raises(ValueError, match="Unknown warehouse type"):
            build_adapter("snowflake")

    def test_invalid_json_string(self):
        with pytest.raises(TypeError, match="JSON"):
            build_adapter("duckdb", "{not valid json}")

    def test_wrong_params_type(self):
        with pytest.raises(TypeError, match="dict, JSON string, or None"):
            build_adapter("duckdb", 12345)  # type: ignore
