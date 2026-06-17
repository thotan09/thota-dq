"""
Seed a local DuckDB file with realistic retail data — including intentional
data quality issues so the Aegis agent has real failures to diagnose.

Run:  python examples/retail_basic/seed_data.py
Creates: examples/retail_basic/retail.duckdb
"""

import duckdb
from pathlib import Path

DB_PATH = Path(__file__).parent / "retail.duckdb"


def seed(path: Path = DB_PATH) -> None:
    con = duckdb.connect(str(path))

    for tbl in ("orders", "customers", "products"):
        con.execute(f"DROP TABLE IF EXISTS {tbl}")

    # ── customers ────────────────────────────────────────────────────────────
    con.execute("""
        CREATE TABLE customers (
            customer_id   INTEGER PRIMARY KEY,
            email         TEXT,
            signup_date   DATE,
            country       TEXT,
            lifetime_value FLOAT
        )
    """)
    con.execute("""
        INSERT INTO customers VALUES
        (1,  'alice@example.com',  '2023-01-15', 'US',   4500.00),
        (2,  'bob@example.com',    '2023-03-22', 'UK',   1200.00),
        (3,  'carol@example.com',  '2024-06-01', 'US',   850.00),
        (4,  NULL,                 '2024-07-10', 'CA',   320.00),   -- missing email
        (5,  'dave@example.com',   '2024-08-05', 'AU',   -75.00),   -- negative LTV
        (6,  'alice@example.com',  '2024-09-01', 'US',   100.00),   -- duplicate email
        (7,  'eve@example.com',    '2099-12-31', 'US',   200.00)    -- future signup date
    """)

    # ── products ─────────────────────────────────────────────────────────────
    con.execute("""
        CREATE TABLE products (
            product_id   INTEGER PRIMARY KEY,
            sku          TEXT,
            name         TEXT,
            price        FLOAT,
            category     TEXT,
            in_stock     BOOLEAN
        )
    """)
    con.execute("""
        INSERT INTO products VALUES
        (1,  'SKU-001', 'Running Shoes',   89.99,  'footwear',  TRUE),
        (2,  'SKU-002', 'Yoga Mat',        29.99,  'fitness',   TRUE),
        (3,  'SKU-003', 'Water Bottle',    14.99,  'fitness',   FALSE),
        (4,  NULL,      'Mystery Item',    19.99,  'unknown',   TRUE),  -- missing SKU
        (5,  'SKU-005', 'Hiking Boots',    -5.00,  'footwear',  TRUE),  -- negative price
        (6,  'SKU-006', 'Resistance Band', 9.99,   'fitness',   NULL)   -- null in_stock
    """)

    # ── orders ───────────────────────────────────────────────────────────────
    con.execute("""
        CREATE TABLE orders (
            order_id    INTEGER,
            customer_id INTEGER,
            product_id  INTEGER,
            order_date  DATE,
            quantity    INTEGER,
            revenue     FLOAT,
            status      TEXT
        )
    """)
    con.execute("""
        INSERT INTO orders VALUES
        (1001, 1, 1, '2024-11-01', 2,  179.98, 'completed'),
        (1002, 2, 2, '2024-11-03', 1,   29.99, 'completed'),
        (1003, 3, 3, '2024-11-05', 3,   44.97, 'shipped'),
        (1004, 1, 1, '2024-11-10', 1,   89.99, 'completed'),
        (1005, 9, 2, '2024-11-12', 1,   29.99, 'completed'),  -- customer_id 9 doesn't exist
        (1006, 2, 1, '2024-11-15', 0,    0.00, 'pending'),    -- zero quantity
        (NULL, 3, 2, '2024-11-18', 1,   29.99, 'completed'),  -- NULL order_id
        (1007, 1, 5, '2024-11-20', 1,  -89.99, 'refunded'),   -- negative revenue
        (1008, 4, 3, '2099-12-25', 2,   89.94, 'pending')     -- future order date
    """)

    con.close()
    print(f"Seeded retail.duckdb at {path}")
    print("  customers : 7 rows (1 null email, 1 negative LTV, 1 duplicate email, 1 future date)")
    print("  products  : 6 rows (1 null SKU, 1 negative price, 1 null boolean)")
    print("  orders    : 9 rows (1 null order_id, 1 negative revenue, 1 orphan FK, 1 future date)")


if __name__ == "__main__":
    seed()
