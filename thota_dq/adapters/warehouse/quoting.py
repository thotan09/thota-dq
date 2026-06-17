"""SQL identifier quoting and string literal escaping per warehouse dialect.

Each adapter imports the quote function that matches its dialect. All quoting
functions handle multi-part qualified names (schema.table, db.schema.table)
by quoting each part independently.
"""
from __future__ import annotations

# ── Identifier quoting ────────────────────────────────────────────────────────

def _quote_double(name: str) -> str:
    """ANSI SQL double-quote quoting. Escapes embedded double-quotes by doubling."""
    return '"' + name.replace('"', '""') + '"'


def _quote_backtick(name: str) -> str:
    """Backtick quoting (BigQuery, Databricks/Spark SQL). Escapes embedded backticks."""
    return "`" + name.replace("`", "``") + "`"


def quote_qualified_ansi(name: str) -> str:
    """Quote a possibly-qualified identifier using ANSI double-quote style.

    Handles schema.table and db.schema.table by quoting each dot-separated part.
    Used by: DuckDB, Athena (Presto/Trino), PostgreSQL, Redshift.
    """
    return ".".join(_quote_double(p) for p in name.split(".") if p)


def quote_qualified_bigquery(name: str) -> str:
    """Quote a possibly-qualified identifier using BigQuery backtick style.

    Handles project.dataset.table by quoting each part independently.
    """
    return ".".join(_quote_backtick(p) for p in name.split(".") if p)


def quote_qualified_spark(name: str) -> str:
    """Quote a possibly-qualified identifier using Spark SQL backtick style.

    Handles catalog.schema.table by quoting each part independently.
    Used by: Databricks.
    """
    return ".".join(_quote_backtick(p) for p in name.split(".") if p)


# ── String literal escaping ───────────────────────────────────────────────────

def escape_string_literal(value: str) -> str:
    """Escape a value for safe inclusion in a SQL single-quoted string literal.

    Doubles any embedded single-quotes per the SQL standard.
    Use for regex patterns and accepted-values list items — NOT for identifiers.

    Example:
        f"WHERE col = '{escape_string_literal(user_value)}'"
    """
    return value.replace("'", "''")
