# Contributing to Aegis DQ

Thanks for your interest in contributing. Aegis DQ is an open-source project and welcomes pull requests, bug reports, docs improvements, and new adapters or rule types. This guide covers everything you need to go from zero to a merged PR.

---

## Quick setup

```bash
# fork the repo on GitHub, then clone your fork
git clone https://github.com/<your-username>/aegis-dq
cd aegis-dq

# install with all dev dependencies
pip install -e ".[dev]"

# verify everything passes
pytest tests/ -q
```

You should see 292 tests pass. If anything is red, open an issue before going further.

---

## Where to contribute

| Area | What's needed |
|---|---|
| New warehouse adapter | Snowflake, Postgres/Redshift (see below) |
| New rule type | `cross_table_count_match` and others (see below) |
| New LLM adapter | Bedrock, Vertex AI, Cohere |
| Documentation | Tutorials, how-to guides, docstrings |
| Bug fixes | Check the [issue tracker](https://github.com/aegis-dq/aegis-dq/issues) |

---

## How to add a new warehouse adapter

Use `aegis/adapters/athena.py` as your reference implementation.

**Step 1 — create the adapter file**

```
aegis/adapters/<name>.py
```

**Step 2 — extend `WarehouseAdapter`**

```python
from aegis.adapters.base import WarehouseAdapter

class SnowflakeAdapter(WarehouseAdapter):
    def __init__(self, **kwargs):
        # store connection params
        ...
```

**Step 3 — implement `execute_rule`**

Every adapter must implement one method:

```python
def execute_rule(self, rule: DataQualityRule) -> RuleResult:
    # build SQL from rule.logic, run it, return RuleResult
    ...
```

Translate the rule's `logic.type` to SQL using the same dispatch pattern as `DuckDBAdapter`. Mind SQL dialect differences (e.g., Snowflake uses `ILIKE`, `QUALIFY`, and backtick-free identifiers).

**Step 4 — register the adapter in the CLI**

In `aegis/cli.py`, find the `_build_warehouse_adapter` function and add an `elif` branch:

```python
elif warehouse == "snowflake":
    from aegis.adapters.snowflake import SnowflakeAdapter
    return SnowflakeAdapter(**connection_kwargs)
```

**Step 5 — write tests using `sys.modules` stubs**

Optional dependencies (like `snowflake-connector-python`) must not be installed in the test environment. Use the stub pattern:

```python
import sys
import types

# stub out the optional dep before importing your adapter
snowflake_stub = types.ModuleType("snowflake")
connector_stub = types.ModuleType("snowflake.connector")
sys.modules["snowflake"] = snowflake_stub
sys.modules["snowflake.connector"] = connector_stub

from aegis.adapters.snowflake import SnowflakeAdapter

def test_execute_rule_not_null(monkeypatch):
    adapter = SnowflakeAdapter(account="x", user="y", password="z", database="d", schema="s")
    # monkeypatch adapter._conn.execute to return a fake result
    ...
```

See `tests/test_athena_adapter.py` for a complete example.

---

## How to add a new rule type

**Step 1 — add the type to the `RuleType` enum**

In `aegis/models.py`:

```python
class RuleType(StrEnum):
    ...
    CROSS_TABLE_COUNT_MATCH = "cross_table_count_match"
```

**Step 2 — add a handler in each adapter**

In `aegis/adapters/duckdb.py` (and BigQuery, Databricks, Athena adapters), add a branch to the rule dispatch:

```python
elif rule.logic.type == RuleType.CROSS_TABLE_COUNT_MATCH:
    sql = f"""
        SELECT COUNT(*) = (SELECT COUNT(*) FROM {rule.logic.reference_table})
        FROM {rule.scope.table}
    """
    ...
```

**Step 3 — update the validator**

In `aegis/validator.py`, add any required field checks for the new type so `aegis validate` catches misconfigured rules early:

```python
if rule.logic.type == RuleType.CROSS_TABLE_COUNT_MATCH:
    if not rule.logic.reference_table:
        errors.append(f"{rule.metadata.id}: cross_table_count_match requires logic.reference_table")
```

---

## Good first issues

These are concrete, self-contained, and well-scoped for a first contribution:

1. **Add a Snowflake adapter** — copy `aegis/adapters/athena.py`, adapt the SQL dialect (use `snowflake-connector-python`), stub the dep in tests. Issue: [#snowflake](https://github.com/aegis-dq/aegis-dq/issues)

2. **Add a Postgres / Redshift adapter** — same pattern, use `psycopg2`. The SQL dialect is close to DuckDB so the translation layer is small.

3. **Add a `cross_table_count_match` rule type** — validates that two tables have the same row count. Follow the 3-step guide above.

4. **Write a tutorial blog post** — a 1000-word walkthrough using Aegis with a public dataset (NYC taxi, TPC-H, etc.). Drop it in `docs/tutorials/`.

5. **Improve error messages in the validator** — `aegis validate` currently prints terse errors. Add line numbers, suggested fixes, and links to the rule schema reference.

---

## Testing

Run the full suite:

```bash
pytest tests/ -q
```

Run a specific file:

```bash
pytest tests/test_duckdb_adapter.py -v
```

**The `sys.modules` stub pattern** is used throughout for optional dependencies. Any adapter that wraps a third-party library (BigQuery, Databricks, etc.) must be testable without that library installed. The pattern:

1. Build a `types.ModuleType` stub before the import.
2. Register it in `sys.modules`.
3. Import the adapter module.
4. Monkeypatch connection methods to return controlled data.

This keeps CI fast and dependency-free while still testing adapter logic.

---

## Code style

Aegis uses `ruff` for linting and formatting.

```bash
# lint
ruff check aegis tests

# format
ruff format aegis tests
```

Both run in CI. A PR with lint failures will not be merged. Configure your editor to run `ruff format` on save to avoid surprises.

---

## PR process

**Branch naming:**

```
feat/<short-description>       # new feature or adapter
fix/<short-description>        # bug fix
docs/<short-description>       # documentation only
chore/<short-description>      # dependency bumps, tooling
```

**Commit message style** — use a prefix that matches the branch type:

```
feat: add Snowflake warehouse adapter
fix: handle NULL values in composite_unique rule
docs: add Athena quickstart to getting-started guide
```

**Before opening a PR:**

- [ ] `pytest tests/ -q` passes locally
- [ ] `ruff check aegis tests` is clean
- [ ] New adapter or rule type has tests
- [ ] If adding a new adapter, add it to the warehouse table in `README.md`

PRs are reviewed within a few days. Small, focused PRs merge faster than large ones.

---

## License

By contributing, you agree that your contributions will be licensed under the [Apache 2.0 License](LICENSE).
