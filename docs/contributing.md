# Contributing to Aegis

Thanks for your interest in contributing. Aegis is an early-stage project and every contribution matters.

## Getting started

```bash
git clone https://github.com/aegis-dq/aegis-dq
cd aegis-dq
pip install -e ".[dev]"
```

Run tests:

```bash
pytest tests/ -v
```

Run linter:

```bash
ruff check aegis tests
ruff check aegis tests --fix   # auto-fix
```

## What to work on

Check [open issues](https://github.com/aegis-dq/aegis-dq/issues) — especially those labeled [`good first issue`](https://github.com/aegis-dq/aegis-dq/issues?q=label%3A%22good+first+issue%22).

Good entry points for new contributors:

- **New warehouse adapter** — copy `aegis/adapters/warehouse/duckdb.py`, implement the same interface for Postgres, MySQL, etc.
- **New LLM adapter** — copy `aegis/adapters/llm/anthropic.py`, implement `complete()` for any OpenAI-compatible endpoint.
- **New rule type** — add to `RuleType` enum in `schema.py`, implement in `duckdb.py`, add tests.
- **Industry pack** — create a `aegis-packs/<domain>/rules/` directory with domain-specific rule templates.

## Pull request process

1. Fork the repo and create a feature branch: `feat/<short-description>`
2. Write tests for your change — all PRs must keep tests green
3. Run `ruff check aegis tests` — no lint errors
4. Open a PR referencing the issue it closes (`Closes #N`)
5. Keep PRs focused — one issue per PR

## Code style

- Python 3.11+, type hints throughout
- Ruff for formatting and linting (`line-length = 100`)
- `async/await` for all I/O — no blocking calls in the hot path
- No comments explaining *what* the code does — only *why* when non-obvious

## Community

Questions and discussion: open a [GitHub Discussion](https://github.com/aegis-dq/aegis-dq/discussions).

## Code of Conduct

Be respectful. We follow the [Contributor Covenant](https://www.contributor-covenant.org/).
