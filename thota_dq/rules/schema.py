"""Pydantic v2 models for Aegis rule schema."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .sql_safety import validate_custom_sql, validate_expression

# Strict identifier patterns — enforced on all user-provided table/column names.
# Allows schema.table and db.schema.table but rejects SQL metacharacters.
_TABLE_IDENT = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z_][A-Za-z0-9_-]*){0,2}$"
)
_COLUMN_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class RuleType(StrEnum):
    SQL_EXPRESSION = "sql_expression"
    NOT_NULL = "not_null"
    UNIQUE = "unique"
    ROW_COUNT = "row_count"
    FRESHNESS = "freshness"
    CUSTOM_SQL = "custom_sql"
    # New types
    NOT_EMPTY_STRING = "not_empty_string"
    COMPOSITE_UNIQUE = "composite_unique"
    BETWEEN = "between"
    MIN_VALUE_CHECK = "min_value_check"
    MAX_VALUE_CHECK = "max_value_check"
    REGEX_MATCH = "regex_match"
    ACCEPTED_VALUES = "accepted_values"
    NOT_ACCEPTED_VALUES = "not_accepted_values"
    FOREIGN_KEY = "foreign_key"
    NULL_PERCENTAGE_BELOW = "null_percentage_below"
    DUPLICATE_PERCENTAGE_BELOW = "duplicate_percentage_below"
    MEAN_BETWEEN = "mean_between"
    NO_FUTURE_DATES = "no_future_dates"
    ROW_COUNT_BETWEEN = "row_count_between"
    COLUMN_SUM_BETWEEN = "column_sum_between"
    CONDITIONAL_NOT_NULL = "conditional_not_null"
    DATE_ORDER = "date_order"
    COLUMN_EXISTS = "column_exists"
    STDDEV_BELOW = "stddev_below"
    # Reconciliation
    RECONCILE_ROW_COUNT = "reconcile_row_count"
    RECONCILE_COLUMN_SUM = "reconcile_column_sum"
    RECONCILE_KEY_MATCH = "reconcile_key_match"
    # ML / statistical anomaly detection
    ZSCORE_OUTLIER = "zscore_outlier"
    ISOLATION_FOREST = "isolation_forest"
    LEARNED_THRESHOLD = "learned_threshold"


class RuleScope(BaseModel):
    warehouse: str = "duckdb"
    database: str | None = None
    schema_name: str | None = Field(None, alias="schema")  # 'schema' is reserved
    table: str
    columns: list[str] = []

    model_config = {"populate_by_name": True}

    @field_validator("table")
    @classmethod
    def _validate_table(cls, v: str) -> str:
        if not _TABLE_IDENT.match(v):
            raise ValueError(
                f"Invalid table identifier {v!r}. "
                "Must be alphanumeric with underscores, optionally qualified as schema.table."
            )
        return v

    @field_validator("columns")
    @classmethod
    def _validate_columns(cls, v: list[str]) -> list[str]:
        for col in v:
            if not _COLUMN_IDENT.match(col):
                raise ValueError(
                    f"Invalid column identifier {col!r}. "
                    "Must be alphanumeric with underscores only."
                )
        return v


class RuleLogic(BaseModel):
    type: RuleType
    expression: str | None = None  # SQL WHERE clause (rows that PASS)
    query: str | None = None  # full custom SQL — must return (passed: bool, row_count: int)
    threshold: float | None = None  # for row_count, freshness, null_percentage_below, etc.
    unit: str | None = None  # "hours", "rows", etc.
    # New fields for extended rule types
    min_value: float | None = None       # for between, mean_between, column_sum_between
    max_value: float | None = None       # for between, row_count_between, column_sum_between
    pattern: str | None = None           # for regex_match
    values: list[str] | None = None      # for accepted_values / not_accepted_values
    reference_table: str | None = None   # for foreign_key
    reference_column: str | None = None  # for foreign_key
    condition: str | None = None         # SQL expression for conditional_not_null
    column_b: str | None = None          # second column for date_order
    source_table: str | None = None      # reconciliation: table to compare against
    tolerance_pct: float = 0.0           # reconciliation: allowed % deviation (0.0 = exact)
    # ML / statistical anomaly detection
    zscore_threshold: float | None = None  # z-score cutoff (default 3.0)
    contamination: float | None = None     # isolation_forest: expected anomaly fraction (0.0–0.5)
    min_history_days: int | None = None    # learned_threshold: minimum history required

    @field_validator("expression", "condition")
    @classmethod
    def _validate_sql_expression(cls, v: str | None) -> str | None:
        if v is not None:
            validate_expression(v)
        return v

    @field_validator("pattern")
    @classmethod
    def _validate_pattern(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                re.compile(v)
            except re.error as e:
                raise ValueError(f"Invalid regex pattern: {e}") from e
        return v

    @field_validator("column_b", "reference_column")
    @classmethod
    def _validate_column_ident(cls, v: str | None) -> str | None:
        if v is not None and not _COLUMN_IDENT.match(v):
            raise ValueError(
                f"Invalid column identifier {v!r}. "
                "Must be alphanumeric with underscores only."
            )
        return v

    @field_validator("reference_table", "source_table")
    @classmethod
    def _validate_table_ident(cls, v: str | None) -> str | None:
        if v is not None and not _TABLE_IDENT.match(v):
            raise ValueError(
                f"Invalid table identifier {v!r}. "
                "Must be alphanumeric with underscores, optionally qualified as schema.table."
            )
        return v

    @field_validator("query")
    @classmethod
    def _validate_custom_query(cls, v: str | None) -> str | None:
        if v is not None:
            validate_custom_sql(v)
        return v


class ReconciliationConfig(BaseModel):
    source_table: str
    source_column: str
    transform: str | None = None
    tolerance: float = 0.0


class DiagnosisHints(BaseModel):
    common_causes: list[str] = []
    lineage_hints: dict[str, list[str]] = {}


class RemediationConfig(BaseModel):
    auto_remediate: bool = False
    proposal_strategy: Literal["llm_with_lineage", "llm_simple", "none"] = "llm_simple"


class SLAConfig(BaseModel):
    detection_window: str = "1h"
    notification_target: str | None = None


class RuleMetadata(BaseModel):
    id: str
    domain: str | None = None
    severity: Severity = Severity.MEDIUM
    owner: str | None = None
    tags: list[str] = []
    description: str | None = None
    # Versioning (Stage 4)
    version: str = "1.0.0"
    status: Literal["draft", "active", "deprecated"] = "draft"
    generated_by: str | None = None


class DataQualityRule(BaseModel):
    api_version: str = Field("aegis.dev/v1", alias="apiVersion")
    kind: str = "DataQualityRule"
    metadata: RuleMetadata
    spec_scope: RuleScope = Field(..., alias="scope")
    spec_logic: RuleLogic = Field(..., alias="logic")
    reconciliation: ReconciliationConfig | None = None
    diagnosis: DiagnosisHints = Field(default_factory=DiagnosisHints)
    remediation: RemediationConfig = Field(default_factory=RemediationConfig)
    sla: SLAConfig = Field(default_factory=SLAConfig)

    model_config = {"populate_by_name": True}


class RuleResult(BaseModel):
    rule_id: str
    passed: bool
    row_count_checked: int = 0
    row_count_failed: int = 0
    failure_sample: list[dict[str, Any]] = []
    error: str | None = None
    duration_ms: float = 0.0


class RuleFailure(BaseModel):
    rule: DataQualityRule
    result: RuleResult
