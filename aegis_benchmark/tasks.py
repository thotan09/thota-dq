"""100 DataGovBench-style eval tasks across 6 data quality categories.

Each task specifies:
- setup_sql: DDL + DML to build an in-memory DuckDB fixture
- rule: DataQualityRule spec dict
- ground_truth: expected pass/fail, failure category, and diagnosis keywords

Categories (DataGovBench alignment):
  imputation   — NULL / missing value checks          (20 tasks)
  dedup        — uniqueness / duplicate checks         (20 tasks)
  filtering    — value validity / constraint checks    (20 tasks)
  refinement   — format, range, statistical checks     (15 tasks)
  integration  — cross-table / referential checks      (15 tasks)
  classification — volume / table-level checks         (10 tasks)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvalTask:
    task_id: str
    category: str           # imputation | dedup | filtering | refinement | integration | classification
    description: str
    setup_sql: list[str]    # executed in order against a fresh :memory: DuckDB
    rule: dict              # DataQualityRule spec (passed to model_validate)
    ground_truth: dict      # {passed: bool, failure_category: str|None, keywords: list[str]}


def _rule(rule_id: str, table: str, logic: dict, severity: str = "high",
          columns: list[str] | None = None) -> dict:
    return {
        "apiVersion": "aegis.dev/v1",
        "kind": "DataQualityRule",
        "metadata": {"id": rule_id, "severity": severity},
        "scope": {"table": table, "columns": columns or []},
        "logic": logic,
    }


# ---------------------------------------------------------------------------
# IMPUTATION — 20 tasks
# ---------------------------------------------------------------------------

_IMPUTATION: list[EvalTask] = [
    # not_null — 8 tasks (4 pass, 4 fail)
    EvalTask(
        task_id="imp_01", category="imputation",
        description="orders.customer_id: no NULLs → pass",
        setup_sql=[
            "CREATE TABLE orders (id INT, customer_id INT)",
            "INSERT INTO orders VALUES (1,10),(2,20),(3,30)",
        ],
        rule=_rule("imp_01", "orders", {"type": "not_null"}, columns=["customer_id"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="imp_02", category="imputation",
        description="orders.customer_id: 1 NULL → fail",
        setup_sql=[
            "CREATE TABLE orders (id INT, customer_id INT)",
            "INSERT INTO orders VALUES (1,10),(2,NULL),(3,30)",
        ],
        rule=_rule("imp_02", "orders", {"type": "not_null"}, "critical", ["customer_id"]),
        ground_truth={"passed": False, "failure_category": "null_value", "keywords": ["NULL", "missing"]},
    ),
    EvalTask(
        task_id="imp_03", category="imputation",
        description="payments.amount: no NULLs → pass",
        setup_sql=[
            "CREATE TABLE payments (id INT, amount FLOAT)",
            "INSERT INTO payments VALUES (1,9.99),(2,19.99),(3,4.99)",
        ],
        rule=_rule("imp_03", "payments", {"type": "not_null"}, columns=["amount"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="imp_04", category="imputation",
        description="payments.amount: all NULLs → fail",
        setup_sql=[
            "CREATE TABLE payments (id INT, amount FLOAT)",
            "INSERT INTO payments VALUES (1,NULL),(2,NULL),(3,NULL)",
        ],
        rule=_rule("imp_04", "payments", {"type": "not_null"}, "critical", ["amount"]),
        ground_truth={"passed": False, "failure_category": "null_value", "keywords": ["NULL"]},
    ),
    EvalTask(
        task_id="imp_05", category="imputation",
        description="users.email: no NULLs → pass",
        setup_sql=[
            "CREATE TABLE users (id INT, email VARCHAR)",
            "INSERT INTO users VALUES (1,'a@x.com'),(2,'b@x.com')",
        ],
        rule=_rule("imp_05", "users", {"type": "not_null"}, columns=["email"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="imp_06", category="imputation",
        description="users.email: 50% NULL → fail",
        setup_sql=[
            "CREATE TABLE users (id INT, email VARCHAR)",
            "INSERT INTO users VALUES (1,'a@x.com'),(2,NULL),(3,'c@x.com'),(4,NULL)",
        ],
        rule=_rule("imp_06", "users", {"type": "not_null"}, "high", ["email"]),
        ground_truth={"passed": False, "failure_category": "null_value", "keywords": ["NULL", "email"]},
    ),
    EvalTask(
        task_id="imp_07", category="imputation",
        description="products.sku: no NULLs → pass",
        setup_sql=[
            "CREATE TABLE products (sku VARCHAR, name VARCHAR)",
            "INSERT INTO products VALUES ('A1','Widget'),('B2','Gadget')",
        ],
        rule=_rule("imp_07", "products", {"type": "not_null"}, columns=["sku"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="imp_08", category="imputation",
        description="products.sku: NULLs present → fail",
        setup_sql=[
            "CREATE TABLE products (sku VARCHAR, name VARCHAR)",
            "INSERT INTO products VALUES ('A1','Widget'),(NULL,'Gadget'),(NULL,'Tool')",
        ],
        rule=_rule("imp_08", "products", {"type": "not_null"}, "critical", ["sku"]),
        ground_truth={"passed": False, "failure_category": "null_value", "keywords": ["NULL", "sku"]},
    ),
    # null_percentage_below — 6 tasks (3 pass, 3 fail)
    EvalTask(
        task_id="imp_09", category="imputation",
        description="orders.notes: 10% NULL, threshold 20% → pass",
        setup_sql=[
            "CREATE TABLE orders (id INT, notes VARCHAR)",
            "INSERT INTO orders SELECT i, CASE WHEN i % 10 = 0 THEN NULL ELSE 'note' END FROM range(1,101) t(i)",
        ],
        rule=_rule("imp_09", "orders", {"type": "null_percentage_below", "threshold": 20.0}, columns=["notes"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="imp_10", category="imputation",
        description="orders.notes: 10% NULL, threshold 5% → fail",
        setup_sql=[
            "CREATE TABLE orders (id INT, notes VARCHAR)",
            "INSERT INTO orders SELECT i, CASE WHEN i % 10 = 0 THEN NULL ELSE 'note' END FROM range(1,101) t(i)",
        ],
        rule=_rule("imp_10", "orders", {"type": "null_percentage_below", "threshold": 5.0}, columns=["notes"]),
        ground_truth={"passed": False, "failure_category": "null_rate_exceeded", "keywords": ["NULL", "percent"]},
    ),
    EvalTask(
        task_id="imp_11", category="imputation",
        description="employees.department: 0% NULL, threshold 1% → pass",
        setup_sql=[
            "CREATE TABLE employees (id INT, department VARCHAR)",
            "INSERT INTO employees VALUES (1,'Eng'),(2,'Sales'),(3,'HR')",
        ],
        rule=_rule("imp_11", "employees", {"type": "null_percentage_below", "threshold": 1.0}, columns=["department"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="imp_12", category="imputation",
        description="employees.department: 33% NULL, threshold 10% → fail",
        setup_sql=[
            "CREATE TABLE employees (id INT, department VARCHAR)",
            "INSERT INTO employees VALUES (1,'Eng'),(2,NULL),(3,'HR')",
        ],
        rule=_rule("imp_12", "employees", {"type": "null_percentage_below", "threshold": 10.0}, columns=["department"]),
        ground_truth={"passed": False, "failure_category": "null_rate_exceeded", "keywords": ["NULL", "threshold"]},
    ),
    EvalTask(
        task_id="imp_13", category="imputation",
        description="transactions.ref: 1% NULL, threshold 2% → pass",
        setup_sql=[
            "CREATE TABLE transactions (id INT, ref VARCHAR)",
            "INSERT INTO transactions SELECT i, CASE WHEN i = 50 THEN NULL ELSE 'REF'||i::VARCHAR END FROM range(1,101) t(i)",
        ],
        rule=_rule("imp_13", "transactions", {"type": "null_percentage_below", "threshold": 2.0}, columns=["ref"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="imp_14", category="imputation",
        description="transactions.ref: 50% NULL, threshold 5% → fail",
        setup_sql=[
            "CREATE TABLE transactions (id INT, ref VARCHAR)",
            "INSERT INTO transactions SELECT i, CASE WHEN i % 2 = 0 THEN NULL ELSE 'REF'||i::VARCHAR END FROM range(1,101) t(i)",
        ],
        rule=_rule("imp_14", "transactions", {"type": "null_percentage_below", "threshold": 5.0}, columns=["ref"]),
        ground_truth={"passed": False, "failure_category": "null_rate_exceeded", "keywords": ["NULL", "50"]},
    ),
    # not_empty_string — 4 tasks (2 pass, 2 fail)
    EvalTask(
        task_id="imp_15", category="imputation",
        description="customers.name: no empty strings → pass",
        setup_sql=[
            "CREATE TABLE customers (id INT, name VARCHAR)",
            "INSERT INTO customers VALUES (1,'Alice'),(2,'Bob'),(3,'Carol')",
        ],
        rule=_rule("imp_15", "customers", {"type": "not_empty_string"}, columns=["name"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="imp_16", category="imputation",
        description="customers.name: empty string present → fail",
        setup_sql=[
            "CREATE TABLE customers (id INT, name VARCHAR)",
            "INSERT INTO customers VALUES (1,'Alice'),(2,''),(3,'  ')",
        ],
        rule=_rule("imp_16", "customers", {"type": "not_empty_string"}, "medium", ["name"]),
        ground_truth={"passed": False, "failure_category": "empty_string", "keywords": ["empty", "whitespace"]},
    ),
    EvalTask(
        task_id="imp_17", category="imputation",
        description="products.description: all non-empty → pass",
        setup_sql=[
            "CREATE TABLE products (id INT, description VARCHAR)",
            "INSERT INTO products VALUES (1,'A widget'),(2,'A gadget')",
        ],
        rule=_rule("imp_17", "products", {"type": "not_empty_string"}, columns=["description"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="imp_18", category="imputation",
        description="products.description: whitespace-only row → fail",
        setup_sql=[
            "CREATE TABLE products (id INT, description VARCHAR)",
            "INSERT INTO products VALUES (1,'A widget'),(2,'   '),(3,'')",
        ],
        rule=_rule("imp_18", "products", {"type": "not_empty_string"}, "medium", ["description"]),
        ground_truth={"passed": False, "failure_category": "empty_string", "keywords": ["empty"]},
    ),
    # conditional_not_null — 2 tasks (1 pass, 1 fail)
    EvalTask(
        task_id="imp_19", category="imputation",
        description="orders.ship_date not null when status='shipped' → pass",
        setup_sql=[
            "CREATE TABLE orders (id INT, status VARCHAR, ship_date DATE)",
            "INSERT INTO orders VALUES (1,'shipped','2024-01-01'),(2,'pending',NULL)",
        ],
        rule=_rule("imp_19", "orders",
                   {"type": "conditional_not_null", "condition": "status = 'shipped'"}, "high", ["ship_date"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="imp_20", category="imputation",
        description="orders.ship_date NULL when status='shipped' → fail",
        setup_sql=[
            "CREATE TABLE orders (id INT, status VARCHAR, ship_date DATE)",
            "INSERT INTO orders VALUES (1,'shipped',NULL),(2,'shipped',NULL),(3,'pending',NULL)",
        ],
        rule=_rule("imp_20", "orders",
                   {"type": "conditional_not_null", "condition": "status = 'shipped'"}, "high", ["ship_date"]),
        ground_truth={"passed": False, "failure_category": "conditional_null", "keywords": ["NULL", "condition", "shipped"]},
    ),
]

# ---------------------------------------------------------------------------
# DEDUP — 20 tasks
# ---------------------------------------------------------------------------

_DEDUP: list[EvalTask] = [
    # unique — 8 tasks (4 pass, 4 fail)
    EvalTask(
        task_id="dup_01", category="dedup",
        description="orders.order_id: all unique → pass",
        setup_sql=[
            "CREATE TABLE orders (order_id INT, amount FLOAT)",
            "INSERT INTO orders VALUES (1,10.0),(2,20.0),(3,30.0)",
        ],
        rule=_rule("dup_01", "orders", {"type": "unique"}, columns=["order_id"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="dup_02", category="dedup",
        description="orders.order_id: duplicates present → fail",
        setup_sql=[
            "CREATE TABLE orders (order_id INT, amount FLOAT)",
            "INSERT INTO orders VALUES (1,10.0),(1,20.0),(2,30.0)",
        ],
        rule=_rule("dup_02", "orders", {"type": "unique"}, "high", ["order_id"]),
        ground_truth={"passed": False, "failure_category": "duplicate_key", "keywords": ["duplicate", "unique"]},
    ),
    EvalTask(
        task_id="dup_03", category="dedup",
        description="users.email: all unique → pass",
        setup_sql=[
            "CREATE TABLE users (id INT, email VARCHAR)",
            "INSERT INTO users VALUES (1,'a@x.com'),(2,'b@x.com'),(3,'c@x.com')",
        ],
        rule=_rule("dup_03", "users", {"type": "unique"}, columns=["email"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="dup_04", category="dedup",
        description="users.email: duplicate emails → fail",
        setup_sql=[
            "CREATE TABLE users (id INT, email VARCHAR)",
            "INSERT INTO users VALUES (1,'a@x.com'),(2,'a@x.com'),(3,'c@x.com')",
        ],
        rule=_rule("dup_04", "users", {"type": "unique"}, "critical", ["email"]),
        ground_truth={"passed": False, "failure_category": "duplicate_key", "keywords": ["duplicate"]},
    ),
    EvalTask(
        task_id="dup_05", category="dedup",
        description="products.sku: all unique → pass",
        setup_sql=[
            "CREATE TABLE products (sku VARCHAR, price FLOAT)",
            "INSERT INTO products VALUES ('SKU1',1.0),('SKU2',2.0),('SKU3',3.0)",
        ],
        rule=_rule("dup_05", "products", {"type": "unique"}, columns=["sku"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="dup_06", category="dedup",
        description="products.sku: repeated SKU → fail",
        setup_sql=[
            "CREATE TABLE products (sku VARCHAR, price FLOAT)",
            "INSERT INTO products VALUES ('SKU1',1.0),('SKU1',2.0),('SKU2',3.0)",
        ],
        rule=_rule("dup_06", "products", {"type": "unique"}, "critical", ["sku"]),
        ground_truth={"passed": False, "failure_category": "duplicate_key", "keywords": ["duplicate", "SKU"]},
    ),
    EvalTask(
        task_id="dup_07", category="dedup",
        description="accounts.account_no: single row → pass",
        setup_sql=[
            "CREATE TABLE accounts (account_no VARCHAR, balance FLOAT)",
            "INSERT INTO accounts VALUES ('ACC001', 1000.0)",
        ],
        rule=_rule("dup_07", "accounts", {"type": "unique"}, columns=["account_no"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="dup_08", category="dedup",
        description="accounts.account_no: all rows same value → fail",
        setup_sql=[
            "CREATE TABLE accounts (account_no VARCHAR, balance FLOAT)",
            "INSERT INTO accounts VALUES ('ACC001',100.0),('ACC001',200.0),('ACC001',300.0)",
        ],
        rule=_rule("dup_08", "accounts", {"type": "unique"}, "critical", ["account_no"]),
        ground_truth={"passed": False, "failure_category": "duplicate_key", "keywords": ["duplicate"]},
    ),
    # composite_unique — 6 tasks (3 pass, 3 fail)
    EvalTask(
        task_id="dup_09", category="dedup",
        description="order_items (order_id, product_id): unique combos → pass",
        setup_sql=[
            "CREATE TABLE order_items (order_id INT, product_id INT, qty INT)",
            "INSERT INTO order_items VALUES (1,1,2),(1,2,1),(2,1,3)",
        ],
        rule=_rule("dup_09", "order_items", {"type": "composite_unique"}, columns=["order_id", "product_id"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="dup_10", category="dedup",
        description="order_items (order_id, product_id): duplicate combo → fail",
        setup_sql=[
            "CREATE TABLE order_items (order_id INT, product_id INT, qty INT)",
            "INSERT INTO order_items VALUES (1,1,2),(1,1,3),(2,1,1)",
        ],
        rule=_rule("dup_10", "order_items", {"type": "composite_unique"}, "high", ["order_id", "product_id"]),
        ground_truth={"passed": False, "failure_category": "duplicate_composite_key", "keywords": ["duplicate", "composite"]},
    ),
    EvalTask(
        task_id="dup_11", category="dedup",
        description="schedule (date, shift): unique pairs → pass",
        setup_sql=[
            "CREATE TABLE schedule (date DATE, shift VARCHAR, staff_id INT)",
            "INSERT INTO schedule VALUES ('2024-01-01','AM',1),('2024-01-01','PM',2),('2024-01-02','AM',3)",
        ],
        rule=_rule("dup_11", "schedule", {"type": "composite_unique"}, columns=["date", "shift"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="dup_12", category="dedup",
        description="schedule (date, shift): same slot twice → fail",
        setup_sql=[
            "CREATE TABLE schedule (date DATE, shift VARCHAR, staff_id INT)",
            "INSERT INTO schedule VALUES ('2024-01-01','AM',1),('2024-01-01','AM',2)",
        ],
        rule=_rule("dup_12", "schedule", {"type": "composite_unique"}, "high", ["date", "shift"]),
        ground_truth={"passed": False, "failure_category": "duplicate_composite_key", "keywords": ["duplicate"]},
    ),
    EvalTask(
        task_id="dup_13", category="dedup",
        description="inventory (warehouse, sku): unique → pass",
        setup_sql=[
            "CREATE TABLE inventory (warehouse VARCHAR, sku VARCHAR, qty INT)",
            "INSERT INTO inventory VALUES ('WH1','A',10),('WH1','B',5),('WH2','A',8)",
        ],
        rule=_rule("dup_13", "inventory", {"type": "composite_unique"}, columns=["warehouse", "sku"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="dup_14", category="dedup",
        description="inventory (warehouse, sku): duplicate entry → fail",
        setup_sql=[
            "CREATE TABLE inventory (warehouse VARCHAR, sku VARCHAR, qty INT)",
            "INSERT INTO inventory VALUES ('WH1','A',10),('WH1','A',5)",
        ],
        rule=_rule("dup_14", "inventory", {"type": "composite_unique"}, "high", ["warehouse", "sku"]),
        ground_truth={"passed": False, "failure_category": "duplicate_composite_key", "keywords": ["duplicate"]},
    ),
    # duplicate_percentage_below — 6 tasks (3 pass, 3 fail)
    EvalTask(
        task_id="dup_15", category="dedup",
        description="sessions.token: 0% duplicates, threshold 1% → pass",
        setup_sql=[
            "CREATE TABLE sessions (id INT, token VARCHAR)",
            "INSERT INTO sessions SELECT i, 'tok'||i::VARCHAR FROM range(1,101) t(i)",
        ],
        rule=_rule("dup_15", "sessions", {"type": "duplicate_percentage_below", "threshold": 1.0}, columns=["token"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="dup_16", category="dedup",
        description="sessions.token: 10% duplicates, threshold 5% → fail",
        setup_sql=[
            "CREATE TABLE sessions (id INT, token VARCHAR)",
            "INSERT INTO sessions SELECT i, CASE WHEN i <= 10 THEN 'dup' ELSE 'tok'||i::VARCHAR END FROM range(1,101) t(i)",
        ],
        rule=_rule("dup_16", "sessions", {"type": "duplicate_percentage_below", "threshold": 5.0}, columns=["token"]),
        ground_truth={"passed": False, "failure_category": "duplicate_rate_exceeded", "keywords": ["duplicate", "percent"]},
    ),
    EvalTask(
        task_id="dup_17", category="dedup",
        description="events.event_key: 2% duplicates, threshold 5% → pass",
        setup_sql=[
            "CREATE TABLE events (id INT, event_key VARCHAR)",
            "INSERT INTO events SELECT i, CASE WHEN i <= 2 THEN 'dup' ELSE 'ev'||i::VARCHAR END FROM range(1,101) t(i)",
        ],
        rule=_rule("dup_17", "events", {"type": "duplicate_percentage_below", "threshold": 5.0}, columns=["event_key"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="dup_18", category="dedup",
        description="events.event_key: 50% duplicates, threshold 1% → fail",
        setup_sql=[
            "CREATE TABLE events (id INT, event_key VARCHAR)",
            "INSERT INTO events SELECT i, CASE WHEN i % 2 = 0 THEN 'dup' ELSE 'ev'||i::VARCHAR END FROM range(1,101) t(i)",
        ],
        rule=_rule("dup_18", "events", {"type": "duplicate_percentage_below", "threshold": 1.0}, columns=["event_key"]),
        ground_truth={"passed": False, "failure_category": "duplicate_rate_exceeded", "keywords": ["duplicate"]},
    ),
    EvalTask(
        task_id="dup_19", category="dedup",
        description="logs.request_id: all unique, threshold 0.1% → pass",
        setup_sql=[
            "CREATE TABLE logs (id INT, request_id VARCHAR)",
            "INSERT INTO logs SELECT i, 'req'||i::VARCHAR FROM range(1,1001) t(i)",
        ],
        rule=_rule("dup_19", "logs", {"type": "duplicate_percentage_below", "threshold": 0.1}, columns=["request_id"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="dup_20", category="dedup",
        description="logs.request_id: 20% same value, threshold 1% → fail",
        setup_sql=[
            "CREATE TABLE logs (id INT, request_id VARCHAR)",
            "INSERT INTO logs SELECT i, CASE WHEN i <= 200 THEN 'same' ELSE 'req'||i::VARCHAR END FROM range(1,1001) t(i)",
        ],
        rule=_rule("dup_20", "logs", {"type": "duplicate_percentage_below", "threshold": 1.0}, columns=["request_id"]),
        ground_truth={"passed": False, "failure_category": "duplicate_rate_exceeded", "keywords": ["duplicate"]},
    ),
]

# ---------------------------------------------------------------------------
# FILTERING — 20 tasks
# ---------------------------------------------------------------------------

_FILTERING: list[EvalTask] = [
    # sql_expression — 6 tasks (3 pass, 3 fail)
    EvalTask(
        task_id="flt_01", category="filtering",
        description="orders.amount >= 0: all positive → pass",
        setup_sql=[
            "CREATE TABLE orders (id INT, amount FLOAT)",
            "INSERT INTO orders VALUES (1,10.0),(2,0.0),(3,99.99)",
        ],
        rule=_rule("flt_01", "orders", {"type": "sql_expression", "expression": "amount >= 0"}, columns=["amount"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="flt_02", category="filtering",
        description="orders.amount >= 0: negative values present → fail",
        setup_sql=[
            "CREATE TABLE orders (id INT, amount FLOAT)",
            "INSERT INTO orders VALUES (1,10.0),(2,-5.0),(3,-0.01)",
        ],
        rule=_rule("flt_02", "orders", {"type": "sql_expression", "expression": "amount >= 0"}, "critical", ["amount"]),
        ground_truth={"passed": False, "failure_category": "constraint_violation", "keywords": ["negative", "expression"]},
    ),
    EvalTask(
        task_id="flt_03", category="filtering",
        description="employees.age BETWEEN 18 AND 70: valid ages → pass",
        setup_sql=[
            "CREATE TABLE employees (id INT, age INT)",
            "INSERT INTO employees VALUES (1,25),(2,42),(3,67)",
        ],
        rule=_rule("flt_03", "employees", {"type": "sql_expression", "expression": "age BETWEEN 18 AND 70"}, columns=["age"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="flt_04", category="filtering",
        description="employees.age BETWEEN 18 AND 70: minor present → fail",
        setup_sql=[
            "CREATE TABLE employees (id INT, age INT)",
            "INSERT INTO employees VALUES (1,25),(2,15),(3,200)",
        ],
        rule=_rule("flt_04", "employees", {"type": "sql_expression", "expression": "age BETWEEN 18 AND 70"}, "high", ["age"]),
        ground_truth={"passed": False, "failure_category": "constraint_violation", "keywords": ["expression", "failed"]},
    ),
    EvalTask(
        task_id="flt_05", category="filtering",
        description="transactions.status IN valid set: all valid → pass",
        setup_sql=[
            "CREATE TABLE transactions (id INT, status VARCHAR)",
            "INSERT INTO transactions VALUES (1,'approved'),(2,'pending'),(3,'approved')",
        ],
        rule=_rule("flt_05", "transactions",
                   {"type": "sql_expression", "expression": "status IN ('approved','pending','declined')"}, columns=["status"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="flt_06", category="filtering",
        description="transactions.status: invalid value → fail",
        setup_sql=[
            "CREATE TABLE transactions (id INT, status VARCHAR)",
            "INSERT INTO transactions VALUES (1,'approved'),(2,'UNKNOWN'),(3,'DELETED')",
        ],
        rule=_rule("flt_06", "transactions",
                   {"type": "sql_expression", "expression": "status IN ('approved','pending','declined')"}, "high", ["status"]),
        ground_truth={"passed": False, "failure_category": "constraint_violation", "keywords": ["expression"]},
    ),
    # between — 4 tasks (2 pass, 2 fail)
    EvalTask(
        task_id="flt_07", category="filtering",
        description="products.price between 0.01 and 9999.99 → pass",
        setup_sql=[
            "CREATE TABLE products (id INT, price FLOAT)",
            "INSERT INTO products VALUES (1,9.99),(2,99.0),(3,1.0)",
        ],
        rule=_rule("flt_07", "products", {"type": "between", "min_value": 0.01, "max_value": 9999.99}, columns=["price"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="flt_08", category="filtering",
        description="products.price between 0.01 and 9999.99: price=0 → fail",
        setup_sql=[
            "CREATE TABLE products (id INT, price FLOAT)",
            "INSERT INTO products VALUES (1,9.99),(2,0.0),(3,-1.0)",
        ],
        rule=_rule("flt_08", "products", {"type": "between", "min_value": 0.01, "max_value": 9999.99}, "high", ["price"]),
        ground_truth={"passed": False, "failure_category": "out_of_range", "keywords": ["range", "between"]},
    ),
    EvalTask(
        task_id="flt_09", category="filtering",
        description="scores between 0 and 100 → pass",
        setup_sql=[
            "CREATE TABLE scores (student_id INT, score INT)",
            "INSERT INTO scores VALUES (1,85),(2,92),(3,100),(4,0)",
        ],
        rule=_rule("flt_09", "scores", {"type": "between", "min_value": 0, "max_value": 100}, columns=["score"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="flt_10", category="filtering",
        description="scores between 0 and 100: 101 present → fail",
        setup_sql=[
            "CREATE TABLE scores (student_id INT, score INT)",
            "INSERT INTO scores VALUES (1,85),(2,101),(3,-1)",
        ],
        rule=_rule("flt_10", "scores", {"type": "between", "min_value": 0, "max_value": 100}, "high", ["score"]),
        ground_truth={"passed": False, "failure_category": "out_of_range", "keywords": ["range"]},
    ),
    # regex_match — 4 tasks (2 pass, 2 fail)
    EvalTask(
        task_id="flt_11", category="filtering",
        description="users.phone matches E.164 pattern → pass",
        setup_sql=[
            "CREATE TABLE users (id INT, phone VARCHAR)",
            "INSERT INTO users VALUES (1,'+14155552671'),(2,'+442071838750')",
        ],
        rule=_rule("flt_11", "users", {"type": "regex_match", "pattern": "^\\+[1-9]\\d{7,14}$"}, columns=["phone"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="flt_12", category="filtering",
        description="users.phone: invalid format → fail",
        setup_sql=[
            "CREATE TABLE users (id INT, phone VARCHAR)",
            "INSERT INTO users VALUES (1,'555-1234'),(2,'not-a-phone')",
        ],
        rule=_rule("flt_12", "users", {"type": "regex_match", "pattern": "^\\+[1-9]\\d{7,14}$"}, "medium", ["phone"]),
        ground_truth={"passed": False, "failure_category": "format_mismatch", "keywords": ["regex", "pattern", "format"]},
    ),
    EvalTask(
        task_id="flt_13", category="filtering",
        description="orders.zip_code matches 5-digit pattern → pass",
        setup_sql=[
            "CREATE TABLE orders (id INT, zip_code VARCHAR)",
            "INSERT INTO orders VALUES (1,'94107'),(2,'10001'),(3,'00501')",
        ],
        rule=_rule("flt_13", "orders", {"type": "regex_match", "pattern": "^\\d{5}$"}, columns=["zip_code"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="flt_14", category="filtering",
        description="orders.zip_code: non-numeric zip → fail",
        setup_sql=[
            "CREATE TABLE orders (id INT, zip_code VARCHAR)",
            "INSERT INTO orders VALUES (1,'9410A'),(2,'XXXXX')",
        ],
        rule=_rule("flt_14", "orders", {"type": "regex_match", "pattern": "^\\d{5}$"}, "medium", ["zip_code"]),
        ground_truth={"passed": False, "failure_category": "format_mismatch", "keywords": ["pattern", "format"]},
    ),
    # accepted_values — 4 tasks (2 pass, 2 fail)
    EvalTask(
        task_id="flt_15", category="filtering",
        description="orders.currency in [USD, EUR, GBP] → pass",
        setup_sql=[
            "CREATE TABLE orders (id INT, currency VARCHAR)",
            "INSERT INTO orders VALUES (1,'USD'),(2,'EUR'),(3,'GBP')",
        ],
        rule=_rule("flt_15", "orders", {"type": "accepted_values", "values": ["USD", "EUR", "GBP"]}, columns=["currency"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="flt_16", category="filtering",
        description="orders.currency: unknown currency → fail",
        setup_sql=[
            "CREATE TABLE orders (id INT, currency VARCHAR)",
            "INSERT INTO orders VALUES (1,'USD'),(2,'XYZ'),(3,'BTC')",
        ],
        rule=_rule("flt_16", "orders", {"type": "accepted_values", "values": ["USD", "EUR", "GBP"]}, "high", ["currency"]),
        ground_truth={"passed": False, "failure_category": "invalid_value", "keywords": ["accepted", "value"]},
    ),
    EvalTask(
        task_id="flt_17", category="filtering",
        description="tickets.priority in [low, medium, high] → pass",
        setup_sql=[
            "CREATE TABLE tickets (id INT, priority VARCHAR)",
            "INSERT INTO tickets VALUES (1,'low'),(2,'high'),(3,'medium')",
        ],
        rule=_rule("flt_17", "tickets", {"type": "accepted_values", "values": ["low", "medium", "high"]}, columns=["priority"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="flt_18", category="filtering",
        description="tickets.priority: 'critical' not in allowed set → fail",
        setup_sql=[
            "CREATE TABLE tickets (id INT, priority VARCHAR)",
            "INSERT INTO tickets VALUES (1,'low'),(2,'critical'),(3,'URGENT')",
        ],
        rule=_rule("flt_18", "tickets", {"type": "accepted_values", "values": ["low", "medium", "high"]}, "high", ["priority"]),
        ground_truth={"passed": False, "failure_category": "invalid_value", "keywords": ["accepted", "value"]},
    ),
    # no_future_dates — 2 tasks (1 pass, 1 fail)
    EvalTask(
        task_id="flt_19", category="filtering",
        description="transactions.created_at: all past dates → pass",
        setup_sql=[
            "CREATE TABLE transactions (id INT, created_at DATE)",
            "INSERT INTO transactions VALUES (1,'2020-01-01'),(2,'2023-06-15')",
        ],
        rule=_rule("flt_19", "transactions", {"type": "no_future_dates"}, columns=["created_at"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="flt_20", category="filtering",
        description="transactions.created_at: future date present → fail",
        setup_sql=[
            "CREATE TABLE transactions (id INT, created_at DATE)",
            "INSERT INTO transactions VALUES (1,'2020-01-01'),(2,'2099-12-31')",
        ],
        rule=_rule("flt_20", "transactions", {"type": "no_future_dates"}, "medium", ["created_at"]),
        ground_truth={"passed": False, "failure_category": "future_date", "keywords": ["future", "date"]},
    ),
]

# ---------------------------------------------------------------------------
# REFINEMENT — 15 tasks
# ---------------------------------------------------------------------------

_REFINEMENT: list[EvalTask] = [
    # min_value_check — 4 tasks (2 pass, 2 fail)
    EvalTask(
        task_id="ref_01", category="refinement",
        description="payments.amount >= 0.01 (min_value) → pass",
        setup_sql=[
            "CREATE TABLE payments (id INT, amount FLOAT)",
            "INSERT INTO payments VALUES (1,9.99),(2,0.01),(3,100.0)",
        ],
        rule=_rule("ref_01", "payments", {"type": "min_value_check", "min_value": 0.01}, columns=["amount"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="ref_02", category="refinement",
        description="payments.amount >= 0.01: zero amount → fail",
        setup_sql=[
            "CREATE TABLE payments (id INT, amount FLOAT)",
            "INSERT INTO payments VALUES (1,9.99),(2,0.0),(3,-5.0)",
        ],
        rule=_rule("ref_02", "payments", {"type": "min_value_check", "min_value": 0.01}, "high", ["amount"]),
        ground_truth={"passed": False, "failure_category": "below_minimum", "keywords": ["minimum", "threshold"]},
    ),
    EvalTask(
        task_id="ref_03", category="refinement",
        description="ratings.stars >= 1 → pass",
        setup_sql=[
            "CREATE TABLE ratings (id INT, stars INT)",
            "INSERT INTO ratings VALUES (1,3),(2,5),(3,1)",
        ],
        rule=_rule("ref_03", "ratings", {"type": "min_value_check", "min_value": 1}, columns=["stars"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="ref_04", category="refinement",
        description="ratings.stars >= 1: zero stars → fail",
        setup_sql=[
            "CREATE TABLE ratings (id INT, stars INT)",
            "INSERT INTO ratings VALUES (1,3),(2,0),(3,-1)",
        ],
        rule=_rule("ref_04", "ratings", {"type": "min_value_check", "min_value": 1}, "medium", ["stars"]),
        ground_truth={"passed": False, "failure_category": "below_minimum", "keywords": ["minimum"]},
    ),
    # max_value_check — 4 tasks (2 pass, 2 fail)
    EvalTask(
        task_id="ref_05", category="refinement",
        description="discounts.pct <= 100 → pass",
        setup_sql=[
            "CREATE TABLE discounts (id INT, pct FLOAT)",
            "INSERT INTO discounts VALUES (1,10.0),(2,50.0),(3,100.0)",
        ],
        rule=_rule("ref_05", "discounts", {"type": "max_value_check", "max_value": 100.0}, columns=["pct"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="ref_06", category="refinement",
        description="discounts.pct <= 100: 150% discount → fail",
        setup_sql=[
            "CREATE TABLE discounts (id INT, pct FLOAT)",
            "INSERT INTO discounts VALUES (1,10.0),(2,150.0),(3,200.0)",
        ],
        rule=_rule("ref_06", "discounts", {"type": "max_value_check", "max_value": 100.0}, "high", ["pct"]),
        ground_truth={"passed": False, "failure_category": "exceeds_maximum", "keywords": ["maximum", "threshold"]},
    ),
    EvalTask(
        task_id="ref_07", category="refinement",
        description="employees.hours_per_week <= 60 → pass",
        setup_sql=[
            "CREATE TABLE employees (id INT, hours_per_week FLOAT)",
            "INSERT INTO employees VALUES (1,40.0),(2,45.0),(3,60.0)",
        ],
        rule=_rule("ref_07", "employees", {"type": "max_value_check", "max_value": 60.0}, columns=["hours_per_week"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="ref_08", category="refinement",
        description="employees.hours_per_week <= 60: 80 hrs → fail",
        setup_sql=[
            "CREATE TABLE employees (id INT, hours_per_week FLOAT)",
            "INSERT INTO employees VALUES (1,40.0),(2,80.0),(3,100.0)",
        ],
        rule=_rule("ref_08", "employees", {"type": "max_value_check", "max_value": 60.0}, "medium", ["hours_per_week"]),
        ground_truth={"passed": False, "failure_category": "exceeds_maximum", "keywords": ["maximum"]},
    ),
    # mean_between — 4 tasks (2 pass, 2 fail)
    EvalTask(
        task_id="ref_09", category="refinement",
        description="orders.amount mean between 50 and 500 → pass",
        setup_sql=[
            "CREATE TABLE orders (id INT, amount FLOAT)",
            "INSERT INTO orders SELECT i, 100.0 + (i % 50) FROM range(1,101) t(i)",
        ],
        rule=_rule("ref_09", "orders", {"type": "mean_between", "min_value": 50.0, "max_value": 500.0}, columns=["amount"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="ref_10", category="refinement",
        description="orders.amount mean outside [50,500]: extreme values → fail",
        setup_sql=[
            "CREATE TABLE orders (id INT, amount FLOAT)",
            "INSERT INTO orders VALUES (1,10000.0),(2,9000.0),(3,11000.0)",
        ],
        rule=_rule("ref_10", "orders", {"type": "mean_between", "min_value": 50.0, "max_value": 500.0}, "medium", ["amount"]),
        ground_truth={"passed": False, "failure_category": "statistical_anomaly", "keywords": ["mean", "average"]},
    ),
    EvalTask(
        task_id="ref_11", category="refinement",
        description="sensor.reading mean between -10 and 40 → pass",
        setup_sql=[
            "CREATE TABLE sensor (id INT, reading FLOAT)",
            "INSERT INTO sensor VALUES (1,20.0),(2,22.0),(3,18.0),(4,25.0)",
        ],
        rule=_rule("ref_11", "sensor", {"type": "mean_between", "min_value": -10.0, "max_value": 40.0}, columns=["reading"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="ref_12", category="refinement",
        description="sensor.reading mean outside [-10,40]: extreme spike → fail",
        setup_sql=[
            "CREATE TABLE sensor (id INT, reading FLOAT)",
            "INSERT INTO sensor VALUES (1,200.0),(2,250.0),(3,300.0)",
        ],
        rule=_rule("ref_12", "sensor", {"type": "mean_between", "min_value": -10.0, "max_value": 40.0}, "medium", ["reading"]),
        ground_truth={"passed": False, "failure_category": "statistical_anomaly", "keywords": ["mean"]},
    ),
    # stddev_below — 3 tasks (1 pass, 1 fail, 1 pass with high threshold)
    EvalTask(
        task_id="ref_13", category="refinement",
        description="prices.stddev below 100: low variance → pass",
        setup_sql=[
            "CREATE TABLE prices (id INT, price FLOAT)",
            "INSERT INTO prices SELECT i, 100.0 + (i % 10) FROM range(1,101) t(i)",
        ],
        rule=_rule("ref_13", "prices", {"type": "stddev_below", "threshold": 100.0}, columns=["price"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="ref_14", category="refinement",
        description="prices.stddev below 1: high variance → fail",
        setup_sql=[
            "CREATE TABLE prices (id INT, price FLOAT)",
            "INSERT INTO prices VALUES (1,1.0),(2,1000.0),(3,5000.0),(4,2.0)",
        ],
        rule=_rule("ref_14", "prices", {"type": "stddev_below", "threshold": 1.0}, "low", ["price"]),
        ground_truth={"passed": False, "failure_category": "high_variance", "keywords": ["variance", "stddev", "deviation"]},
    ),
    EvalTask(
        task_id="ref_15", category="refinement",
        description="latency.ms stddev below 1000: normal ops → pass",
        setup_sql=[
            "CREATE TABLE latency (id INT, ms FLOAT)",
            "INSERT INTO latency SELECT i, 200.0 + (i % 100) FROM range(1,201) t(i)",
        ],
        rule=_rule("ref_15", "latency", {"type": "stddev_below", "threshold": 1000.0}, columns=["ms"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
]

# ---------------------------------------------------------------------------
# INTEGRATION — 15 tasks
# ---------------------------------------------------------------------------

_INTEGRATION: list[EvalTask] = [
    # foreign_key — 4 tasks (2 pass, 2 fail)
    EvalTask(
        task_id="int_01", category="integration",
        description="order_items.order_id references orders.id → pass",
        setup_sql=[
            "CREATE TABLE orders (id INT)",
            "INSERT INTO orders VALUES (1),(2),(3)",
            "CREATE TABLE order_items (id INT, order_id INT)",
            "INSERT INTO order_items VALUES (1,1),(2,2),(3,3)",
        ],
        rule=_rule("int_01", "order_items",
                   {"type": "foreign_key", "reference_table": "orders", "reference_column": "id"}, columns=["order_id"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="int_02", category="integration",
        description="order_items.order_id: orphan reference → fail",
        setup_sql=[
            "CREATE TABLE orders (id INT)",
            "INSERT INTO orders VALUES (1),(2)",
            "CREATE TABLE order_items (id INT, order_id INT)",
            "INSERT INTO order_items VALUES (1,1),(2,99),(3,100)",
        ],
        rule=_rule("int_02", "order_items",
                   {"type": "foreign_key", "reference_table": "orders", "reference_column": "id"}, "critical", ["order_id"]),
        ground_truth={"passed": False, "failure_category": "referential_integrity", "keywords": ["foreign", "reference", "orphan"]},
    ),
    EvalTask(
        task_id="int_03", category="integration",
        description="payments.account_id references accounts.id → pass",
        setup_sql=[
            "CREATE TABLE accounts (id INT)",
            "INSERT INTO accounts VALUES (10),(20),(30)",
            "CREATE TABLE payments (id INT, account_id INT)",
            "INSERT INTO payments VALUES (1,10),(2,20),(3,30)",
        ],
        rule=_rule("int_03", "payments",
                   {"type": "foreign_key", "reference_table": "accounts", "reference_column": "id"}, columns=["account_id"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="int_04", category="integration",
        description="payments.account_id: invalid account refs → fail",
        setup_sql=[
            "CREATE TABLE accounts (id INT)",
            "INSERT INTO accounts VALUES (10),(20)",
            "CREATE TABLE payments (id INT, account_id INT)",
            "INSERT INTO payments VALUES (1,10),(2,999),(3,888)",
        ],
        rule=_rule("int_04", "payments",
                   {"type": "foreign_key", "reference_table": "accounts", "reference_column": "id"}, "critical", ["account_id"]),
        ground_truth={"passed": False, "failure_category": "referential_integrity", "keywords": ["foreign", "reference"]},
    ),
    # date_order — 4 tasks (2 pass, 2 fail)
    EvalTask(
        task_id="int_05", category="integration",
        description="projects.start_date <= end_date → pass",
        setup_sql=[
            "CREATE TABLE projects (id INT, start_date DATE, end_date DATE)",
            "INSERT INTO projects VALUES (1,'2024-01-01','2024-06-01'),(2,'2024-03-01','2024-12-31')",
        ],
        rule=_rule("int_05", "projects",
                   {"type": "date_order", "column_b": "end_date"}, columns=["start_date"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="int_06", category="integration",
        description="projects.start_date > end_date: inverted → fail",
        setup_sql=[
            "CREATE TABLE projects (id INT, start_date DATE, end_date DATE)",
            "INSERT INTO projects VALUES (1,'2024-12-01','2024-01-01'),(2,'2025-01-01','2024-06-01')",
        ],
        rule=_rule("int_06", "projects",
                   {"type": "date_order", "column_b": "end_date"}, "high", ["start_date"]),
        ground_truth={"passed": False, "failure_category": "date_order_violation", "keywords": ["date", "order", "start", "end"]},
    ),
    EvalTask(
        task_id="int_07", category="integration",
        description="loans.origination_date <= maturity_date → pass",
        setup_sql=[
            "CREATE TABLE loans (id INT, origination_date DATE, maturity_date DATE)",
            "INSERT INTO loans VALUES (1,'2020-01-01','2025-01-01'),(2,'2022-06-01','2027-06-01')",
        ],
        rule=_rule("int_07", "loans",
                   {"type": "date_order", "column_b": "maturity_date"}, columns=["origination_date"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="int_08", category="integration",
        description="loans: maturity before origination → fail",
        setup_sql=[
            "CREATE TABLE loans (id INT, origination_date DATE, maturity_date DATE)",
            "INSERT INTO loans VALUES (1,'2025-01-01','2020-01-01')",
        ],
        rule=_rule("int_08", "loans",
                   {"type": "date_order", "column_b": "maturity_date"}, "high", ["origination_date"]),
        ground_truth={"passed": False, "failure_category": "date_order_violation", "keywords": ["date", "order"]},
    ),
    # cross-table row count checks via custom_sql — 4 tasks (2 pass, 2 fail)
    EvalTask(
        task_id="int_09", category="integration",
        description="staging_orders row count matches orders → pass",
        setup_sql=[
            "CREATE TABLE orders (id INT)",
            "INSERT INTO orders VALUES (1),(2),(3)",
            "CREATE TABLE staging_orders (id INT)",
            "INSERT INTO staging_orders VALUES (1),(2),(3)",
        ],
        rule=_rule("int_09", "staging_orders",
                   {"type": "custom_sql",
                    "query": "SELECT (SELECT COUNT(*) FROM staging_orders) = (SELECT COUNT(*) FROM orders) AS passed, (SELECT COUNT(*) FROM staging_orders) AS row_count"}),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="int_10", category="integration",
        description="staging_orders: missing rows vs orders → fail",
        setup_sql=[
            "CREATE TABLE orders (id INT)",
            "INSERT INTO orders VALUES (1),(2),(3),(4),(5)",
            "CREATE TABLE staging_orders (id INT)",
            "INSERT INTO staging_orders VALUES (1),(2)",
        ],
        rule=_rule("int_10", "staging_orders",
                   {"type": "custom_sql",
                    "query": "SELECT (SELECT COUNT(*) FROM staging_orders) = (SELECT COUNT(*) FROM orders) AS passed, (SELECT COUNT(*) FROM staging_orders) AS row_count"}, "high"),
        ground_truth={"passed": False, "failure_category": "row_count_mismatch", "keywords": ["row", "count", "mismatch"]},
    ),
    EvalTask(
        task_id="int_11", category="integration",
        description="archive_events: orphan IDs not in events → fail (referential check via custom_sql)",
        setup_sql=[
            "CREATE TABLE events (id INT)",
            "INSERT INTO events SELECT i FROM range(1, 101) t(i)",
            "CREATE TABLE archive_events (id INT)",
            "INSERT INTO archive_events SELECT i FROM range(50, 151) t(i)",
        ],
        rule=_rule("int_11", "archive_events",
                   {"type": "custom_sql",
                    "query": "SELECT COUNT(*) = 0 AS passed, COUNT(*) AS row_count FROM archive_events a WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.id = a.id)"}, "high"),
        ground_truth={"passed": False, "failure_category": "referential_integrity", "keywords": ["reference", "orphan"]},
    ),
    EvalTask(
        task_id="int_12", category="integration",
        description="archive_events: all IDs exist in events → pass",
        setup_sql=[
            "CREATE TABLE events (id INT)",
            "INSERT INTO events SELECT i FROM range(1, 101) t(i)",
            "CREATE TABLE archive_events (id INT)",
            "INSERT INTO archive_events SELECT i FROM range(1, 51) t(i)",
        ],
        rule=_rule("int_12", "archive_events",
                   {"type": "custom_sql",
                    "query": "SELECT COUNT(*) = 0 AS passed, COUNT(*) AS row_count FROM archive_events a WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.id = a.id)"}),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    # freshness — 3 tasks (2 pass, 1 fail)
    EvalTask(
        task_id="int_13", category="integration",
        description="events.created_at: recent timestamp → pass",
        setup_sql=[
            "CREATE TABLE events (id INT, created_at TIMESTAMPTZ)",
            "INSERT INTO events VALUES (1, NOW() - INTERVAL '1 hour')",
        ],
        rule=_rule("int_13", "events", {"type": "freshness", "threshold": 24.0, "unit": "hours"}, columns=["created_at"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="int_14", category="integration",
        description="events.created_at: 48h old, threshold 24h → fail",
        setup_sql=[
            "CREATE TABLE events (id INT, created_at TIMESTAMPTZ)",
            "INSERT INTO events VALUES (1, NOW() - INTERVAL '48 hours')",
        ],
        rule=_rule("int_14", "events", {"type": "freshness", "threshold": 24.0, "unit": "hours"}, "high", ["created_at"]),
        ground_truth={"passed": False, "failure_category": "stale_data", "keywords": ["fresh", "stale", "hours"]},
    ),
    EvalTask(
        task_id="int_15", category="integration",
        description="metrics.recorded_at: 1h old, threshold 2h → pass",
        setup_sql=[
            "CREATE TABLE metrics (id INT, recorded_at TIMESTAMPTZ)",
            "INSERT INTO metrics VALUES (1, NOW() - INTERVAL '1 hour')",
        ],
        rule=_rule("int_15", "metrics", {"type": "freshness", "threshold": 2.0, "unit": "hours"}, columns=["recorded_at"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
]

# ---------------------------------------------------------------------------
# CLASSIFICATION (volume / table-level) — 10 tasks
# ---------------------------------------------------------------------------

_CLASSIFICATION: list[EvalTask] = [
    # row_count — 3 tasks (2 pass, 1 fail)
    EvalTask(
        task_id="cls_01", category="classification",
        description="orders: 3 rows, threshold 1 → pass",
        setup_sql=[
            "CREATE TABLE orders (id INT)",
            "INSERT INTO orders VALUES (1),(2),(3)",
        ],
        rule=_rule("cls_01", "orders", {"type": "row_count", "threshold": 1}),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="cls_02", category="classification",
        description="orders: 0 rows, threshold 1 → fail",
        setup_sql=["CREATE TABLE orders (id INT)"],
        rule=_rule("cls_02", "orders", {"type": "row_count", "threshold": 1}, "critical"),
        ground_truth={"passed": False, "failure_category": "insufficient_rows", "keywords": ["row", "count", "empty"]},
    ),
    EvalTask(
        task_id="cls_03", category="classification",
        description="daily_summary: 1000 rows, threshold 500 → pass",
        setup_sql=[
            "CREATE TABLE daily_summary (id INT)",
            "INSERT INTO daily_summary SELECT i FROM range(1, 1001) t(i)",
        ],
        rule=_rule("cls_03", "daily_summary", {"type": "row_count", "threshold": 500}),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    # row_count_between — 4 tasks (2 pass, 2 fail)
    EvalTask(
        task_id="cls_04", category="classification",
        description="orders: 50 rows, expected [10, 100] → pass",
        setup_sql=[
            "CREATE TABLE orders (id INT)",
            "INSERT INTO orders SELECT i FROM range(1, 51) t(i)",
        ],
        rule=_rule("cls_04", "orders", {"type": "row_count_between", "min_value": 10, "max_value": 100}),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="cls_05", category="classification",
        description="orders: 5 rows, expected [10, 100] → fail",
        setup_sql=[
            "CREATE TABLE orders (id INT)",
            "INSERT INTO orders SELECT i FROM range(1, 6) t(i)",
        ],
        rule=_rule("cls_05", "orders", {"type": "row_count_between", "min_value": 10, "max_value": 100}, "high"),
        ground_truth={"passed": False, "failure_category": "row_count_out_of_range", "keywords": ["row", "count"]},
    ),
    EvalTask(
        task_id="cls_06", category="classification",
        description="orders: 100 rows, expected [10, 100] → pass (boundary)",
        setup_sql=[
            "CREATE TABLE orders (id INT)",
            "INSERT INTO orders SELECT i FROM range(1, 101) t(i)",
        ],
        rule=_rule("cls_06", "orders", {"type": "row_count_between", "min_value": 10, "max_value": 100}),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="cls_07", category="classification",
        description="orders: 1000 rows, expected [10, 100] → fail (too many)",
        setup_sql=[
            "CREATE TABLE orders (id INT)",
            "INSERT INTO orders SELECT i FROM range(1, 1001) t(i)",
        ],
        rule=_rule("cls_07", "orders", {"type": "row_count_between", "min_value": 10, "max_value": 100}, "medium"),
        ground_truth={"passed": False, "failure_category": "row_count_out_of_range", "keywords": ["row", "count"]},
    ),
    # column_sum_between — 3 tasks (2 pass, 1 fail)
    EvalTask(
        task_id="cls_08", category="classification",
        description="payments.amount sum between 100 and 10000 → pass",
        setup_sql=[
            "CREATE TABLE payments (id INT, amount FLOAT)",
            "INSERT INTO payments VALUES (1,100.0),(2,200.0),(3,300.0)",
        ],
        rule=_rule("cls_08", "payments",
                   {"type": "column_sum_between", "min_value": 100.0, "max_value": 10000.0}, columns=["amount"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
    EvalTask(
        task_id="cls_09", category="classification",
        description="payments.amount sum > 10000 → fail",
        setup_sql=[
            "CREATE TABLE payments (id INT, amount FLOAT)",
            "INSERT INTO payments VALUES (1,5000.0),(2,6000.0),(3,1000.0)",
        ],
        rule=_rule("cls_09", "payments",
                   {"type": "column_sum_between", "min_value": 100.0, "max_value": 10000.0}, "high", ["amount"]),
        ground_truth={"passed": False, "failure_category": "sum_out_of_range", "keywords": ["sum", "range"]},
    ),
    EvalTask(
        task_id="cls_10", category="classification",
        description="daily_revenue.total sum in expected range → pass",
        setup_sql=[
            "CREATE TABLE daily_revenue (day DATE, total FLOAT)",
            "INSERT INTO daily_revenue VALUES ('2024-01-01',1000.0),('2024-01-02',1500.0)",
        ],
        rule=_rule("cls_10", "daily_revenue",
                   {"type": "column_sum_between", "min_value": 500.0, "max_value": 5000.0}, columns=["total"]),
        ground_truth={"passed": True, "failure_category": None, "keywords": []},
    ),
]

# ---------------------------------------------------------------------------
# Full task catalog
# ---------------------------------------------------------------------------

TASKS: list[EvalTask] = (
    _IMPUTATION + _DEDUP + _FILTERING + _REFINEMENT + _INTEGRATION + _CLASSIFICATION
)

assert len(TASKS) == 100, f"Expected 100 tasks, got {len(TASKS)}"

CATEGORIES = ["imputation", "dedup", "filtering", "refinement", "integration", "classification"]
