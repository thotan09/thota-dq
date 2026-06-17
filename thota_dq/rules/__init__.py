"""Aegis rules — schema, parser, and built-in rules."""

from .parser import load_rules
from .schema import (
    DataQualityRule,
    RuleFailure,
    RuleLogic,
    RuleMetadata,
    RuleResult,
    RuleScope,
    RuleType,
    Severity,
)

__all__ = [
    "DataQualityRule",
    "RuleMetadata",
    "RuleScope",
    "RuleLogic",
    "RuleResult",
    "RuleFailure",
    "RuleType",
    "Severity",
    "load_rules",
]
