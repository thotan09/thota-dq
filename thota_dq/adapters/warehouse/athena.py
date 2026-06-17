"""Athena warehouse adapter.

Requires: pip install thota-dq[athena]

Authentication follows the standard boto3 credential chain:
  - Explicit aws_access_key_id / aws_secret_access_key / aws_session_token
  - AWS_* environment variables
  - ~/.aws/credentials / instance profile

Table references use the schema_name configured on the adapter unless the
caller supplies a two-part schema.table reference.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ...rules.schema import DataQualityRule, RuleResult, RuleType
from .base import WarehouseAdapter
from .quoting import escape_string_literal, quote_qualified_ansi


class AthenaAdapter(WarehouseAdapter):
    """Warehouse adapter backed by Amazon Athena (Presto/Trino SQL dialect)."""

    def __init__(
        self,
        s3_staging_dir: str,
        region_name: str,
        schema_name: str = "default",
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_session_token: str | None = None,
    ):
        """
        Args:
            s3_staging_dir: S3 path for query result staging (e.g. "s3://my-bucket/athena/")
            region_name: AWS region (e.g. "us-east-1")
            schema_name: Default Glue/Athena database (schema) name
            aws_access_key_id: AWS access key ID (uses boto3 chain if None)
            aws_secret_access_key: AWS secret access key (uses boto3 chain if None)
            aws_session_token: AWS session token for temporary credentials
        """
        try:
            import pyathena  # noqa: F401  # type: ignore[import]
        except ImportError as e:
            raise ImportError(
                "Athena support requires 'pyathena'. Install with: pip install thota-dq[athena]"
            ) from e

        self._s3_staging_dir = s3_staging_dir
        self._region_name = region_name
        self._schema_name = schema_name
        self._aws_access_key_id = aws_access_key_id
        self._aws_secret_access_key = aws_secret_access_key
        self._aws_session_token = aws_session_token
        self._conn: Any = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _get_conn(self) -> Any:
        """Return (and lazily create) the PyAthena connection."""
        if self._conn is None:
            from pyathena import connect  # type: ignore[import]

            self._conn = connect(
                s3_staging_dir=self._s3_staging_dir,
                region_name=self._region_name,
                schema_name=self._schema_name,
                aws_access_key_id=self._aws_access_key_id,
                aws_secret_access_key=self._aws_secret_access_key,
                aws_session_token=self._aws_session_token,
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
        """Execute *sql* and return all rows as a list of tuples."""
        cursor.execute(sql)
        return list(cursor.fetchall())

    def _sample_rows(self, cursor: Any, sql: str) -> list[dict]:
        """Execute *sql* and return rows as a list of dicts.

        pyathena cursors expose column names via cursor.description.
        """
        cursor.execute(sql)
        rows = cursor.fetchall()
        if not rows:
            return []
        if cursor.description:
            col_names = [d[0] for d in cursor.description]
            return [dict(zip(col_names, r)) for r in rows]
        return [dict(enumerate(r)) for r in rows]

    def _q(self, identifier: str) -> str:
        """Double-quote a Presto/Athena identifier."""
        return '"' + identifier.replace('"', '""') + '"'

    def _qt(self, name: str) -> str:
        """Quote a possibly-qualified table name (each dot-separated part)."""
        return quote_qualified_ansi(name)

    def _full_table(self, table: str) -> str:
        """Qualify table with schema_name if not already qualified."""
        parts = table.split(".")
        if len(parts) >= 2:
            return table
        return f"{self._schema_name}.{table}"

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
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    failure_sample=sample,
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # UNIQUE
            # ----------------------------------------------------------------
            elif logic.type == RuleType.UNIQUE:
                col = self._q(rule.spec_scope.columns[0])
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                dups = self._scalar(cursor, f"SELECT COUNT(*) - COUNT(DISTINCT {col}) FROM {t}")
                sample = []
                if dups > 0:
                    sample = self._sample_rows(
                        cursor,
                        f"SELECT {col}, COUNT(*) AS cnt FROM {t} "
                        f"GROUP BY {col} HAVING COUNT(*) > 1 LIMIT 5",
                    )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=dups == 0,
                    row_count_checked=total,
                    row_count_failed=dups,
                    failure_sample=sample,
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # SQL_EXPRESSION
            # ----------------------------------------------------------------
            elif logic.type == RuleType.SQL_EXPRESSION:
                expr = logic.expression or "TRUE"
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(cursor, f"SELECT COUNT(*) FROM {t} WHERE NOT ({expr})")
                sample = []
                if fail_count > 0:
                    sample = self._sample_rows(
                        cursor, f"SELECT * FROM {t} WHERE NOT ({expr}) LIMIT 5"
                    )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    failure_sample=sample,
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # ROW_COUNT
            # ----------------------------------------------------------------
            elif logic.type == RuleType.ROW_COUNT:
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                threshold = int(logic.threshold or 0)
                passed = total >= threshold
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=passed,
                    row_count_checked=total,
                    row_count_failed=0 if passed else 1,
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # FRESHNESS  (Presto/Athena: date_diff)
            # ----------------------------------------------------------------
            elif logic.type == RuleType.FRESHNESS:
                col = self._q(rule.spec_scope.columns[0])
                hours = logic.threshold or 24
                latest = self._scalar(cursor, f"SELECT MAX({col}) FROM {t}")
                if latest is None:
                    return RuleResult(
                        rule_id=rule.metadata.id,
                        passed=False,
                        error="No rows — cannot determine freshness",
                        duration_ms=ms(),
                    )
                age_hours = self._scalar(
                    cursor,
                    f"SELECT date_diff('hour', CAST(MAX({col}) AS TIMESTAMP), NOW()) FROM {t}",
                )
                passed = float(age_hours) <= float(hours)
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=passed,
                    row_count_checked=1,
                    row_count_failed=0 if passed else 1,
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # CUSTOM_SQL
            # ----------------------------------------------------------------
            elif logic.type == RuleType.CUSTOM_SQL:
                rows = self._fetchall(cursor, logic.query or "SELECT 1 WHERE FALSE")
                fail_count = len(rows)
                sample = (
                    [dict(zip([d[0] for d in cursor.description], r)) for r in rows[:5]]
                    if fail_count > 0
                    else []
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=fail_count,
                    row_count_failed=fail_count,
                    failure_sample=sample,
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # NOT_EMPTY_STRING
            # ----------------------------------------------------------------
            elif logic.type == RuleType.NOT_EMPTY_STRING:
                col = self._q(rule.spec_scope.columns[0])
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM {t} "
                    f"WHERE {col} IS NULL OR TRIM(CAST({col} AS VARCHAR)) = ''",
                )
                sample = []
                if fail_count > 0:
                    sample = self._sample_rows(
                        cursor,
                        f"SELECT * FROM {t} "
                        f"WHERE {col} IS NULL OR TRIM(CAST({col} AS VARCHAR)) = '' LIMIT 5",
                    )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    failure_sample=sample,
                    duration_ms=ms(),
                )

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
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=dups == 0,
                    row_count_checked=total,
                    row_count_failed=int(dups),
                    duration_ms=ms(),
                )

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
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # MIN_VALUE_CHECK
            # ----------------------------------------------------------------
            elif logic.type == RuleType.MIN_VALUE_CHECK:
                col = self._q(rule.spec_scope.columns[0])
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor, f"SELECT COUNT(*) FROM {t} WHERE {col} < {logic.min_value}"
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # MAX_VALUE_CHECK
            # ----------------------------------------------------------------
            elif logic.type == RuleType.MAX_VALUE_CHECK:
                col = self._q(rule.spec_scope.columns[0])
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor, f"SELECT COUNT(*) FROM {t} WHERE {col} > {logic.max_value}"
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # REGEX_MATCH  (Presto/Athena: regexp_like)
            # ----------------------------------------------------------------
            elif logic.type == RuleType.REGEX_MATCH:
                col = self._q(rule.spec_scope.columns[0])
                pattern = escape_string_literal(logic.pattern or "")
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM {t} "
                    f"WHERE NOT regexp_like(CAST({col} AS VARCHAR), '{pattern}')",
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # ACCEPTED_VALUES
            # ----------------------------------------------------------------
            elif logic.type == RuleType.ACCEPTED_VALUES:
                col = self._q(rule.spec_scope.columns[0])
                values_list = ", ".join(
                    f"'{escape_string_literal(v)}'" for v in (logic.values or [])
                )
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM {t} WHERE CAST({col} AS VARCHAR) NOT IN ({values_list})",
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # NOT_ACCEPTED_VALUES
            # ----------------------------------------------------------------
            elif logic.type == RuleType.NOT_ACCEPTED_VALUES:
                col = self._q(rule.spec_scope.columns[0])
                values_list = ", ".join(
                    f"'{escape_string_literal(v)}'" for v in (logic.values or [])
                )
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM {t} WHERE CAST({col} AS VARCHAR) IN ({values_list})",
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # FOREIGN_KEY
            # ----------------------------------------------------------------
            elif logic.type == RuleType.FOREIGN_KEY:
                col = self._q(rule.spec_scope.columns[0])
                ref_table = self._qt(
                    self._full_table(logic.reference_table or rule.spec_scope.table)
                )
                ref_col = self._q(logic.reference_column or rule.spec_scope.columns[0])
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM {t} "
                    f"WHERE {col} IS NOT NULL "
                    f"AND {col} NOT IN (SELECT {ref_col} FROM {ref_table})",
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # NULL_PERCENTAGE_BELOW
            # ----------------------------------------------------------------
            elif logic.type == RuleType.NULL_PERCENTAGE_BELOW:
                col = self._q(rule.spec_scope.columns[0])
                threshold = logic.threshold or 0.0
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                nulls = self._scalar(cursor, f"SELECT COUNT(*) FROM {t} WHERE {col} IS NULL")
                pct = (nulls * 100.0 / total) if total > 0 else 0.0
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=pct <= threshold,
                    row_count_checked=total,
                    row_count_failed=nulls,
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # DUPLICATE_PERCENTAGE_BELOW
            # ----------------------------------------------------------------
            elif logic.type == RuleType.DUPLICATE_PERCENTAGE_BELOW:
                col = self._q(rule.spec_scope.columns[0])
                threshold = logic.threshold or 0.0
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                dups = self._scalar(cursor, f"SELECT COUNT(*) - COUNT(DISTINCT {col}) FROM {t}")
                pct = (dups * 100.0 / total) if total > 0 else 0.0
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=pct <= threshold,
                    row_count_checked=total,
                    row_count_failed=int(dups),
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # MEAN_BETWEEN
            # ----------------------------------------------------------------
            elif logic.type == RuleType.MEAN_BETWEEN:
                col = self._q(rule.spec_scope.columns[0])
                min_v, max_v = logic.min_value, logic.max_value
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                mean = float(self._scalar(cursor, f"SELECT AVG({col}) FROM {t}") or 0.0)
                passed = (min_v is None or mean >= min_v) and (max_v is None or mean <= max_v)
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=passed,
                    row_count_checked=total,
                    row_count_failed=0 if passed else 1,
                    failure_sample=[] if passed else [{"mean": mean}],
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # STDDEV_BELOW  (Presto/Athena: stddev)
            # ----------------------------------------------------------------
            elif logic.type == RuleType.STDDEV_BELOW:
                col = self._q(rule.spec_scope.columns[0])
                threshold = logic.threshold or 0.0
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                stddev = float(self._scalar(cursor, f"SELECT stddev({col}) FROM {t}") or 0.0)
                passed = stddev <= threshold
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=passed,
                    row_count_checked=total,
                    row_count_failed=0 if passed else 1,
                    failure_sample=[] if passed else [{"stddev": stddev}],
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # NO_FUTURE_DATES  (Presto/Athena: current_timestamp)
            # ----------------------------------------------------------------
            elif logic.type == RuleType.NO_FUTURE_DATES:
                col = self._q(rule.spec_scope.columns[0])
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    cursor, f"SELECT COUNT(*) FROM {t} WHERE {col} > current_timestamp"
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

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
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # COLUMN_EXISTS  (Athena: information_schema.columns)
            # ----------------------------------------------------------------
            elif logic.type == RuleType.COLUMN_EXISTS:
                col = rule.spec_scope.columns[0]
                # Resolve schema and table name separately
                parts = rule.spec_scope.table.split(".")
                tbl_name = parts[-1]
                schema = parts[-2] if len(parts) >= 2 else self._schema_name
                # Escape values used as string literals in the WHERE clause
                exists_count = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM information_schema.columns "
                    f"WHERE table_schema = '{escape_string_literal(schema)}' "
                    f"AND table_name = '{escape_string_literal(tbl_name)}' "
                    f"AND column_name = '{escape_string_literal(col)}'",
                )
                exists = int(exists_count or 0) > 0
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=exists,
                    row_count_failed=0 if exists else 1,
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # ROW_COUNT_BETWEEN
            # ----------------------------------------------------------------
            elif logic.type == RuleType.ROW_COUNT_BETWEEN:
                min_v = logic.min_value or 0
                max_v = logic.max_value or float("inf")
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                passed = min_v <= total <= max_v
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=passed,
                    row_count_checked=total,
                    row_count_failed=0 if passed else 1,
                    failure_sample=[] if passed else [{"row_count": total}],
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # COLUMN_SUM_BETWEEN
            # ----------------------------------------------------------------
            elif logic.type == RuleType.COLUMN_SUM_BETWEEN:
                col = self._q(rule.spec_scope.columns[0])
                min_v, max_v = logic.min_value, logic.max_value
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                total_sum = float(self._scalar(cursor, f"SELECT SUM({col}) FROM {t}") or 0.0)
                passed = (min_v is None or total_sum >= min_v) and (
                    max_v is None or total_sum <= max_v
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=passed,
                    row_count_checked=total,
                    row_count_failed=0 if passed else 1,
                    failure_sample=[] if passed else [{"sum": total_sum}],
                    duration_ms=ms(),
                )

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
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

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
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=passed,
                    row_count_checked=src_count,
                    row_count_failed=abs(src_count - tgt_count),
                    failure_sample=sample,
                    duration_ms=ms(),
                )

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
                    abs(src_sum - tgt_sum) / abs(src_sum) <= tol if src_sum != 0 else tgt_sum == 0
                )
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {t}")
                sample = [] if passed else [{"source_sum": src_sum, "target_sum": tgt_sum}]
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=passed,
                    row_count_checked=total,
                    row_count_failed=0 if passed else 1,
                    failure_sample=sample,
                    duration_ms=ms(),
                )

            # ----------------------------------------------------------------
            # RECONCILE_KEY_MATCH
            # ----------------------------------------------------------------
            elif logic.type == RuleType.RECONCILE_KEY_MATCH:
                col = self._q(rule.spec_scope.columns[0])
                src = self._qt(self._full_table(logic.source_table or rule.spec_scope.table))
                total = self._scalar(cursor, f"SELECT COUNT(*) FROM {src}")
                missing_in_tgt = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM {src} WHERE {col} NOT IN (SELECT {col} FROM {t})",
                )
                missing_in_src = self._scalar(
                    cursor,
                    f"SELECT COUNT(*) FROM {t} WHERE {col} NOT IN (SELECT {col} FROM {src})",
                )
                passed = missing_in_tgt == 0 and missing_in_src == 0
                sample = (
                    []
                    if passed
                    else [
                        {"missing_in_target": missing_in_tgt, "missing_in_source": missing_in_src}
                    ]
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=passed,
                    row_count_checked=total,
                    row_count_failed=missing_in_tgt + missing_in_src,
                    failure_sample=sample,
                    duration_ms=ms(),
                )

            else:
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=False,
                    error=f"Unsupported rule type: {logic.type}",
                    duration_ms=ms(),
                )

        except Exception as e:
            return RuleResult(
                rule_id=rule.metadata.id, passed=False, error=str(e), duration_ms=ms()
            )
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
