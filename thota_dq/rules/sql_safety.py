"""SQL safety validation for user-provided rule fields.

Two layers of defense against SQL injection:
  Layer 1 — forbidden pattern/keyword scan (fast, string-level)
  Layer 2 — sqlglot AST parse + denylist of dangerous node types

Called by Pydantic validators in schema.py so that malicious payloads
are rejected at rule-parse time, before reaching any warehouse adapter.
"""
from __future__ import annotations

import re

import sqlglot
import sqlglot.errors
from sqlglot import exp


class UnsafeSQLExpression(ValueError):
    """Raised when a rule field contains disallowed SQL constructs."""


# ── String-level forbidden patterns ──────────────────────────────────────────

_FORBIDDEN_PATTERNS = (
    ";",    # statement terminator — prevents stacked queries
    "--",   # line comment — used to mask injection tails
    "/*",   # block comment open
    "*/",   # block comment close
)

# Keywords forbidden in WHERE-clause expression/condition fields.
# SELECT/UNION/WITH would indicate an embedded full query, not an expression.
_FORBIDDEN_EXPR_KEYWORDS = (
    "SELECT", "UNION", "INTERSECT", "EXCEPT", "WITH",
    "DROP", "DELETE", "INSERT", "UPDATE", "TRUNCATE",
    "ALTER", "CREATE", "GRANT", "REVOKE",
    "EXECUTE", "EXEC", "CALL", "LOAD_FILE",
)

# Lighter set for CUSTOM_SQL query fields (full SELECT is expected there).
_FORBIDDEN_QUERY_KEYWORDS = (
    "DROP", "DELETE", "INSERT", "UPDATE", "TRUNCATE",
    "ALTER", "CREATE", "GRANT", "REVOKE",
    "EXECUTE", "EXEC", "CALL", "LOAD_FILE",
)

# ── AST-level denylist ────────────────────────────────────────────────────────

_FORBIDDEN_NODE_TYPES = frozenset({
    exp.Subquery,
    exp.Union,
    exp.Intersect,
    exp.Except,
    exp.Create,
    exp.Drop,
    exp.Delete,
    exp.Insert,
    exp.Update,
    exp.TruncateTable,
    exp.Command,
    exp.Show,
    exp.Use,
    exp.Exists,
})


# ── Public validators ─────────────────────────────────────────────────────────

def validate_expression(expr_text: str) -> None:
    """Validate a SQL WHERE-clause fragment (expression / condition fields).

    Raises UnsafeSQLExpression if disallowed constructs are detected.
    Does not raise if sqlglot cannot parse due to dialect-specific syntax —
    string-level checks already guard against the most dangerous patterns.
    """
    upper = expr_text.upper()

    for pat in _FORBIDDEN_PATTERNS:
        if pat in upper:
            raise UnsafeSQLExpression(
                f"SQL expression contains forbidden pattern {pat!r}. "
                "Use simple comparison expressions without comments or statement terminators."
            )

    for kw in _FORBIDDEN_EXPR_KEYWORDS:
        if re.search(r"\b" + kw + r"\b", upper):
            raise UnsafeSQLExpression(
                f"SQL expression contains forbidden keyword {kw!r}. "
                "Expression fields must be WHERE-clause fragments, not full SQL statements."
            )

    # AST check: wrap the expression in a SELECT so sqlglot can parse it,
    # then walk the tree and reject dangerous node types.
    try:
        wrapped = f"SELECT * FROM _t WHERE {expr_text}"
        parsed = sqlglot.parse_one(
            wrapped,
            dialect="duckdb",
            error_level=sqlglot.errors.ErrorLevel.RAISE,
        )
        for node in parsed.walk():
            if type(node) in _FORBIDDEN_NODE_TYPES:
                raise UnsafeSQLExpression(
                    f"SQL expression contains forbidden construct: {type(node).__name__}."
                )
            # A Select nested inside the outer wrapper = subquery injection.
            if isinstance(node, exp.Select) and node.parent is not None:
                raise UnsafeSQLExpression(
                    "SQL expression contains an embedded SELECT statement. "
                    "Subqueries are not allowed in expression fields."
                )
    except sqlglot.errors.SqlglotError:
        # Dialect-specific syntax that sqlglot can't parse. String-level checks
        # already passed, so proceed. The adapter will catch SQL errors at runtime.
        pass


def validate_custom_sql(query_text: str) -> None:
    """Light validation for CUSTOM_SQL query fields.

    CUSTOM_SQL is an intentional full-SQL escape hatch, so SELECT is allowed.
    We only forbid statement stacking and DDL/DML keywords.
    """
    upper = query_text.upper()

    for pat in _FORBIDDEN_PATTERNS:
        if pat in upper:
            raise UnsafeSQLExpression(
                f"Custom SQL query contains forbidden pattern {pat!r}."
            )

    for kw in _FORBIDDEN_QUERY_KEYWORDS:
        if re.search(r"\b" + kw + r"\b", upper):
            raise UnsafeSQLExpression(
                f"Custom SQL query contains forbidden keyword {kw!r}. "
                "CUSTOM_SQL must be a SELECT query — DDL and DML are not allowed."
            )
