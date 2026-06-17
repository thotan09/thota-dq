"""Tests for stages 4-6: rule versioning, LLM generator, thota-dq generate CLI."""
from __future__ import annotations

import asyncio

import duckdb
import pytest
import yaml

# ---------------------------------------------------------------------------
# Stage 4 — RuleMetadata versioning fields
# ---------------------------------------------------------------------------

class TestRuleMetadataVersioning:
    def test_defaults(self):
        from thota_dq.rules.schema import RuleMetadata
        m = RuleMetadata(id="orders_amount_positive")
        assert m.version == "1.0.0"
        assert m.status == "draft"
        assert m.generated_by is None

    def test_explicit_values(self):
        from thota_dq.rules.schema import RuleMetadata
        m = RuleMetadata(
            id="orders_amount_positive",
            version="2.0.0",
            status="active",
            generated_by="llm/claude-sonnet-4-6",
        )
        assert m.version == "2.0.0"
        assert m.status == "active"
        assert m.generated_by == "llm/claude-sonnet-4-6"

    def test_invalid_status_rejected(self):
        from pydantic import ValidationError

        from thota_dq.rules.schema import RuleMetadata
        with pytest.raises(ValidationError):
            RuleMetadata(id="x", status="unknown_status")

    def test_full_rule_roundtrip(self):
        """DataQualityRule with versioning fields survives YAML round-trip."""
        rule_yaml = """
apiVersion: aegis.dev/v1
kind: DataQualityRule
metadata:
  id: orders_amount_positive
  severity: high
  version: "1.0.0"
  status: draft
  generated_by: llm/claude-sonnet-4-6
scope:
  table: orders
logic:
  type: sql_expression
  expression: "amount > 0"
"""
        from thota_dq.rules.parser import _parse_rule
        rule = _parse_rule(yaml.safe_load(rule_yaml))
        assert rule.metadata.version == "1.0.0"
        assert rule.metadata.status == "draft"
        assert rule.metadata.generated_by == "llm/claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Stage 4 — Rule version store
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "test_versions.db"


class TestRuleVersionStore:
    def test_save_and_retrieve(self, tmp_db):
        from thota_dq.memory.rule_versions import get_rule_versions_sync, save_rule_version

        asyncio.run(save_rule_version(
            rule_id="orders_amount_positive",
            version="1.0.0",
            status="draft",
            yaml_content="expression: amount > 0",
            generated_by="llm/test",
            path=tmp_db,
        ))
        versions = get_rule_versions_sync("orders_amount_positive", path=tmp_db)
        assert len(versions) == 1
        assert versions[0]["rule_id"] == "orders_amount_positive"
        assert versions[0]["status"] == "draft"
        assert versions[0]["generated_by"] == "llm/test"

    def test_multiple_versions(self, tmp_db):
        from thota_dq.memory.rule_versions import get_rule_versions_sync, save_rule_version

        asyncio.run(save_rule_version("r1", "1.0.0", "draft", "v1", path=tmp_db))
        asyncio.run(save_rule_version("r1", "2.0.0", "draft", "v2", path=tmp_db))
        versions = get_rule_versions_sync("r1", path=tmp_db)
        assert len(versions) == 2

    def test_upsert_same_version(self, tmp_db):
        from thota_dq.memory.rule_versions import get_rule_versions_sync, save_rule_version

        asyncio.run(save_rule_version("r1", "1.0.0", "draft", "original", path=tmp_db))
        asyncio.run(save_rule_version("r1", "1.0.0", "active", "updated", path=tmp_db))
        versions = get_rule_versions_sync("r1", path=tmp_db)
        # UNIQUE(rule_id, version) → INSERT OR REPLACE → still one record
        assert len(versions) == 1
        assert versions[0]["status"] == "active"

    def test_promote_rule(self, tmp_db):
        from thota_dq.memory.rule_versions import (
            get_rule_versions_sync,
            promote_rule,
            save_rule_version,
        )

        asyncio.run(save_rule_version("r1", "1.0.0", "draft", "yaml", path=tmp_db))
        promoted = asyncio.run(promote_rule("r1", "1.0.0", "active", path=tmp_db))
        assert promoted is True
        versions = get_rule_versions_sync("r1", path=tmp_db)
        assert versions[0]["status"] == "active"

    def test_promote_nonexistent_returns_false(self, tmp_db):
        from thota_dq.memory.rule_versions import promote_rule

        result = asyncio.run(promote_rule("no_such_rule", "1.0.0", "active", path=tmp_db))
        assert result is False

    def test_empty_db_returns_empty_list(self, tmp_path):
        from thota_dq.memory.rule_versions import get_rule_versions_sync
        # DB file doesn't exist yet
        versions = get_rule_versions_sync("any_rule", path=tmp_path / "missing.db")
        assert versions == []


# ---------------------------------------------------------------------------
# Stage 5 — introspect_table
# ---------------------------------------------------------------------------

@pytest.fixture
def orders_conn():
    c = duckdb.connect(":memory:")
    c.execute("""
        CREATE TABLE orders (
            order_id    INTEGER,
            amount      DOUBLE,
            status      VARCHAR,
            customer_id INTEGER
        )
    """)
    c.execute("INSERT INTO orders VALUES (1, 99.99, 'shipped', 10)")
    c.execute("INSERT INTO orders VALUES (2, -5.00, 'pending', 11)")
    yield c
    c.close()


class TestIntrospectTable:
    def test_basic_schema(self, orders_conn):
        from thota_dq.rules.generator import introspect_table
        info = introspect_table(orders_conn, "orders")
        assert info["table"] == "orders"
        assert info["row_count"] == 2
        col_names = [c["name"] for c in info["columns"]]
        assert "order_id" in col_names
        assert "amount" in col_names
        assert "status" in col_names

    def test_numeric_min_max(self, orders_conn):
        from thota_dq.rules.generator import introspect_table
        info = introspect_table(orders_conn, "orders")
        amount_col = next(c for c in info["columns"] if c["name"] == "amount")
        assert amount_col["min"] == pytest.approx(-5.0)
        assert amount_col["max"] == pytest.approx(99.99)

    def test_varchar_no_min_max(self, orders_conn):
        from thota_dq.rules.generator import introspect_table
        info = introspect_table(orders_conn, "orders")
        status_col = next(c for c in info["columns"] if c["name"] == "status")
        assert status_col["min"] is None
        assert status_col["max"] is None

    def test_nonexistent_table_returns_empty(self, orders_conn):
        from thota_dq.rules.generator import introspect_table
        info = introspect_table(orders_conn, "nonexistent_table")
        assert info["columns"] == []
        assert info["row_count"] == 0


# ---------------------------------------------------------------------------
# Stage 5 — generate_rules with mock LLM
# ---------------------------------------------------------------------------

_VALID_YAML_RESPONSE = """\
```yaml
rules:
  - apiVersion: aegis.dev/v1
    kind: DataQualityRule
    metadata:
      id: orders_amount_positive
      severity: high
      version: "1.0.0"
      status: draft
    scope:
      table: orders
    logic:
      type: sql_expression
      expression: "amount > 0"
  - apiVersion: aegis.dev/v1
    kind: DataQualityRule
    metadata:
      id: orders_order_id_not_null
      severity: high
      version: "1.0.0"
      status: draft
    scope:
      table: orders
      columns: [order_id]
    logic:
      type: not_null
```
"""


class _MockLLM:
    def __init__(self, response: str, model: str = "test-model"):
        self._model = model
        self._response = response
        self.call_count = 0

    async def complete(self, system: str, user: str, max_tokens: int = 512):
        self.call_count += 1
        return self._response, 100, 50


class TestGenerateRules:
    def test_parses_valid_response(self):
        from thota_dq.rules.generator import generate_rules
        llm = _MockLLM(_VALID_YAML_RESPONSE)
        schema_info = {"table": "orders", "row_count": 2, "columns": []}
        raw_yaml, rules = asyncio.run(generate_rules("orders", schema_info, llm))
        assert len(rules) == 2
        assert rules[0]["metadata"]["id"] == "orders_amount_positive"

    def test_stamps_generated_by(self):
        from thota_dq.rules.generator import generate_rules
        llm = _MockLLM(_VALID_YAML_RESPONSE, model="claude-sonnet-4-6")
        schema_info = {"table": "orders", "row_count": 0, "columns": []}
        _, rules = asyncio.run(generate_rules("orders", schema_info, llm))
        assert all(r["metadata"]["generated_by"] == "claude-sonnet-4-6" for r in rules)

    def test_stamps_version_and_status(self):
        from thota_dq.rules.generator import generate_rules
        llm = _MockLLM(_VALID_YAML_RESPONSE)
        schema_info = {"table": "orders", "row_count": 0, "columns": []}
        _, rules = asyncio.run(generate_rules("orders", schema_info, llm))
        for r in rules:
            assert r["metadata"]["version"] == "1.0.0"
            assert r["metadata"]["status"] == "draft"

    def test_strips_markdown_fences(self):
        from thota_dq.rules.generator import generate_rules
        llm = _MockLLM(_VALID_YAML_RESPONSE)
        schema_info = {"table": "orders", "row_count": 0, "columns": []}
        raw_yaml, _ = asyncio.run(generate_rules("orders", schema_info, llm))
        assert "```" not in raw_yaml

    def test_empty_response_returns_empty_rules(self):
        from thota_dq.rules.generator import generate_rules
        llm = _MockLLM("I cannot generate rules for this table.")
        schema_info = {"table": "orders", "row_count": 0, "columns": []}
        raw_yaml, rules = asyncio.run(generate_rules("orders", schema_info, llm))
        assert rules == []

    def test_kb_text_included_in_prompt(self):
        """KB text must be passed to the LLM (verify via call count and that it doesn't crash)."""
        from thota_dq.rules.generator import generate_rules
        llm = _MockLLM(_VALID_YAML_RESPONSE)
        schema_info = {"table": "orders", "row_count": 0, "columns": []}
        _, rules = asyncio.run(
            generate_rules("orders", schema_info, llm, kb_text="Amount must always be positive.")
        )
        assert llm.call_count == 1
        assert len(rules) == 2  # KB didn't break anything


# ---------------------------------------------------------------------------
# Stage 5/6 — _extract_yaml and _build_user_prompt helpers
# ---------------------------------------------------------------------------

class TestGeneratorHelpers:
    def test_extract_yaml_with_fences(self):
        from thota_dq.rules.generator import _extract_yaml
        text = "Here you go:\n```yaml\nrules: []\n```\n"
        assert _extract_yaml(text) == "rules: []"

    def test_extract_yaml_no_fences(self):
        from thota_dq.rules.generator import _extract_yaml
        assert _extract_yaml("rules: []") == "rules: []"

    def test_build_user_prompt_contains_table(self):
        from thota_dq.rules.generator import _build_user_prompt
        info = {"table": "orders", "row_count": 100, "columns": [
            {"name": "amount", "type": "DOUBLE", "null_count": 0,
             "distinct_count": 50, "min": 0.0, "max": 999.0}
        ]}
        prompt = _build_user_prompt(info, max_rules=10, kb_text=None)
        assert "orders" in prompt
        assert "amount" in prompt
        assert "min=0.0" in prompt

    def test_build_user_prompt_includes_kb(self):
        from thota_dq.rules.generator import _build_user_prompt
        info = {"table": "t", "row_count": 0, "columns": []}
        prompt = _build_user_prompt(info, 5, kb_text="Amount must be positive.")
        assert "Amount must be positive." in prompt

    def test_stamp_metadata_sets_fields(self):
        from thota_dq.rules.generator import _stamp_metadata
        rules = [{"metadata": {"id": "r1"}}]
        _stamp_metadata(rules, "test-model")
        assert rules[0]["metadata"]["generated_by"] == "test-model"
        assert rules[0]["metadata"]["version"] == "1.0.0"
        assert rules[0]["metadata"]["status"] == "draft"


# ---------------------------------------------------------------------------
# Stage 5 — generated YAML passes validate_file
# ---------------------------------------------------------------------------

class TestGeneratedYamlValidation:
    def test_generated_rules_pass_validation(self, tmp_path):
        from thota_dq.rules.generator import generate_rules
        from thota_dq.rules.validator import validate_file

        llm = _MockLLM(_VALID_YAML_RESPONSE)
        schema_info = {"table": "orders", "row_count": 2, "columns": []}
        raw_yaml, _ = asyncio.run(generate_rules("orders", schema_info, llm))

        out = tmp_path / "generated_rules.yaml"
        out.write_text(raw_yaml)

        report = validate_file(out, check_sql=True)
        sql_errors = [
            e for r in report.results for e in r.errors if e.startswith("[sql]")
        ]
        assert sql_errors == [], f"Unexpected SQL errors: {sql_errors}"
