"""SQL injection defense tests for Phase 1a security hardening.

Covers all four defense layers:
  - Pydantic identifier validators (table/column names)
  - Expression/condition field validators (WHERE-clause fragments)
  - Pattern field validator (LIKE/REGEX)
  - Custom SQL validator (full SELECT escape hatch)
  - Quoting utilities (identifier quoting, string literal escaping)
"""
from __future__ import annotations

import pytest

from thota_dq.adapters.warehouse.quoting import (
    escape_string_literal,
    quote_qualified_ansi,
    quote_qualified_bigquery,
    quote_qualified_spark,
)
from thota_dq.rules.sql_safety import UnsafeSQLExpression, validate_custom_sql, validate_expression

# ── validate_expression ───────────────────────────────────────────────────────

class TestValidateExpressionValid:
    def test_simple_comparison(self):
        validate_expression("age > 18")

    def test_string_equality(self):
        validate_expression("status = 'active'")

    def test_between(self):
        validate_expression("amount BETWEEN 0 AND 1000")

    def test_is_null(self):
        validate_expression("col IS NULL")

    def test_is_not_null(self):
        validate_expression("col IS NOT NULL")

    def test_in_list(self):
        validate_expression("region IN ('US', 'EU', 'APAC')")

    def test_not_in_list(self):
        validate_expression("status NOT IN ('deleted', 'archived')")

    def test_like_pattern(self):
        validate_expression("email LIKE '%@example.com'")

    def test_compound_and(self):
        validate_expression("age > 18 AND country = 'US'")

    def test_compound_or(self):
        validate_expression("status = 'active' OR status = 'pending'")

    def test_numeric_cast(self):
        validate_expression("CAST(score AS DOUBLE) > 0.5")

    def test_date_comparison(self):
        validate_expression("created_at > '2024-01-01'")

    def test_parenthesized(self):
        validate_expression("(a > 1 AND b < 10) OR c = 'x'")


class TestValidateExpressionBlockedPatterns:
    def test_semicolon(self):
        with pytest.raises(UnsafeSQLExpression, match="forbidden pattern"):
            validate_expression("1=1; DROP TABLE users")

    def test_line_comment(self):
        with pytest.raises(UnsafeSQLExpression, match="forbidden pattern"):
            validate_expression("1=1 --injected")

    def test_block_comment_open(self):
        with pytest.raises(UnsafeSQLExpression, match="forbidden pattern"):
            validate_expression("1 /* comment")

    def test_block_comment_close(self):
        with pytest.raises(UnsafeSQLExpression, match="forbidden pattern"):
            validate_expression("comment */ 1")


class TestValidateExpressionBlockedKeywords:
    def test_select(self):
        with pytest.raises(UnsafeSQLExpression, match="SELECT"):
            validate_expression("1=1 AND SELECT password FROM users")

    def test_union(self):
        # No SELECT in payload so UNION is caught first
        with pytest.raises(UnsafeSQLExpression, match="UNION"):
            validate_expression("col = 1 UNION col = 2")

    def test_intersect(self):
        with pytest.raises(UnsafeSQLExpression, match="INTERSECT"):
            validate_expression("col = 1 INTERSECT col = 2")

    def test_except(self):
        with pytest.raises(UnsafeSQLExpression, match="EXCEPT"):
            validate_expression("col = 1 EXCEPT col = 2")

    def test_with(self):
        with pytest.raises(UnsafeSQLExpression, match="WITH"):
            validate_expression("col WITH TIES = 1")

    def test_drop(self):
        with pytest.raises(UnsafeSQLExpression, match="DROP"):
            validate_expression("1 OR DROP TABLE users")

    def test_delete(self):
        with pytest.raises(UnsafeSQLExpression, match="DELETE"):
            validate_expression("1 OR DELETE FROM users")

    def test_insert(self):
        with pytest.raises(UnsafeSQLExpression, match="INSERT"):
            validate_expression("1 OR INSERT INTO t VALUES (1)")

    def test_update(self):
        with pytest.raises(UnsafeSQLExpression, match="UPDATE"):
            validate_expression("1 OR UPDATE t SET x=1")

    def test_truncate(self):
        with pytest.raises(UnsafeSQLExpression, match="TRUNCATE"):
            validate_expression("1 OR TRUNCATE TABLE users")

    def test_create(self):
        # No SELECT in payload so CREATE is caught first
        with pytest.raises(UnsafeSQLExpression, match="CREATE"):
            validate_expression("1 OR CREATE TABLE evil (x INT)")

    def test_execute(self):
        with pytest.raises(UnsafeSQLExpression, match="EXECUTE"):
            validate_expression("1 OR EXECUTE sp_evil")

    def test_exec(self):
        # Use payload without semicolon to ensure EXEC is the trigger
        with pytest.raises(UnsafeSQLExpression, match="EXEC"):
            validate_expression("1 OR EXEC xp_cmdshell")

    def test_call(self):
        with pytest.raises(UnsafeSQLExpression, match="CALL"):
            validate_expression("1 OR CALL drop_all()")

    def test_load_file(self):
        with pytest.raises(UnsafeSQLExpression, match="LOAD_FILE"):
            validate_expression("col = LOAD_FILE('/etc/passwd')")


class TestValidateExpressionBlockedASTNodes:
    def test_subquery_in(self):
        with pytest.raises(UnsafeSQLExpression):
            validate_expression("col IN (SELECT id FROM other_table)")

    def test_subquery_exists(self):
        with pytest.raises(UnsafeSQLExpression):
            validate_expression("EXISTS (SELECT 1 FROM other_table WHERE x=1)")

    def test_nested_select(self):
        with pytest.raises(UnsafeSQLExpression):
            validate_expression("col = (SELECT max(id) FROM other_table)")


# ── validate_custom_sql ───────────────────────────────────────────────────────

class TestValidateCustomSqlValid:
    def test_simple_select(self):
        validate_custom_sql("SELECT * FROM t")

    def test_select_with_where(self):
        validate_custom_sql("SELECT id, name FROM users WHERE active = 1")

    def test_select_with_join(self):
        validate_custom_sql("SELECT a.id FROM a JOIN b ON a.id = b.a_id")

    def test_select_with_group_by(self):
        validate_custom_sql("SELECT region, COUNT(*) FROM orders GROUP BY region")

    def test_select_with_having(self):
        validate_custom_sql("SELECT col, COUNT(*) FROM t GROUP BY col HAVING COUNT(*) > 1")

    def test_select_with_cte(self):
        validate_custom_sql("WITH cte AS (SELECT 1 AS x) SELECT * FROM cte")


class TestValidateCustomSqlBlocked:
    def test_semicolon_stacked_query(self):
        with pytest.raises(UnsafeSQLExpression, match="forbidden pattern"):
            validate_custom_sql("SELECT * FROM t; DROP TABLE t")

    def test_line_comment(self):
        with pytest.raises(UnsafeSQLExpression, match="forbidden pattern"):
            validate_custom_sql("SELECT 1 -- malicious comment")

    def test_drop(self):
        with pytest.raises(UnsafeSQLExpression, match="DROP"):
            validate_custom_sql("DROP TABLE users")

    def test_delete(self):
        with pytest.raises(UnsafeSQLExpression, match="DELETE"):
            validate_custom_sql("DELETE FROM users WHERE 1=1")

    def test_insert(self):
        with pytest.raises(UnsafeSQLExpression, match="INSERT"):
            validate_custom_sql("INSERT INTO users VALUES (1, 'evil')")

    def test_update(self):
        with pytest.raises(UnsafeSQLExpression, match="UPDATE"):
            validate_custom_sql("UPDATE users SET password='pwned' WHERE 1=1")

    def test_truncate(self):
        with pytest.raises(UnsafeSQLExpression, match="TRUNCATE"):
            validate_custom_sql("TRUNCATE TABLE users")

    def test_grant(self):
        with pytest.raises(UnsafeSQLExpression, match="GRANT"):
            validate_custom_sql("GRANT ALL ON *.* TO 'evil'@'%'")

    def test_exec(self):
        with pytest.raises(UnsafeSQLExpression, match="EXEC"):
            validate_custom_sql("EXEC xp_cmdshell('whoami')")


# ── Pydantic schema identifier validators ─────────────────────────────────────

class TestSchemaIdentifierValidators:
    def _make_scope(self, table: str):
        from thota_dq.rules.schema import RuleScope
        return RuleScope(table=table, columns=["id"])

    def _make_scope_cols(self, columns: list[str]):
        from thota_dq.rules.schema import RuleScope
        return RuleScope(table="my_table", columns=columns)

    def test_valid_table_simple(self):
        s = self._make_scope("orders")
        assert s.table == "orders"

    def test_valid_table_qualified(self):
        s = self._make_scope("mydb.orders")
        assert s.table == "mydb.orders"

    def test_valid_table_bigquery_project(self):
        s = self._make_scope("my-project.dataset.table")
        assert s.table == "my-project.dataset.table"

    def test_invalid_table_semicolon(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="table"):
            self._make_scope("orders; DROP TABLE orders")

    def test_invalid_table_space(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="table"):
            self._make_scope("my table")

    def test_invalid_table_quote(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="table"):
            self._make_scope("table'OR'1'='1")

    def test_valid_column(self):
        s = self._make_scope_cols(["user_id", "created_at"])
        assert s.columns == ["user_id", "created_at"]

    def test_invalid_column_space(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="columns"):
            self._make_scope_cols(["col name"])

    def test_invalid_column_semicolon(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="columns"):
            self._make_scope_cols(["col; DROP TABLE t"])


# ── Quoting utilities ─────────────────────────────────────────────────────────

class TestEscapeStringLiteral:
    def test_no_quotes(self):
        assert escape_string_literal("hello") == "hello"

    def test_single_quote(self):
        assert escape_string_literal("O'Brien") == "O''Brien"

    def test_multiple_quotes(self):
        assert escape_string_literal("it's a 'test'") == "it''s a ''test''"

    def test_sql_injection_payload(self):
        payload = "' OR '1'='1"
        escaped = escape_string_literal(payload)
        assert "'" not in escaped.replace("''", "")

    def test_empty_string(self):
        assert escape_string_literal("") == ""


class TestQuoteQualifiedAnsi:
    def test_simple(self):
        assert quote_qualified_ansi("orders") == '"orders"'

    def test_two_part(self):
        assert quote_qualified_ansi("mydb.orders") == '"mydb"."orders"'

    def test_three_part(self):
        assert quote_qualified_ansi("cat.schema.table") == '"cat"."schema"."table"'

    def test_reserved_word(self):
        assert quote_qualified_ansi("select") == '"select"'

    def test_embedded_double_quote(self):
        assert quote_qualified_ansi('bad"name') == '"bad""name"'

    def test_injection_attempt(self):
        # Embedded double-quote is escaped as "" — the identifier is neutralized
        # even if it somehow bypasses Pydantic validators
        malicious = 'orders"; DROP TABLE orders'
        quoted = quote_qualified_ansi(malicious)
        # The double-quote in the name becomes "" — no unbalanced quote to break out
        assert quoted == '"orders""; DROP TABLE orders"'
        assert quoted.startswith('"') and quoted.endswith('"')


class TestQuoteQualifiedBigQuery:
    def test_project_dataset_table(self):
        assert quote_qualified_bigquery("my-project.ds.tbl") == "`my-project`.`ds`.`tbl`"

    def test_embedded_backtick(self):
        assert quote_qualified_bigquery("bad`name") == "`bad``name`"


class TestQuoteQualifiedSpark:
    def test_two_part(self):
        assert quote_qualified_spark("db.table") == "`db`.`table`"

    def test_embedded_backtick(self):
        assert quote_qualified_spark("bad`name") == "`bad``name`"
