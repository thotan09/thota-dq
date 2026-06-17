"""Tests for the dbt manifest parser and rule converter."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from thota_dq.integrations.dbt.parser import (
    dbt_test_to_rule,
    load_manifest,
    manifest_to_rules,
    manifest_to_yaml,
)
from thota_dq.rules.schema import RuleType, Severity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_node(
    test_name: str,
    column_name: str = "order_id",
    model_ref: str = "model.project.orders",
    severity: str = "ERROR",
    extra_kwargs: dict | None = None,
) -> dict:
    kwargs: dict = {"column_name": column_name, "model": "ref('orders')"}
    if extra_kwargs:
        kwargs.update(extra_kwargs)
    return {
        "resource_type": "test",
        "test_metadata": {"name": test_name, "kwargs": kwargs},
        "depends_on": {"nodes": [model_ref]},
        "config": {"severity": severity},
    }


def _make_model_node(name: str) -> dict:
    return {
        "resource_type": "model",
        "name": name,
        "config": {"severity": "warn"},
    }


def _make_manifest(tests: list[dict]) -> dict:
    nodes: dict = {}
    for t in tests:
        nodes[t["key"]] = t["node"]
    return {"nodes": nodes}


def _make_full_manifest(test_entries: list[dict]) -> dict:
    """Build a manifest that includes both model nodes and test nodes."""
    nodes: dict = {}
    # Add a model node for 'orders'
    nodes["model.project.orders"] = _make_model_node("orders")
    for t in test_entries:
        nodes[t["key"]] = t["node"]
    return {"nodes": nodes}


# ---------------------------------------------------------------------------
# Individual rule conversion tests
# ---------------------------------------------------------------------------

def test_not_null_test_converts_correctly():
    node = _make_test_node("not_null")
    manifest = _make_full_manifest([{"key": "test.project.not_null_orders_order_id.abc123", "node": node}])
    rule = dbt_test_to_rule("test.project.not_null_orders_order_id.abc123", node, manifest)

    assert rule is not None
    assert rule.spec_logic.type == RuleType.NOT_NULL
    assert "order_id" in rule.spec_scope.columns
    assert rule.spec_scope.table == "orders"


def test_unique_test_converts_correctly():
    node = _make_test_node("unique", column_name="id")
    manifest = _make_full_manifest([{"key": "test.project.unique_orders_id.xyz", "node": node}])
    rule = dbt_test_to_rule("test.project.unique_orders_id.xyz", node, manifest)

    assert rule is not None
    assert rule.spec_logic.type == RuleType.UNIQUE
    assert "id" in rule.spec_scope.columns


def test_accepted_values_test():
    node = _make_test_node(
        "accepted_values",
        column_name="status",
        extra_kwargs={"values": ["placed", "shipped", "returned"]},
    )
    manifest = _make_full_manifest([{"key": "test.project.accepted_values_orders_status.aaa", "node": node}])
    rule = dbt_test_to_rule("test.project.accepted_values_orders_status.aaa", node, manifest)

    assert rule is not None
    assert rule.spec_logic.type == RuleType.ACCEPTED_VALUES
    assert rule.spec_logic.values == ["placed", "shipped", "returned"]


def test_relationships_test():
    node = _make_test_node(
        "relationships",
        column_name="customer_id",
        extra_kwargs={"to": "ref('customers')", "field": "id"},
    )
    manifest = _make_full_manifest([{"key": "test.project.relationships_orders_customer_id.bbb", "node": node}])
    rule = dbt_test_to_rule("test.project.relationships_orders_customer_id.bbb", node, manifest)

    assert rule is not None
    assert rule.spec_logic.type == RuleType.FOREIGN_KEY
    assert rule.spec_logic.reference_table == "customers"
    assert rule.spec_logic.reference_column == "id"


def test_unsupported_test_returns_none():
    node = _make_test_node("expression_is_true")
    manifest = _make_full_manifest([{"key": "test.project.expression_is_true_orders.ccc", "node": node}])
    result = dbt_test_to_rule("test.project.expression_is_true_orders.ccc", node, manifest)
    assert result is None


def test_non_test_node_skipped():
    model_node = _make_model_node("orders")
    manifest = {"nodes": {"model.project.orders": model_node}}
    result = dbt_test_to_rule("model.project.orders", model_node, manifest)
    assert result is None


# ---------------------------------------------------------------------------
# manifest_to_rules
# ---------------------------------------------------------------------------

def test_manifest_to_rules_filters_none():
    """manifest_to_rules should include supported tests and skip others."""
    not_null_node = _make_test_node("not_null")
    unsupported_node = _make_test_node("expression_is_true")
    model_node = _make_model_node("orders")

    manifest = {
        "nodes": {
            "model.project.orders": model_node,
            "test.project.not_null_orders_order_id.aaa": not_null_node,
            "test.project.expression_is_true_orders.bbb": unsupported_node,
        }
    }

    rules = manifest_to_rules(manifest)
    assert len(rules) == 1
    assert rules[0].spec_logic.type == RuleType.NOT_NULL


# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------

def test_severity_mapping_error_to_high():
    node = _make_test_node("not_null", severity="ERROR")
    manifest = _make_full_manifest([{"key": "test.project.not_null_orders_order_id.s1", "node": node}])
    rule = dbt_test_to_rule("test.project.not_null_orders_order_id.s1", node, manifest)
    assert rule is not None
    assert rule.metadata.severity == Severity.HIGH


def test_severity_mapping_warn_to_low():
    node = _make_test_node("not_null", severity="warn")
    manifest = _make_full_manifest([{"key": "test.project.not_null_orders_order_id.s2", "node": node}])
    rule = dbt_test_to_rule("test.project.not_null_orders_order_id.s2", node, manifest)
    assert rule is not None
    assert rule.metadata.severity == Severity.LOW


def test_severity_default_is_medium():
    node = _make_test_node("unique", severity="")
    manifest = _make_full_manifest([{"key": "test.project.unique_orders_id.s3", "node": node}])
    rule = dbt_test_to_rule("test.project.unique_orders_id.s3", node, manifest)
    assert rule is not None
    assert rule.metadata.severity == Severity.MEDIUM


# ---------------------------------------------------------------------------
# manifest_to_yaml
# ---------------------------------------------------------------------------

def test_manifest_to_yaml_produces_valid_yaml():
    node = _make_test_node("not_null", column_name="order_id")
    manifest = _make_full_manifest([{"key": "test.project.not_null_orders_order_id.y1", "node": node}])

    yaml_str = manifest_to_yaml(manifest)
    parsed = yaml.safe_load(yaml_str)

    assert "rules" in parsed
    assert len(parsed["rules"]) == 1
    rule_doc = parsed["rules"][0]
    assert rule_doc["apiVersion"] == "thota_dq.dev/v1"
    assert rule_doc["kind"] == "DataQualityRule"
    assert "metadata" in rule_doc
    assert "scope" in rule_doc
    assert "logic" in rule_doc
    assert rule_doc["logic"]["type"] == "not_null"


def test_manifest_to_yaml_accepted_values_includes_values():
    node = _make_test_node(
        "accepted_values",
        column_name="status",
        extra_kwargs={"values": ["active", "inactive"]},
    )
    manifest = _make_full_manifest([{"key": "test.project.accepted_values_orders_status.y2", "node": node}])
    yaml_str = manifest_to_yaml(manifest)
    parsed = yaml.safe_load(yaml_str)

    rule_doc = parsed["rules"][0]
    assert rule_doc["logic"]["values"] == ["active", "inactive"]


def test_manifest_to_yaml_foreign_key_includes_reference_fields():
    node = _make_test_node(
        "relationships",
        column_name="customer_id",
        extra_kwargs={"to": "ref('customers')", "field": "id"},
    )
    manifest = _make_full_manifest([{"key": "test.project.relationships_orders_customer_id.y3", "node": node}])
    yaml_str = manifest_to_yaml(manifest)
    parsed = yaml.safe_load(yaml_str)

    rule_doc = parsed["rules"][0]
    assert rule_doc["logic"]["reference_table"] == "customers"
    assert rule_doc["logic"]["reference_column"] == "id"


# ---------------------------------------------------------------------------
# load_manifest (file I/O)
# ---------------------------------------------------------------------------

def test_load_manifest_from_file(tmp_path: Path):
    data = {
        "nodes": {
            "model.project.orders": _make_model_node("orders"),
            "test.project.not_null_orders_id.abc": _make_test_node("not_null"),
        }
    }
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(data))

    loaded = load_manifest(manifest_file)
    assert "nodes" in loaded
    assert len(loaded["nodes"]) == 2


# ---------------------------------------------------------------------------
# Rule ID sanitization
# ---------------------------------------------------------------------------

def test_rule_id_is_sanitized():
    node = _make_test_node("not_null")
    key = "test.project.not_null_orders_order_id.abc123"
    manifest = _make_full_manifest([{"key": key, "node": node}])
    rule = dbt_test_to_rule(key, node, manifest)

    assert rule is not None
    # Must not contain dots, hyphens or spaces
    assert "." not in rule.metadata.id
    assert "-" not in rule.metadata.id
    assert " " not in rule.metadata.id


def test_rule_id_truncated_to_max_length():
    node = _make_test_node("unique")
    long_key = "test.project." + "a" * 200 + ".hash"
    manifest = _make_full_manifest([{"key": long_key, "node": node}])
    rule = dbt_test_to_rule(long_key, node, manifest)

    assert rule is not None
    assert len(rule.metadata.id) <= 64
