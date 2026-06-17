"""Tests for the PostgreSQL/Redshift warehouse adapter (fully mocked — no real DB needed)."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from thota_dq.rules.schema import DataQualityRule

# ---------------------------------------------------------------------------
# Install a fake psycopg2 into sys.modules before importing the adapter
# ---------------------------------------------------------------------------


def _install_psycopg2_mock() -> MagicMock:
    pg_mod = types.ModuleType("psycopg2")
    fake_conn = MagicMock()
    fake_cursor = MagicMock()
    fake_conn.cursor.return_value = fake_cursor
    pg_mod.connect = MagicMock(return_value=fake_conn)
    sys.modules["psycopg2"] = pg_mod
    return fake_cursor


_install_psycopg2_mock()

from thota_dq.adapters.warehouse.postgres import PostgresAdapter  # noqa: E402

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
    return DataQualityRule.model_validate(
        {
            "apiVersion": "thota_dq.dev/v1",
            "kind": "DataQualityRule",
            "metadata": {"id": rule_id, "severity": "high"},
            "scope": {"table": table, "columns": columns or []},
            "logic": logic,
        }
    )


def _make_cursor(scalar: int | float | str | None = 0, rows: list | None = None) -> MagicMock:
    """Return a fresh MagicMock cursor with configurable fetchone / fetchall."""
    c = MagicMock()
    c.fetchone.return_value = (scalar,)
    c.fetchall.return_value = rows or []
    c.description = None
    return c


def _make_adapter(cursor: MagicMock | None = None) -> PostgresAdapter:
    """
    Build a PostgresAdapter bypassing __init__. Attach a fake connection
    whose cursor() returns the supplied MagicMock cursor.
    """
    fake_conn = MagicMock()
    if cursor is not None:
        fake_conn.cursor.return_value = cursor
    adapter = PostgresAdapter.__new__(PostgresAdapter)
    adapter._host = "localhost"
    adapter._port = 5432
    adapter._dbname = "postgres"
    adapter._user = "postgres"
    adapter._password = ""
    adapter._schema = "public"
    adapter._dsn = None
    adapter._conn = fake_conn
    return adapter


# ---------------------------------------------------------------------------
# Table name resolution
# ---------------------------------------------------------------------------


def test_full_table_unqualified_uses_schema():
    adapter = _make_adapter()
    assert adapter._full_table("orders") == "public.orders"


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
# REGEX_MATCH  (PostgreSQL: ~ operator, NOT regexp_like)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regex_match_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r9", "regex_match", columns=["email"], pattern=r"^.+@.+\..+$")
    result = await adapter.execute_rule(rule)
    assert result.passed
    # Verify ~ was used in the SQL (not regexp_like)
    sql_calls = [str(call) for call in cursor.execute.call_args_list]
    assert any("~" in s for s in sql_calls)
    assert not any("regexp_like" in s for s in sql_calls)


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
    rule = _make_rule("r11", "accepted_values", columns=["status"], values=["active", "inactive"])
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_accepted_values_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(80,), (5,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r12", "accepted_values", columns=["status"], values=["active", "inactive"])
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 5


# ---------------------------------------------------------------------------
# FRESHNESS  (PostgreSQL: EXTRACT(EPOCH FROM ...), NOT date_diff)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_freshness_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [("2026-05-11",), (2,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r13", "freshness", columns=["updated_at"], threshold=24)
    result = await adapter.execute_rule(rule)
    assert result.passed
    # Verify EXTRACT was used (not date_diff)
    sql_calls = [str(call) for call in cursor.execute.call_args_list]
    assert any("EXTRACT" in s for s in sql_calls)
    assert not any("date_diff" in s for s in sql_calls)


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
    adapter = PostgresAdapter.__new__(PostgresAdapter)
    adapter._conn = fake_conn
    await adapter.close()
    fake_conn.close.assert_called_once()
    assert adapter._conn is None


@pytest.mark.asyncio
async def test_close_noop_when_no_conn():
    adapter = PostgresAdapter.__new__(PostgresAdapter)
    adapter._conn = None
    # Should not raise
    await adapter.close()


# ---------------------------------------------------------------------------
# Error handling — cursor.execute raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_raises_returns_error_result():
    cursor = MagicMock()
    cursor.execute.side_effect = Exception("connection refused")
    adapter = _make_adapter(cursor)
    rule = _make_rule("r17", "not_null", columns=["order_id"])
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert "connection refused" in result.error


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
# COLUMN_EXISTS  (PostgreSQL: information_schema.columns)
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


# ---------------------------------------------------------------------------
# DSN — verify psycopg2.connect is called with the DSN string
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dsn_used_when_provided():
    import psycopg2  # the mocked module in sys.modules

    # Reset the module-level mock to a fresh state so we can verify the call
    fake_conn = MagicMock()
    fake_cursor = MagicMock()
    fake_cursor.fetchone.return_value = (100,)
    fake_cursor.fetchall.return_value = []
    fake_cursor.description = None
    fake_conn.cursor.return_value = fake_cursor
    psycopg2.connect = MagicMock(return_value=fake_conn)

    dsn_string = "postgresql://user:pass@host:5432/mydb"
    adapter = PostgresAdapter(dsn=dsn_string)
    rule = _make_rule("r23", "row_count", threshold=1)

    # The second fetchone call (row_count_failed check) also needs a value
    fake_cursor.fetchone.side_effect = [(500,)]

    await adapter.execute_rule(rule)

    psycopg2.connect.assert_called_once_with(dsn_string)


# ---------------------------------------------------------------------------
# NOT_EMPTY_STRING  (PostgreSQL: CAST ... AS TEXT, not VARCHAR)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_not_empty_string_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r24", "not_empty_string", columns=["name"])
    result = await adapter.execute_rule(rule)
    assert result.passed
    sql_calls = [str(call) for call in cursor.execute.call_args_list]
    # Verify TEXT cast was used (not VARCHAR)
    assert any("TEXT" in s for s in sql_calls)
    assert not any("VARCHAR" in s for s in sql_calls)


@pytest.mark.asyncio
async def test_not_empty_string_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (3,)]
    cursor.fetchall.return_value = [("",)]
    cursor.description = [("name",)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r25", "not_empty_string", columns=["name"])
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 3


# ---------------------------------------------------------------------------
# COMPOSITE_UNIQUE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_unique_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(200,), (0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r26", "composite_unique", columns=["order_id", "product_id"])
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_composite_unique_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(200,), (5,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r27", "composite_unique", columns=["order_id", "product_id"])
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 5


# ---------------------------------------------------------------------------
# BETWEEN
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_between_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r28", "between", columns=["price"], min_value=0, max_value=1000)
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_between_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (2,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r29", "between", columns=["price"], min_value=0, max_value=1000)
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 2


# ---------------------------------------------------------------------------
# MIN_VALUE_CHECK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_min_value_check_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r30", "min_value_check", columns=["age"], min_value=0)
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_min_value_check_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (4,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r31", "min_value_check", columns=["age"], min_value=0)
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 4


# ---------------------------------------------------------------------------
# MAX_VALUE_CHECK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_value_check_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r32", "max_value_check", columns=["discount"], max_value=100)
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_max_value_check_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (2,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r33", "max_value_check", columns=["discount"], max_value=100)
    result = await adapter.execute_rule(rule)
    assert not result.passed


# ---------------------------------------------------------------------------
# NOT_ACCEPTED_VALUES
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_not_accepted_values_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r34", "not_accepted_values", columns=["status"], values=["deleted"])
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_not_accepted_values_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (3,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r35", "not_accepted_values", columns=["status"], values=["deleted"])
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 3


# ---------------------------------------------------------------------------
# FOREIGN_KEY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_foreign_key_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule(
        "r36",
        "foreign_key",
        columns=["customer_id"],
        reference_table="customers",
        reference_column="id",
    )
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_foreign_key_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (6,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule(
        "r37",
        "foreign_key",
        columns=["customer_id"],
        reference_table="customers",
        reference_column="id",
    )
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 6


# ---------------------------------------------------------------------------
# DUPLICATE_PERCENTAGE_BELOW
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_percentage_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (1,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r38", "duplicate_percentage_below", columns=["email"], threshold=5.0)
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_duplicate_percentage_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (20,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r39", "duplicate_percentage_below", columns=["email"], threshold=5.0)
    result = await adapter.execute_rule(rule)
    assert not result.passed


# ---------------------------------------------------------------------------
# MEAN_BETWEEN
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mean_between_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (50.0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r40", "mean_between", columns=["score"], min_value=10, max_value=90)
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_mean_between_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (5.0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r41", "mean_between", columns=["score"], min_value=10, max_value=90)
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.failure_sample[0]["mean"] == 5.0


# ---------------------------------------------------------------------------
# STDDEV_BELOW
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stddev_below_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (3.0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r42", "stddev_below", columns=["price"], threshold=10.0)
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_stddev_below_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (15.0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r43", "stddev_below", columns=["price"], threshold=10.0)
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.failure_sample[0]["stddev"] == 15.0


# ---------------------------------------------------------------------------
# NO_FUTURE_DATES
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_future_dates_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r44", "no_future_dates", columns=["created_at"])
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_no_future_dates_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (2,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r45", "no_future_dates", columns=["created_at"])
    result = await adapter.execute_rule(rule)
    assert not result.passed


# ---------------------------------------------------------------------------
# DATE_ORDER
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_date_order_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r46", "date_order", columns=["start_date"], column_b="end_date")
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_date_order_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (3,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r47", "date_order", columns=["start_date"], column_b="end_date")
    result = await adapter.execute_rule(rule)
    assert not result.passed


# ---------------------------------------------------------------------------
# ROW_COUNT_BETWEEN
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_row_count_between_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(500,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r48", "row_count_between", min_value=100, max_value=1000)
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_row_count_between_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(5,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r49", "row_count_between", min_value=100, max_value=1000)
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.failure_sample[0]["row_count"] == 5


# ---------------------------------------------------------------------------
# COLUMN_SUM_BETWEEN
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_column_sum_between_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (500.0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule(
        "r50", "column_sum_between", columns=["amount"], min_value=100, max_value=1000
    )
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_column_sum_between_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (5.0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule(
        "r51", "column_sum_between", columns=["amount"], min_value=100, max_value=1000
    )
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.failure_sample[0]["sum"] == 5.0


# ---------------------------------------------------------------------------
# CONDITIONAL_NOT_NULL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conditional_not_null_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule(
        "r52", "conditional_not_null", columns=["shipped_at"], condition="status = 'shipped'"
    )
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_conditional_not_null_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (4,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule(
        "r53", "conditional_not_null", columns=["shipped_at"], condition="status = 'shipped'"
    )
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 4


# ---------------------------------------------------------------------------
# RECONCILE_COLUMN_SUM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_column_sum_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(1000.0,), (1000.0,), (100,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule(
        "r54", "reconcile_column_sum", columns=["revenue"], source_table="staging.orders"
    )
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_reconcile_column_sum_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(1000.0,), (500.0,), (100,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule(
        "r55", "reconcile_column_sum", columns=["revenue"], source_table="staging.orders"
    )
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.failure_sample[0]["source_sum"] == 1000.0
    assert result.failure_sample[0]["target_sum"] == 500.0


# ---------------------------------------------------------------------------
# RECONCILE_KEY_MATCH
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_key_match_pass():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (0,), (0,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule(
        "r56", "reconcile_key_match", columns=["order_id"], source_table="staging.orders"
    )
    result = await adapter.execute_rule(rule)
    assert result.passed


@pytest.mark.asyncio
async def test_reconcile_key_match_fail():
    cursor = _make_cursor()
    cursor.fetchone.side_effect = [(100,), (3,), (2,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule(
        "r57", "reconcile_key_match", columns=["order_id"], source_table="staging.orders"
    )
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 5
    assert result.failure_sample[0]["missing_in_target"] == 3
    assert result.failure_sample[0]["missing_in_source"] == 2


# ---------------------------------------------------------------------------
# CUSTOM_SQL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_sql_pass():
    # 0 rows returned = no violations = PASS
    cursor = _make_cursor()
    cursor.fetchall.return_value = []
    adapter = _make_adapter(cursor)
    rule = _make_rule(
        "r58", "custom_sql", query="SELECT order_id FROM orders WHERE order_id IS NULL"
    )
    result = await adapter.execute_rule(rule)
    assert result.passed
    assert result.row_count_failed == 0


@pytest.mark.asyncio
async def test_custom_sql_fail():
    # rows returned = violations = FAIL
    cursor = _make_cursor()
    cursor.fetchall.return_value = [(1,), (2,), (3,)]
    adapter = _make_adapter(cursor)
    rule = _make_rule("r59", "custom_sql", query="SELECT order_id FROM orders WHERE amount < 0")
    result = await adapter.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 3
