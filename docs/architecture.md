# Architecture

Aegis is a LangGraph-orchestrated agent that runs a deterministic 5-node pipeline. Each node is a discrete step with a defined input state and output state. Nodes that call an LLM are skippable (`--no-llm`) without affecting the others.

---

## The 5-node pipeline

```
rules.yaml
    │
    ▼
  plan ──► parallel_table ──► reconcile ──► remediate ──► report
                 │
         ┌──────────────────┐
         │  per table:      │
         │  execute         │
         │  classify        │
         │  diagnose        │  ← tables run concurrently
         │  rca             │
         └──────────────────┘
```

### 1. plan

Reads rules (YAML or Python objects), validates each against the Pydantic schema, and builds an execution plan — an ordered list grouped by table. Rules with shared scope are batched; the output is a `{table → [rules]}` mapping consumed by the next node.

### 2. parallel_table

The core fan-out node. Groups rules by target table and launches a full mini-pipeline for **each table concurrently** using `asyncio.gather`:

```
per table (concurrent):
  execute  → run all rules for this table against the warehouse adapter
  classify → heuristic severity triage (escalates if >5% rows fail or blast radius is high)
  diagnose → LLM writes plain-English explanation + likely cause + recommended action
  rca      → LLM traces root cause through the OpenLineage lineage graph
```

Results from all tables are merged back into a single state before the next node. With N tables, the wall-clock time is bounded by the slowest table, not the sum of all tables.

### 3. reconcile

Handles **cross-table reconciliation rules** (`reconcile_row_count`, `reconcile_column_sum`, `reconcile_key_match`). Runs source and target queries in parallel and computes the delta against a configurable tolerance. Non-reconciliation rules pass through unchanged.

### 4. remediate

For each diagnosed failure, calls the LLM with the rule type, diagnosis, and RCA context to generate a **targeted SQL fix**. Returns a `RemediationProposal` with `proposed_sql`, `confidence` (high / medium / low), and a `caveat` explaining what to verify before running. Skipped when `remediation.proposal_strategy = "none"` or when `--no-llm` is set.

### 5. report

Assembles the final report: run metadata, severity breakdown, per-rule results with LLM diagnosis, RCA, and remediation SQL, total LLM cost, and run duration. Writes to stdout via Rich, to `--output-json` if specified, and to the SQLite audit trail (`~/.aegis/history.db`).

---

## Adapters

Aegis uses a two-tier adapter pattern — one tier for LLMs, one for warehouses. Adapters are thin protocol implementations; the pipeline nodes never call a warehouse or LLM directly.

```
LLM adapters
─────────────────────────────────────────────────
  Anthropic   claude-haiku-4-5 (default)
              claude-sonnet-4-5
              claude-opus-4-5

  OpenAI      gpt-4o-mini (default)
              gpt-4o

  Ollama      any locally-pulled model
              (llama3.2, mistral, phi3, etc.)
              runs on http://localhost:11434

  AWS Bedrock amazon.nova-pro-v1:0 (default, no approval needed)
              any Converse API-compatible model
              uses ~/.aws/credentials profile

Warehouse adapters
─────────────────────────────────────────────────
  DuckDB      local file or in-memory
  BigQuery    project + dataset via service account
  Databricks  cluster or SQL warehouse via token
  Athena      S3 + Glue catalog via IAM role
```

Implementing a new warehouse adapter requires a single Python class with three methods: `connect()`, `execute_scalar(sql)`, and `execute_sample(sql, limit)`.

---

## Audit trail

Every LLM call made during a run is recorded in `~/.aegis/history.db` (SQLite). The schema has two tables:

- **runs** — one row per `aegis run` invocation: `run_id`, `started_at`, `rules_file`, `warehouse`, `llm`, `total_cost_usd`, `summary_json`
- **decisions** — one row per LLM call: `run_id`, `node` (diagnose / rca / classify / remediate), `rule_id`, `prompt`, `response`, `model`, `input_tokens`, `output_tokens`, `cost_usd`, `latency_ms`

The `decisions` table has an FTS5 virtual table on `(prompt, response)`, enabling full-text search:

```bash title="Terminal"
aegis audit search "null order_id"
aegis audit search "currency conversion"
```

### ShareGPT export for fine-tuning

```bash title="Terminal"
aegis audit export-dataset output.jsonl
```

Each entry in the JSONL file is a ShareGPT-format conversation: the system prompt, the user turn (rule context + failed rows), and the assistant turn (the actual LLM diagnosis). This format is directly compatible with fine-tuning pipelines for most open-source models.

---

## Integrations

### Airflow

The `AegisOperator` wraps an `aegis run` invocation as a native Airflow task. See [Airflow Integration](integrations/airflow.md).

### dbt

`aegis dbt generate manifest.json` reads a dbt `manifest.json` and emits Aegis rules for every `not_null`, `unique`, `accepted_values`, and `relationships` test found in the manifest. See [dbt Integration](integrations/dbt.md).

### MCP server

Aegis ships a Model Context Protocol server that exposes nine tools to Claude Desktop (or any MCP-compatible client):

| Tool | Description |
|---|---|
| `load_pipeline` | Load a `pipeline.yaml` manifest — returns connection params and goal as context |
| `run_validation` | Run a rules file against a warehouse and return the report |
| `list_runs` | List recent runs from the audit trail |
| `get_run_report` | Get the full report for a past run by ID |
| `get_trajectory` | Return the full node-by-node decision log for a run |
| `search_decisions` | Full-text search across all past LLM diagnoses |
| `compare_reports` | Diff two runs — regressions, fixes, pass-rate delta |
| `summarize_reports` | Compact summary of one or more runs |
| `check_consistency` | Detect flapping rules and rule-set drift between two runs |

See [MCP Server](integrations/mcp.md) for the Claude Desktop configuration.
