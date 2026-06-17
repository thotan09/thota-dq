"""Tests for the retail industry pack."""

from __future__ import annotations

from pathlib import Path

from thota_dq.rules.builtin.packs.retail import _PACK_YAML, load_retail_pack
from thota_dq.rules.parser import load_rules
from thota_dq.rules.schema import Severity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PACK_YAML_PATH: Path = _PACK_YAML


def _load_pack_yaml() -> list:
    """Load rules directly from the YAML file (no substitution)."""
    return load_rules(PACK_YAML_PATH)


# ---------------------------------------------------------------------------
# 1. YAML validity
# ---------------------------------------------------------------------------


def test_retail_yaml_is_valid():
    """The pack YAML must parse without errors and contain >= 20 rules."""
    rules = _load_pack_yaml()
    assert len(rules) >= 20, f"Expected >= 20 rules, got {len(rules)}"


# ---------------------------------------------------------------------------
# 2. Table coverage
# ---------------------------------------------------------------------------


def test_retail_pack_covers_all_tables():
    """Rules must reference all four canonical retail tables."""
    rules = _load_pack_yaml()
    tables = {r.spec_scope.table for r in rules}
    assert "orders" in tables, "No rules for 'orders' table"
    assert "order_items" in tables, "No rules for 'order_items' table"
    assert "products" in tables, "No rules for 'products' table"
    assert "customers" in tables, "No rules for 'customers' table"


# ---------------------------------------------------------------------------
# 3. Default table names via load_retail_pack()
# ---------------------------------------------------------------------------


def test_load_retail_pack_default_tables():
    """load_retail_pack() with defaults must return rules with original table names."""
    rules = load_retail_pack()
    tables = {r.spec_scope.table for r in rules}
    assert "orders" in tables
    assert "order_items" in tables
    assert "products" in tables
    assert "customers" in tables


# ---------------------------------------------------------------------------
# 4. Custom orders table name
# ---------------------------------------------------------------------------


def test_load_retail_pack_custom_orders_table():
    """load_retail_pack(orders_table='raw_orders') must substitute the table name."""
    rules = load_retail_pack(orders_table="raw_orders")
    orders_tables = {r.spec_scope.table for r in rules if "orders" in r.metadata.id and "items" not in r.metadata.id}
    assert "raw_orders" in orders_tables, (
        f"Expected 'raw_orders' in order-scoped rules, got: {orders_tables}"
    )
    # The original canonical name must not appear for orders rules
    assert "orders" not in orders_tables, (
        "Canonical 'orders' table still present after substitution"
    )


def test_load_retail_pack_custom_tables():
    """All four custom table names must appear in the loaded rules."""
    rules = load_retail_pack(
        orders_table="raw_orders",
        order_items_table="raw_order_lines",
        products_table="dim_products",
        customers_table="dim_customers",
    )
    tables = {r.spec_scope.table for r in rules}
    assert "raw_orders" in tables
    assert "raw_order_lines" in tables
    assert "dim_products" in tables
    assert "dim_customers" in tables


# ---------------------------------------------------------------------------
# 5. Custom warehouse
# ---------------------------------------------------------------------------


def test_load_retail_pack_custom_warehouse():
    """load_retail_pack(warehouse='bigquery') must set warehouse on all rules."""
    rules = load_retail_pack(warehouse="bigquery")
    warehouses = {r.spec_scope.warehouse for r in rules}
    assert warehouses == {"bigquery"}, f"Expected only 'bigquery', got {warehouses}"


# ---------------------------------------------------------------------------
# 6. Diagnosis hints
# ---------------------------------------------------------------------------


def test_all_rules_have_diagnosis_hints():
    """Every rule must have at least one common_cause in its diagnosis block."""
    rules = _load_pack_yaml()
    missing = [
        r.metadata.id
        for r in rules
        if not r.diagnosis.common_causes
    ]
    assert not missing, f"Rules missing diagnosis.common_causes: {missing}"


# ---------------------------------------------------------------------------
# 7. Critical rules per table
# ---------------------------------------------------------------------------


def test_critical_rules_exist():
    """Each table must have at least one critical severity rule."""
    rules = _load_pack_yaml()
    critical_tables = {
        r.spec_scope.table
        for r in rules
        if r.metadata.severity == Severity.CRITICAL
    }
    for table in ("orders", "order_items", "products", "customers"):
        assert table in critical_tables, f"No critical rule found for table '{table}'"


# ---------------------------------------------------------------------------
# 8. Specific rule existence
# ---------------------------------------------------------------------------


def test_order_id_not_null_rule():
    """The canonical not_null rule for order_id must exist with correct id."""
    rules = _load_pack_yaml()
    rule_ids = {r.metadata.id for r in rules}
    assert "retail_orders_no_null_order_id" in rule_ids


def test_email_regex_rule():
    """An email regex rule must exist for the customers table."""
    rules = _load_pack_yaml()
    email_rules = [
        r for r in rules
        if r.spec_scope.table == "customers"
        and r.spec_logic.type.value == "regex_match"
    ]
    assert email_rules, "No regex_match rule found for customers table"
    # Verify the pattern contains basic email structure markers
    pattern = email_rules[0].spec_logic.pattern or ""
    assert "@" in pattern, f"Email regex pattern does not contain '@': {pattern!r}"


# ---------------------------------------------------------------------------
# 9. Order status accepted values
# ---------------------------------------------------------------------------


def test_status_accepted_values():
    """The order status rule must include all expected lifecycle statuses."""
    rules = _load_pack_yaml()
    status_rules = [
        r for r in rules
        if r.spec_scope.table == "orders"
        and r.spec_logic.type.value == "accepted_values"
    ]
    assert status_rules, "No accepted_values rule found for orders.status"

    rule = status_rules[0]
    values = set(rule.spec_logic.values or [])
    expected = {"placed", "confirmed", "shipped", "delivered", "cancelled", "refunded"}
    assert expected == values, (
        f"Status values mismatch.\nExpected: {expected}\nGot: {values}"
    )


# ---------------------------------------------------------------------------
# 10. Rule ID prefix convention
# ---------------------------------------------------------------------------


def test_all_rule_ids_prefixed_retail():
    """All rule IDs in the pack must start with 'retail_'."""
    rules = _load_pack_yaml()
    bad = [r.metadata.id for r in rules if not r.metadata.id.startswith("retail_")]
    assert not bad, f"Rule IDs not prefixed with 'retail_': {bad}"


# ---------------------------------------------------------------------------
# 11. Unique rule IDs
# ---------------------------------------------------------------------------


def test_all_rule_ids_unique():
    """All rule IDs in the pack must be unique."""
    rules = _load_pack_yaml()
    ids = [r.metadata.id for r in rules]
    assert len(ids) == len(set(ids)), (
        f"Duplicate rule IDs found: {[i for i in ids if ids.count(i) > 1]}"
    )


# ---------------------------------------------------------------------------
# 12. Revenue non-negative rule
# ---------------------------------------------------------------------------


def test_revenue_non_negative_rule_exists():
    """A sql_expression rule checking revenue >= 0 must exist."""
    rules = _load_pack_yaml()
    revenue_rules = [
        r for r in rules
        if r.spec_scope.table == "orders"
        and r.spec_logic.type.value == "sql_expression"
        and r.spec_logic.expression is not None
        and "revenue" in r.spec_logic.expression
    ]
    assert revenue_rules, "No sql_expression revenue check found for orders table"
