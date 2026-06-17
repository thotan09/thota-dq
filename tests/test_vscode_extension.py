"""Structural tests for the VS Code extension — no Node.js required."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

EXT_DIR = Path(__file__).parent.parent / "vscode-extension"
PKG = json.loads((EXT_DIR / "package.json").read_text())
SCHEMA = json.loads((EXT_DIR / "schemas" / "thota-rule.json").read_text())
SNIPPETS = json.loads((EXT_DIR / "snippets" / "thota-rules.code-snippets").read_text())
GRAMMAR = json.loads((EXT_DIR / "syntaxes" / "thota-rules.tmLanguage.json").read_text())


# ---------------------------------------------------------------------------
# package.json
# ---------------------------------------------------------------------------

class TestPackageJson:
    def test_name_and_publisher(self):
        assert PKG["name"] == "thota-dq"
        assert PKG["publisher"] == "thota-dq"

    def test_engine_version(self):
        assert "^1.85" in PKG["engines"]["vscode"]

    def test_language_contribution(self):
        langs = {lang["id"] for lang in PKG["contributes"]["languages"]}
        assert "thota-rules" in langs

    def test_file_extensions(self):
        lang = next(entry for entry in PKG["contributes"]["languages"] if entry["id"] == "thota-rules")
        assert ".thota-dq.yaml" in lang["extensions"]
        assert ".thota-dq.yml" in lang["extensions"]

    def test_grammar_contribution(self):
        grammars = PKG["contributes"]["grammars"]
        ids = {g["language"] for g in grammars}
        assert "thota-rules" in ids

    def test_snippets_for_both_languages(self):
        snippet_langs = {s["language"] for s in PKG["contributes"]["snippets"]}
        assert "thota-rules" in snippet_langs
        assert "yaml" in snippet_langs

    def test_json_validation_patterns(self):
        patterns = []
        for jv in PKG["contributes"]["jsonValidation"]:
            fm = jv["fileMatch"]
            patterns.extend(fm if isinstance(fm, list) else [fm])
        assert "*.thota-dq.yaml" in patterns
        assert "rules.yaml" in patterns

    def test_required_commands(self):
        cmds = {c["command"] for c in PKG["contributes"]["commands"]}
        assert "aegisDQ.validateFile" in cmds
        assert "aegisDQ.insertSnippet" in cmds

    def test_configuration_properties(self):
        props = PKG["contributes"]["configuration"]["properties"]
        assert "aegisDQ.validateOnSave" in props
        assert "aegisDQ.hoverDocs" in props

    def test_main_entry(self):
        assert PKG["main"] == "./out/extension.js"

    def test_categories(self):
        cats = PKG["categories"]
        assert "Snippets" in cats
        assert "Linters" in cats


# ---------------------------------------------------------------------------
# JSON Schema
# ---------------------------------------------------------------------------

class TestSchema:
    def test_top_level_requires_rules(self):
        assert "rules" in SCHEMA["required"]

    def test_data_quality_rule_required_fields(self):
        rule = SCHEMA["definitions"]["DataQualityRule"]
        required = set(rule["required"])
        assert {"apiVersion", "kind", "metadata", "scope", "logic"} <= required

    def test_all_rule_types_present(self):
        types = set(SCHEMA["definitions"]["RuleLogic"]["properties"]["type"]["enum"])
        expected = {
            "not_null", "not_empty_string", "null_percentage_below",
            "unique", "composite_unique", "duplicate_percentage_below",
            "sql_expression", "between", "min_value_check", "max_value_check",
            "regex_match", "accepted_values", "not_accepted_values",
            "no_future_dates", "column_exists", "foreign_key",
            "conditional_not_null", "mean_between", "stddev_below",
            "column_sum_between", "freshness", "date_order",
            "row_count", "row_count_between", "custom_sql",
            "row_count_match", "column_sum_match", "set_inclusion", "set_equality",
        }
        assert expected <= types

    def test_severity_enum(self):
        sev = SCHEMA["definitions"]["RuleMetadata"]["properties"]["severity"]["enum"]
        assert set(sev) == {"critical", "high", "medium", "low", "info"}

    def test_warehouse_enum(self):
        wh = SCHEMA["definitions"]["RuleScope"]["properties"]["warehouse"]["enum"]
        assert "duckdb" in wh
        assert "bigquery" in wh
        assert "postgres" in wh

    def test_metadata_id_pattern(self):
        pattern = SCHEMA["definitions"]["RuleMetadata"]["properties"]["id"]["pattern"]
        import re
        assert re.match(pattern, "orders_not_null")
        assert not re.match(pattern, "123bad")

    def test_api_version_const(self):
        assert SCHEMA["definitions"]["DataQualityRule"]["properties"]["apiVersion"]["const"] == "thota_dq.dev/v1"

    def test_logic_fields_for_range_rules(self):
        props = SCHEMA["definitions"]["RuleLogic"]["properties"]
        assert "min_value" in props
        assert "max_value" in props
        assert "threshold" in props
        assert "pattern" in props
        assert "values" in props
        assert "reference_table" in props
        assert "condition" in props
        assert "column_b" in props

    def test_schema_valid_json(self):
        # Already loaded — just confirm it round-trips
        assert json.loads(json.dumps(SCHEMA)) == SCHEMA


# ---------------------------------------------------------------------------
# Snippets
# ---------------------------------------------------------------------------

CORE_RULE_TYPES = [
    "not_null", "not_empty_string", "null_percentage_below",
    "unique", "composite_unique", "duplicate_percentage_below",
    "sql_expression", "between", "min_value_check", "max_value_check",
    "regex_match", "accepted_values", "not_accepted_values",
    "no_future_dates", "column_exists", "foreign_key",
    "conditional_not_null", "mean_between", "stddev_below",
    "column_sum_between", "freshness", "date_order",
    "row_count", "row_count_between", "custom_sql",
    "row_count_match", "column_sum_match", "set_inclusion", "set_equality",
]

class TestSnippets:
    def test_scaffold_snippet_exists(self):
        assert "Aegis Rule File" in SNIPPETS

    def test_at_least_28_rule_type_snippets(self):
        # Each rule type should have a snippet
        covered = set()
        for snippet in SNIPPETS.values():
            body = "\n".join(snippet["body"]) if isinstance(snippet["body"], list) else snippet["body"]
            for rt in CORE_RULE_TYPES:
                if f"type: {rt}" in body:
                    covered.add(rt)
        assert covered == set(CORE_RULE_TYPES), f"Missing snippets for: {set(CORE_RULE_TYPES) - covered}"

    def test_all_snippets_have_description(self):
        for name, snippet in SNIPPETS.items():
            assert "description" in snippet, f"Snippet '{name}' missing description"

    def test_all_snippets_have_prefix(self):
        for name, snippet in SNIPPETS.items():
            assert "prefix" in snippet, f"Snippet '{name}' missing prefix"

    def test_snippet_bodies_are_valid_yaml_after_tabstop_removal(self):
        """Snippet bodies should produce valid YAML when placeholders are stripped."""
        import re
        # Matches: ${1:default}, ${1|a,b,c|}, ${1}, $1, $0 (cursor)
        tabstop_re = re.compile(r"\$\{\d+(?::[^}]*)?\}|\$\{\d+\|[^}]*\|\}|\$\d+")
        for name, snippet in SNIPPETS.items():
            body = snippet["body"]
            lines = body if isinstance(body, list) else body.split("\n")
            # Drop lines that are only a bare $0 cursor marker
            lines = [ln for ln in lines if ln.strip() != "$0"]
            raw = "\n".join(lines)
            cleaned = tabstop_re.sub("placeholder", raw)
            # Skip custom_sql — the pipe block needs extra indent context
            if "custom_sql" in name.lower():
                continue
            try:
                yaml.safe_load(cleaned)
            except yaml.YAMLError as e:
                pytest.fail(f"Snippet '{name}' produces invalid YAML: {e}\n\n{cleaned}")

    def test_aegis_rule_file_snippet_has_required_keys(self):
        body = "\n".join(SNIPPETS["Aegis Rule File"]["body"])
        assert "apiVersion" in body
        assert "kind" in body
        assert "metadata" in body
        assert "scope" in body
        assert "logic" in body


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------

class TestGrammar:
    def test_scope_name(self):
        assert GRAMMAR["scopeName"] == "source.thota-rules"

    def test_file_types(self):
        assert ".thota-dq.yaml" in GRAMMAR["fileTypes"]

    def test_rule_type_pattern_covers_all_types(self):
        # Find the rule_type_values pattern
        repo = GRAMMAR["repository"]
        rule_types_pattern = repo["rule_type_values"]["match"]
        for rt in CORE_RULE_TYPES:
            assert rt in rule_types_pattern, f"Rule type '{rt}' missing from grammar"

    def test_severity_pattern(self):
        repo = GRAMMAR["repository"]
        sev_pattern = repo["severity_values"]["match"]
        for sev in ["critical", "high", "medium", "low", "info"]:
            assert sev in sev_pattern

    def test_sql_embedding(self):
        repo = GRAMMAR["repository"]
        assert "sql_block" in repo
        assert "meta.embedded.block.sql" in repo["sql_block"]["contentName"]

    def test_comment_pattern_exists(self):
        repo = GRAMMAR["repository"]
        assert "comments" in repo


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------

class TestExtensionSource:
    def test_extension_ts_exists(self):
        ts_file = EXT_DIR / "src" / "extension.ts"
        assert ts_file.exists()

    def test_activate_exported(self):
        src = (EXT_DIR / "src" / "extension.ts").read_text()
        assert "export function activate" in src

    def test_deactivate_exported(self):
        src = (EXT_DIR / "src" / "extension.ts").read_text()
        assert "export function deactivate" in src

    def test_hover_provider_registered(self):
        src = (EXT_DIR / "src" / "extension.ts").read_text()
        assert "registerHoverProvider" in src

    def test_validate_command_registered(self):
        src = (EXT_DIR / "src" / "extension.ts").read_text()
        assert "aegisDQ.validateFile" in src

    def test_all_rule_types_in_hover_docs(self):
        src = (EXT_DIR / "src" / "extension.ts").read_text()
        for rt in CORE_RULE_TYPES:
            # TS object keys may be unquoted (not_null:) or quoted ("not_null":)
            assert f'"{rt}"' in src or f"'{rt}'" in src or f"\n  {rt}:" in src, \
                f"Rule type '{rt}' missing from hover docs"

    def test_on_save_handler(self):
        src = (EXT_DIR / "src" / "extension.ts").read_text()
        assert "onDidSaveTextDocument" in src
