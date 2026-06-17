# Thota DQ

[![CI](https://github.com/thotan09/thota-dq/actions/workflows/ci.yml/badge.svg)](https://github.com/thotan09/thota-dq/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/thota-dq)](https://pypi.org/project/thota-dq/)
[![Downloads](https://img.shields.io/pypi/dm/thota-dq)](https://pypi.org/project/thota-dq/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![GitHub Marketplace](https://img.shields.io/badge/GitHub%20Marketplace-Thota%20DQ-blueviolet?logo=github)](https://github.com/marketplace/actions/thota-dq)

**Maintained by [Naveen Thota](mailto:thotan09@gmail.com)**

**The open-source agentic data quality framework.** Point it at your policy docs and warehouse — it generates rules, validates your data, diagnoses every failure with LLM root-cause analysis, and proposes SQL fixes. Run from the CLI, Airflow, GitHub Actions, or conversationally via Hermes.

Real-world result: **12 AML policy docs → 55 rules generated → 11 BSA/OFAC violations detected → all diagnosed → $0.01 total LLM cost.**

> Originally based on [aegis-dq](https://github.com/aegis-dq/aegis-dq). Maintained and extended by [Naveen Thota](mailto:thotan09@gmail.com).

- **31 rule types** — completeness, uniqueness, validity, referential integrity, statistical, ML anomaly detection
- **6 warehouse adapters** — DuckDB, Postgres/Redshift, BigQuery, Databricks, AWS Athena, Snowflake
- **Pluggable LLMs** — Anthropic Claude, OpenAI, Ollama (local), AWS Bedrock
- **Agentic pipeline** — plan → parallel validation → LLM diagnose → RCA → SQL remediate → report
- **Hermes + MCP** — run full pipelines conversationally; listed on [Glama.ai](https://glama.ai/mcp/servers/aegis-dq/aegis-dq)

---

## GitHub Actions — Quick Start

Add a data quality gate to any workflow in under 2 minutes:

```yaml
# .github/workflows/data-quality.yml
name: Data Quality

on: [push, pull_request]

jobs:
  data-quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Validate data quality
        uses: thotan09/thota-dq@v0.7.0
        with:
          rules-file: rules.yaml
          db: data/warehouse.duckdb
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

The step **fails the job automatically** when any rules fail, blocking broken data from reaching production. Set `fail-on-failure: 'false'` to report without blocking.

**Offline mode (no API key required):**

```yaml
      - name: Validate data quality (offline)
        uses: thotan09/thota-dq@v0.7.0
        with:
          rules-file: rules.yaml
          db: data/warehouse.duckdb
          no-llm: 'true'
```

### Action inputs

| Input | Default | Description |
|---|---|---|
| `rules-file` | `rules.yaml` | Path to rules YAML |
| `db` | `:memory:` | DuckDB file path |
| `warehouse` | `duckdb` | `duckdb` · `postgres` · `redshift` |
| `pg-dsn` | — | PostgreSQL / Redshift connection DSN |
| `no-llm` | `false` | Skip LLM — free offline validation |
| `llm` | `anthropic` | `anthropic` · `openai` · `ollama` |
| `llm-model` | *(provider default)* | Override the default model |
| `fail-on-failure` | `true` | Fail the step when rules fail |
| `version` | *(latest)* | Pin a specific `aegis-dq` version |
| `anthropic-api-key` | — | Required when `llm: anthropic` |
| `openai-api-key` | — | Required when `llm: openai` |

### Action outputs

| Output | Description |
|---|---|
| `rules-checked` | Total rules evaluated |
| `passed` | Rules that passed |
| `failed` | Rules that failed |
| `pass-rate` | Pass rate as a decimal (e.g. `"91.67"`) |
| `report-json` | Absolute path to the full JSON report |

**Using outputs in downstream steps:**

```yaml
      - name: Validate data quality
        id: dq
        uses: thotan09/thota-dq@v0.7.0
        with:
          rules-file: rules.yaml

      - name: Post summary
        run: echo "Pass rate: ${{ steps.dq.outputs.pass-rate }}%"
```

---

## Demo

![Aegis DQ Demo](docs/demo.gif)

```
╭──────────────────────────────────────────────────────╮
│ Aegis DQ  —  RetailCo E-commerce Demo                │
│ LLM: amazon.nova-pro-v1:0 via AWS Bedrock            │
╰──────────────────────────────────────────────────────╯

✓ Pipeline complete in 7.1s · 12 rules · $0.0056 LLM cost

╭──────────────── Validation Summary ─────────────────╮
│  Rules checked  │  12                               │
│  Passed         │  1   │  Failed  │  11             │
│  Pass rate      │  8%  │  Cost    │  $0.005576      │
╰─────────────────────────────────────────────────────╯

LLM Diagnoses
  orders_customer_fk  →  Order placed with customer_id=99 that does not exist.
                         Likely cause: customer deleted or test record not cleaned up.

  products_sku_unique →  Duplicate SKU-001 — two products share the same identifier.
                         Likely cause: duplicate import from supplier feed.

Remediation SQL (LLM-generated)
  orders_status_valid          UPDATE orders SET status = 'SHIPPED' WHERE status = 'DISPATCHED';
  products_price_positive      UPDATE products SET price = ABS(price) WHERE price < 0;
  products_stock_non_negative  UPDATE products SET stock_quantity = 0 WHERE stock_quantity < 0;
```

---

## Hermes integration — conversational data quality

Aegis DQ integrates with [Hermes](https://github.com/nousresearch/hermes-agent) via MCP. Point Hermes at your context and your warehouse — it handles the rest.

```
You (Hermes chat)
     │
     ▼
Hermes — memory, scheduling, multi-channel delivery
     │  MCP
     ▼
Aegis DQ — rules engine, LLM diagnosis, audit trail
     │
     ▼
Your warehouse + Your LLM
```

**Setup (2 steps):**

```bash
pip install aegis-dq
```

Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  aegis:
    command: aegis
    args: [mcp]
    env:
      ANTHROPIC_API_KEY: "${ANTHROPIC_API_KEY}"
```

**Define a pipeline manifest once:**

```yaml
# pipeline.yaml
name: orders-dq
rules: ./rules.yaml
database: ./warehouse.duckdb
kb:
  - ./policy.md     # business rules, SLAs, compliance docs
  - ./schema.md
goal: |
  Run all rules. For every failure explain the business impact,
  likely root cause, and a concrete remediation step.
```

**Then just ask:**

```
Load the pipeline at pipeline.yaml and run it.
```

Hermes calls `load_pipeline` → `run_validation` → returns a structured report. No flags, no re-explaining context on every run.

Full setup guide: [aegis-dq.dev/integrations/hermes](https://aegis-dq.dev/integrations/hermes) · MCP listing: [glama.ai/mcp/servers/aegis-dq/aegis-dq](https://glama.ai/mcp/servers/aegis-dq/aegis-dq)

---

## Why Aegis?

| | Aegis DQ | Great Expectations / Soda | Monte Carlo / Anomalo |
|---|---|---|---|
| Open source | ✅ Apache 2.0 | ✅ | ❌ Commercial |
| Agentic LLM diagnosis + RCA | ✅ | ❌ | ✅ Proprietary |
| SQL auto-fix proposals | ✅ | ❌ | ❌ |
| Audit trail (per-decision log) | ✅ | Partial | ✅ Proprietary |
| Pluggable LLM (Anthropic, OpenAI, Bedrock, Ollama) | ✅ | ❌ | ❌ |
| dbt integration | ✅ | ✅ | Partial |
| Portable open rule standard | ✅ | Partial | ❌ |
| ML anomaly detection | ✅ built-in | ❌ | ✅ Proprietary |

---

## Install

```bash
pip install thota-dq
```

| Extra | What it adds |
|---|---|
| `thota-dq[bigquery]` | BigQuery adapter |
| `thota-dq[databricks]` | Databricks adapter |
| `thota-dq[athena]` | AWS Athena adapter |
| `thota-dq[postgres]` | PostgreSQL / Redshift adapter |
| `thota-dq[snowflake]` | Snowflake adapter |
| `thota-dq[rest]` | REST API server (FastAPI + uvicorn) |
| `thota-dq[openai]` | OpenAI LLM provider |
| `thota-dq[airflow]` | Airflow `AegisOperator` |
| `thota-dq[mcp]` | MCP server for Hermes, Claude Desktop, and any MCP-compatible agent |
| `thota-dq[ml]` | scikit-learn anomaly detection |

---

## 5-minute quickstart

**Step 1 — Install**

```bash
pip install thota-dq
```

**Step 2 — Seed a demo database**

```python
import duckdb

con = duckdb.connect("demo.db")
con.execute("""
    CREATE TABLE orders AS
    SELECT i AS order_id, 'placed' AS status, i * 9.99 AS revenue
    FROM range(1, 10001) t(i)
""")
# introduce some bad data
con.execute("UPDATE orders SET order_id = NULL WHERE order_id % 200 = 0")
con.execute("UPDATE orders SET revenue = -5.00 WHERE order_id % 500 = 0")
con.close()
```

**Step 3 — Generate rules from your schema (no hand-writing)**

```bash
export ANTHROPIC_API_KEY=sk-ant-...

# Generate rules from table schema alone
aegis generate orders --db demo.db --output rules.yaml

# Or point it at a policy doc and get business validation rules too
aegis generate orders --db demo.db --kb docs/orders_policy.md --output rules.yaml
```

The LLM introspects your schema and generates `not_null`, `accepted_values`, `between`, and `custom_sql` rules automatically. Generated rules are stamped `status: draft` — review and promote to `active`.

**Step 4 — Run**

```bash
aegis run rules.yaml --db demo.db
```

Run without an API key (pass/fail only, no LLM diagnosis):

```bash
aegis run rules.yaml --db demo.db --no-llm
```

---

## Pipeline

Every `aegis run` passes your data through a LangGraph pipeline:

```
rules (Python / YAML)
    │
    ▼
  plan ──► parallel_table ──► reconcile ──► remediate ──► report
                 │
         ┌──────────────────┐
         │  per table:      │
         │  execute         │
         │  classify        │
         │  diagnose        │  ← concurrent across all tables
         │  rca             │
         └──────────────────┘
```

- **plan** — parse and validate rules, build an execution graph
- **parallel_table** — concurrently fans out per table: execute all rules, classify failures by severity, diagnose with LLM, and trace root causes
- **reconcile** — compare results against expected thresholds
- **remediate** — LLM proposes a targeted SQL fix for each diagnosed failure
- **report** — structured JSON + optional Slack notification

---

## Rule types (31 total)

| Category | Types |
|---|---|
| Completeness | `not_null` `not_empty_string` `null_percentage_below` |
| Uniqueness | `unique` `composite_unique` `duplicate_percentage_below` |
| Validity | `sql_expression` `between` `min_value_check` `max_value_check` `regex_match` `accepted_values` `not_accepted_values` `no_future_dates` `column_exists` |
| Referential | `foreign_key` `conditional_not_null` |
| Statistical | `mean_between` `stddev_below` `column_sum_between` |
| Timeliness | `freshness` `date_order` |
| Volume | `row_count` `row_count_between` `custom_sql` |
| Cross-table | `reconcile_row_count` `reconcile_column_sum` `reconcile_key_match` |
| ML / Anomaly | `zscore_outlier` `isolation_forest` `learned_threshold` |

Example rule:

```yaml
rules:
  - apiVersion: aegis.dev/v1
    kind: DataQualityRule
    metadata:
      id: orders_revenue_non_negative
      severity: critical
      owner: revenue-team
      tags: [revenue, validity]
    scope:
      warehouse: duckdb
      table: orders
    logic:
      type: sql_expression
      expression: "revenue >= 0"
```

---

## Generate rules with the LLM

Instead of writing rules by hand, let Aegis introspect your table schema and generate a draft rules file:

```bash
# Schema-aware structural rules (not_null, between, unique, accepted_values...)
aegis generate orders --db warehouse.duckdb --output orders_rules.yaml
```

Add a `--kb` document — any plain text or markdown file describing your business logic — and the LLM generates **business validation rules** alongside structural ones:

```bash
aegis generate orders \
  --db warehouse.duckdb \
  --kb docs/orders_policy.md \
  --output orders_rules.yaml
```

**What goes in a KB file?** Anything your team knows about the data:

```
# orders_policy.md
- status must be one of: placed, confirmed, shipped, delivered, cancelled
- amount must be greater than 0; refunds are handled in a separate table
- customer_id must reference a valid customer (no test accounts: id > 1000)
- order_date must not be in the future
- discount_pct must be between 0 and 0.5 (max 50% discount)
```

The LLM turns these into `accepted_values`, `sql_expression`, `between`, and `foreign_key` rules automatically. Generated rules are stamped `status: draft` — review, promote to `active`, and commit.

**All `aegis generate` options:**

| Flag | Default | Description |
|---|---|---|
| `--db` | — | DuckDB file for schema introspection |
| `--kb` | — | Business-context file (text/markdown) |
| `--output` | `rules.yaml` | Output YAML file |
| `--max-rules` | `20` | Cap on number of rules generated |
| `--no-verify` | `false` | Skip SQL verification of generated rules |
| `--save-versions` | `false` | Persist rules to version store |
| `--provider` | `anthropic` | LLM provider |
| `--model` | *(default)* | Override model |

---

## Warehouse adapters

| Adapter | Install | Status |
|---|---|---|
| DuckDB | built-in | ✅ GA |
| BigQuery | `aegis-dq[bigquery]` | ✅ GA |
| Databricks | `aegis-dq[databricks]` | ✅ GA |
| AWS Athena | `aegis-dq[athena]` | ✅ GA |
| Postgres / Redshift | `aegis-dq[postgres]` | ✅ GA |
| Snowflake | `aegis-dq[snowflake]` | ✅ GA |

---

## LLM providers

| Provider | Install | Default model |
|---|---|---|
| Anthropic (Claude) | built-in | `claude-haiku-4-5` |
| OpenAI | `aegis-dq[openai]` | `gpt-4o-mini` |
| Ollama (local) | `aegis-dq[ollama]` | `llama3.2` |
| AWS Bedrock | `pip install boto3` | `amazon.nova-pro-v1:0` |

Switch providers at the CLI:

```bash
aegis run rules.yaml --llm openai --llm-model gpt-4o
aegis run rules.yaml --llm ollama --llm-model llama3.2
aegis run rules.yaml --llm bedrock --llm-model amazon.nova-pro-v1:0
```

---

## Integrations

| Integration | What it does |
|---|---|
| GitHub Action | CI/CD gate — fails the job when rules fail |
| `aegis-dq[rest]` | REST API server — `aegis serve` |
| `aegis-dq[airflow]` | `AegisOperator` — drop-in Airflow task |
| `aegis-dq[mcp]` | MCP server for Hermes, Claude Desktop, Cursor, and any MCP-compatible agent |
| `aegis dbt generate` | Convert dbt `manifest.json` to Aegis rules |

---

## CLI reference

| Command | Description |
|---|---|
| `aegis init` | Generate a starter `rules.yaml` |
| `aegis validate <config>` | Check YAML syntax + schema (no warehouse needed) |
| `aegis generate <table>` | LLM-generate rules from table schema |
| `aegis run <config>` | Run validation, diagnose failures, produce a report |
| `aegis rules list` | Browse built-in rule templates |
| `aegis audit trajectory <run-id>` | Inspect the LLM decision trail for a past run |
| `aegis audit search <query>` | Full-text search across audit logs |
| `aegis dbt generate <manifest>` | Convert a dbt manifest to Aegis rules |
| `aegis mcp` | Start the MCP server for Hermes, Claude Desktop, or any MCP client |

**`aegis run` flags:**

| Flag | Default | Description |
|---|---|---|
| `--db` | `:memory:` | DuckDB file path |
| `--llm` | `anthropic` | LLM provider |
| `--llm-model` | *(provider default)* | Override model name |
| `--no-llm` | `false` | Skip LLM diagnosis entirely |
| `--output-json` | *(none)* | Write full JSON report to file |
| `--notify` | *(none)* | Slack webhook URL |
| `--notify-on` | `failures` | When to notify: `all` · `failures` · `critical` |

---

## Roadmap

| Phase | Version | Items | Status |
|---|---|---|---|
| Foundation | v0.1 | Core agent, DuckDB, CLI, audit trail | ✅ Done |
| Differentiate | v0.5 | BigQuery, Databricks, Athena, Airflow, Ollama, RCA, ShareGPT export, FTS5 search, dbt, MCP | ✅ Done |
| Quality | v0.7 | SQL verification pipeline, rule versioning, `aegis generate` (LLM + KB), GitHub Action, ML anomaly detection | ✅ Done |
| Mature | v1.0 | Postgres, REST API, parallel subagents, VS Code extension, eval suite, banking/healthcare packs | 🚧 In progress |

Full issue tracker: [github.com/thotan09/thota-dq/issues](https://github.com/thotan09/thota-dq/issues)

---

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) to get started.

Good first issues: [label:good first issue](https://github.com/thotan09/thota-dq/issues?q=label%3A%22good+first+issue%22)

## Author

**Naveen Thota** — [thotan09@gmail.com](mailto:thotan09@gmail.com)

## License

[Apache 2.0](LICENSE)
