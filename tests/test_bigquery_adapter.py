"""Tests for the BigQuery warehouse adapter (fully mocked — no GCP credentials)."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from thota_dq.rules.schema import DataQualityRule

# ---------------------------------------------------------------------------
# Inject a fake google.cloud.bigquery into sys.modules before any import of
# the BigQuery adapter so the real package is never required.
# ---------------------------------------------------------------------------

def _install_bq_mock() -> None:
    google = types.ModuleType("google")
    cloud = types.ModuleType("google.cloud")
    bq = types.ModuleType("google.cloud.bigquery")
    bq.Client = MagicMock()
    google.cloud = cloud
    cloud.bigquery = bq
    sys.modules.setdefault("google", google)
    sys.modules.setdefault("google.cloud", cloud)
    sys.modules.setdefault("google.cloud.bigquery", bq)


_install_bq_mock()

# Now safe to import — google.cloud.bigquery is satisfied by the stub above
import importlib as _il  # noqa: E402

import thota_dq.adapters.warehouse.bigquery as _bq_mod  # noqa: E402

_il.reload(_bq_mod)  # ensure the module uses our stub
from thota_dq.adapters.warehouse.bigquery import BigQueryAdapter  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rule(rule_id: str, rule_type: str, table: str = "orders",
               columns: list[str] | None = None, **logic_kwargs) -> DataQualityRule:
    logic = {"type": rule_type, **logic_kwargs}
    return DataQualityRule.model_validate({
        "apiVersion": "thota_dq.dev/v1",
        "kind": "DataQualityRule",
        "metadata": {"id": rule_id, "severity": "high"},
        "scope": {"table": table, "columns": columns or []},
        "logic": logic,
    })


def _make_adapter(scalar_values: list | None = None,
                  sample_values: list | None = None) -> BigQueryAdapter:
    """Build a BigQueryAdapter whose _scalar and _sample_rows are mocked."""
    adapter = BigQueryAdapter.__new__(BigQueryAdapter)
    adapter._project = "test-project"
    adapter._dataset = "test_dataset"
    adapter._location = "US"
    adapter._client = MagicMock()

    scalar_iter = iter(scalar_values or [])
    adapter._scalar = MagicMock(side_effect=lambda sql: next(scalar_iter))

    sample_iter = iter(sample_values or [[] * 100])
    adapter._sample_rows = MagicMock(side_effect=lambda sql: next(sample_iter, []))

    return adapter


# ---------------------------------------------------------------------------
# Table name resolution
# ---------------------------------------------------------------------------

def test_full_table_unqualified():
    adapter = _make_adapter()
    assert adapter._full_table("orders") == "test-project.test_dataset.orders"


def test_full_table_two_part():
    adapter = _make_adapter()
    assert adapter._full_table("other_ds.orders") == "test-project.other_ds.orders"


def test_full_table_three_part():
    adapter = _make_adapter()
    assert adapter._full_table("proj.ds.orders") == "proj.ds.orders"


# ---------------------------------------------------------------------------
# NOT_NULL
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_not_null_pass():
    adapter = _make_adapter(scalar_values=[100, 0], sample_values=[[]])
    rule = _make_rule("r", "not_null", columns=["order_id"])
    result = await adapter.execute_rule(rule)
    assert result.passed
    assert result.row_count_checked == 100
    assert result.row_count_failed == 0


@pytest.mark.asyncio
async def test_not_null_fail():
    adapter = _make_adapter(scalar_values=[100, 5], sample_values=[[{"order_id": None}]])
    rule = _make_rule("r", "not_null", columns=["order_id"])
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 5
    assert len(result.failure_sample) == 1


# ---------------------------------------------------------------------------
# UNIQUE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unique_pass():
    adapter = _make_adapter(scalar_values=[50, 0], sample_values=[[]])
    rule = _make_rule("r", "unique", columns=["order_id"])
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_unique_fail():
    adapter = _make_adapter(scalar_values=[50, 3], sample_values=[[{"order_id": 1, "cnt": 2}]])
    rule = _make_rule("r", "unique", columns=["order_id"])
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 3


# ---------------------------------------------------------------------------
# SQL_EXPRESSION
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sql_expression_pass():
    adapter = _make_adapter(scalar_values=[200, 0], sample_values=[[]])
    rule = _make_rule("r", "sql_expression", expression="revenue >= 0")
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_sql_expression_fail():
    adapter = _make_adapter(scalar_values=[200, 4], sample_values=[[{"revenue": -10}]])
    rule = _make_rule("r", "sql_expression", expression="revenue >= 0")
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 4


# ---------------------------------------------------------------------------
# ROW_COUNT
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_row_count_pass():
    adapter = _make_adapter(scalar_values=[500])
    rule = _make_rule("r", "row_count", threshold=100)
    result = await adapter.execute_rule(rule)
    assert result.passed
    assert result.row_count_checked == 500


@pytest.mark.asyncio
async def test_row_count_fail():
    adapter = _make_adapter(scalar_values=[10])
    rule = _make_rule("r", "row_count", threshold=100)
    result = await adapter.execute_rule(rule)
    assert not result.passed


# ---------------------------------------------------------------------------
# FRESHNESS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_freshness_pass():
    adapter = _make_adapter(scalar_values=["2026-05-12", 2])
    rule = _make_rule("r", "freshness", columns=["updated_at"], threshold=24)
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_freshness_fail():
    adapter = _make_adapter(scalar_values=["2026-05-10", 50])
    rule = _make_rule("r", "freshness", columns=["updated_at"], threshold=24)
    result = await adapter.execute_rule(rule)
    assert not result.passed


@pytest.mark.asyncio
async def test_freshness_no_rows():
    adapter = _make_adapter(scalar_values=[None])
    rule = _make_rule("r", "freshness", columns=["updated_at"], threshold=24)
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.error is not None


# ---------------------------------------------------------------------------
# BETWEEN
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_between_pass():
    adapter = _make_adapter(scalar_values=[100, 0])
    rule = _make_rule("r", "between", columns=["age"], min_value=0, max_value=120)
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_between_fail():
    adapter = _make_adapter(scalar_values=[100, 3])
    rule = _make_rule("r", "between", columns=["age"], min_value=0, max_value=120)
    result = await adapter.execute_rule(rule)
    assert not result.passed


# ---------------------------------------------------------------------------
# REGEX_MATCH (BigQuery uses REGEXP_CONTAINS)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_regex_match_pass():
    adapter = _make_adapter(scalar_values=[100, 0])
    rule = _make_rule("r", "regex_match", columns=["email"], pattern=r"^.+@.+\..+$")
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_regex_match_fail():
    adapter = _make_adapter(scalar_values=[100, 7])
    rule = _make_rule("r", "regex_match", columns=["email"], pattern=r"^.+@.+\..+$")
    result = await adapter.execute_rule(rule)
    assert not result.passed


# ---------------------------------------------------------------------------
# NULL_PERCENTAGE_BELOW
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_null_percentage_pass():
    adapter = _make_adapter(scalar_values=[100, 3])
    rule = _make_rule("r", "null_percentage_below", columns=["desc"], threshold=5.0)
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_null_percentage_fail():
    adapter = _make_adapter(scalar_values=[100, 10])
    rule = _make_rule("r", "null_percentage_below", columns=["desc"], threshold=5.0)
    result = await adapter.execute_rule(rule)
    assert not result.passed


# ---------------------------------------------------------------------------
# RECONCILE_ROW_COUNT
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reconcile_row_count_pass():
    adapter = _make_adapter(scalar_values=[100, 100])
    rule = _make_rule("r", "reconcile_row_count", source_table="staging.orders")
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_reconcile_row_count_fail():
    adapter = _make_adapter(scalar_values=[100, 90])
    rule = _make_rule("r", "reconcile_row_count", source_table="staging.orders")
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.failure_sample[0]["source_rows"] == 100
    assert result.failure_sample[0]["target_rows"] == 90


# ---------------------------------------------------------------------------
# Exception handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exception_returns_error_result():
    adapter = _make_adapter()
    adapter._scalar = MagicMock(side_effect=Exception("BQ quota exceeded"))
    rule = _make_rule("r", "not_null", columns=["order_id"])
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert "BQ quota exceeded" in result.error


# ---------------------------------------------------------------------------
# Unsupported rule type
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unsupported_rule_type_returns_error():
    adapter = _make_adapter()
    rule = _make_rule("r", "row_count", threshold=1)
    # Patch logic type to something fake via object mutation
    rule.spec_logic.__class__ = rule.spec_logic.__class__
    original_type = rule.spec_logic.type
    object.__setattr__(rule.spec_logic, "type", "nonexistent_type")  # type: ignore[arg-type]
    result = await adapter.execute_rule(rule)
    object.__setattr__(rule.spec_logic, "type", original_type)
    assert not result.passed
    assert result.error is not None
