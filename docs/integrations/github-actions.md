# GitHub Actions Integration

Block PRs when data quality rules fail — before bad data reaches production.

---

## Quick start

```yaml title=".github/workflows/data-quality.yml"
# .github/workflows/data-quality.yml
name: Data Quality Gate

on: [push, pull_request]

jobs:
  aegis:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run Aegis DQ
        uses: aegis-dq/aegis-dq@v0.7.0
        with:
          rules: rules.yaml
          db: warehouse.duckdb
          fail-on: failures
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

---

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `rules` | ✅ | — | Path to rules YAML file |
| `db` | — | `:memory:` | DuckDB file path |
| `fail-on` | — | `failures` | When to fail: `failures` \| `critical` \| `never` |
| `no-llm` | — | `false` | Skip LLM diagnosis |

---

## Outputs

| Output | Description |
|---|---|
| `rules-checked` | Total number of rules run |
| `passed` | Number of rules that passed |
| `failed` | Number of rules that failed |
| `pass-rate` | Pass rate as a percentage string |

```yaml title=".github/workflows/data-quality.yml"
- name: Run Aegis DQ
  id: aegis
  uses: aegis-dq/aegis-dq@v0.7.0
  with:
    rules: rules.yaml
    db: warehouse.duckdb

- name: Print results
  run: |
    echo "Rules checked: ${{ steps.aegis.outputs.rules-checked }}"
    echo "Pass rate: ${{ steps.aegis.outputs.pass-rate }}"
```

---

## Run without LLM (free)

```yaml title=".github/workflows/data-quality.yml"
- name: Run Aegis DQ (no LLM)
  uses: aegis-dq/aegis-dq@v0.7.0
  with:
    rules: rules.yaml
    db: warehouse.duckdb
    no-llm: true
```

No API key needed. Pure validation — catches rule failures at zero cost.

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | All rules passed |
| `1` | One or more rules failed |
| `2` | Configuration or connection error |
