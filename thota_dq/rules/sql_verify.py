"""SQL verification pipeline — three progressive stages.

Stage 1 (always available): sqlglot syntax parse — offline, no DB needed.
Stage 2 (schema provided):  column/table existence check via sqlglot AST.
Stage 3 (conn provided):    dry-run execution against a 0-row result set.

After any stage failure an optional LLM self-correction loop retries up to
max_retries times, feeding the error message back to the model.

Usage
-----
# Offline syntax only
result = verify_expression_sync("revenue >= 0", "orders")

# Full pipeline with a live DuckDB connection
schema = get_duckdb_schema(conn, "orders")
result = verify_expression_sync("revenue >= 0", "orders", conn=conn, schema=schema)

# Async with LLM self-correction
result = await verify_and_fix(
    sql="revenue >= 0",
    mode="expression",
    table="orders",
    llm=llm_adapter,
    conn=conn,
    schema=schema,
)
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SqlError:
    stage: str      # "syntax" | "schema" | "dry_run"
    message: str


@dataclass
class VerifyResult:
    sql: str                             # final SQL (may differ after LLM fix)
    passed: bool
    errors: list[SqlError] = field(default_factory=list)
    fixes_applied: int = 0               # number of LLM correction iterations used


# ---------------------------------------------------------------------------
# Stage 1 — Syntax
# ---------------------------------------------------------------------------

def check_syntax(sql: str, dialect: str = "duckdb") -> list[SqlError]:
    """Parse *sql* with sqlglot.  Returns an empty list when valid."""
    import sqlglot
    import sqlglot.errors as sge

    try:
        sqlglot.parse_one(sql, dialect=dialect, error_level=sge.ErrorLevel.RAISE)
        return []
    except sge.ParseError as exc:
        return [SqlError(stage="syntax", message=str(exc))]
    except Exception as exc:
        return [SqlError(stage="syntax", message=f"Unexpected parse error: {exc}")]


# ---------------------------------------------------------------------------
# Stage 2 — Schema (column existence)
# ---------------------------------------------------------------------------

def _extract_column_refs(sql: str) -> list[tuple[str | None, str]]:
    """Return [(table_qualifier_or_None, column_name), ...] from the AST."""
    import sqlglot
    try:
        tree = sqlglot.parse_one(sql, dialect="duckdb")
    except Exception:
        return []
    return [
        (col.table if col.table else None, col.name)
        for col in tree.find_all(sqlglot.exp.Column)
    ]


def check_schema(
    sql: str,
    default_table: str,
    schema: dict[str, list[str]],
) -> list[SqlError]:
    """Check that every column reference in *sql* exists in *schema*.

    schema: {table_name: [col1, col2, ...]}
    Unqualified columns are checked against *default_table*.
    """
    errors: list[SqlError] = []
    for tbl_ref, col_name in _extract_column_refs(sql):
        target = tbl_ref or default_table
        known = schema.get(target, [])
        if known and col_name.lower() not in {c.lower() for c in known}:
            sample = ", ".join(known[:8]) + ("…" if len(known) > 8 else "")
            errors.append(SqlError(
                stage="schema",
                message=(
                    f"Column '{col_name}' not found in '{target}'. "
                    f"Available: {sample}"
                ),
            ))
    return errors


def get_duckdb_schema(conn, table: str) -> dict[str, list[str]]:
    """Fetch column names for *table* from a live DuckDB connection."""
    try:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ?",
            [table],
        ).fetchall()
        return {table: [r[0] for r in rows]}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Stage 3 — Dry-run (0-row execution)
# ---------------------------------------------------------------------------

def _execute_dry(conn, sql: str) -> list[SqlError]:
    try:
        conn.execute(sql)
        return []
    except Exception as exc:
        msg = str(exc)
        # Strip DuckDB internal path noise
        if "\n" in msg:
            msg = msg.split("\n")[0]
        return [SqlError(stage="dry_run", message=msg)]


def dry_run_expression(conn, expression: str, table: str) -> list[SqlError]:
    """Validate a WHERE-clause fragment by running a 0-row SELECT."""
    sql = f"SELECT 1 FROM {table} WHERE NOT ({expression}) LIMIT 0"
    return _execute_dry(conn, sql)


def dry_run_query(conn, query: str) -> list[SqlError]:
    """Validate a full SELECT query by wrapping it in a 0-row shell."""
    wrapped = f"SELECT * FROM ({query}) _aegis_dry LIMIT 0"
    return _execute_dry(conn, wrapped)


# ---------------------------------------------------------------------------
# Combined sync verifiers (safe to call inside ThreadPoolExecutors)
# ---------------------------------------------------------------------------

def verify_expression_sync(
    expression: str,
    table: str,
    conn=None,
    schema: dict[str, list[str]] | None = None,
    dialect: str = "duckdb",
) -> VerifyResult:
    """Verify a SQL WHERE-clause expression through all available stages."""
    wrapped = f"SELECT 1 FROM {table} WHERE NOT ({expression})"

    errs = check_syntax(wrapped, dialect)
    if errs:
        return VerifyResult(sql=expression, passed=False, errors=errs)

    if schema:
        errs = check_schema(wrapped, table, schema)
        if errs:
            return VerifyResult(sql=expression, passed=False, errors=errs)

    if conn is not None:
        errs = dry_run_expression(conn, expression, table)
        if errs:
            return VerifyResult(sql=expression, passed=False, errors=errs)

    return VerifyResult(sql=expression, passed=True)


def verify_query_sync(
    query: str,
    table: str,
    conn=None,
    schema: dict[str, list[str]] | None = None,
    dialect: str = "duckdb",
) -> VerifyResult:
    """Verify a full SELECT query through all available stages."""
    errs = check_syntax(query, dialect)
    if errs:
        return VerifyResult(sql=query, passed=False, errors=errs)

    if schema:
        errs = check_schema(query, table, schema)
        if errs:
            return VerifyResult(sql=query, passed=False, errors=errs)

    if conn is not None:
        errs = dry_run_query(conn, query)
        if errs:
            return VerifyResult(sql=query, passed=False, errors=errs)

    return VerifyResult(sql=query, passed=True)


def verify_statement_sync(
    statement: str,
    dialect: str = "duckdb",
) -> VerifyResult:
    """Verify a DML statement (UPDATE/DELETE/INSERT) — syntax only.

    Dry-run is intentionally skipped for DML to avoid accidental mutations.
    """
    errs = check_syntax(statement, dialect)
    if errs:
        return VerifyResult(sql=statement, passed=False, errors=errs)
    return VerifyResult(sql=statement, passed=True)


# ---------------------------------------------------------------------------
# LLM self-correction loop (async)
# ---------------------------------------------------------------------------

_FIX_SYSTEM = (
    "You are a SQL expert. The SQL below contains an error. "
    "Output only the corrected SQL — no explanation, no markdown fences."
)


async def verify_and_fix(
    sql: str,
    mode: str,             # "expression" | "query" | "statement"
    table: str,
    llm=None,              # LLMAdapter | None
    conn=None,
    schema: dict[str, list[str]] | None = None,
    dialect: str = "duckdb",
    max_retries: int = 3,
) -> VerifyResult:
    """Verify SQL and optionally self-correct via LLM on failure.

    mode:
        "expression" — WHERE-clause fragment (SELECT wrapper applied internally)
        "query"      — full SELECT query
        "statement"  — DML (UPDATE/DELETE/INSERT), syntax-only verification
    """
    _verify = {
        "expression": lambda s: verify_expression_sync(s, table, conn, schema, dialect),
        "query":      lambda s: verify_query_sync(s, table, conn, schema, dialect),
        "statement":  lambda s: verify_statement_sync(s, dialect),
    }[mode]

    result = _verify(sql)
    if result.passed or llm is None:
        return result

    current = sql
    for attempt in range(1, max_retries + 1):
        error_msg = result.errors[0].message if result.errors else "unknown error"
        prompt = (
            f"Mode: {mode}\n"
            f"Table: {table}\n"
            f"SQL:\n{current}\n\n"
            f"Error: {error_msg}\n\n"
            "Output only the corrected SQL."
        )
        try:
            fixed_text, _, _ = await llm.complete(_FIX_SYSTEM, prompt, max_tokens=512)
        except Exception:
            break

        # Strip any markdown the LLM might add
        fixed = fixed_text.strip()
        for fence in ("```sql", "```SQL", "```"):
            if fixed.startswith(fence):
                fixed = fixed[len(fence):]
        fixed = fixed.rstrip("`").strip()

        new_result = _verify(fixed)
        new_result.fixes_applied = attempt

        if new_result.passed:
            return new_result

        current = fixed
        result = new_result

    result.fixes_applied = max_retries
    return result
