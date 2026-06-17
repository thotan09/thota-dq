# CLI Reference

All Aegis commands, flags, and options.

---

## `aegis run`

Run data quality checks defined in a YAML rules file.

```bash title="Terminal"
aegis run rules.yaml --db warehouse.duckdb
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `config` | path | required | Path to rules YAML file |
| `--db` | text | `:memory:` | DuckDB file path |
| `--warehouse`, `-w` | text | `duckdb` | Warehouse: `duckdb` \| `postgres` |
| `--pg-dsn` | text | — | Postgres/Redshift DSN string |
| `--pg-host` | text | `localhost` | Postgres host |
| `--pg-port` | int | `5432` | Postgres port (use `5439` for Redshift) |
| `--pg-dbname` | text | `postgres` | Database name |
| `--pg-user` | text | `postgres` | Postgres user |
| `--pg-password` | text | — | Postgres password |
| `--pg-schema` | text | `public` | Default schema |
| `--no-llm` | flag | off | Skip LLM diagnosis — pure validation, $0 |
| `--llm` | text | `anthropic` | LLM provider: `anthropic` \| `openai` \| `ollama` \| `bedrock` |
| `--llm-model` | text | — | Override the default model name |
| `--ollama-host` | text | `http://localhost:11434` | Ollama base URL |
| `--output-json`, `-o` | path | — | Write JSON report to file |
| `--notify` | text | — | Slack webhook URL (or set `AEGIS_SLACK_WEBHOOK`) |
| `--notify-on` | text | `failures` | When to notify: `all` \| `failures` \| `critical` |

**Examples:**

```bash title="Terminal"
# Offline — no LLM, no API key
aegis run rules.yaml --db warehouse.duckdb --no-llm

# With Anthropic Claude
export ANTHROPIC_API_KEY=sk-ant-...
aegis run rules.yaml --db warehouse.duckdb

# With Ollama (fully local)
aegis run rules.yaml --db warehouse.duckdb --llm ollama --llm-model llama3.2

# Against Postgres
aegis run rules.yaml --warehouse postgres --pg-host localhost --pg-dbname mydb

# Write JSON report for CI
aegis run rules.yaml --db warehouse.duckdb --output report.json
```

---

## `aegis validate`

Check rule YAML syntax and schema without touching any warehouse.

```bash title="Terminal"
aegis validate rules.yaml
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `config` | path | required | Path to rules YAML file |
| `--check-sql` | flag | off | Verify SQL syntax for `sql_expression` / `custom_sql` rules |
| `--db` | text | — | DuckDB path — enables schema-aware and dry-run SQL checks |
| `--warnings` / `--no-warnings` | flag | on | Show warnings |

**Examples:**

```bash title="Terminal"
# Syntax check only (no DB needed)
aegis validate rules.yaml

# Syntax + SQL verification
aegis validate rules.yaml --check-sql

# Full validation — syntax + schema + dry-run
aegis validate rules.yaml --db warehouse.duckdb
```

---

## `aegis generate`

Introspect a table schema and generate draft rules using an LLM.

```bash title="Terminal"
aegis generate orders --db warehouse.duckdb --output rules.yaml
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `table` | text | required | Table name to generate rules for |
| `--db` | text | — | DuckDB file path for schema introspection |
| `--output`, `-o` | path | `rules.yaml` | Output YAML file |
| `--kb` | path | — | Knowledge-base file (text/markdown) with business rules |
| `--provider` | text | `anthropic` | LLM provider: `anthropic` \| `bedrock` \| `openai` \| `ollama` |
| `--model`, `-m` | text | — | LLM model override |
| `--max-rules` | int | `20` | Maximum number of rules to generate |
| `--no-verify` | flag | off | Skip SQL verification of generated rules |
| `--save-versions` | flag | off | Persist generated rules to version store |

**Examples:**

```bash title="Terminal"
# Structural rules from schema only
aegis generate orders --db warehouse.duckdb --output orders_rules.yaml

# Structural + business rules from a policy doc
aegis generate orders --db warehouse.duckdb \
  --kb docs/orders_policy.md \
  --output orders_rules.yaml

# Use Ollama for $0 generation
aegis generate orders --db warehouse.duckdb \
  --provider ollama --model llama3.2
```

Generated rules are stamped `status: draft` — review and promote to `active` before committing.

---

## `aegis audit`

Inspect the audit trail of all past runs.

### `aegis audit list-runs`

List all run IDs, newest first.

```bash title="Terminal"
aegis audit list-runs
```

### `aegis audit trajectory`

Show the full node-by-node decision trajectory for a run.

```bash title="Terminal"
aegis audit trajectory <run-id>
```

### `aegis audit search`

Full-text search across all LLM decisions.

```bash title="Terminal"
aegis audit search "null email"
aegis audit search "customer_id"
```

### `aegis audit export-dataset`

Export run trajectories as ShareGPT JSONL for fine-tuning.

```bash title="Terminal"
# Export a specific run
aegis audit export-dataset output.jsonl --run-id <run-id>

# Export all runs
aegis audit export-dataset output.jsonl
```

---

## `aegis init`

Full project scaffolding — creates `aegis.yaml` (project-wide LLM + warehouse defaults), `pipelines/<name>/pipeline.yaml`, `pipelines/<name>/rules.yaml`, `.aegis/`, and `.gitignore`.

```bash title="Terminal"
aegis init [directory] --name <pipeline-name> --warehouse <type>
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `directory` | path | `.` | Target directory to scaffold into |
| `--name`, `-n` | text | `my-pipeline` | Pipeline name — used for the `pipelines/<name>/` subdirectory |
| `--warehouse`, `-w` | text | `duckdb` | Default warehouse: `duckdb` \| `bigquery` \| `postgres` \| `athena` \| `databricks` |
| `--force`, `-f` | flag | off | Overwrite existing files |

**Examples:**

```bash title="Terminal"
# New project in current directory
aegis init my-project --name orders-dq

# New project with BigQuery defaults
aegis init my-project --name orders-dq --warehouse bigquery
```

---

## `aegis pipeline`

Run or inspect a pipeline manifest.

```bash title="Terminal"
# Run a pipeline
aegis pipeline run pipelines/orders-dq/pipeline.yaml

# Inspect without running
aegis pipeline show pipelines/orders-dq/pipeline.yaml
```

The manifest inherits `warehouse` and `llm` from the nearest `aegis.yaml`. Override only what differs. See [Pipeline Manifests →](integrations/hermes.md#pipeline-manifests-define-once-run-forever).

---

## `aegis validate` — SQL stages

| Stage | Flag | What it checks |
|---|---|---|
| Stage 1 | `--check-sql` | Syntax only via sqlglot |
| Stage 2 | `--db path` | Schema — column names exist in table |
| Stage 3 | `--db path` | Dry-run — SQL executes without error |

---

## `aegis mcp`

Start the Aegis MCP server for use with Claude Desktop.

```bash title="Terminal"
aegis mcp
```

See [MCP Server →](integrations/mcp.md) for configuration details.

---

## `aegis dbt`

dbt integration commands.

```bash title="Terminal"
# Convert dbt manifest to Aegis rules
aegis dbt generate manifest.json --output rules.yaml
```

See [dbt Integration →](integrations/dbt.md) for full usage.

---

## Environment variables

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `AEGIS_SLACK_WEBHOOK` | Slack webhook URL for notifications |
| `AWS_PROFILE` | AWS profile for Bedrock (e.g. `default`, `prod`) |
| `AWS_DEFAULT_REGION` | AWS region for Bedrock (e.g. `us-east-1`). When set, auto-selects Bedrock as the LLM provider. |
| `AEGIS_LLM_PROVIDER` | Override the LLM provider: `anthropic` \| `openai` \| `bedrock` \| `ollama` |
| `AEGIS_LLM_MODEL` | Override the model name (e.g. `claude-haiku-4-5-20251001`, `gpt-4o-mini`, `amazon.nova-pro-v1:0`) |
