"""Warehouse adapters."""

from .base import WarehouseAdapter
from .duckdb import DuckDBAdapter

__all__ = ["WarehouseAdapter", "DuckDBAdapter"]
