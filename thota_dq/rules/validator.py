"""Dry-run rule validation — checks YAML syntax and schema correctness offline.

With --check-sql / conn supplied the validator also runs the SQL verification
pipeline (sqlglot syntax → schema check → DuckDB dry-run) for every
sql_expression and custom_sql rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from .schema import DataQualityRule, RuleLogic, RuleType


@dataclass
class RuleValidationResult:
    index: int                  # position in file (0-based)
    rule_id: str | None         # metadata.id if parseable
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class FileValidationReport:
    path: Path
    results: list[RuleValidationResult]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def valid_count(self) -> int:
        return sum(1 for r in self.results if r.valid)

    @property
    def invalid_count(self) -> int:
        return self.total - self.valid_count

    @property
    def ok(self) -> bool:
        return self.invalid_count == 0


# Rules that require specific logic fields to be set
_REQUIRED_FIELDS: dict[RuleType, list[str]] = {
    RuleType.BETWEEN:               ["min_value", "max_value"],
    RuleType.MIN_VALUE_CHECK:       ["min_value"],
    RuleType.MAX_VALUE_CHECK:       ["max_value"],
    RuleType.REGEX_MATCH:           ["pattern"],
    RuleType.ACCEPTED_VALUES:       ["values"],
    RuleType.NOT_ACCEPTED_VALUES:   ["values"],
    RuleType.FOREIGN_KEY:           ["reference_table", "reference_column"],
    RuleType.CONDITIONAL_NOT_NULL:  ["condition"],
    RuleType.DATE_ORDER:            ["column_b"],
    RuleType.MEAN_BETWEEN:          ["min_value", "max_value"],
    RuleType.COLUMN_SUM_BETWEEN:    ["min_value", "max_value"],
    RuleType.ROW_COUNT_BETWEEN:     ["min_value", "max_value"],
    RuleType.NULL_PERCENTAGE_BELOW: ["threshold"],
    RuleType.DUPLICATE_PERCENTAGE_BELOW: ["threshold"],
    RuleType.STDDEV_BELOW:          ["threshold"],
    RuleType.ROW_COUNT:             ["threshold"],
    RuleType.SQL_EXPRESSION:        ["expression"],
    RuleType.CUSTOM_SQL:            ["query"],
    RuleType.RECONCILE_ROW_COUNT:   ["source_table"],
    RuleType.RECONCILE_COLUMN_SUM:  ["source_table"],
    RuleType.RECONCILE_KEY_MATCH:   ["source_table"],
}

# Rules that require at least one column in scope.columns
_REQUIRES_COLUMN: set[RuleType] = {
    RuleType.NOT_NULL,
    RuleType.NOT_EMPTY_STRING,
    RuleType.UNIQUE,
    RuleType.COMPOSITE_UNIQUE,
    RuleType.BETWEEN,
    RuleType.MIN_VALUE_CHECK,
    RuleType.MAX_VALUE_CHECK,
    RuleType.REGEX_MATCH,
    RuleType.ACCEPTED_VALUES,
    RuleType.NOT_ACCEPTED_VALUES,
    RuleType.FOREIGN_KEY,
    RuleType.NULL_PERCENTAGE_BELOW,
    RuleType.DUPLICATE_PERCENTAGE_BELOW,
    RuleType.MEAN_BETWEEN,
    RuleType.STDDEV_BELOW,
    RuleType.NO_FUTURE_DATES,
    RuleType.COLUMN_EXISTS,
    RuleType.CONDITIONAL_NOT_NULL,
    RuleType.DATE_ORDER,
    RuleType.COLUMN_SUM_BETWEEN,
    RuleType.RECONCILE_COLUMN_SUM,
    RuleType.RECONCILE_KEY_MATCH,
}


def _semantic_errors(rule: DataQualityRule) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for semantic rule correctness beyond Pydantic."""
    errors: list[str] = []
    warnings: list[str] = []
    logic: RuleLogic = rule.spec_logic

    # Check required logic fields per rule type
    required = _REQUIRED_FIELDS.get(logic.type, [])
    for f in required:
        if getattr(logic, f, None) is None:
            errors.append(f"logic.{f} is required for rule type '{logic.type}'")

    # Check column presence where needed
    if logic.type in _REQUIRES_COLUMN and not rule.spec_scope.columns:
        errors.append(f"scope.columns must have at least one entry for rule type '{logic.type}'")

    # Warn about missing description
    if not rule.metadata.description:
        warnings.append("metadata.description is not set — consider adding one for clarity")

    # Warn about missing owner
    if not rule.metadata.owner:
        warnings.append("metadata.owner is not set")

    return errors, warnings


def _sql_errors(
    rule: DataQualityRule,
    conn=None,
) -> list[str]:
    """Run the SQL verification pipeline for sql_expression / custom_sql rules.

    Stage 1 (always):   sqlglot syntax parse
    Stage 2 (conn):     schema-aware column check
    Stage 3 (conn):     0-row dry-run execution

    Returns a list of human-readable error strings.
    """
    from .sql_verify import (
        get_duckdb_schema,
        verify_expression_sync,
        verify_query_sync,
    )

    logic = rule.spec_logic
    table = rule.spec_scope.table
    schema = get_duckdb_schema(conn, table) if conn is not None else None

    if logic.type == RuleType.SQL_EXPRESSION and logic.expression:
        result = verify_expression_sync(logic.expression, table, conn=conn, schema=schema)
        if not result.passed:
            return [f"[sql] {e.stage}: {e.message}" for e in result.errors]

    elif logic.type == RuleType.CUSTOM_SQL and logic.query:
        result = verify_query_sync(logic.query, table, conn=conn, schema=schema)
        if not result.passed:
            return [f"[sql] {e.stage}: {e.message}" for e in result.errors]

    return []


def _parse_raw_doc(data: dict) -> dict:
    """Flatten nested spec structure (mirrors parser._parse_rule logic)."""
    data = dict(data)
    if "spec" in data:
        spec = data.pop("spec")
        data["scope"] = spec.get("scope", {})
        data["logic"] = spec.get("logic", {})
        for k in ("reconciliation", "diagnosis", "remediation", "sla"):
            if k in spec:
                data[k] = spec[k]
    return data


def validate_file(
    path: str | Path,
    check_sql: bool = False,
    conn=None,
) -> FileValidationReport:
    """Validate all rules in a YAML file.

    Args:
        path:      Path to the rules YAML file.
        check_sql: When True, run the SQL verification pipeline for
                   sql_expression and custom_sql rules (Stage 1 always;
                   Stages 2 + 3 require *conn*).
        conn:      Live DuckDB connection for schema-aware + dry-run checks.
                   Implies check_sql=True when provided.

    Returns a FileValidationReport with per-rule results. Never raises —
    all errors are captured and returned as structured results.
    """
    if conn is not None:
        check_sql = True
    path = Path(path)
    results: list[RuleValidationResult] = []

    # Step 1 — parse YAML
    try:
        text = path.read_text()
        docs = list(yaml.safe_load_all(text))
    except FileNotFoundError:
        return FileValidationReport(
            path=path,
            results=[RuleValidationResult(
                index=0, rule_id=None, valid=False,
                errors=[f"File not found: {path}"],
            )],
        )
    except yaml.YAMLError as exc:
        return FileValidationReport(
            path=path,
            results=[RuleValidationResult(
                index=0, rule_id=None, valid=False,
                errors=[f"YAML syntax error: {exc}"],
            )],
        )

    # Step 2 — flatten docs into a list of raw rule dicts
    raw_rules: list[dict] = []
    for doc in docs:
        if doc is None:
            continue
        if isinstance(doc, dict) and "rules" in doc:
            raw_rules.extend(doc["rules"])
        elif isinstance(doc, list):
            raw_rules.extend(doc)
        elif isinstance(doc, dict):
            raw_rules.append(doc)

    if not raw_rules:
        return FileValidationReport(
            path=path,
            results=[RuleValidationResult(
                index=0, rule_id=None, valid=False,
                errors=["No rules found in file"],
            )],
        )

    # Step 3 — validate each rule
    for i, raw in enumerate(raw_rules):
        rule_id: str | None = None
        try:
            rule_id = raw.get("metadata", {}).get("id") if isinstance(raw, dict) else None
        except Exception:
            pass

        try:
            flat = _parse_raw_doc(raw)
            rule = DataQualityRule.model_validate(flat, from_attributes=False)
            rule_id = rule.metadata.id
            sem_errors, warnings = _semantic_errors(rule)
            if check_sql:
                sem_errors = sem_errors + _sql_errors(rule, conn=conn)
            results.append(RuleValidationResult(
                index=i,
                rule_id=rule_id,
                valid=len(sem_errors) == 0,
                errors=sem_errors,
                warnings=warnings,
            ))
        except ValidationError as exc:
            errs = [f"{' → '.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()]
            results.append(RuleValidationResult(
                index=i, rule_id=rule_id, valid=False, errors=errs,
            ))
        except Exception as exc:
            results.append(RuleValidationResult(
                index=i, rule_id=rule_id, valid=False,
                errors=[f"Unexpected error: {exc}"],
            ))

    return FileValidationReport(path=path, results=results)
