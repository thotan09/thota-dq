"""Abstract base class for warehouse adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ...rules.schema import DataQualityRule, RuleResult


class WarehouseAdapter(ABC):
    """Abstract warehouse adapter — execute rules against a data warehouse."""

    @abstractmethod
    async def execute_rule(self, rule: DataQualityRule) -> RuleResult:
        """Execute a single rule and return its result."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the warehouse connection."""
        ...
