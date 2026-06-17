# MCP Server

Aegis ships a [Model Context Protocol](https://modelcontextprotocol.io) server that exposes nine tools to any MCP-compatible client. Connect Claude Desktop, Cursor, Cline, Hermes, or any other MCP client and run data quality validations conversationally.

---

## Start the server

```bash title="Terminal"
aegis mcp
```

The server uses **stdio transport** by default — it runs as a subprocess managed by your MCP client. For remote access, use SSE:

```bash title="Terminal"
aegis mcp --transport sse --port 8765
```

---

## Tools

### `load_pipeline`

Load a [`pipeline.yaml` manifest](hermes.md#pipeline-manifests-define-once-run-forever) and return its configuration and goal as context. Use this before `run_validation` to let the LLM understand what the pipeline does without you re-explaining it.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `manifest_path` | string | Path to a `pipeline.yaml` manifest file |

**Returns**: JSON object with `name`, `description`, `goal`, `rules_path`, `warehouse`, `connection_params`, `kb`, and a pre-built `run_validation_call` object ready to pass directly to `run_validation`.

**Example**

```json title="load_pipeline"
{ "manifest_path": "demo/fraud/pipeline.yaml" }
```

---

### `run_validation`

Run a rules YAML file against a warehouse. Returns a JSON report with pass/fail per rule, LLM diagnosis, root cause analysis, and remediation SQL.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `rules_path` | string | required | Path to the rules YAML file |
| `warehouse` | string | `"duckdb"` | Warehouse type: `duckdb`, `bigquery`, `athena`, `databricks`, `postgres` |
| `connection_params` | string (JSON) | `"{}"` | Warehouse connection kwargs as a JSON object. Falls back to environment variables if omitted. |
| `no_llm` | bool | `false` | Skip LLM diagnosis. Returns rule pass/fail only. |

**Examples**

=== "DuckDB"
    ```json
    {
      "rules_path": "/home/user/rules/orders.yaml",
      "warehouse": "duckdb",
      "connection_params": "{\"path\": \"/data/prod.duckdb\"}"
    }
    ```

=== "BigQuery"
    ```json
    {
      "rules_path": "/home/user/rules/orders.yaml",
      "warehouse": "bigquery",
      "connection_params": "{\"project\": \"my-project\", \"dataset\": \"analytics\"}"
    }
    ```

=== "Athena"
    ```json
    {
      "rules_path": "/home/user/rules/orders.yaml",
      "warehouse": "athena",
      "connection_params": "{\"s3_staging_dir\": \"s3://bucket/athena/\", \"region_name\": \"us-east-1\"}"
    }
    ```

=== "Databricks"
    ```json
    {
      "rules_path": "/home/user/rules/orders.yaml",
      "warehouse": "databricks",
      "connection_params": "{\"server_hostname\": \"abc.azuredatabricks.net\", \"http_path\": \"/sql/1.0/warehouses/abc\", \"access_token\": \"dapi...\"}"
    }
    ```

=== "Postgres"
    ```json
    {
      "rules_path": "/home/user/rules/orders.yaml",
      "warehouse": "postgres",
      "connection_params": "{\"dsn\": \"postgresql://user:pass@host:5432/db\"}"
    }
    ```

**Using environment variables instead**

Set warehouse env vars in your client config (see [MCP Clients](mcp-clients.md)) and omit `connection_params`. Aegis picks them up automatically:

```json title="run_validation (env vars)"
{ "rules_path": "/home/user/rules/orders.yaml", "warehouse": "bigquery" }
```

---

### `list_runs`

List recent run IDs from the audit trail, newest first.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `limit` | int | `20` | Maximum number of run IDs to return |

**Returns**: JSON array of run ID strings.

---

### `get_run_report`

Get the full report for a past validation run.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `run_id` | string | Run ID from `list_runs` |

**Returns**: JSON object with `run_id`, `summary`, `failures`, and metadata.

---

### `get_trajectory`

Get the node-by-node LLM decision log for a run — every prompt, response, cost, and latency. Useful for auditing exactly what Aegis decided and why.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `run_id` | string | Run ID from `list_runs` |

**Returns**: JSON array of decision records, one per agent node that made an LLM call.

---

### `search_decisions`

Full-text search across all LLM decisions in the audit trail.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | string | required | Search terms (e.g. `"null order_id"`, `"root cause ETL"`) |
| `run_id` | string | `null` | Restrict search to a specific run |
| `limit` | int | `20` | Maximum results |

**Returns**: JSON array of matching decision records with run ID, step, and summary.

---

### `compare_reports`

Compare two validation runs side by side. Shows regressions (rules that newly failed), fixes (rules that stopped failing), persistent failures, and summary deltas (pass rate, cost).

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `run_id_a` | string | Baseline run ID |
| `run_id_b` | string | Comparison run ID |

**Returns**: JSON with `regressions`, `fixes`, `persistent_failures`, `summary_delta` (pass rate diff, failed count diff, cost diff), and full summaries for both runs.

**Example**

```json title="compare_reports"
{ "run_id_a": "run-20260513", "run_id_b": "run-20260514" }
```

---

### `summarize_reports`

Compact summary of one or more runs — pass rate, severity breakdown, top failures, and cost per run. Useful for a quick multi-run overview without loading full reports.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `run_ids` | list[string] | One or more run IDs to summarize |

**Returns**: JSON with a `runs` array — one entry per run with `pass_rate`, `severity_breakdown`, `top_failures` (up to 5), and `cost_usd`.

**Example**

```json title="summarize_reports"
{ "run_ids": ["run-20260513", "run-20260514", "run-20260515"] }
```

---

### `check_consistency`

Check consistency between two runs. Identifies flapping rules (different pass/fail status between runs) and rule-set drift (different number of rules evaluated). Returns a `consistency_score_pct` so you can tell at a glance whether the two runs agree.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `run_id_a` | string | First run ID |
| `run_id_b` | string | Second run ID |

**Returns**: JSON with `flapping_rules`, `consistent_failures`, `consistency_score_pct`, `rule_set_changed`, and a boolean `consistent` flag.

**Example**

```json title="check_consistency"
{ "run_id_a": "run-20260513", "run_id_b": "run-20260514" }
```

---

## Example client prompts

```
Load the pipeline at demo/fraud/pipeline.yaml and run it.
```

```
Run /home/user/rules/orders.yaml against BigQuery and summarise the failures.
```

```
Show me the last 5 validation runs.
```

```
What did Aegis diagnose for run run_20260513_143022_a1b2c3?
```

```
Search the audit trail for anything about null order IDs.
```

```
Run my rules against Athena offline — no LLM, just tell me what passes and fails.
```

---

## Client setup guides

- [Hermes](hermes.md)
- [Claude Desktop, Cursor, Cline](mcp-clients.md)
