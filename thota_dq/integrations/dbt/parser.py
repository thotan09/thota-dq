"""Parse dbt manifest.json artifacts and convert dbt tests to Aegis rules."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from ...rules.schema import (
    DataQualityRule,
    RuleLogic,
    RuleMetadata,
    RuleScope,
    RuleType,
    Severity,
)

# ---------------------------------------------------------------------------
# dbt test name → Aegis RuleType
# ---------------------------------------------------------------------------

_TEST_TYPE_MAP: dict[str, RuleType] = {
    "not_null": RuleType.NOT_NULL,
    "unique": RuleType.UNIQUE,
    "accepted_values": RuleType.ACCEPTED_VALUES,
    "relationships": RuleType.FOREIGN_KEY,
}

# dbt severity string → Aegis Severity
_SEVERITY_MAP: dict[str, Severity] = {
    "error": Severity.HIGH,
    "warn": Severity.LOW,
}


def load_manifest(path: str | Path) -> dict:
    """Load and return parsed manifest.json."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _sanitize_id(raw: str, max_len: int = 64) -> str:
    """Turn a dbt node key into a valid, stable identifier."""
    sanitized = re.sub(r"[^a-zA-Z0-9]", "_", raw)
    # Collapse consecutive underscores
    sanitized = re.sub(r"_+", "_", sanitized)
    sanitized = sanitized.strip("_")
    return sanitized[:max_len]


def _resolve_table(node: dict, manifest: dict) -> str:
    """Resolve the table name from depends_on.nodes, preferring model nodes."""
    depends = node.get("depends_on", {}).get("nodes", [])
    for dep in depends:
        if dep.startswith("model."):
            # "model.project.orders" → "orders"
            parts = dep.split(".")
            if len(parts) >= 3:
                # Check the manifest for the node's actual name
                model_node = manifest.get("nodes", {}).get(dep)
                if model_node:
                    return model_node.get("name", parts[-1])
                return parts[-1]
    # Fallback: last segment of first dependency
    if depends:
        return depends[0].split(".")[-1]
    return "unknown"


def _map_severity(node: dict) -> Severity:
    """Map dbt config severity to Aegis Severity."""
    raw = node.get("config", {}).get("severity", "")
    return _SEVERITY_MAP.get(raw.lower(), Severity.MEDIUM)


def dbt_test_to_rule(node_key: str, node: dict, manifest: dict) -> DataQualityRule | None:
    """Convert one dbt test node to an Aegis DataQualityRule.

    Returns None if the test type is unsupported or the node is not a test.
    """
    if node.get("resource_type") != "test":
        return None

    test_metadata = node.get("test_metadata", {})
    test_name = test_metadata.get("name", "")
    rule_type = _TEST_TYPE_MAP.get(test_name)
    if rule_type is None:
        return None

    kwargs = test_metadata.get("kwargs", {})
    column_name: str | None = kwargs.get("column_name")
    table_name = _resolve_table(node, manifest)
    severity = _map_severity(node)
    rule_id = _sanitize_id(node_key)

    # Build logic
    logic_kwargs: dict = {"type": rule_type}

    if rule_type == RuleType.ACCEPTED_VALUES:
        values = kwargs.get("values")
        if values is not None:
            logic_kwargs["values"] = [str(v) for v in values]

    elif rule_type == RuleType.FOREIGN_KEY:
        ref_raw = kwargs.get("to", "")
        # "ref('customers')" → "customers"
        ref_match = re.search(r"ref\(['\"](\w+)['\"]\)", ref_raw)
        reference_table = ref_match.group(1) if ref_match else ref_raw
        logic_kwargs["reference_table"] = reference_table
        logic_kwargs["reference_column"] = kwargs.get("field", "id")

    logic = RuleLogic(**logic_kwargs)

    columns = [column_name] if column_name else []

    scope = RuleScope(warehouse="duckdb", table=table_name, columns=columns)
    metadata = RuleMetadata(id=rule_id, severity=severity)

    return DataQualityRule(
        **{
            "apiVersion": "aegis.dev/v1",
            "kind": "DataQualityRule",
            "metadata": metadata,
            "scope": scope,
            "logic": logic,
        }
    )


def manifest_to_rules(manifest: dict) -> list[DataQualityRule]:
    """Convert all supported dbt tests in a manifest to Aegis rules."""
    rules: list[DataQualityRule] = []
    for key, node in manifest.get("nodes", {}).items():
        rule = dbt_test_to_rule(key, node, manifest)
        if rule is not None:
            rules.append(rule)
    return rules


def manifest_to_yaml(manifest: dict) -> str:
    """Convert manifest to a rules YAML string ready to write to disk."""
    rules = manifest_to_rules(manifest)
    docs: list[dict] = []
    for rule in rules:
        doc: dict = {
            "apiVersion": rule.api_version,
            "kind": rule.kind,
            "metadata": {
                "id": rule.metadata.id,
                "severity": str(rule.metadata.severity),
            },
            "scope": {
                "warehouse": rule.spec_scope.warehouse,
                "table": rule.spec_scope.table,
                "columns": rule.spec_scope.columns,
            },
            "logic": {
                "type": str(rule.spec_logic.type),
            },
        }
        # Include optional logic fields only when set
        if rule.spec_logic.values is not None:
            doc["logic"]["values"] = rule.spec_logic.values
        if rule.spec_logic.reference_table is not None:
            doc["logic"]["reference_table"] = rule.spec_logic.reference_table
        if rule.spec_logic.reference_column is not None:
            doc["logic"]["reference_column"] = rule.spec_logic.reference_column

        docs.append(doc)

    return yaml.dump({"rules": docs}, default_flow_style=False, sort_keys=False)
