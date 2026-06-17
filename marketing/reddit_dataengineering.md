# Reddit Post — r/dataengineering

**Subreddit:** r/dataengineering
**Cross-post to:** r/Python, r/MachineLearning, r/dataanalysis
**Best time:** Tuesday–Thursday, 8am–12pm ET (peak engagement)
**Post type:** Text post (not link post — gets more engagement)

---

## Title (choose one)

**Option A:**
> I built an open-source data quality framework that uses LLMs to explain *why* checks fail — not just that they did

**Option B:**
> Tired of GE/Soda telling me what failed but not why — so I built Aegis DQ with LLM diagnosis and SQL auto-fix

**Option C:**
> Show r/dataengineering: Aegis DQ v0.6.0 — agentic DQ with LangGraph, 31 rule types, and aegis generate for LLM-written rules

---

## Body

**The problem I kept hitting:**

Every data quality tool I've used — Great Expectations, Soda, dbt tests — tells you *that* a check failed. `orders_amount_positive FAILED`. Cool. Now what?

You still have to open a notebook, query the table, look at the bad rows, figure out which pipeline wrote them, check the upstream source, and write a fix. That's the actual work. None of the tools help with it.

**What I built:**

Aegis DQ is an open-source Python framework with an LLM-powered diagnosis pipeline. For every failure it gives you:

1. **Plain-English explanation** — "Order placed with customer_id=99 that does not exist in the customers table"
2. **Root cause** — "Customer was deleted or is a test account not cleaned up in staging"
3. **Proposed SQL fix** — `UPDATE orders SET status = 'SHIPPED' WHERE status = 'DISPATCHED';` — verified for syntax before you see it

Here's what the output actually looks like:

```
╭──────────────── Validation Summary ─────────────────╮
│  Rules checked  │  12                               │
│  Passed         │  1   │  Failed  │  11             │
│  Pass rate      │  8%  │  Cost    │  $0.005576      │
╰─────────────────────────────────────────────────────╯

LLM Diagnoses
  orders_customer_fk  →  Order placed with customer_id=99 that does not exist.
                         Likely cause: customer deleted or test record not cleaned up.
                         Action: Verify customer_id=99; check recent deletions.

  products_sku_unique →  Duplicate SKU-001 found — two products share the same identifier.
                         Likely cause: duplicate import from supplier feed.

Remediation SQL
  orders_status_valid          UPDATE orders SET status = 'SHIPPED' WHERE status = 'DISPATCHED';
  products_price_positive      UPDATE products SET price = ABS(price) WHERE price < 0;
```

**How it works:**

5-node LangGraph pipeline: `plan → parallel_table → reconcile → remediate → report`

Each table runs concurrently. For every failure: classify by severity → LLM diagnose → trace root cause → propose SQL fix. Every LLM call is logged to a searchable SQLite audit trail.

**New in v0.6.0 — `aegis generate`:**

Instead of writing rules by hand, point it at your table and it writes them for you:

```bash
# Structural rules from schema stats
aegis generate orders --db warehouse.duckdb --output rules.yaml

# + business rules from your policy docs
aegis generate orders --db warehouse.duckdb --kb docs/orders_policy.md
```

Pass a plain-text document describing your business logic and it generates `accepted_values`, `regex_match`, and `sql_expression` rules automatically.

**Tech stack:** LangGraph, Pydantic, DuckDB, sqlglot, aiosqlite, Typer
**LLMs:** Anthropic Claude, OpenAI, Ollama (fully local/offline), AWS Bedrock
**Warehouses:** DuckDB, Postgres/Redshift, BigQuery, Databricks, Athena, Snowflake
**31 rule types** across completeness, uniqueness, validity, referential, statistical, ML anomaly

**Links:**
- GitHub: https://github.com/aegis-dq/aegis-dq
- Docs: https://aegis-dq.dev
- `pip install aegis-dq`

Happy to answer any questions about the architecture, the LLM prompting strategy, or the SQL verification pipeline. Would especially love feedback from anyone running GE or Soda in production — curious what pain points I might have missed.

---

## Cross-post variations

### r/Python version (shorter, more technical)
> Title: Aegis DQ v0.6.0 – LangGraph-based data quality framework with LLM diagnosis, sqlglot SQL verification, and aegis generate for schema-aware rule generation

Body: Focus on the tech stack — LangGraph pipeline design, sqlglot 3-stage verification, async parallel execution, aiosqlite audit trail. Link to architecture docs.

### r/MachineLearning version
> Title: Using LLMs for data quality diagnosis — built an open-source framework that explains *why* data checks fail

Body: Focus on the LLM prompt engineering, the self-correction loop for SQL generation, and the ML anomaly detection (zscore_outlier, isolation_forest, learned_threshold). Link to architecture docs.

---

## Comment response templates

**"Just use dbt tests"**
> dbt tests give you pass/fail. Aegis adds LLM diagnosis explaining why, root cause tracing, and SQL fix proposals. They're complementary — Aegis has a dbt manifest parser that converts your existing dbt tests to Aegis rules.

**"This seems expensive to run with an LLM"**
> The RetailCo demo (12 rules, 4 tables) costs $0.005 with Claude Haiku. `--no-llm` mode is free — pure rule validation, no API needed. Or use Ollama for $0 at any scale.

**"How does the diagnosis quality compare to just asking ChatGPT?"**
> The pipeline is deterministic and structured — every diagnosis is logged with the exact prompt, response, cost, and latency. You can search audit logs, export for fine-tuning, and reproduce any diagnosis. A raw ChatGPT call gives you nothing auditable.
