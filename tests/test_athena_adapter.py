"""Tests for the Athena warehouse adapter (fully mocked — no AWS credentials needed)."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from thota_dq.rules.schema import DataQualityRule

# ---------------------------------------------------------------------------
# Install a fake pyathena into sys.modules before importing the adapter
# ---------------------------------------------------------------------------

def _install_pyathena_mock() -> MagicMock:
    pa_mod = types.ModuleType("pyathena")
    fake_conn = MagicMock()
    fake_cursor = MagicMock()
    fake_conn.cursor.return_value = fake_cursor
    pa_mod.connect = MagicMock(return_value=fake_conn)
    sys.modules["pyathena"] = pa_mod
    return fake_cursor


_install_pyathena_mock()

from thota_dq.adapters.warehouse.athena import AthenaAdapter  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rule(
    rule_id: str,
    rule_type: str,
    table: str = "orders",
    columns: list[str] | None = None,
    **logic_kwargs,
) -> DataQualityRule:
    logic = {"type": rule_type, **logic_kwargs}
    return DataQualityRule.model_validate({
        "apiVersion": "thota_dq.dev/v1",
        "kind": "DataQualityRule",
        "metadata": {"id": rule_id, "severity": "high"},
        "scope": {"table": table, "columns": columns or []},
        "logic": logic,
    })


def _make_cursor(scalar: int | float | str | None = 0, rows: list | None = None) -> MagicMock:
    """Return a fresh MagicMock cursor with configurable fetchone / fetchall."""
    c = MagicMock()
    c.fetchone.return_value = (scalar,)
    c.fetchall.return_value = rows or []
    c.description = None
    return c


def _make_adapter(cursor: MagicMock | None = None) -> AthenaAdapter:
    """
    Build an AthenaAdapter bypassing __init__. Attach a fake connection
    whose cursor() returns the supplied MagicMock cursor.
    """
    fake_conn = MagicMock()
    if cursor is not None:
        fake_conn.cursor.return_value = cursor
    adapter = AthenaAdapter.__new__(AthenaAdapter)
    adapter._s3_staging_dir = "s3://test-bucket/athena/"
    adapter._region_name = "us-east-1"
    adapter._schema_name = "test_db"
    adapter._aws_access_key_id = None
    adapter._aws_secret_access_key = None
    adapter._aws_session_token = None
    adapter._conn = fake_conn
    return adapter


# ---------------------------------------------------------------------------
# Table name resolution
# ---------------------------------------------------------------------------

def test_full_table_unqualified_uses_schema():
    adapter = _make_adapter()
    assert adapter._full_table("orders") == "test_db.orders"


def test_full_table_two_part_passthrough():
    adapter = _make_adapter()
    assert adapter._full_table("other_db.orders") == "other_db.orders"


# ---------------------------------------------------------------------------
# NOT_NULL
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_not_null_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r1", "not_null", columns=["order_id"])
    result = await adapter.execute_rule(rule)
    assert result.passed
    assert result.row_count_checked == 100
    assert result.row_count_failed == 0


@pytest.mark.asyncio
async def test_not_null_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (7,)]
    cursor.fetchall.return_value = [(None,)]
    cursor.description = [("order_id",)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r2", "not_null", columns=["order_id"])
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 7


# ---------------------------------------------------------------------------
# UNIQUE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unique_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(50,), (0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r3", "unique", columns=["order_id"])
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_unique_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(50,), (3,)]
    cursor.fetchall.return_value = [(1, 2)]
    cursor.description = [("order_id",), ("cnt",)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r4", "unique", columns=["order_id"])
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 3


# ---------------------------------------------------------------------------
# SQL_EXPRESSION
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sql_expression_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(200,), (0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r5", "sql_expression", expression="revenue >= 0")
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_sql_expression_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(200,), (4,)]
    cursor.fetchall.return_value = [(-10,)]
    cursor.description = [("revenue",)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r6", "sql_expression", expression="revenue >= 0")
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 4


# ---------------------------------------------------------------------------
# ROW_COUNT
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_row_count_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(500,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r7", "row_count", threshold=100)
    result = await adapter.execute_rule(rule)
    assert result.passed
    assert result.row_count_checked == 500


@pytest.mark.asyncio
async def test_row_count_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(10,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r8", "row_count", threshold=100)
    result = await adapter.execute_rule(rule)
    assert not result.passed


# ---------------------------------------------------------------------------
# REGEX_MATCH  (Presto/Athena: regexp_like)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_regex_match_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r9", "regex_match", columns=["email"], pattern=r"^.+@.+\..+$")
    result = await adapter.execute_rule(rule)
    assert result.passed
    # Verify regexp_like was used in the SQL
    sql_calls = [str(call) for call in cursor.execute.call_args_list]
    assert any("regexp_like" in s for s in sql_calls)


@pytest.mark.asyncio
async def test_regex_match_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (7,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r10", "regex_match", columns=["email"], pattern=r"^.+@.+\..+$")
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 7


# ---------------------------------------------------------------------------
# ACCEPTED_VALUES
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_accepted_values_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(80,), (0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r11", "accepted_values", columns=["status"],
                      values=["active", "inactive"])
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_accepted_values_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(80,), (5,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r12", "accepted_values", columns=["status"],
                      values=["active", "inactive"])
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 5


# ---------------------------------------------------------------------------
# FRESHNESS  (Presto/Athena: date_diff)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_freshness_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [("2026-05-11",), (2,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r13", "freshness", columns=["updated_at"], threshold=24)
    result = await adapter.execute_rule(rule)
    assert result.passed
    # Verify date_diff was used
    sql_calls = [str(call) for call in cursor.execute.call_args_list]
    assert any("date_diff" in s for s in sql_calls)


@pytest.mark.asyncio
async def test_freshness_no_rows():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(None,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r14", "freshness", columns=["updated_at"], threshold=24)
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.error is not None


# ---------------------------------------------------------------------------
# RECONCILE_ROW_COUNT
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reconcile_row_count_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (100,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r15", "reconcile_row_count", source_table="staging.orders")
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_reconcile_row_count_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (80,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r16", "reconcile_row_count", source_table="staging.orders")
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.failure_sample[0]["source_rows"] == 100
    assert result.failure_sample[0]["target_rows"] == 80


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_calls_conn_close():
    fake_conn = MagicMock()
    adapter = AthenaAdapter.__new__(AthenaAdapter)
    adapter._conn = fake_conn
    await adapter.close()
    fake_conn.close.assert_called_once()
    assert adapter._conn is None


@pytest.mark.asyncio
async def test_close_noop_when_no_conn():
    adapter = AthenaAdapter.__new__(AthenaAdapter)
    adapter._conn = None
    # Should not raise
    await adapter.close()


# ---------------------------------------------------------------------------
# Error handling — cursor.execute raises
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_raises_returns_error_result():
    cursor = MagicMock()
    cursor.execute.side_effect = Exception("Athena query timeout")
    adapter = _make_adapter(cursor)
    rule = _make_rule("r17", "not_null", columns=["order_id"])
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert "Athena query timeout" in result.error


# ---------------------------------------------------------------------------
# Unsupported rule type
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unsupported_rule_type_returns_error():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r18", "row_count", threshold=1)
    object.__setattr__(rule.spec_logic, "type", "nonexistent_type")  # type: ignore[arg-type]
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.error is not None


# ---------------------------------------------------------------------------
# NULL_PERCENTAGE_BELOW
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_null_percentage_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (3,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r19", "null_percentage_below", columns=["desc"], threshold=5.0)
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_null_percentage_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (10,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r20", "null_percentage_below", columns=["desc"], threshold=5.0)
    result = await adapter.execute_rule(rule)
    assert not result.passed


# ---------------------------------------------------------------------------
# COLUMN_EXISTS  (Athena: information_schema.columns)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_column_exists_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(1,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r21", "column_exists", table="orders", columns=["order_id"])
    result = await adapter.execute_rule(rule)
    assert result.passed
    sql_calls = [str(call) for call in cursor.execute.call_args_list]
    assert any("information_schema.columns" in s for s in sql_calls)


@pytest.mark.asyncio
async def test_column_exists_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r22", "column_exists", table="orders", columns=["nonexistent"])
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 1
