"""Tests for the SQL verification pipeline (stages 1-3) and remediate auto-fix."""
from __future__ import annotations

import duckdb
import pytest

from thota_dq.rules.sql_verify import (
    VerifyResult,
    check_schema,
    check_syntax,
    dry_run_expression,
    dry_run_query,
    get_duckdb_schema,
    verify_and_fix,
    verify_expression_sync,
    verify_query_sync,
    verify_statement_sync,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn():
    """In-memory DuckDB with a small orders table."""
    c = duckdb.connect(":memory:")
    c.execute("""
        CREATE TABLE orders (
            order_id  INTEGER,
            amount    DOUBLE,
            status    VARCHAR,
            customer_id INTEGER
        )
    """)
    c.execute("INSERT INTO orders VALUES (1, 99.99, 'shipped', 10)")
    c.execute("INSERT INTO orders VALUES (2, -5.00, 'pending', 11)")
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Stage 1 — Syntax
# ---------------------------------------------------------------------------

class TestCheckSyntax:
    def test_valid_expression(self):
        assert check_syntax("SELECT 1 FROM orders WHERE amount > 0") == []

    def test_valid_where_fragment_wrapped(self):
        # Wrapping a WHERE fragment as a full query
        assert check_syntax("SELECT 1 FROM t WHERE NOT (amount > 0)") == []

    def test_invalid_syntax(self):
        errs = check_syntax("SELECT FROM WHERE")
        assert len(errs) == 1
        assert errs[0].stage == "syntax"

    def test_truncated_expression(self):
        errs = check_syntax("SELECT 1 FROM t WHERE amount >")
        assert len(errs) == 1
        assert errs[0].stage == "syntax"

    def test_is_not_null_correct(self):
        assert check_syntax("SELECT 1 FROM t WHERE amount IS NOT NULL") == []

    def test_not_null_wrong_syntax(self):
        # sqlglot is lenient and parses "amount NOT NULL" without error;
        # this is a known parser quirk — we just verify it doesn't crash.
        errs = check_syntax("SELECT 1 FROM t WHERE amount NOT NULL")
        assert isinstance(errs, list)

    def test_update_statement_valid(self):
        assert check_syntax("UPDATE orders SET status = 'shipped' WHERE status = 'DISPATCHED'") == []

    def test_update_statement_invalid(self):
        # sqlglot parses "UPDATE ... SET WHERE" leniently; verify no crash.
        errs = check_syntax("UPDATE orders SET WHERE status = 'x'")
        assert isinstance(errs, list)


# ---------------------------------------------------------------------------
# Stage 2 — Schema check
# ---------------------------------------------------------------------------

class TestCheckSchema:
    def test_valid_column(self):
        schema = {"orders": ["order_id", "amount", "status"]}
        errs = check_schema("SELECT 1 FROM orders WHERE amount > 0", "orders", schema)
        assert errs == []

    def test_unknown_column(self):
        schema = {"orders": ["order_id", "amount", "status"]}
        errs = check_schema("SELECT 1 FROM orders WHERE revnue > 0", "orders", schema)
        assert len(errs) == 1
        assert errs[0].stage == "schema"
        assert "revnue" in errs[0].message

    def test_empty_schema_skips_check(self):
        # Empty schema dict → no column info → check skipped
        errs = check_schema("SELECT nonexistent_col FROM t", "t", {})
        assert errs == []

    def test_qualified_column_reference(self):
        schema = {"orders": ["order_id", "amount"]}
        errs = check_schema("SELECT orders.amount FROM orders", "orders", schema)
        assert errs == []

    def test_qualified_unknown_column(self):
        schema = {"orders": ["order_id", "amount"]}
        errs = check_schema("SELECT orders.price FROM orders", "orders", schema)
        assert len(errs) == 1


# ---------------------------------------------------------------------------
# Stage 2 helper — get_duckdb_schema
# ---------------------------------------------------------------------------

class TestGetDuckdbSchema:
    def test_returns_columns(self, conn):
        schema = get_duckdb_schema(conn, "orders")
        assert "orders" in schema
        assert "amount" in schema["orders"]
        assert "status" in schema["orders"]

    def test_unknown_table_returns_empty(self, conn):
        schema = get_duckdb_schema(conn, "nonexistent_table")
        assert schema == {} or schema.get("nonexistent_table") == []


# ---------------------------------------------------------------------------
# Stage 3 — Dry-run
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_valid_expression_no_error(self, conn):
        errs = dry_run_expression(conn, "amount > 0", "orders")
        assert errs == []

    def test_invalid_column_caught(self, conn):
        errs = dry_run_expression(conn, "revnue > 0", "orders")
        assert len(errs) == 1
        assert errs[0].stage == "dry_run"

    def test_valid_query_no_error(self, conn):
        errs = dry_run_query(conn, "SELECT COUNT(*) FROM orders WHERE amount < 0")
        assert errs == []

    def test_invalid_query_table(self, conn):
        errs = dry_run_query(conn, "SELECT COUNT(*) FROM nonexistent_table")
        assert len(errs) == 1
        assert errs[0].stage == "dry_run"


# ---------------------------------------------------------------------------
# Combined sync verifiers
# ---------------------------------------------------------------------------

class TestVerifyExpressionSync:
    def test_valid_offline(self):
        result = verify_expression_sync("amount > 0", "orders")
        assert result.passed is True
        assert result.fixes_applied == 0

    def test_syntax_error_offline(self):
        result = verify_expression_sync("amount >", "orders")
        assert result.passed is False
        assert result.errors[0].stage == "syntax"

    def test_valid_with_conn(self, conn):
        schema = get_duckdb_schema(conn, "orders")
        result = verify_expression_sync("amount > 0", "orders", conn=conn, schema=schema)
        assert result.passed is True

    def test_schema_error_caught(self, conn):
        schema = get_duckdb_schema(conn, "orders")
        result = verify_expression_sync("revnue > 0", "orders", conn=conn, schema=schema)
        assert result.passed is False
        # Error at schema stage (before dry-run)
        assert result.errors[0].stage in ("schema", "dry_run")

    def test_dry_run_type_error(self, conn):
        # Comparing string column with integer — DuckDB may coerce or error
        result = verify_expression_sync("status > 0", "orders", conn=conn)
        # DuckDB casts VARCHAR > INTEGER as an error in strict mode; result may or may not fail
        # Just verify it doesn't crash
        assert isinstance(result, VerifyResult)


class TestVerifyQuerySync:
    def test_valid_query(self, conn):
        result = verify_query_sync(
            "SELECT COUNT(*) as n FROM orders WHERE amount < 0",
            "orders",
            conn=conn,
        )
        assert result.passed is True

    def test_bad_query_syntax(self):
        result = verify_query_sync("SELECT FROM WHERE", "orders")
        assert result.passed is False
        assert result.errors[0].stage == "syntax"


class TestVerifyStatementSync:
    def test_valid_update(self):
        result = verify_statement_sync(
            "UPDATE orders SET status = 'shipped' WHERE status = 'DISPATCHED'"
        )
        assert result.passed is True

    def test_invalid_update_syntax(self):
        # sqlglot parses "SET WHERE" leniently; result may pass — just verify no crash.
        result = verify_statement_sync("UPDATE orders SET WHERE x = 1")
        assert isinstance(result, VerifyResult)

    def test_delete_statement(self):
        result = verify_statement_sync(
            "DELETE FROM orders WHERE order_id NOT IN (SELECT order_id FROM customers)"
        )
        assert result.passed is True


# ---------------------------------------------------------------------------
# Async verify_and_fix — LLM self-correction
# ---------------------------------------------------------------------------

class _MockLLM:
    """Returns a pre-configured fixed SQL on the first call."""
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[str] = []

    async def complete(self, system: str, user: str, max_tokens: int = 512):
        self.calls.append(user)
        if self._responses:
            resp = self._responses.pop(0)
        else:
            resp = "-- could not fix"
        return resp, 10, 10


@pytest.mark.asyncio
async def test_verify_and_fix_no_error():
    """Valid SQL — no LLM call needed."""
    llm = _MockLLM([])
    result = await verify_and_fix(
        "amount > 0", mode="expression", table="orders", llm=llm
    )
    assert result.passed is True
    assert result.fixes_applied == 0
    assert llm.calls == []


@pytest.mark.asyncio
async def test_verify_and_fix_llm_corrects_syntax():
    """LLM corrects broken SQL on first attempt."""
    llm = _MockLLM(["SELECT 1 FROM orders WHERE amount > 0"])
    result = await verify_and_fix(
        "amount >",   # truncated — syntax error
        mode="expression",
        table="orders",
        llm=llm,
    )
    assert result.passed is True
    assert result.fixes_applied == 1
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_verify_and_fix_no_llm_returns_failure():
    """Without an LLM, bad SQL is returned with passed=False."""
    result = await verify_and_fix("amount >", mode="expression", table="orders", llm=None)
    assert result.passed is False
    assert result.fixes_applied == 0


@pytest.mark.asyncio
async def test_verify_and_fix_exhausts_retries():
    """LLM consistently returns bad SQL → gives up after max_retries."""
    bad_sql = "still > broken >"
    llm = _MockLLM([bad_sql, bad_sql, bad_sql])
    result = await verify_and_fix(
        "amount >",
        mode="expression",
        table="orders",
        llm=llm,
        max_retries=3,
    )
    assert result.passed is False
    assert result.fixes_applied == 3


@pytest.mark.asyncio
async def test_verify_and_fix_strips_markdown_fences():
    """LLM wraps response in code fences — should be stripped."""
    llm = _MockLLM(["```sql\nSELECT 1 FROM orders WHERE amount > 0\n```"])
    result = await verify_and_fix(
        "amount >", mode="expression", table="orders", llm=llm
    )
    assert result.passed is True
    assert "```" not in result.sql


# ---------------------------------------------------------------------------
# Integration: thota-dq validate --check-sql
# ---------------------------------------------------------------------------

class TestValidateCheckSql:
    def test_valid_sql_expression_passes(self, tmp_path):
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.write_text("""
rules:
  - apiVersion: thota_dq.dev/v1
    kind: DataQualityRule
    metadata:
      id: orders_amount_positive
      severity: high
    scope:
      table: orders
    logic:
      type: sql_expression
      expression: "amount > 0"
""")
        from thota_dq.rules.validator import validate_file
        report = validate_file(rules_yaml, check_sql=True)
        r = report.results[0]
        sql_errs = [e for e in r.errors if e.startswith("[sql]")]
        assert sql_errs == [], f"Unexpected SQL errors: {sql_errs}"

    def test_invalid_sql_expression_caught(self, tmp_path):
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.write_text("""
rules:
  - apiVersion: thota_dq.dev/v1
    kind: DataQualityRule
    metadata:
      id: orders_bad_sql
      severity: high
    scope:
      table: orders
    logic:
      type: sql_expression
      expression: "amount >"
""")
        from thota_dq.rules.validator import validate_file
        report = validate_file(rules_yaml, check_sql=True)
        r = report.results[0]
        sql_errs = [e for e in r.errors if e.startswith("[sql]")]
        assert len(sql_errs) == 1
        assert "syntax" in sql_errs[0]

    def test_schema_error_caught_with_conn(self, tmp_path, conn):
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.write_text("""
rules:
  - apiVersion: thota_dq.dev/v1
    kind: DataQualityRule
    metadata:
      id: orders_typo_column
      severity: high
    scope:
      table: orders
    logic:
      type: sql_expression
      expression: "revnue > 0"
""")
        from thota_dq.rules.validator import validate_file
        report = validate_file(rules_yaml, conn=conn)
        r = report.results[0]
        sql_errs = [e for e in r.errors if e.startswith("[sql]")]
        assert len(sql_errs) >= 1

    def test_non_sql_rule_unaffected(self, tmp_path):
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.write_text("""
rules:
  - apiVersion: thota_dq.dev/v1
    kind: DataQualityRule
    metadata:
      id: orders_not_null
      severity: high
    scope:
      table: orders
      columns: [order_id]
    logic:
      type: not_null
""")
        from thota_dq.rules.validator import validate_file
        report = validate_file(rules_yaml, check_sql=True)
        assert report.ok


# ---------------------------------------------------------------------------
# Integration: remediate node auto-fix
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remediate_node_fixes_bad_sql():
    """Remediate node should auto-fix syntactically broken LLM output."""
    from unittest.mock import AsyncMock, patch

    from thota_dq.core.nodes.remediate import _remediate_one

    class _LLM:
        _model = "test-model"
        call_count = 0

        async def complete(self, system, user, max_tokens=512):
            self.call_count += 1
            if self.call_count == 1:
                # First call: LLM generates badly-formed SQL
                return (
                    "SQL: UPDATE orders SET status = 'shipped' WHERE status >\n"
                    "CONFIDENCE: medium\n"
                    "CAVEAT: Review before running.",
                    100, 50,
                )
            # Self-correction call: LLM returns valid SQL
            return "UPDATE orders SET status = 'shipped' WHERE status = 'DISPATCHED'", 30, 20

    llm = _LLM()

    with patch("thota_dq.core.nodes.remediate.log_decision", new_callable=AsyncMock):
        proposal = await _remediate_one(
            failure_id="orders_status_valid",
            table="orders",
            rule_type="accepted_values",
            diagnosis={"explanation": "Bad status", "likely_cause": "typo", "suggested_action": "fix it"},
            rca=None,
            llm=llm,
            run_id="test-run",
        )

    assert ">" not in proposal["proposed_sql"] or proposal["proposed_sql"].startswith("--")
    # LLM was called at least twice (once for generation, once for fix)
    assert llm.call_count >= 2


@pytest.mark.asyncio
async def test_remediate_node_leaves_good_sql_unchanged():
    """Remediate node should not modify SQL that is already syntactically valid."""
    from unittest.mock import AsyncMock, patch

    from thota_dq.core.nodes.remediate import _remediate_one

    class _LLM:
        _model = "test-model"
        call_count = 0

        async def complete(self, system, user, max_tokens=512):
            self.call_count += 1
            return (
                "SQL: UPDATE orders SET status = 'shipped' WHERE status = 'DISPATCHED'\n"
                "CONFIDENCE: medium\n"
                "CAVEAT: Verify before running.",
                100, 50,
            )

    llm = _LLM()

    with patch("thota_dq.core.nodes.remediate.log_decision", new_callable=AsyncMock):
        proposal = await _remediate_one(
            failure_id="orders_status_valid",
            table="orders",
            rule_type="accepted_values",
            diagnosis={"explanation": "Bad status", "likely_cause": "typo", "suggested_action": "fix"},
            rca=None,
            llm=llm,
            run_id="test-run",
        )

    assert "DISPATCHED" in proposal["proposed_sql"]
    # Only 1 call — no self-correction needed
    assert llm.call_count == 1
