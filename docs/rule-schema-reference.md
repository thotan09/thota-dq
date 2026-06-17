# Rule Schema Reference

All Aegis rules follow a consistent YAML schema anchored on `apiVersion: aegis.dev/v1`.

---

## Full schema

```yaml
apiVersion: aegis.dev/v1
kind: DataQualityRule

metadata:
  id: <string>                  # required — unique identifier
  severity: critical|high|medium|low|info   # default: medium
  domain: <string>              # optional — e.g. retail, banking
  owner: <string>               # optional — team or person responsible
  tags: [<string>, ...]         # optional — for filtering and grouping
  description: <string>         # optional — human-readable description

scope:
  warehouse: duckdb             # default: duckdb
  database: <string>            # optional
  schema: <string>              # optional
  table: <string>               # required
  columns: [<string>, ...]      # required for column-scoped rules

logic:
  type: <rule_type>             # required — see types below
  # type-specific fields follow

diagnosis:
  common_causes: [<string>, ...]         # hints for LLM diagnosis
  lineage_hints:
    upstream_tables: [<string>, ...]

remediation:
  auto_remediate: false                  # default: false — never auto-fixes
  proposal_strategy: llm_simple|llm_with_lineage|none

sla:
  detection_window: 1h                   # how fast failures must be detected
  notification_target: slack://channel   # where to send alerts
```

---

## Rule types

### Completeness

#### `not_null`
Fails if any value in `columns[0]` is NULL.

```yaml
scope:
  table: orders
  columns: [order_id]
logic:
  type: not_null
```

#### `not_empty_string`
Fails if any value in `columns[0]` is NULL, empty string `''`, or whitespace-only.

```yaml
scope:
  table: customers
  columns: [email]
logic:
  type: not_empty_string
```

#### `null_percentage_below`
Fails if the percentage of NULL values in `columns[0]` exceeds `threshold` percent.

```yaml
scope:
  table: products
  columns: [description]
logic:
  type: null_percentage_below
  threshold: 5.0     # fail if > 5% nulls
```

---

### Uniqueness

#### `unique`
Fails if any value in `columns[0]` appears more than once (excluding NULLs).

```yaml
scope:
  table: customers
  columns: [email]
logic:
  type: unique
```

#### `composite_unique`
Fails if any combination of values across all listed `columns` is duplicated.

```yaml
scope:
  table: order_items
  columns: [order_id, product_id]
logic:
  type: composite_unique
```

#### `duplicate_percentage_below`
Fails if the percentage of duplicate values in `columns[0]` exceeds `threshold`.

```yaml
scope:
  table: orders
  columns: [order_id]
logic:
  type: duplicate_percentage_below
  threshold: 1.0     # fail if > 1% duplicates
```

---

### Validity — Numeric

#### `sql_expression`
Fails for any row where the SQL expression evaluates to false. The expression is a WHERE clause for rows that **pass**.

```yaml
scope:
  table: orders
logic:
  type: sql_expression
  expression: "revenue >= 0 AND quantity > 0"
```

#### `between`
Fails if `columns[0]` is outside the range `[min_value, max_value]`.

```yaml
scope:
  table: customers
  columns: [age]
logic:
  type: between
  min_value: 0
  max_value: 120
```

#### `min_value_check`
Fails if `columns[0]` is less than `min_value`.

```yaml
scope:
  table: orders
  columns: [quantity]
logic:
  type: min_value_check
  min_value: 1
```

#### `max_value_check`
Fails if `columns[0]` exceeds `max_value`.

```yaml
scope:
  table: orders
  columns: [discount_pct]
logic:
  type: max_value_check
  max_value: 100.0
```

---

### Validity — String

#### `regex_match`
Fails if `columns[0]` does not match `pattern` (uses DuckDB `regexp_matches`).

```yaml
scope:
  table: customers
  columns: [email]
logic:
  type: regex_match
  pattern: '^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
```

#### `accepted_values`
Fails if `columns[0]` contains a value not in the `values` list.

```yaml
scope:
  table: orders
  columns: [status]
logic:
  type: accepted_values
  values: [pending, shipped, completed, refunded]
```

#### `not_accepted_values`
Fails if `columns[0]` contains any value in the prohibited `values` list.

```yaml
scope:
  table: orders
  columns: [status]
logic:
  type: not_accepted_values
  values: [test, dummy, placeholder]
```

#### `column_exists`
Fails if `columns[0]` does not exist in the table schema.

```yaml
scope:
  table: orders
  columns: [order_id]
logic:
  type: column_exists
```

---

### Validity — Temporal

#### `no_future_dates`
Fails if `columns[0]` contains any date greater than today.

```yaml
scope:
  table: orders
  columns: [order_date]
logic:
  type: no_future_dates
```

#### `date_order`
Fails if `columns[0]` is greater than `column_b` (i.e. start > end).

```yaml
scope:
  table: subscriptions
  columns: [start_date]
logic:
  type: date_order
  column_b: end_date
```

#### `freshness`
Fails if the maximum value of `columns[0]` is older than `threshold` hours ago. If no column is specified, checks the table's last modification time.

```yaml
scope:
  table: orders
  columns: [updated_at]
logic:
  type: freshness
  threshold: 24      # fail if no data newer than 24 hours
  unit: hours
```

---

### Referential Integrity

#### `foreign_key`
Fails if any non-null value in `columns[0]` does not exist in `reference_table.reference_column`.

```yaml
scope:
  table: orders
  columns: [customer_id]
logic:
  type: foreign_key
  reference_table: customers
  reference_column: customer_id
```

#### `conditional_not_null`
Fails if `columns[0]` is NULL when `condition` is true.

```yaml
scope:
  table: orders
  columns: [refund_reason]
logic:
  type: conditional_not_null
  condition: "status = 'refunded'"
```

---

### Statistical

#### `mean_between`
Fails if the mean of `columns[0]` is outside `[min_value, max_value]`.

```yaml
scope:
  table: orders
  columns: [revenue]
logic:
  type: mean_between
  min_value: 10.0
  max_value: 500.0
```

#### `stddev_below`
Fails if the standard deviation of `columns[0]` exceeds `threshold`.

```yaml
scope:
  table: sensor_readings
  columns: [temperature]
logic:
  type: stddev_below
  threshold: 15.0
```

#### `column_sum_between`
Fails if the sum of `columns[0]` is outside `[min_value, max_value]`.

```yaml
scope:
  table: daily_settlements
  columns: [amount]
logic:
  type: column_sum_between
  min_value: 0
  max_value: 1000000
```

---

### Volume

#### `row_count`
Fails if the table has fewer than `threshold` rows.

```yaml
scope:
  table: orders
logic:
  type: row_count
  threshold: 100
```

#### `row_count_between`
Fails if the row count is outside `[min_value, max_value]`.

```yaml
scope:
  table: daily_orders
logic:
  type: row_count_between
  min_value: 50
  max_value: 10000
```

#### `custom_sql`
Runs an arbitrary SQL query. The query must return a single boolean value — `true` means the check passed.

```yaml
scope:
  table: orders
logic:
  type: custom_sql
  query: |
    SELECT COUNT(*) = 0
    FROM orders o
    LEFT JOIN customers c ON o.customer_id = c.customer_id
    WHERE c.customer_id IS NULL
```

---

!!! tip "Test SQL before committing"
    Use `aegis validate rules.yaml --db path/to/db` to dry-run all `sql_expression` and `custom_sql` rules against your actual warehouse before a full pipeline run. This catches syntax errors, missing columns, and dialect mismatches (e.g. DuckDB's `date_diff` vs. `DATEDIFF`) without writing to the audit trail or incurring LLM cost.

---

## Severity levels

| Level | Meaning | Typical use |
|---|---|---|
| `critical` | Data is unusable — pipeline should stop | NULL primary keys, broken foreign keys |
| `high` | Significant quality issue — must be fixed soon | Negative revenue, invalid status codes |
| `medium` | Noticeable quality issue — investigate | Freshness exceeded, high null rate |
| `low` | Minor quality concern | Missing optional fields |
| `info` | Informational — no action required | Statistical baselines |

---

## Built-in templates

Rather than writing logic from scratch, reference a named template from the catalog:

```bash
aegis rules list                        # see all 31 templates
aegis rules list --category validity    # filter by category
aegis rules list --json                 # machine-readable output
```

Each template maps directly to one of the 31 rule types above with sensible defaults already set.
