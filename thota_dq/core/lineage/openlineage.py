"""Lightweight OpenLineage JSON loader.

Parses OpenLineage RunEvent JSON (single event or list of events) and builds
a LineageGraph — a mapping of output_table → list[input_tables] that the RCA
node uses to trace upstream dependencies.

OpenLineage spec: https://openlineage.io/spec/1-0-5/OpenLineage.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# LineageGraph maps a dataset name → its direct upstream datasets
LineageGraph = dict[str, list[str]]


def _dataset_name(ds: dict[str, Any]) -> str:
    """Produce a readable name from an OpenLineage dataset object."""
    namespace = ds.get("namespace", "")
    name = ds.get("name", "")
    return f"{namespace}.{name}" if namespace else name


def _parse_event(event: dict[str, Any], graph: LineageGraph) -> None:
    inputs = event.get("inputs", [])
    outputs = event.get("outputs", [])
    upstream = [_dataset_name(i) for i in inputs if i.get("name")]
    for out in outputs:
        out_name = _dataset_name(out)
        if not out_name:
            continue
        existing = graph.get(out_name, [])
        merged = list(dict.fromkeys(existing + upstream))
        graph[out_name] = merged


def load_lineage(path: str | Path) -> LineageGraph:
    """Parse an OpenLineage JSON file and return a LineageGraph.

    Accepts a single RunEvent dict or a list of RunEvent dicts.
    Silently ignores malformed entries.
    """
    raw = json.loads(Path(path).read_text())
    events = raw if isinstance(raw, list) else [raw]
    graph: LineageGraph = {}
    for event in events:
        if isinstance(event, dict):
            _parse_event(event, graph)
    return graph


def lineage_from_hints(hints: dict[str, list[str]]) -> LineageGraph:
    """Build a LineageGraph directly from rule-level lineage_hints dicts.

    hints format: {"upstream_tables": ["table_a", "table_b"]}
    Returns: {"<target>": ["table_a", "table_b"]} — caller fills in the target.
    """
    return {"__hints__": hints.get("upstream_tables", [])}


def upstream_chain(table: str, graph: LineageGraph, depth: int = 3) -> list[str]:
    """Walk upstream from `table` up to `depth` hops, returning unique ancestors."""
    visited: list[str] = []
    frontier = [table]
    for _ in range(depth):
        next_frontier: list[str] = []
        for node in frontier:
            for parent in graph.get(node, []):
                if parent not in visited and parent != table:
                    visited.append(parent)
                    next_frontier.append(parent)
        frontier = next_frontier
        if not frontier:
            break
    return visited
