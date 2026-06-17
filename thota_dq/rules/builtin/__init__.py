"""Built-in rule templates and helpers."""

from __future__ import annotations

from .catalog import CATALOG, BuiltinTemplate


def get_template(name: str) -> BuiltinTemplate | None:
    """Return the BuiltinTemplate with the given name, or None if not found."""
    return next((t for t in CATALOG if t.name == name), None)


__all__ = ["CATALOG", "BuiltinTemplate", "get_template"]
