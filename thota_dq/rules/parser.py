"""Parse YAML rule files into DataQualityRule objects."""

from __future__ import annotations

from pathlib import Path

import yaml

from .schema import DataQualityRule


def load_rules(path: str | Path) -> list[DataQualityRule]:
    """Load rules from a YAML file. Supports list-of-rules and rules: key."""
    path = Path(path)
    text = path.read_text()
    docs = list(yaml.safe_load_all(text))

    rules: list[DataQualityRule] = []
    for doc in docs:
        if doc is None:
            continue
        if isinstance(doc, dict) and "rules" in doc:
            for r in doc["rules"]:
                rules.append(_parse_rule(r))
        elif isinstance(doc, list):
            for r in doc:
                rules.append(_parse_rule(r))
        else:
            rules.append(_parse_rule(doc))
    return rules


def _parse_rule(data: dict) -> DataQualityRule:
    """Parse a single rule dict into a DataQualityRule. Handles nested spec structure."""
    # Work on a copy so we don't mutate the original
    data = dict(data)

    # Flatten nested spec structure if present
    if "spec" in data:
        spec = data.pop("spec")
        data["scope"] = spec.get("scope", {})
        data["logic"] = spec.get("logic", {})
        for k in ("reconciliation", "diagnosis", "remediation", "sla"):
            if k in spec:
                data[k] = spec[k]

    return DataQualityRule.model_validate(data, from_attributes=False)
