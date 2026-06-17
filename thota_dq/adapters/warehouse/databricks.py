"""Databricks warehouse adapter.

Requires: pip install thota-dq[databricks]

Authentication uses a personal access token passed directly.
Table references should match the catalog/schema configured on the adapter,
or be fully qualified as catalog.schema.table.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ...rules.schema import DataQualityRule, RuleResult, RuleType
from .base import WarehouseAdapter
from .quoting import escape_string_literal, quote_qualified_spark


class DatabricksAdapter(WarehouseAdapter):
    """Warehouse adapter backed by Databricks SQL (Spark SQL dialect)."""

    def __init__(
        self,
        server_hostname: str,
        http_path: str,
        access_token: str,
        catalog: str | None = None,
        schema: str | None = None,
        port: int = 443,
    ):
        """
        Args:
            server_hostname: Databricks workspace hostname (e.g. "abc.azuredatabricks.net")
            http_path: SQL warehouse HTTP path (e.g. "/sql/1.0/warehouses/abc123")
            access_token: Personal access token or service principal secret
            catalog: Default Unity Catalog catalog name (optional)
            schema: Default schema / database name (optional)
            port: Port for the SQL connector (default 443)
        """
        try:
            import databricks.sql  # noqa: F401  # type: ignore[import]
        except ImportError as e:
            raise ImportError(
                "Databricks support requires 'databricks-sql-connector'. "
                "Install with: pip install thota-dq[databricks]"
            ) from e

        self._server_hostname = server_hostname
        self._http_path = http_path
        self._access_token = access_token
        self._catalog = catalog
        self._schema = schema
        self._port = port
        self._conn: Any = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _get_conn(self) -> Any:
        """Return (and lazily create) the Databricks SQL connection."""
        if self._conn is None:
            from databricks import sql as dbsql  # type: ignore[import]

            self._conn = dbsql.connect(
                server_hostname=self._server_hostname,
                http_path=self._http_path,
                access_token=self._access_token,
            )
        return self._conn

    # ------------------------------------------------------------------
    # Low-level query helpers
    # ------------------------------------------------------------------

    def _scalar(self, cursor: Any, sql: str) -> Any:
        """Execute *sql* and return the first column of the first row."""
        cursor.execute(sql)
        row = cursor.fetchone()
        return row[0] if row is not None else None

    def _fetchall(self, cursor: Any, sql: str) -> list[tuple]:
        """Execute *sql* and return all rows as tuples."""
        cursor.execute(sql)
        raw = cursor.fetchall()
        # databricks-sql-connector returns Row objects with .asDict(); guard for
        # both Row and plain tuple (test mocks use tuples).
        result = []
        for r in raw:
            if hasattr(r, "asDict"):
                result.append(tuple(r.asDict().values()))
            else:
                result.append(tuple(r))
        return result

    def _sample_rows(self, cursor: Any, sql: str) -> list[dict]:
        """Execute *sql* and return rows as a list of dicts."""
        cursor.execute(sql)
        raw = cursor.fetchall()
        result = []
        for r in raw:
            if isinstance(r, dict):
                result.append(r)
            elif hasattr(r, "asDict"):
                result.append(r.asDict())
            else:
                # fallback: wrap positional values — callers supply SELECT *
                result.append(dict(enumerate(r)))
        return result

    def _q(self, identifier: str) -> str:
        """Backtick-quote a Spark SQL identifier."""
        return "`" + identifier.replace("`", "``") + "`"

    def _qt(self, name: str) -> str:
        """Quote a possibly-qualified table name (each dot-separated part)."""
        return quote_qualified_spark(name)

    def _full_table(self, table: str) -> str:
        """Qualify table with catalog.schema if not already qualified."""
        parts = table.split(".")
        if len(parts) == 3:
            return table
        if len(parts) == 2:
            if self._catalog:
                return f"{self._catalog}.{table}"
            return table
        if self._catalog and self._schema:
            return f"{self._catalog}.{self._schema}.{table}"
        if self._schema:
            return f"{self._schema}.{table}"
        return table

    # ------------------------------------------------------------------
    # Core rule execution (synchronous — called via run_in_executor)
    # ------------------------------------------------------------------

    def _execute_sync(self, rule: DataQualityRule) -> RuleResult:  # noqa: C901
        t = self._qt(self._full_table(rule.spec_scope.table))
        logic = rule.spec_logic
        start = time.monotonic()

        def ms() -> float:
            return (time.monotonic() - start) * 1000

        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            # ----------------------------------------------------------------
            # NOT_NULL
            # ----------------------------------------------------------------
            if logic.type == RuleType.NOT_NULL:
                col = self._q(rule.spec_scope.columns[0])
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(cursor, f"SELECT COUNT(*) FROM {t} WHERE {col} IS NULL")
                sample: list[dict] = []
                if fail_count > 0:
                    sample = self._sample_rows(
                        cursor, f"SELECT * FROM {t} WHERE {col} IS NULL LIMIT 5"
                    )
                return RuleResult(rule_id=rule.metadata.id, passed=fail_count == 0,
                                  row_count_checked=total, row_count_failed=fail_count,
                                  failure_sample=sample, duration_ms=ms())

            # ----------------------------------------------------------------
            # UNIQUE
            # ----------------------------------------------------------------
            elif logic.type == RuleType.UNIQUE:
                col = self._q(rule.spec_scope.columns[0])
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                dups = self._scalar(
                    cursor, f"SELECT COUNT(*) - COUNT(DISTINCT {col}) FROM {t}"
                )
                sample = []
                if dups > 0:
                    sample = self._sample_rows(
                        cursor,
                        f"SELECT {col}, COUNT(*) AS cnt FROM {t} "
                        f"GROUP BY {col} HAVING COUNT(*) > 1 LIMIT 5",
                    )
                return RuleResult(rule_id=rule.metadata.id, passed=dups == 0,
                                  row_count_checked=total, row_count_failed=dups,
                                  failure_sample=sample, duration_ms=ms())

            # ----------------------------------------------------------------
            # SQL_EXPRESSION
            # ----------------------------------------------------------------
            elif logic.type == RuleType.SQL_EXPRESSION:
                expr = logic.expression or "TRUE"
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor, f"SELECT COUNT(*) FROM {t} WHERE NOT ({expr})"
                )
                sample = []
                if fail_count > 0:
                    sample = self._sample_rows(
                        cursor, f"SELECT * FROM {t} WHERE NOT ({expr}) LIMIT 5"
                    )
                return RuleResult(rule_id=rule.metadata.id, passed=fail_count == 0,
                                  row_count_checked=total, row_count_failed=fail_count,
                                  failure_sample=sample, duration_ms=ms())

            # ----------------------------------------------------------------
            # ROW_COUNT
            # ----------------------------------------------------------------
            elif logic.type == RuleType.ROW_COUNT:
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                threshold = int(logic.threshold or 0)
                passed = total >= threshold
                return RuleResult(rule_id=rule.metadata.id, passed=passed,
                                  row_count_checked=total,
                                  row_count_failed=0 if passed else 1, duration_ms=ms())

            # ----------------------------------------------------------------
            # FRESHNESS
            # ----------------------------------------------------------------
            elif logic.type == RuleType.FRESHNESS:
                col = self._q(rule.spec_scope.columns[0])
                hours = logic.threshold or 24
                latest = self._scalar(cursor, f"SELECT MAX({col}) FROM {t}")
                if latest is None:
                    return RuleResult(rule_id=rule.metadata.id, passed=False,
                                      error="No rows — cannot determine freshness",
                                      duration_ms=ms())
                age_hours = self._scalar(
                    cursor,
                    f"SELECT (unix_timestamp(NOW()) - unix_timestamp(MAX({col}))) / 3600 FROM {t}",
                )
                passed = float(age_hours) <= float(hours)
                return RuleResult(rule_id=rule.metadata.id, passed=passed,
                                  row_count_checked=1,
                                  row_count_failed=0 if passed else 1, duration_ms=ms())

            # ----------------------------------------------------------------
            # CUSTOM_SQL
            # ----------------------------------------------------------------
            elif logic.type == RuleType.CUSTOM_SQL:
                rows = self._fetchall(cursor, logic.query or "SELECT FALSE, 0")
                row = rows[0] if rows else (False, 0)
                passed = bool(row[0])
                row_count = int(row[1]) if len(row) > 1 else 0
                return RuleResult(rule_id=rule.metadata.id, passed=passed,
                                  row_count_checked=row_count, duration_ms=ms())

            # ----------------------------------------------------------------
            # NOT_EMPTY_STRING
            # ----------------------------------------------------------------
            elif logic.type == RuleType.NOT_EMPTY_STRING:
                col = self._q(rule.spec_scope.columns[0])
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM {t} "
                    f"WHERE {col} IS NULL OR TRIM(CAST({col} AS STRING)) = ''",
                )
                sample = []
                if fail_count > 0:
                    sample = self._sample_rows(
                        cursor,
                        f"SELECT * FROM {t} "
                        f"WHERE {col} IS NULL OR TRIM(CAST({col} AS STRING)) = '' LIMIT 5",
                    )
                return RuleResult(rule_id=rule.metadata.id, passed=fail_count == 0,
                                  row_count_checked=total, row_count_failed=fail_count,
                                  failure_sample=sample, duration_ms=ms())

            # ----------------------------------------------------------------
            # COMPOSITE_UNIQUE
            # ----------------------------------------------------------------
            elif logic.type == RuleType.COMPOSITE_UNIQUE:
                cols = ", ".join(self._q(c) for c in rule.spec_scope.columns)
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                dups = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM ("
                    f"SELECT {cols}, COUNT(*) AS cnt FROM {t} GROUP BY {cols} HAVING COUNT(*) > 1"
                    f") _dups",
                )
                return RuleResult(rule_id=rule.metadata.id, passed=dups == 0,
                                  row_count_checked=total, row_count_failed=int(dups),
                                  duration_ms=ms())

            # ----------------------------------------------------------------
            # BETWEEN
            # ----------------------------------------------------------------
            elif logic.type == RuleType.BETWEEN:
                col = self._q(rule.spec_scope.columns[0])
                min_v, max_v = logic.min_value, logic.max_value
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM {t} WHERE {col} < {min_v} OR {col} > {max_v}",
                )
                return RuleResult(rule_id=rule.metadata.id, passed=fail_count == 0,
                                  row_count_checked=total, row_count_failed=fail_count,
                                  duration_ms=ms())

            # ----------------------------------------------------------------
            # MIN_VALUE_CHECK
            # ----------------------------------------------------------------
            elif logic.type == RuleType.MIN_VALUE_CHECK:
                col = self._q(rule.spec_scope.columns[0])
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor, f"SELECT COUNT(*) FROM {t} WHERE {col} < {logic.min_value}"
                )
                return RuleResult(rule_id=rule.metadata.id, passed=fail_count == 0,
                                  row_count_checked=total, row_count_failed=fail_count,
                                  duration_ms=ms())

            # ----------------------------------------------------------------
            # MAX_VALUE_CHECK
            # ----------------------------------------------------------------
            elif logic.type == RuleType.MAX_VALUE_CHECK:
                col = self._q(rule.spec_scope.columns[0])
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor, f"SELECT COUNT(*) FROM {t} WHERE {col} > {logic.max_value}"
                )
                return RuleResult(rule_id=rule.metadata.id, passed=fail_count == 0,
                                  row_count_checked=total, row_count_failed=fail_count,
                                  duration_ms=ms())

            # ----------------------------------------------------------------
            # REGEX_MATCH  (Spark SQL: RLIKE)
            # ----------------------------------------------------------------
            elif logic.type == RuleType.REGEX_MATCH:
                col = self._q(rule.spec_scope.columns[0])
                pattern = escape_string_literal(logic.pattern or "")
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM {t} "
                    f"WHERE NOT (CAST({col} AS STRING) RLIKE '{pattern}')",
                )
                return RuleResult(rule_id=rule.metadata.id, passed=fail_count == 0,
                                  row_count_checked=total, row_count_failed=fail_count,
                                  duration_ms=ms())

            # ----------------------------------------------------------------
            # ACCEPTED_VALUES
            # ----------------------------------------------------------------
            elif logic.type == RuleType.ACCEPTED_VALUES:
                col = self._q(rule.spec_scope.columns[0])
                values_list = ", ".join(f"'{escape_string_literal(v)}'" for v in (logic.values or []))
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM {t} "
                    f"WHERE CAST({col} AS STRING) NOT IN ({values_list})",
                )
                return RuleResult(rule_id=rule.metadata.id, passed=fail_count == 0,
                                  row_count_checked=total, row_count_failed=fail_count,
                                  duration_ms=ms())

            # ----------------------------------------------------------------
            # NOT_ACCEPTED_VALUES
            # ----------------------------------------------------------------
            elif logic.type == RuleType.NOT_ACCEPTED_VALUES:
                col = self._q(rule.spec_scope.columns[0])
                values_list = ", ".join(f"'{escape_string_literal(v)}'" for v in (logic.values or []))
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM {t} "
                    f"WHERE CAST({col} AS STRING) IN ({values_list})",
                )
                return RuleResult(rule_id=rule.metadata.id, passed=fail_count == 0,
                                  row_count_checked=total, row_count_failed=fail_count,
                                  duration_ms=ms())

            # ----------------------------------------------------------------
            # FOREIGN_KEY
            # ----------------------------------------------------------------
            elif logic.type == RuleType.FOREIGN_KEY:
                col = self._q(rule.spec_scope.columns[0])
                ref_table = self._qt(self._full_table(logic.reference_table or rule.spec_scope.table))
                ref_col = self._q(logic.reference_column or rule.spec_scope.columns[0])
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM {t} "
                    f"WHERE {col} IS NOT NULL "
                    f"AND {col} NOT IN (SELECT {ref_col} FROM {ref_table})",
                )
                return RuleResult(rule_id=rule.metadata.id, passed=fail_count == 0,
                                  row_count_checked=total, row_count_failed=fail_count,
                                  duration_ms=ms())

            # ----------------------------------------------------------------
            # NULL_PERCENTAGE_BELOW
            # ----------------------------------------------------------------
            elif logic.type == RuleType.NULL_PERCENTAGE_BELOW:
                col = self._q(rule.spec_scope.columns[0])
                threshold = logic.threshold or 0.0
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                nulls = self._scalar(cursor, f"SELECT COUNT(*) FROM {t} WHERE {col} IS NULL")
                pct = (nulls * 100.0 / total) if total > 0 else 0.0
                return RuleResult(rule_id=rule.metadata.id, passed=pct <= threshold,
                                  row_count_checked=total, row_count_failed=nulls,
                                  duration_ms=ms())

            # ----------------------------------------------------------------
            # DUPLICATE_PERCENTAGE_BELOW
            # ----------------------------------------------------------------
            elif logic.type == RuleType.DUPLICATE_PERCENTAGE_BELOW:
                col = self._q(rule.spec_scope.columns[0])
                threshold = logic.threshold or 0.0
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                dups = self._scalar(
                    cursor, f"SELECT COUNT(*) - COUNT(DISTINCT {col}) FROM {t}"
                )
                pct = (dups * 100.0 / total) if total > 0 else 0.0
                return RuleResult(rule_id=rule.metadata.id, passed=pct <= threshold,
                                  row_count_checked=total, row_count_failed=int(dups),
                                  duration_ms=ms())

            # ----------------------------------------------------------------
            # MEAN_BETWEEN
            # ----------------------------------------------------------------
            elif logic.type == RuleType.MEAN_BETWEEN:
                col = self._q(rule.spec_scope.columns[0])
                min_v, max_v = logic.min_value, logic.max_value
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                mean = float(self._scalar(cursor, f"SELECT AVG({col}) FROM {t}") or 0.0)
                passed = (min_v is None or mean >= min_v) and (max_v is None or mean <= max_v)
                return RuleResult(rule_id=rule.metadata.id, passed=passed,
                                  row_count_checked=total,
                                  row_count_failed=0 if passed else 1,
                                  failure_sample=[] if passed else [{"mean": mean}],
                                  duration_ms=ms())

            # ----------------------------------------------------------------
            # STDDEV_BELOW  (Spark SQL: STDDEV)
            # ----------------------------------------------------------------
            elif logic.type == RuleType.STDDEV_BELOW:
                col = self._q(rule.spec_scope.columns[0])
                threshold = logic.threshold or 0.0
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                stddev = float(self._scalar(cursor, f"SELECT STDDEV({col}) FROM {t}") or 0.0)
                passed = stddev <= threshold
                return RuleResult(rule_id=rule.metadata.id, passed=passed,
                                  row_count_checked=total,
                                  row_count_failed=0 if passed else 1,
                                  failure_sample=[] if passed else [{"stddev": stddev}],
                                  duration_ms=ms())

            # ----------------------------------------------------------------
            # NO_FUTURE_DATES  (Spark SQL: NOW())
            # ----------------------------------------------------------------
            elif logic.type == RuleType.NO_FUTURE_DATES:
                col = self._q(rule.spec_scope.columns[0])
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor, f"SELECT COUNT(*) FROM {t} WHERE {col} > NOW()"
                )
                return RuleResult(rule_id=rule.metadata.id, passed=fail_count == 0,
                                  row_count_checked=total, row_count_failed=fail_count,
                                  duration_ms=ms())

            # ----------------------------------------------------------------
            # DATE_ORDER
            # ----------------------------------------------------------------
            elif logic.type == RuleType.DATE_ORDER:
                col_a = self._q(rule.spec_scope.columns[0])
                col_b = self._q(logic.column_b or "")
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM {t} "
                    f"WHERE {col_a} IS NOT NULL AND {col_b} IS NOT NULL AND {col_a} > {col_b}",
                )
                return RuleResult(rule_id=rule.metadata.id, passed=fail_count == 0,
                                  row_count_checked=total, row_count_failed=fail_count,
                                  duration_ms=ms())

            # ----------------------------------------------------------------
            # COLUMN_EXISTS  (Spark SQL: SHOW COLUMNS IN table)
            # ----------------------------------------------------------------
            elif logic.type == RuleType.COLUMN_EXISTS:
                col = rule.spec_scope.columns[0]
                cursor.execute(f"SHOW COLUMNS IN {t}")
                rows = cursor.fetchall()
                # Each row is a Row/tuple; the column name is the first field
                col_names: list[str] = []
                for r in rows:
                    if hasattr(r, "asDict"):
                        d = r.asDict()
                        col_names.append(next(iter(d.values()), "").lower())
                    else:
                        col_names.append(str(r[0]).lower())
                exists = col.lower() in col_names
                return RuleResult(rule_id=rule.metadata.id, passed=exists,
                                  row_count_failed=0 if exists else 1, duration_ms=ms())

            # ----------------------------------------------------------------
            # ROW_COUNT_BETWEEN
            # ----------------------------------------------------------------
            elif logic.type == RuleType.ROW_COUNT_BETWEEN:
                min_v = logic.min_value or 0
                max_v = logic.max_value or float("inf")
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                passed = min_v <= total <= max_v
                return RuleResult(rule_id=rule.metadata.id, passed=passed,
                                  row_count_checked=total,
                                  row_count_failed=0 if passed else 1,
                                  failure_sample=[] if passed else [{"row_count": total}],
                                  duration_ms=ms())

            # ----------------------------------------------------------------
            # COLUMN_SUM_BETWEEN
            # ----------------------------------------------------------------
            elif logic.type == RuleType.COLUMN_SUM_BETWEEN:
                col = self._q(rule.spec_scope.columns[0])
                min_v, max_v = logic.min_value, logic.max_value
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                total_sum = float(
                    self._scalar(cursor, f"SELECT SUM({col}) FROM {t}") or 0.0
                )
                passed = (min_v is None or total_sum >= min_v) and (
                    max_v is None or total_sum <= max_v
                )
                return RuleResult(rule_id=rule.metadata.id, passed=passed,
                                  row_count_checked=total,
                                  row_count_failed=0 if passed else 1,
                                  failure_sample=[] if passed else [{"sum": total_sum}],
                                  duration_ms=ms())

            # ----------------------------------------------------------------
            # CONDITIONAL_NOT_NULL
            # ----------------------------------------------------------------
            elif logic.type == RuleType.CONDITIONAL_NOT_NULL:
                col = self._q(rule.spec_scope.columns[0])
                condition = logic.condition or "TRUE"
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM {t} WHERE ({condition}) AND {col} IS NULL",
                )
                return RuleResult(rule_id=rule.metadata.id, passed=fail_count == 0,
                                  row_count_checked=total, row_count_failed=fail_count,
                                  duration_ms=ms())

            # ----------------------------------------------------------------
            # RECONCILE_ROW_COUNT
            # ----------------------------------------------------------------
            elif logic.type == RuleType.RECONCILE_ROW_COUNT:
                src = self._qt(self._full_table(logic.source_table or rule.spec_scope.table))
                tol = logic.tolerance_pct / 100.0
                src_count = self._scalar(cursor, f"SELECT COUNT(*) FROM {src}")
                tgt_count = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                if src_count == 0:
                    passed = tgt_count == 0
                else:
                    passed = abs(src_count - tgt_count) / src_count <= tol
                sample = [] if passed else [{"source_rows": src_count, "target_rows": tgt_count}]
                return RuleResult(rule_id=rule.metadata.id, passed=passed,
                                  row_count_checked=src_count,
                                  row_count_failed=abs(src_count - tgt_count),
                                  failure_sample=sample, duration_ms=ms())

            # ----------------------------------------------------------------
            # RECONCILE_COLUMN_SUM
            # ----------------------------------------------------------------
            elif logic.type == RuleType.RECONCILE_COLUMN_SUM:
                col = self._q(rule.spec_scope.columns[0])
                src = self._qt(self._full_table(logic.source_table or rule.spec_scope.table))
                tol = logic.tolerance_pct / 100.0
                src_sum = float(
                    self._scalar(cursor, f"SELECT COALESCE(SUM({col}), 0) FROM {src}") or 0
                )
                tgt_sum = float(
                    self._scalar(cursor, f"SELECT COALESCE(SUM({col}), 0) FROM {t}") or 0
                )
                passed = (
                    abs(src_sum - tgt_sum) / abs(src_sum) <= tol
                    if src_sum != 0
                    else tgt_sum == 0
                )
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                sample = [] if passed else [{"source_sum": src_sum, "target_sum": tgt_sum}]
                return RuleResult(rule_id=rule.metadata.id, passed=passed,
                                  row_count_checked=total,
                                  row_count_failed=0 if passed else 1,
                                  failure_sample=sample, duration_ms=ms())

            # ----------------------------------------------------------------
            # RECONCILE_KEY_MATCH
            # ----------------------------------------------------------------
            elif logic.type == RuleType.RECONCILE_KEY_MATCH:
                col = self._q(rule.spec_scope.columns[0])
                src = self._qt(self._full_table(logic.source_table or rule.spec_scope.table))
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {src}")
                missing_in_tgt = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM {src} "
                    f"WHERE {col} NOT IN (SELECT {col} FROM {t})",
                )
                missing_in_src = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM {t} "
                    f"WHERE {col} NOT IN (SELECT {col} FROM {src})",
                )
                passed = missing_in_tgt == 0 and missing_in_src == 0
                sample = (
                    []
                    if passed
                    else [{"missing_in_target": missing_in_tgt, "missing_in_source": missing_in_src}]
                )
                return RuleResult(rule_id=rule.metadata.id, passed=passed,
                                  row_count_checked=total,
                                  row_count_failed=missing_in_tgt + missing_in_src,
                                  failure_sample=sample, duration_ms=ms())

            else:
                return RuleResult(rule_id=rule.metadata.id, passed=False,
                                  error=f"Unsupported rule type: {logic.type}",
                                  duration_ms=ms())

        except Exception as e:
            return RuleResult(rule_id=rule.metadata.id, passed=False,
                              error=str(e), duration_ms=ms())
        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # Public async interface
    # ------------------------------------------------------------------

    async def execute_rule(self, rule: DataQualityRule) -> RuleResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._execute_sync, rule)

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
