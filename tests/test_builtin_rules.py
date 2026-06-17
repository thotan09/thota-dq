"""Tests for the 30 built-in rule types and the builtin catalog."""

from __future__ import annotations

import asyncio

import pytest

from thota_dq.adapters.warehouse.duckdb import DuckDBAdapter
from thota_dq.rules.builtin import CATALOG, get_template
from thota_dq.rules.schema import (
    DataQualityRule,
    RuleLogic,
    RuleMetadata,
    RuleScope,
    RuleType,
    Severity,
)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

async def _setup(adapter: DuckDBAdapter, *statements: str) -> None:
    """Run SQL in the adapter's executor thread — ensures connection lives there."""
    loop = asyncio.get_running_loop()

    def _run() -> None:
        conn = adapter._get_conn()
        for sql in statements:
            conn.execute(sql)

    await loop.run_in_executor(adapter._executor, _run)


def make_rule(rule_type: RuleType, table: str = "t", columns: list[str] | None = None, **kwargs) -> DataQualityRule:
    return DataQualityRule(
        apiVersion="thota_dq.dev/v1",
        metadata=RuleMetadata(id=f"test_{rule_type.value}", severity=Severity.HIGH),
        scope=RuleScope(table=table, columns=columns or []),
        logic=RuleLogic(type=rule_type, **kwargs),
    )


# ──────────────────────────────────────────────────────────────────────────────
# not_empty_string
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def adapter_strings():
    adapter = DuckDBAdapter(":memory:")
    await _setup(
        adapter,
        "CREATE TABLE t (name VARCHAR)",
        "INSERT INTO t VALUES ('Alice'), (''), ('  '), (NULL), ('Bob')",
    )
    return adapter


@pytest.mark.asyncio
async def test_not_empty_string_fails(adapter_strings):
    rule = make_rule(RuleType.NOT_EMPTY_STRING, columns=["name"])
    result = await adapter_strings.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 3  # empty string, whitespace, NULL


@pytest.mark.asyncio
async def test_not_empty_string_passes():
    adapter = DuckDBAdapter(":memory:")
    await _setup(
        adapter,
        "CREATE TABLE t (name VARCHAR)",
        "INSERT INTO t VALUES ('Alice'), ('Bob'), ('Charlie')",
    )
    rule = make_rule(RuleType.NOT_EMPTY_STRING, columns=["name"])
    result = await adapter.execute_rule(rule)
    assert result.passed
    assert result.row_count_failed == 0


# ──────────────────────────────────────────────────────────────────────────────
# between
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def adapter_numbers():
    adapter = DuckDBAdapter(":memory:")
    await _setup(
        adapter,
        "CREATE TABLE t (val FLOAT)",
        "INSERT INTO t VALUES (1.0), (5.0), (10.0), (15.0), (-3.0)",
    )
    return adapter


@pytest.mark.asyncio
async def test_between_fails_outside_range(adapter_numbers):
    rule = make_rule(RuleType.BETWEEN, columns=["val"], min_value=0.0, max_value=10.0)
    result = await adapter_numbers.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 2  # 15.0 and -3.0


@pytest.mark.asyncio
async def test_between_passes_inside_range():
    adapter = DuckDBAdapter(":memory:")
    await _setup(
        adapter,
        "CREATE TABLE t (val FLOAT)",
        "INSERT INTO t VALUES (1.0), (5.0), (9.9)",
    )
    rule = make_rule(RuleType.BETWEEN, columns=["val"], min_value=0.0, max_value=10.0)
    result = await adapter.execute_rule(rule)
    assert result.passed
    assert result.row_count_failed == 0


# ──────────────────────────────────────────────────────────────────────────────
# regex_match (email)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def adapter_emails():
    adapter = DuckDBAdapter(":memory:")
    await _setup(
        adapter,
        "CREATE TABLE t (email VARCHAR)",
        "INSERT INTO t VALUES ('user@example.com'), ('bad-email'), ('another@test.org')",
    )
    return adapter


EMAIL_PATTERN = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"


@pytest.mark.asyncio
async def test_regex_match_fails_invalid_email(adapter_emails):
    rule = make_rule(RuleType.REGEX_MATCH, columns=["email"], pattern=EMAIL_PATTERN)
    result = await adapter_emails.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 1  # 'bad-email'


@pytest.mark.asyncio
async def test_regex_match_passes_valid_emails():
    adapter = DuckDBAdapter(":memory:")
    await _setup(
        adapter,
        "CREATE TABLE t (email VARCHAR)",
        "INSERT INTO t VALUES ('alice@example.com'), ('bob@test.co.uk')",
    )
    rule = make_rule(RuleType.REGEX_MATCH, columns=["email"], pattern=EMAIL_PATTERN)
    result = await adapter.execute_rule(rule)
    assert result.passed


# ──────────────────────────────────────────────────────────────────────────────
# accepted_values
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def adapter_status():
    adapter = DuckDBAdapter(":memory:")
    await _setup(
        adapter,
        "CREATE TABLE t (status VARCHAR)",
        "INSERT INTO t VALUES ('active'), ('inactive'), ('banned'), ('pending')",
    )
    return adapter


@pytest.mark.asyncio
async def test_accepted_values_fails_unknown(adapter_status):
    rule = make_rule(
        RuleType.ACCEPTED_VALUES,
        columns=["status"],
        values=["active", "inactive"],
    )
    result = await adapter_status.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 2  # 'banned' and 'pending'


@pytest.mark.asyncio
async def test_accepted_values_passes():
    adapter = DuckDBAdapter(":memory:")
    await _setup(
        adapter,
        "CREATE TABLE t (status VARCHAR)",
        "INSERT INTO t VALUES ('active'), ('inactive')",
    )
    rule = make_rule(
        RuleType.ACCEPTED_VALUES,
        columns=["status"],
        values=["active", "inactive"],
    )
    result = await adapter.execute_rule(rule)
    assert result.passed


# ──────────────────────────────────────────────────────────────────────────────
# foreign_key
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def adapter_fk():
    adapter = DuckDBAdapter(":memory:")
    await _setup(
        adapter,
        "CREATE TABLE customers (id INT)",
        "INSERT INTO customers VALUES (1), (2), (3)",
        "CREATE TABLE orders (customer_id INT)",
        "INSERT INTO orders VALUES (1), (2), (99)",  # 99 is orphan
    )
    return adapter


@pytest.mark.asyncio
async def test_foreign_key_fails_orphan(adapter_fk):
    rule = DataQualityRule(
        apiVersion="thota_dq.dev/v1",
        metadata=RuleMetadata(id="test_fk", severity=Severity.HIGH),
        scope=RuleScope(table="orders", columns=["customer_id"]),
        logic=RuleLogic(
            type=RuleType.FOREIGN_KEY,
            reference_table="customers",
            reference_column="id",
        ),
    )
    result = await adapter_fk.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 1  # row with customer_id=99


@pytest.mark.asyncio
async def test_foreign_key_passes_valid():
    adapter = DuckDBAdapter(":memory:")
    await _setup(
        adapter,
        "CREATE TABLE customers (id INT)",
        "INSERT INTO customers VALUES (1), (2), (3)",
        "CREATE TABLE orders (customer_id INT)",
        "INSERT INTO orders VALUES (1), (2), (3)",
    )
    rule = DataQualityRule(
        apiVersion="thota_dq.dev/v1",
        metadata=RuleMetadata(id="test_fk_pass", severity=Severity.HIGH),
        scope=RuleScope(table="orders", columns=["customer_id"]),
        logic=RuleLogic(
            type=RuleType.FOREIGN_KEY,
            reference_table="customers",
            reference_column="id",
        ),
    )
    result = await adapter.execute_rule(rule)
    assert result.passed


# ──────────────────────────────────────────────────────────────────────────────
# null_percentage_below
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def adapter_nulls():
    adapter = DuckDBAdapter(":memory:")
    # 4 NULLs out of 10 = 40%
    await _setup(
        adapter,
        "CREATE TABLE t (val INT)",
        "INSERT INTO t VALUES (1),(2),(3),(4),(5),(6),(NULL),(NULL),(NULL),(NULL)",
    )
    return adapter


@pytest.mark.asyncio
async def test_null_pct_fails_exceeds_threshold(adapter_nulls):
    rule = make_rule(RuleType.NULL_PERCENTAGE_BELOW, columns=["val"], threshold=5.0)
    result = await adapter_nulls.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 4  # 4 nulls


@pytest.mark.asyncio
async def test_null_pct_passes_below_threshold(adapter_nulls):
    rule = make_rule(RuleType.NULL_PERCENTAGE_BELOW, columns=["val"], threshold=50.0)
    result = await adapter_nulls.execute_rule(rule)
    assert result.passed


# ──────────────────────────────────────────────────────────────────────────────
# no_future_dates
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def adapter_dates():
    adapter = DuckDBAdapter(":memory:")
    await _setup(
        adapter,
        "CREATE TABLE t (dt DATE)",
        "INSERT INTO t VALUES ('2020-01-01'), ('2023-06-15'), ('2099-12-31')",
    )
    return adapter


@pytest.mark.asyncio
async def test_no_future_dates_fails(adapter_dates):
    rule = make_rule(RuleType.NO_FUTURE_DATES, columns=["dt"])
    result = await adapter_dates.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 1  # 2099-12-31


@pytest.mark.asyncio
async def test_no_future_dates_passes():
    adapter = DuckDBAdapter(":memory:")
    await _setup(
        adapter,
        "CREATE TABLE t (dt DATE)",
        "INSERT INTO t VALUES ('2020-01-01'), ('2023-06-15')",
    )
    rule = make_rule(RuleType.NO_FUTURE_DATES, columns=["dt"])
    result = await adapter.execute_rule(rule)
    assert result.passed


# ──────────────────────────────────────────────────────────────────────────────
# composite_unique
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def adapter_composite():
    adapter = DuckDBAdapter(":memory:")
    # (1,1) appears twice — duplicate combo
    await _setup(
        adapter,
        "CREATE TABLE t (a INT, b INT)",
        "INSERT INTO t VALUES (1,1),(1,2),(1,1),(2,2)",
    )
    return adapter


@pytest.mark.asyncio
async def test_composite_unique_fails_duplicate_combo(adapter_composite):
    rule = DataQualityRule(
        apiVersion="thota_dq.dev/v1",
        metadata=RuleMetadata(id="test_comp_unique", severity=Severity.HIGH),
        scope=RuleScope(table="t", columns=["a", "b"]),
        logic=RuleLogic(type=RuleType.COMPOSITE_UNIQUE),
    )
    result = await adapter_composite.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 1  # one extra duplicate


@pytest.mark.asyncio
async def test_composite_unique_passes():
    adapter = DuckDBAdapter(":memory:")
    await _setup(
        adapter,
        "CREATE TABLE t (a INT, b INT)",
        "INSERT INTO t VALUES (1,1),(1,2),(2,1),(2,2)",
    )
    rule = DataQualityRule(
        apiVersion="thota_dq.dev/v1",
        metadata=RuleMetadata(id="test_comp_unique_pass", severity=Severity.HIGH),
        scope=RuleScope(table="t", columns=["a", "b"]),
        logic=RuleLogic(type=RuleType.COMPOSITE_UNIQUE),
    )
    result = await adapter.execute_rule(rule)
    assert result.passed


# ──────────────────────────────────────────────────────────────────────────────
# column_exists
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def adapter_schema():
    adapter = DuckDBAdapter(":memory:")
    await _setup(
        adapter,
        "CREATE TABLE t (real_col INT)",
        "INSERT INTO t VALUES (1)",
    )
    return adapter


@pytest.mark.asyncio
async def test_column_exists_passes(adapter_schema):
    rule = make_rule(RuleType.COLUMN_EXISTS, columns=["real_col"])
    result = await adapter_schema.execute_rule(rule)
    assert result.passed
    assert result.row_count_failed == 0


@pytest.mark.asyncio
async def test_column_exists_fails_missing(adapter_schema):
    rule = make_rule(RuleType.COLUMN_EXISTS, columns=["nonexistent_col"])
    result = await adapter_schema.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 1


# ──────────────────────────────────────────────────────────────────────────────
# mean_between
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def adapter_mean():
    adapter = DuckDBAdapter(":memory:")
    await _setup(
        adapter,
        "CREATE TABLE t (score FLOAT)",
        "INSERT INTO t VALUES (10.0),(20.0),(30.0),(40.0),(50.0)",  # mean = 30
    )
    return adapter


@pytest.mark.asyncio
async def test_mean_between_fails_outside_range(adapter_mean):
    rule = make_rule(RuleType.MEAN_BETWEEN, columns=["score"], min_value=0.0, max_value=25.0)
    result = await adapter_mean.execute_rule(rule)
    assert not result.passed
    assert result.row_count_failed == 1
    assert len(result.failure_sample) == 1
    assert result.failure_sample[0]["mean"] == pytest.approx(30.0)


@pytest.mark.asyncio
async def test_mean_between_passes(adapter_mean):
    rule = make_rule(RuleType.MEAN_BETWEEN, columns=["score"], min_value=25.0, max_value=35.0)
    result = await adapter_mean.execute_rule(rule)
    assert result.passed
    assert result.row_count_failed == 0


# ──────────────────────────────────────────────────────────────────────────────
# Catalog integrity
# ──────────────────────────────────────────────────────────────────────────────

def test_catalog_has_exactly_30_templates():
    assert len(CATALOG) == 30


def test_catalog_all_names_unique():
    names = [t.name for t in CATALOG]
    assert len(names) == len(set(names)), "Duplicate template names found"


def test_get_template_found():
    t = get_template("email_format")
    assert t is not None
    assert t.name == "email_format"
    assert t.category == "validity"


def test_get_template_not_found():
    t = get_template("does_not_exist")
    assert t is None


def test_catalog_all_have_required_fields():
    for t in CATALOG:
        assert t.name, f"Template missing name: {t}"
        assert t.category, f"Template missing category: {t.name}"
        assert t.description, f"Template missing description: {t.name}"
        assert t.logic, f"Template missing logic: {t.name}"
        assert t.default_severity, f"Template missing default_severity: {t.name}"
        assert "type" in t.logic, f"Template logic missing 'type': {t.name}"
