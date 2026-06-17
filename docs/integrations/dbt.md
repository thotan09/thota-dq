# dbt Integration

Aegis can read a dbt `manifest.json` and automatically generate Aegis rules for every dbt test in your project. This lets you reuse your existing dbt test definitions without rewriting them.

---

## Generate rules from a dbt manifest

```bash title="Terminal"
aegis dbt generate manifest.json
```

This writes `rules.yaml` in the current directory (use `--output` to change the path):

```bash title="Terminal"
aegis dbt generate manifest.json --output dbt_rules.yaml
```

### What gets converted

| dbt test type | Aegis rule type |
|---|---|
| `not_null` | `not_null` |
| `unique` | `unique` |
| `accepted_values` | `accepted_values` |
| `relationships` | `foreign_key` |
| `dbt_utils.expression_is_true` | `sql_expression` |
| `dbt_utils.not_empty_string` | `not_empty_string` |

Custom generic tests that do not map to a known Aegis rule type are emitted as `custom_sql` rules using the compiled SQL from the manifest.

---

## Run the generated rules

```bash title="Terminal"
aegis run dbt_rules.yaml --db my_warehouse.duckdb
```

Or point at BigQuery:

```bash title="Terminal"
aegis run dbt_rules.yaml --warehouse bigquery --project my-gcp-project --dataset my_dataset
```

---

## Keep rules in sync

Add this to your dbt project's `on-run-end` hook in `dbt_project.yml` to regenerate Aegis rules after every `dbt compile`:

```yaml title="dbt_project.yml"
on-run-end:
  - "{{ aegis_dbt_generate(results) }}"
```

Or run it in CI before your Aegis validation step:

```bash title="Terminal"
dbt compile --profiles-dir . && \
aegis dbt generate target/manifest.json --output rules.yaml && \
aegis run rules.yaml --no-llm
```
