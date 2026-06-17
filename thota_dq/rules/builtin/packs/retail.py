"""Retail industry pack — 25 pre-built rules for e-commerce DQ."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ...parser import load_rules
from ...schema import DataQualityRule

_PACK_YAML = Path(__file__).parent / "retail.yaml"


def load_retail_pack(
    orders_table: str = "orders",
    order_items_table: str = "order_items",
    products_table: str = "products",
    customers_table: str = "customers",
    warehouse: str = "duckdb",
) -> list[DataQualityRule]:
    """Load retail pack rules with customisable table names.

    Args:
        orders_table: Name of your orders table (default: "orders").
        order_items_table: Name of your order line-items table (default: "order_items").
        products_table: Name of your products/catalog table (default: "products").
        customers_table: Name of your customers table (default: "customers").
        warehouse: Warehouse type string, e.g. "duckdb", "bigquery", "snowflake".

    Returns:
        A list of :class:`~thota_dq.rules.schema.DataQualityRule` objects ready to run.
    """
    text = _PACK_YAML.read_text()

    # Substitute canonical table names with caller's actual names.
    # Use newline-terminated patterns to avoid partial matches (e.g. "orders"
    # inside "order_items").
    text = text.replace("table: orders\n", f"table: {orders_table}\n")
    text = text.replace("table: order_items\n", f"table: {order_items_table}\n")
    text = text.replace("table: products\n", f"table: {products_table}\n")
    text = text.replace("table: customers\n", f"table: {customers_table}\n")
    text = text.replace("warehouse: duckdb", f"warehouse: {warehouse}")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(text)
        tmp = f.name
    try:
        return load_rules(Path(tmp))
    finally:
        os.unlink(tmp)
