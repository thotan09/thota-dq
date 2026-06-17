"""Tests for rule schema and parser."""

from __future__ import annotations

import os
import tempfile

from thota_dq.rules.parser import load_rules
from thota_dq.rules.schema import DataQualityRule, RuleType, Severity

SAMPLE_YAML = """\
rules:
  - apiVersion: thota_dq.dev/v1
    kind: DataQualityRule
    metadata:
      id: test_not_null
      severity: critical
    scope:
      table: orders
      columns: [order_id]
    logic:
      type: not_null
"""

MULTI_RULE_YAML = """\
rules:
  - apiVersion: thota_dq.dev/v1
    kind: DataQualityRule
    metadata:
      id: rule_one
      severity: high
    scope:
      table: customers
      columns: [customer_id]
    logic:
      type: unique

  - apiVersion: thota_dq.dev/v1
    kind: DataQualityRule
    metadata:
      id: rule_two
      severity: medium
    scope:
      table: customers
    logic:
      type: row_count
      threshold: 100
"""

SPEC_NESTED_YAML = """\
apiVersion: thota_dq.dev/v1
kind: DataQualityRule
metadata:
  id: nested_spec_rule
  severity: low
spec:
  scope:
    table: events
    columns: [event_id]
  logic:
    type: not_null
"""


def _write_tmp(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    f.write(content)
    f.flush()
    f.close()
    return f.name


def test_parse_single_rule():
    path = _write_tmp(SAMPLE_YAML)
    try:
        rules = load_rules(path)
    finally:
        os.unlink(path)

    assert len(rules) == 1
    rule = rules[0]
    assert rule.metadata.id == "test_not_null"
    assert rule.metadata.severity == Severity.CRITICAL
    assert rule.spec_logic.type == RuleType.NOT_NULL
    assert rule.spec_scope.table == "orders"
    assert rule.spec_scope.columns == ["order_id"]


def test_parse_multiple_rules():
    path = _write_tmp(MULTI_RULE_YAML)
    try:
        rules = load_rules(path)
    finally:
        os.unlink(path)

    assert len(rules) == 2
    assert rules[0].metadata.id == "rule_one"
    assert rules[0].spec_logic.type == RuleType.UNIQUE
    assert rules[1].metadata.id == "rule_two"
    assert rules[1].spec_logic.type == RuleType.ROW_COUNT
    assert rules[1].spec_logic.threshold == 100.0


def test_parse_nested_spec():
    """Rules with a nested 'spec:' block should also parse correctly."""
    path = _write_tmp(SPEC_NESTED_YAML)
    try:
        rules = load_rules(path)
    finally:
        os.unlink(path)

    assert len(rules) == 1
    assert rules[0].metadata.id == "nested_spec_rule"
    assert rules[0].spec_scope.table == "events"


def test_rule_defaults():
    path = _write_tmp(SAMPLE_YAML)
    try:
        rules = load_rules(path)
    finally:
        os.unlink(path)

    rule = rules[0]
    # Check Pydantic defaults
    assert rule.kind == "DataQualityRule"
    assert rule.diagnosis.common_causes == []
    assert rule.remediation.auto_remediate is False
    assert rule.sla.detection_window == "1h"


def test_rule_is_dataqualityrule_instance():
    path = _write_tmp(SAMPLE_YAML)
    try:
        rules = load_rules(path)
    finally:
        os.unlink(path)

    assert isinstance(rules[0], DataQualityRule)
