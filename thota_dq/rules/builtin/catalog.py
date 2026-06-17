"""Built-in rule template catalog — 30 named templates."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BuiltinTemplate:
    name: str
    category: str  # completeness, validity, uniqueness, statistical, volume, timeliness, referential
    description: str
    logic: dict
    default_severity: str
    tags: list[str] = field(default_factory=list)


CATALOG: list[BuiltinTemplate] = [
    # ── Completeness (5) ─────────────────────────────────────────────────────
    BuiltinTemplate(
        name="not_null",
        category="completeness",
        description="Column must not contain NULL values.",
        logic={"type": "not_null"},
        default_severity="high",
        tags=["completeness", "null"],
    ),
    BuiltinTemplate(
        name="not_empty_string",
        category="completeness",
        description="Column must not contain empty or whitespace-only strings.",
        logic={"type": "not_empty_string"},
        default_severity="medium",
        tags=["completeness", "string"],
    ),
    BuiltinTemplate(
        name="not_null_or_empty",
        category="completeness",
        description="Column must not contain NULL values or empty/whitespace strings.",
        logic={"type": "not_empty_string"},
        default_severity="high",
        tags=["completeness", "null", "string"],
    ),
    BuiltinTemplate(
        name="null_pct_below_1",
        category="completeness",
        description="NULL values must represent less than 1% of rows.",
        logic={"type": "null_percentage_below", "threshold": 1.0},
        default_severity="medium",
        tags=["completeness", "null", "percentage"],
    ),
    BuiltinTemplate(
        name="null_pct_below_5",
        category="completeness",
        description="NULL values must represent less than 5% of rows.",
        logic={"type": "null_percentage_below", "threshold": 5.0},
        default_severity="low",
        tags=["completeness", "null", "percentage"],
    ),
    # ── Uniqueness (3) ───────────────────────────────────────────────────────
    BuiltinTemplate(
        name="unique",
        category="uniqueness",
        description="Column values must be unique across the table.",
        logic={"type": "unique"},
        default_severity="high",
        tags=["uniqueness"],
    ),
    BuiltinTemplate(
        name="composite_unique",
        category="uniqueness",
        description="Combination of specified columns must be unique across the table.",
        logic={"type": "composite_unique"},
        default_severity="high",
        tags=["uniqueness", "composite"],
    ),
    BuiltinTemplate(
        name="duplicate_pct_below_1",
        category="uniqueness",
        description="Duplicate values must represent less than 1% of rows.",
        logic={"type": "duplicate_percentage_below", "threshold": 1.0},
        default_severity="medium",
        tags=["uniqueness", "duplicate", "percentage"],
    ),
    # ── Validity — Numeric (5) ───────────────────────────────────────────────
    BuiltinTemplate(
        name="positive",
        category="validity",
        description="Column values must be strictly positive (> 0).",
        logic={"type": "min_value_check", "min_value": 0.000001},
        default_severity="high",
        tags=["validity", "numeric"],
    ),
    BuiltinTemplate(
        name="non_negative",
        category="validity",
        description="Column values must be non-negative (>= 0).",
        logic={"type": "min_value_check", "min_value": 0.0},
        default_severity="medium",
        tags=["validity", "numeric"],
    ),
    BuiltinTemplate(
        name="between",
        category="validity",
        description="Column values must fall between min_value and max_value (inclusive). Set min_value and max_value.",
        logic={"type": "between"},
        default_severity="medium",
        tags=["validity", "numeric", "range"],
    ),
    BuiltinTemplate(
        name="max_value_check",
        category="validity",
        description="Column values must not exceed max_value. Set max_value.",
        logic={"type": "max_value_check"},
        default_severity="medium",
        tags=["validity", "numeric"],
    ),
    BuiltinTemplate(
        name="percentage",
        category="validity",
        description="Column values must be a valid percentage between 0 and 100.",
        logic={"type": "between", "min_value": 0.0, "max_value": 100.0},
        default_severity="medium",
        tags=["validity", "numeric", "percentage"],
    ),
    # ── Validity — String (4) ────────────────────────────────────────────────
    BuiltinTemplate(
        name="email_format",
        category="validity",
        description="Column values must match a valid email address format.",
        logic={
            "type": "regex_match",
            "pattern": r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$",
        },
        default_severity="medium",
        tags=["validity", "string", "email", "regex"],
    ),
    BuiltinTemplate(
        name="iso_date_format",
        category="validity",
        description="Column values must match ISO 8601 date format (YYYY-MM-DD).",
        logic={"type": "regex_match", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        default_severity="medium",
        tags=["validity", "string", "date", "regex"],
    ),
    BuiltinTemplate(
        name="accepted_values",
        category="validity",
        description="Column values must belong to a predefined allowed set. Set values list.",
        logic={"type": "accepted_values"},
        default_severity="high",
        tags=["validity", "string", "categorical"],
    ),
    BuiltinTemplate(
        name="no_rejected_values",
        category="validity",
        description="Column values must not appear in a prohibited set. Set values list.",
        logic={"type": "not_accepted_values"},
        default_severity="high",
        tags=["validity", "string", "categorical"],
    ),
    # ── Validity — Temporal (4) ──────────────────────────────────────────────
    BuiltinTemplate(
        name="no_future_dates",
        category="timeliness",
        description="Date/timestamp column must not contain future dates.",
        logic={"type": "no_future_dates"},
        default_severity="medium",
        tags=["timeliness", "date"],
    ),
    BuiltinTemplate(
        name="freshness_1h",
        category="timeliness",
        description="Table must have been updated within the last 1 hour.",
        logic={"type": "freshness", "threshold": 1, "unit": "hours"},
        default_severity="high",
        tags=["timeliness", "freshness"],
    ),
    BuiltinTemplate(
        name="freshness_24h",
        category="timeliness",
        description="Table must have been updated within the last 24 hours.",
        logic={"type": "freshness", "threshold": 24, "unit": "hours"},
        default_severity="medium",
        tags=["timeliness", "freshness"],
    ),
    BuiltinTemplate(
        name="date_order",
        category="timeliness",
        description="First date column must be <= second date column (e.g. start <= end). Set column_b.",
        logic={"type": "date_order"},
        default_severity="medium",
        tags=["timeliness", "date", "ordering"],
    ),
    # ── Referential Integrity (2) ────────────────────────────────────────────
    BuiltinTemplate(
        name="foreign_key",
        category="referential",
        description="Column values must exist in a referenced table's column. Set reference_table and reference_column.",
        logic={"type": "foreign_key"},
        default_severity="high",
        tags=["referential", "integrity", "foreign_key"],
    ),
    BuiltinTemplate(
        name="conditional_not_null",
        category="referential",
        description="Column must not be NULL when a SQL condition is true. Set condition.",
        logic={"type": "conditional_not_null"},
        default_severity="high",
        tags=["completeness", "conditional"],
    ),
    # ── Statistical (4) ──────────────────────────────────────────────────────
    BuiltinTemplate(
        name="mean_between",
        category="statistical",
        description="Column mean must fall between min_value and max_value. Set min_value and max_value.",
        logic={"type": "mean_between"},
        default_severity="medium",
        tags=["statistical", "mean", "numeric"],
    ),
    BuiltinTemplate(
        name="stddev_below",
        category="statistical",
        description="Column standard deviation must not exceed threshold. Set threshold.",
        logic={"type": "stddev_below"},
        default_severity="low",
        tags=["statistical", "stddev", "numeric"],
    ),
    BuiltinTemplate(
        name="column_sum_between",
        category="statistical",
        description="Column sum must fall between min_value and max_value. Set min_value and max_value.",
        logic={"type": "column_sum_between"},
        default_severity="medium",
        tags=["statistical", "sum", "numeric"],
    ),
    BuiltinTemplate(
        name="column_exists",
        category="validity",
        description="Specified column must exist in the table.",
        logic={"type": "column_exists"},
        default_severity="critical",
        tags=["validity", "schema"],
    ),
    # ── Volume (3) ───────────────────────────────────────────────────────────
    BuiltinTemplate(
        name="min_row_count",
        category="volume",
        description="Table must contain at least 1 row.",
        logic={"type": "row_count", "threshold": 1},
        default_severity="medium",
        tags=["volume", "row_count"],
    ),
    BuiltinTemplate(
        name="row_count_between",
        category="volume",
        description="Table row count must fall between min_value and max_value. Set min_value and max_value.",
        logic={"type": "row_count_between"},
        default_severity="medium",
        tags=["volume", "row_count", "range"],
    ),
    BuiltinTemplate(
        name="has_data",
        category="volume",
        description="Table must contain at least 1 row (critical severity).",
        logic={"type": "row_count", "threshold": 1},
        default_severity="critical",
        tags=["volume", "row_count"],
    ),
]
