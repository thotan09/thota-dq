"""Tests for Issue #22 — ML/statistical anomaly detection rule types."""
from __future__ import annotations

import math

import pytest

from thota_dq.rules.anomaly import (
    check_learned_threshold,
    isolation_forest_detect,
    zscore_outlier_sql,
)
from thota_dq.rules.schema import DataQualityRule, RuleLogic, RuleMetadata, RuleScope, RuleType

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_rule(rule_type: str, col: str, table: str = "t", **logic_kwargs) -> DataQualityRule:
    return DataQualityRule(
        apiVersion="thota_dq.dev/v1",
        kind="DataQualityRule",
        metadata=RuleMetadata(id=f"test_{rule_type}", severity="medium"),
        scope=RuleScope(table=table, columns=[col]),
        logic=RuleLogic(type=RuleType(rule_type), **logic_kwargs),
    )


# ---------------------------------------------------------------------------
# Unit tests — anomaly.py helpers
# ---------------------------------------------------------------------------

class TestZscoreOutlierSql:
    def test_returns_two_strings(self):
        count_sql, sample_sql = zscore_outlier_sql("my_table", "value", 3.0)
        assert "COUNT(*)" in count_sql
        assert "LIMIT 5" in sample_sql

    def test_threshold_embedded(self):
        count_sql, _ = zscore_outlier_sql("t", "col", 2.5)
        assert "2.5" in count_sql

    def test_column_embedded(self):
        count_sql, _ = zscore_outlier_sql("t", "price", 3.0)
        assert "price" in count_sql


class TestIsolationForestDetect:
    def test_returns_list_of_bools(self):
        values = list(range(20))
        result = isolation_forest_detect(values, contamination=0.1)
        assert len(result) == 20
        assert all(isinstance(r, bool) for r in result)

    def test_small_dataset_all_normal(self):
        result = isolation_forest_detect([1.0, 2.0, 3.0], contamination=0.1)
        assert result == [False, False, False]

    def test_obvious_outlier_detected(self):
        # 18 normal values clustered around 0, 2 extreme outliers
        normal = list(range(-9, 9))
        outliers = [1000.0, -1000.0]
        values = normal + outliers
        result = isolation_forest_detect(values, contamination=0.1)
        # The two extreme values should be flagged
        assert result[-2] is True or result[-1] is True

    def test_missing_sklearn_raises_runtime_error(self, monkeypatch):
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name in ("sklearn", "sklearn.ensemble"):
                raise ImportError("mocked missing")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        with pytest.raises(RuntimeError, match="scikit-learn"):
            isolation_forest_detect([1.0, 2.0], contamination=0.1)


class TestCheckLearnedThreshold:
    def test_insufficient_history_passes(self):
        passed, details = check_learned_threshold(50.0, [], zscore_threshold=3.0)
        assert passed is True
        assert details["reason"] == "insufficient_history"

    def test_one_history_point_passes(self):
        passed, details = check_learned_threshold(50.0, [49.0], zscore_threshold=3.0)
        assert passed is True

    def test_normal_value_passes(self):
        # history: mean=100, stddev~0
        history = [100.0] * 10
        passed, details = check_learned_threshold(100.0, history, zscore_threshold=3.0)
        assert passed is True

    def test_extreme_outlier_fails(self):
        history = [10.0, 10.5, 9.5, 10.2, 9.8, 10.1, 10.3, 9.9, 10.0, 10.4]
        passed, details = check_learned_threshold(50.0, history, zscore_threshold=3.0)
        assert passed is False
        assert details["zscore"] > 3.0

    def test_borderline_at_threshold(self):
        # Craft a history where z=3 exactly lands at the boundary
        history = [0.0, 2.0]  # mean=1.0, stddev~=1.41
        mean, std = 1.0, math.sqrt(2)
        # value at z=3.0: mean + 3*std
        boundary_val = mean + 3.0 * std
        passed, details = check_learned_threshold(boundary_val, history, zscore_threshold=3.0)
        assert passed is True

    def test_details_contain_expected_keys(self):
        history = [10.0] * 5 + [11.0] * 5
        _, details = check_learned_threshold(12.0, history, zscore_threshold=3.0)
        for key in ("current_mean", "historical_mean", "historical_stddev", "zscore", "threshold", "history_count"):
            assert key in details


# ---------------------------------------------------------------------------
# Integration tests — DuckDB adapter
# ---------------------------------------------------------------------------

@pytest.fixture
def duckdb_adapter():
    from thota_dq.adapters.warehouse.duckdb import DuckDBAdapter
    adapter = DuckDBAdapter(":memory:")
    # Pre-populate a table with numeric data
    conn = adapter._get_conn()
    conn.execute("CREATE TABLE measurements (id INTEGER, value DOUBLE)")
    # 18 normal values + 2 obvious outliers
    for i, v in enumerate(list(range(1, 19)) + [1000.0, -1000.0]):
        conn.execute("INSERT INTO measurements VALUES (?, ?)", [i, v])
    return adapter


@pytest.mark.asyncio
async def test_zscore_outlier_detects_outliers(duckdb_adapter):
    rule = _make_rule("zscore_outlier", "value", table="measurements", zscore_threshold=3.0)
    result = await duckdb_adapter.execute_rule(rule)
    assert result.passed is False
    assert result.row_count_failed >= 1


@pytest.mark.asyncio
async def test_zscore_outlier_passes_clean_data():
    from thota_dq.adapters.warehouse.duckdb import DuckDBAdapter
    adapter = DuckDBAdapter(":memory:")
    conn = adapter._get_conn()
    conn.execute("CREATE TABLE clean (val DOUBLE)")
    for v in [10.0, 10.1, 9.9, 10.05, 9.95, 10.2, 9.8]:
        conn.execute("INSERT INTO clean VALUES (?)", [v])
    rule = _make_rule("zscore_outlier", "val", table="clean", zscore_threshold=3.0)
    result = await adapter.execute_rule(rule)
    assert result.passed is True


@pytest.mark.asyncio
async def test_isolation_forest_detects_outliers(duckdb_adapter):
    rule = _make_rule("isolation_forest", "value", table="measurements", contamination=0.1)
    result = await duckdb_adapter.execute_rule(rule)
    assert result.passed is False
    assert result.row_count_failed >= 1


@pytest.mark.asyncio
async def test_isolation_forest_small_dataset_passes():
    from thota_dq.adapters.warehouse.duckdb import DuckDBAdapter
    adapter = DuckDBAdapter(":memory:")
    conn = adapter._get_conn()
    conn.execute("CREATE TABLE tiny (val DOUBLE)")
    for v in [1.0, 2.0, 3.0]:
        conn.execute("INSERT INTO tiny VALUES (?)", [v])
    rule = _make_rule("isolation_forest", "val", table="tiny", contamination=0.1)
    result = await adapter.execute_rule(rule)
    # < 10 rows → all treated as normal
    assert result.passed is True


@pytest.mark.asyncio
async def test_learned_threshold_no_history_passes(duckdb_adapter, tmp_path):
    import thota_dq.memory.column_stats as cs_mod
    # Point the module at an empty temp DB so there's no history
    original = cs_mod.DB_PATH
    cs_mod.DB_PATH = tmp_path / "empty.db"
    try:
        rule = _make_rule("learned_threshold", "value", table="measurements", zscore_threshold=3.0)
        result = await duckdb_adapter.execute_rule(rule)
        # No history → should pass (insufficient_history)
        assert result.passed is True
    finally:
        cs_mod.DB_PATH = original


@pytest.mark.asyncio
async def test_learned_threshold_anomalous_mean_fails(tmp_path):
    import thota_dq.memory.column_stats as cs_mod
    from thota_dq.adapters.warehouse.duckdb import DuckDBAdapter

    cs_mod.DB_PATH = tmp_path / "stats.db"
    from thota_dq.memory.column_stats import save_column_stats

    # Seed 10 historical runs all around mean=10
    for i in range(10):
        await save_column_stats(
            run_id=f"run_{i}",
            table="sales",
            column="amount",
            row_count=100,
            mean_val=10.0 + (i % 2) * 0.1,
            stddev_val=0.5,
            min_val=9.0,
            max_val=11.0,
            path=cs_mod.DB_PATH,
        )

    # Current batch has a wildly different mean
    adapter = DuckDBAdapter(":memory:")
    conn = adapter._get_conn()
    conn.execute("CREATE TABLE sales (amount DOUBLE)")
    for v in [1000.0] * 20:
        conn.execute("INSERT INTO sales VALUES (?)", [v])

    rule = _make_rule("learned_threshold", "amount", table="sales", zscore_threshold=3.0)
    result = await adapter.execute_rule(rule)
    assert result.passed is False
    assert result.row_count_failed == 1
    assert "zscore" in result.failure_sample[0]

    cs_mod.DB_PATH = tmp_path / "stats.db"  # cleanup reference


@pytest.mark.asyncio
async def test_learned_threshold_normal_mean_passes(tmp_path):
    import thota_dq.memory.column_stats as cs_mod
    from thota_dq.adapters.warehouse.duckdb import DuckDBAdapter

    cs_mod.DB_PATH = tmp_path / "stats2.db"
    from thota_dq.memory.column_stats import save_column_stats

    for i in range(10):
        await save_column_stats(
            run_id=f"run_{i}",
            table="orders",
            column="total",
            row_count=50,
            mean_val=100.0 + i * 0.5,
            stddev_val=2.0,
            min_val=90.0,
            max_val=110.0,
            path=cs_mod.DB_PATH,
        )

    adapter = DuckDBAdapter(":memory:")
    conn = adapter._get_conn()
    conn.execute("CREATE TABLE orders (total DOUBLE)")
    for v in [100.0, 101.0, 99.5, 100.5, 102.0]:
        conn.execute("INSERT INTO orders VALUES (?)", [v])

    rule = _make_rule("learned_threshold", "total", table="orders", zscore_threshold=3.0)
    result = await adapter.execute_rule(rule)
    assert result.passed is True


# ---------------------------------------------------------------------------
# Column stats store
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_and_load_column_stats(tmp_path):
    import thota_dq.memory.column_stats as cs_mod
    cs_mod.DB_PATH = tmp_path / "cs.db"
    from thota_dq.memory.column_stats import load_column_history_sync, save_column_stats

    for i in range(5):
        await save_column_stats(
            run_id=f"r{i}",
            table="t",
            column="c",
            row_count=10,
            mean_val=float(i),
            stddev_val=1.0,
            min_val=0.0,
            max_val=float(i),
            path=cs_mod.DB_PATH,
        )

    history = load_column_history_sync("t", "c", path=cs_mod.DB_PATH)
    assert len(history) == 5
    assert all(isinstance(v, float) for v in history)


def test_load_missing_db_returns_empty(tmp_path):
    from thota_dq.memory.column_stats import load_column_history_sync
    result = load_column_history_sync("t", "c", path=tmp_path / "nonexistent.db")
    assert result == []
