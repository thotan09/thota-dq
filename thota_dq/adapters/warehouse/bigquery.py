"""BigQuery warehouse adapter.

Requires: pip install thota-dq[bigquery]

Authentication follows the standard Google ADC chain:
  - GOOGLE_APPLICATION_CREDENTIALS env var (service account JSON)
  - gcloud auth application-default login
  - Workload Identity (GKE / Cloud Run)

Table references must be fully qualified: project.dataset.table
or the adapter resolves them against the configured project/dataset.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ...rules.schema import DataQualityRule, RuleResult, RuleType
from .base import WarehouseAdapter
from .quoting import escape_string_literal, quote_qualified_bigquery


class BigQueryAdapter(WarehouseAdapter):
    """Warehouse adapter backed by Google BigQuery."""

    def __init__(
        self,
        project: str,
        dataset: str,
        location: str = "US",
        credentials: Any = None,
    ):
        """
        Args:
            project: GCP project ID (e.g. "my-project")
            dataset: Default dataset (e.g. "my_dataset")
            location: BigQuery location (default "US")
            credentials: google.oauth2.credentials.Credentials or None for ADC
        """
        try:
            from google.cloud import bigquery  # type: ignore[import]
        except ImportError as e:
            raise ImportError(
                "BigQuery support requires 'google-cloud-bigquery'. "
                "Install with: pip install thota-dq[bigquery]"
            ) from e

        self._project = project
        self._dataset = dataset
        self._location = location
        self._client = bigquery.Client(
            project=project,
            credentials=credentials,
            location=location,
        )

    @staticmethod
    def _q(identifier: str) -> str:
        """Backtick-quote a single BigQuery identifier."""
        return "`" + identifier.replace("`", "``") + "`"

    @staticmethod
    def _qt(name: str) -> str:
        """Quote a possibly-qualified BigQuery table name (each dot-separated part)."""
        return quote_qualified_bigquery(name)

    def _full_table(self, table: str) -> str:
        """Qualify table name with project.dataset if not already qualified."""
        parts = table.split(".")
        if len(parts) == 3:
            return table
        if len(parts) == 2:
            return f"{self._project}.{table}"
        return f"{self._project}.{self._dataset}.{table}"

    def _query(self, sql: str) -> list[tuple]:
        """Run a synchronous BQ query and return rows as tuples."""
        rows = list(self._client.query(sql).result())
        return [tuple(r) for r in rows]

    def _scalar(self, sql: str) -> Any:
        rows = self._query(sql)
        return rows[0][0] if rows else None

    def _sample_rows(self, sql: str) -> list[dict]:
        rows = list(self._client.query(sql).result())
        return [dict(r) for r in rows]

    def _execute_sync(self, rule: DataQualityRule) -> RuleResult:  # noqa: C901
        t = self._qt(self._full_table(rule.spec_scope.table))
        logic = rule.spec_logic
        start = time.monotonic()

        def ms() -> float:
            return (time.monotonic() - start) * 1000

        try:
            if logic.type == RuleType.NOT_NULL:
                col = self._q(rule.spec_scope.columns[0])
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(f"SELECT COUNT(*) FROM {t} WHERE {col} IS NULL")
                sample: list[dict] = []
                if fail_count > 0:
                    sample = self._sample_rows(f"SELECT * FROM {t} WHERE {col} IS NULL LIMIT 5")
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    failure_sample=sample,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.UNIQUE:
                col = self._q(rule.spec_scope.columns[0])
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                dups = self._scalar(f"SELECT COUNT(*) - COUNT(DISTINCT {col}) FROM {t}")
                sample = []
                if dups > 0:
                    sample = self._sample_rows(
                        f"SELECT {col}, COUNT(*) AS cnt FROM {t} "
                        f"GROUP BY {col} HAVING COUNT(*) > 1 LIMIT 5"
                    )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=dups == 0,
                    row_count_checked=total,
                    row_count_failed=dups,
                    failure_sample=sample,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.SQL_EXPRESSION:
                expr = logic.expression or "TRUE"
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(f"SELECT COUNT(*) FROM {t} WHERE NOT ({expr})")
                sample = []
                if fail_count > 0:
                    sample = self._sample_rows(f"SELECT * FROM {t} WHERE NOT ({expr}) LIMIT 5")
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    failure_sample=sample,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.ROW_COUNT:
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                threshold = int(logic.threshold or 0)
                passed = total >= threshold
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=passed,
                    row_count_checked=total,
                    row_count_failed=0 if passed else 1,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.FRESHNESS:
                col = self._q(rule.spec_scope.columns[0])
                hours = logic.threshold or 24
                latest = self._scalar(f"SELECT MAX({col}) FROM {t}")
                if latest is None:
                    return RuleResult(
                        rule_id=rule.metadata.id,
                        passed=False,
                        error="No rows — cannot determine freshness",
                        duration_ms=ms(),
                    )
                age_hours = self._scalar(
                    f"SELECT TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX({col}), HOUR) FROM {t}"
                )
                passed = float(age_hours) <= float(hours)
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=passed,
                    row_count_checked=1,
                    row_count_failed=0 if passed else 1,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.CUSTOM_SQL:
                rows = self._query(logic.query or "SELECT 1 WHERE FALSE")
                fail_count = len(rows)
                sample = [dict(r) for r in rows[:5]] if fail_count > 0 else []
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=fail_count,
                    row_count_failed=fail_count,
                    failure_sample=sample,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.NOT_EMPTY_STRING:
                col = self._q(rule.spec_scope.columns[0])
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    f"SELECT COUNT(*) FROM {t} WHERE {col} IS NULL OR TRIM(CAST({col} AS STRING)) = ''"
                )
                sample = []
                if fail_count > 0:
                    sample = self._sample_rows(
                        f"SELECT * FROM {t} WHERE {col} IS NULL OR TRIM(CAST({col} AS STRING)) = '' LIMIT 5"
                    )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    failure_sample=sample,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.COMPOSITE_UNIQUE:
                cols = ", ".join(self._q(c) for c in rule.spec_scope.columns)
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                dups = self._scalar(
                    f"SELECT COUNT(*) FROM (SELECT {cols}, COUNT(*) AS cnt FROM {t} "
                    f"GROUP BY {cols} HAVING COUNT(*) > 1)"
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=dups == 0,
                    row_count_checked=total,
                    row_count_failed=int(dups),
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.BETWEEN:
                col = self._q(rule.spec_scope.columns[0])
                min_v, max_v = logic.min_value, logic.max_value
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    f"SELECT COUNT(*) FROM {t} WHERE {col} < {min_v} OR {col} > {max_v}"
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.MIN_VALUE_CHECK:
                col = self._q(rule.spec_scope.columns[0])
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    f"SELECT COUNT(*) FROM {t} WHERE {col} < {logic.min_value}"
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.MAX_VALUE_CHECK:
                col = self._q(rule.spec_scope.columns[0])
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    f"SELECT COUNT(*) FROM {t} WHERE {col} > {logic.max_value}"
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.REGEX_MATCH:
                col = self._q(rule.spec_scope.columns[0])
                pattern = escape_string_literal(logic.pattern or "")
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    f"SELECT COUNT(*) FROM {t} WHERE NOT REGEXP_CONTAINS(CAST({col} AS STRING), r'{pattern}')"
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.ACCEPTED_VALUES:
                col = self._q(rule.spec_scope.columns[0])
                values_list = ", ".join(
                    f"'{escape_string_literal(v)}'" for v in (logic.values or [])
                )
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    f"SELECT COUNT(*) FROM {t} WHERE CAST({col} AS STRING) NOT IN ({values_list})"
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.NOT_ACCEPTED_VALUES:
                col = self._q(rule.spec_scope.columns[0])
                values_list = ", ".join(
                    f"'{escape_string_literal(v)}'" for v in (logic.values or [])
                )
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    f"SELECT COUNT(*) FROM {t} WHERE CAST({col} AS STRING) IN ({values_list})"
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.FOREIGN_KEY:
                col = self._q(rule.spec_scope.columns[0])
                ref_table = self._qt(
                    self._full_table(logic.reference_table or rule.spec_scope.table)
                )
                ref_col = self._q(logic.reference_column or rule.spec_scope.columns[0])
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    f"SELECT COUNT(*) FROM {t} WHERE {col} IS NOT NULL "
                    f"AND {col} NOT IN (SELECT {ref_col} FROM {ref_table})"
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.NULL_PERCENTAGE_BELOW:
                col = self._q(rule.spec_scope.columns[0])
                threshold = logic.threshold or 0.0
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                nulls = self._scalar(f"SELECT COUNT(*) FROM {t} WHERE {col} IS NULL")
                pct = (nulls * 100.0 / total) if total > 0 else 0.0
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=pct <= threshold,
                    row_count_checked=total,
                    row_count_failed=nulls,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.DUPLICATE_PERCENTAGE_BELOW:
                col = self._q(rule.spec_scope.columns[0])
                threshold = logic.threshold or 0.0
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                dups = self._scalar(f"SELECT COUNT(*) - COUNT(DISTINCT {col}) FROM {t}")
                pct = (dups * 100.0 / total) if total > 0 else 0.0
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=pct <= threshold,
                    row_count_checked=total,
                    row_count_failed=int(dups),
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.MEAN_BETWEEN:
                col = self._q(rule.spec_scope.columns[0])
                min_v, max_v = logic.min_value, logic.max_value
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                mean = float(self._scalar(f"SELECT AVG({col}) FROM {t}") or 0.0)
                passed = (min_v is None or mean >= min_v) and (max_v is None or mean <= max_v)
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=passed,
                    row_count_checked=total,
                    row_count_failed=0 if passed else 1,
                    failure_sample=[] if passed else [{"mean": mean}],
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.STDDEV_BELOW:
                col = self._q(rule.spec_scope.columns[0])
                threshold = logic.threshold or 0.0
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                stddev = float(self._scalar(f"SELECT STDDEV({col}) FROM {t}") or 0.0)
                passed = stddev <= threshold
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=passed,
                    row_count_checked=total,
                    row_count_failed=0 if passed else 1,
                    failure_sample=[] if passed else [{"stddev": stddev}],
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.NO_FUTURE_DATES:
                col = self._q(rule.spec_scope.columns[0])
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(f"SELECT COUNT(*) FROM {t} WHERE {col} > CURRENT_DATE()")
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.DATE_ORDER:
                col_a = self._q(rule.spec_scope.columns[0])
                col_b = self._q(logic.column_b) if logic.column_b else ""
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    f"SELECT COUNT(*) FROM {t} "
                    f"WHERE {col_a} IS NOT NULL AND {col_b} IS NOT NULL AND {col_a} > {col_b}"
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.COLUMN_EXISTS:
                col = rule.spec_scope.columns[0]
                # BigQuery uses the client API for schema introspection — no SQL injection risk
                schema = self._client.get_table(self._full_table(rule.spec_scope.table)).schema
                exists = any(f.name == col for f in schema)
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=exists,
                    row_count_failed=0 if exists else 1,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.ROW_COUNT_BETWEEN:
                min_v = logic.min_value or 0
                max_v = logic.max_value or float("inf")
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                passed = min_v <= total <= max_v
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=passed,
                    row_count_checked=total,
                    row_count_failed=0 if passed else 1,
                    failure_sample=[] if passed else [{"row_count": total}],
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.COLUMN_SUM_BETWEEN:
                col = self._q(rule.spec_scope.columns[0])
                min_v, max_v = logic.min_value, logic.max_value
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                total_sum = float(self._scalar(f"SELECT SUM({col}) FROM {t}") or 0.0)
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

            elif logic.type == RuleType.CONDITIONAL_NOT_NULL:
                col = self._q(rule.spec_scope.columns[0])
                condition = logic.condition or "TRUE"
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                fail_count = self._scalar(
                    f"SELECT COUNT(*) FROM {t} WHERE ({condition}) AND {col} IS NULL"
                )
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=fail_count == 0,
                    row_count_checked=total,
                    row_count_failed=fail_count,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.RECONCILE_ROW_COUNT:
                src = self._qt(self._full_table(logic.source_table or rule.spec_scope.table))
                tol = logic.tolerance_pct / 100.0
                src_count = self._scalar(f"SELECT COUNT(*) FROM {src}")
                tgt_count = self._scalar(f"SELECT COUNT(*) FROM {t}")
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

            elif logic.type == RuleType.RECONCILE_COLUMN_SUM:
                col = self._q(rule.spec_scope.columns[0])
                src = self._qt(self._full_table(logic.source_table or rule.spec_scope.table))
                tol = logic.tolerance_pct / 100.0
                src_sum = float(self._scalar(f"SELECT COALESCE(SUM({col}), 0) FROM {src}") or 0)
                tgt_sum = float(self._scalar(f"SELECT COALESCE(SUM({col}), 0) FROM {t}") or 0)
                passed = (
                    abs(src_sum - tgt_sum) / abs(src_sum) <= tol if src_sum != 0 else tgt_sum == 0
                )
                total = self._scalar(f"SELECT COUNT(*) FROM {t}")
                sample = [] if passed else [{"source_sum": src_sum, "target_sum": tgt_sum}]
                return RuleResult(
                    rule_id=rule.metadata.id,
                    passed=passed,
                    row_count_checked=total,
                    row_count_failed=0 if passed else 1,
                    failure_sample=sample,
                    duration_ms=ms(),
                )

            elif logic.type == RuleType.RECONCILE_KEY_MATCH:
                col = self._q(rule.spec_scope.columns[0])
                src = self._qt(self._full_table(logic.source_table or rule.spec_scope.table))
                total = self._scalar(f"SELECT COUNT(*) FROM {src}")
                missing_in_tgt = self._scalar(
                    f"SELECT COUNT(*) FROM {src} WHERE {col} NOT IN (SELECT {col} FROM {t})"
                )
                missing_in_src = self._scalar(
                    f"SELECT COUNT(*) FROM {t} WHERE {col} NOT IN (SELECT {col} FROM {src})"
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

    async def execute_rule(self, rule: DataQualityRule) -> RuleResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._execute_sync, rule)

    async def close(self) -> None:
        self._client.close()
