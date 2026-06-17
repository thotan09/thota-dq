"""Tests for thota-dq validate (dry-run rule validation)."""

from __future__ import annotations

import textwrap

from thota_dq.rules.validator import validate_file


def write_yaml(tmp_path, content: str):
    f = tmp_path / "rules.yaml"
    f.write_text(textwrap.dedent(content))
    return f


# ── Valid rules ───────────────────────────────────────────────────────────────

def test_valid_not_null(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata:
              id: test_not_null
              severity: critical
              description: Order ID must not be null
              owner: data-team
            scope:
              table: orders
              columns: [order_id]
            logic:
              type: not_null
    """)
    report = validate_file(f)
    assert report.ok
    assert report.valid_count == 1
    assert report.results[0].rule_id == "test_not_null"


def test_valid_sql_expression(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata: {id: revenue_positive, severity: high}
            scope: {table: orders}
            logic: {type: sql_expression, expression: "revenue >= 0"}
    """)
    report = validate_file(f)
    assert report.ok


def test_valid_multiple_rules(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata: {id: rule_a, severity: high}
            scope: {table: orders, columns: [order_id]}
            logic: {type: not_null}
          - apiVersion: thota_dq.dev/v1
            metadata: {id: rule_b, severity: medium}
            scope: {table: orders}
            logic: {type: row_count, threshold: 1}
    """)
    report = validate_file(f)
    assert report.ok
    assert report.total == 2
    assert report.valid_count == 2


def test_valid_between_with_required_fields(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata: {id: age_range, severity: medium}
            scope: {table: customers, columns: [age]}
            logic: {type: between, min_value: 0, max_value: 120}
    """)
    report = validate_file(f)
    assert report.ok


def test_valid_regex_match(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata: {id: email_fmt, severity: medium}
            scope: {table: customers, columns: [email]}
            logic:
              type: regex_match
              pattern: '^.+@.+[.].+$'
    """)
    report = validate_file(f)
    assert report.ok


def test_valid_foreign_key(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata: {id: fk_check, severity: high}
            scope: {table: orders, columns: [customer_id]}
            logic:
              type: foreign_key
              reference_table: customers
              reference_column: customer_id
    """)
    report = validate_file(f)
    assert report.ok


# ── YAML / file errors ────────────────────────────────────────────────────────

def test_file_not_found(tmp_path):
    report = validate_file(tmp_path / "nonexistent.yaml")
    assert not report.ok
    assert any("not found" in e.lower() for e in report.results[0].errors)


def test_invalid_yaml_syntax(tmp_path):
    f = tmp_path / "rules.yaml"
    f.write_text("rules:\n  - id: [unclosed bracket\n")
    report = validate_file(f)
    assert not report.ok
    assert any("yaml" in e.lower() for e in report.results[0].errors)


def test_empty_file(tmp_path):
    f = write_yaml(tmp_path, "")
    report = validate_file(f)
    assert not report.ok
    assert any("no rules" in e.lower() for e in report.results[0].errors)


# ── Schema errors ─────────────────────────────────────────────────────────────

def test_missing_required_metadata_id(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata: {severity: high}
            scope: {table: orders}
            logic: {type: not_null}
    """)
    report = validate_file(f)
    assert not report.ok
    assert report.results[0].errors


def test_invalid_severity_enum(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata: {id: bad_rule, severity: ultra_critical}
            scope: {table: orders}
            logic: {type: not_null}
    """)
    report = validate_file(f)
    assert not report.ok


def test_invalid_rule_type_enum(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata: {id: bad_rule, severity: high}
            scope: {table: orders}
            logic: {type: invented_type}
    """)
    report = validate_file(f)
    assert not report.ok


def test_missing_table_in_scope(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata: {id: no_table, severity: high}
            scope: {columns: [order_id]}
            logic: {type: not_null}
    """)
    report = validate_file(f)
    assert not report.ok


# ── Semantic errors (missing required logic fields) ───────────────────────────

def test_between_missing_min_max(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata: {id: bad_between, severity: high}
            scope: {table: t, columns: [col]}
            logic: {type: between}
    """)
    report = validate_file(f)
    assert not report.ok
    errors = report.results[0].errors
    assert any("min_value" in e for e in errors)
    assert any("max_value" in e for e in errors)


def test_regex_missing_pattern(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata: {id: bad_regex, severity: medium}
            scope: {table: t, columns: [col]}
            logic: {type: regex_match}
    """)
    report = validate_file(f)
    assert not report.ok
    assert any("pattern" in e for e in report.results[0].errors)


def test_accepted_values_missing_values_list(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata: {id: bad_accepted, severity: high}
            scope: {table: t, columns: [status]}
            logic: {type: accepted_values}
    """)
    report = validate_file(f)
    assert not report.ok
    assert any("values" in e for e in report.results[0].errors)


def test_column_required_but_missing(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata: {id: no_col, severity: high}
            scope: {table: orders}
            logic: {type: not_null}
    """)
    report = validate_file(f)
    assert not report.ok
    assert any("columns" in e for e in report.results[0].errors)


def test_foreign_key_missing_reference(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata: {id: bad_fk, severity: high}
            scope: {table: orders, columns: [customer_id]}
            logic: {type: foreign_key}
    """)
    report = validate_file(f)
    assert not report.ok
    errors = report.results[0].errors
    assert any("reference_table" in e for e in errors)
    assert any("reference_column" in e for e in errors)


# ── Partial validity (mixed valid/invalid) ────────────────────────────────────

def test_mixed_valid_and_invalid(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata: {id: good_rule, severity: high}
            scope: {table: orders, columns: [order_id]}
            logic: {type: not_null}
          - apiVersion: thota_dq.dev/v1
            metadata: {id: bad_rule, severity: bogus_level}
            scope: {table: orders}
            logic: {type: not_null}
    """)
    report = validate_file(f)
    assert not report.ok
    assert report.valid_count == 1
    assert report.invalid_count == 1
    assert report.total == 2


# ── Warnings ──────────────────────────────────────────────────────────────────

def test_warns_on_missing_description(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata: {id: no_desc, severity: high}
            scope: {table: orders, columns: [order_id]}
            logic: {type: not_null}
    """)
    report = validate_file(f)
    assert report.ok            # warnings don't make it invalid
    assert report.results[0].warnings


def test_warns_on_missing_owner(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata: {id: no_owner, severity: high, description: Something}
            scope: {table: orders, columns: [order_id]}
            logic: {type: not_null}
    """)
    report = validate_file(f)
    assert report.ok
    assert any("owner" in w for w in report.results[0].warnings)


def test_no_warnings_on_complete_rule(tmp_path):
    f = write_yaml(tmp_path, """
        rules:
          - apiVersion: thota_dq.dev/v1
            metadata:
              id: complete_rule
              severity: high
              description: A fully specified rule
              owner: data-team
            scope: {table: orders, columns: [order_id]}
            logic: {type: not_null}
    """)
    report = validate_file(f)
    assert report.ok
    assert report.results[0].warnings == []
