# Show HN Post

**Post on:** news.ycombinator.com/submit
**Best time:** Monday–Wednesday, 9–11am ET
**Category:** Show HN

---

## Title (choose one)

**Option A (problem-first):**
> Show HN: Aegis DQ – open-source data quality that tells you *why* a check failed, not just that it did

**Option B (feature-first):**
> Show HN: Aegis DQ – agentic data quality with LLM diagnosis, root-cause analysis, and SQL auto-fix

**Option C (contrast):**
> Show HN: I built a data quality framework that uses LLMs to diagnose failures – Great Expectations tells you what failed, this tells you why

---

## Body

Every data quality tool I've used tells me *that* a check failed. None of them tell me *why*.

After a production incident where a NULL cascade took three hours to trace through five tables, I wanted a tool that could explain a failure the way a senior data engineer would: here's what broke, here's the likely cause, here's what to fix.

Aegis DQ is the result. It's an open-source Python framework that runs a 5-node LangGraph pipeline:

```
plan → parallel validation → LLM diagnose → root-cause analysis → SQL remediation
```

For each failure you get:
- **Diagnosis** — what went wrong and why, in plain English
- **Root cause** — which upstream table or process is the origin
- **Proposed SQL** — a targeted `UPDATE`/`DELETE` to fix the data, verified for syntax before you see it

It runs against DuckDB, Postgres, BigQuery, Databricks, and Athena. The LLM is pluggable — Anthropic Claude, OpenAI, Ollama (fully offline/local), or AWS Bedrock. Every decision is logged to a searchable SQLite audit trail.

New in v0.6.0: `aegis generate orders --db warehouse.duckdb --kb policy.md` introspects your table schema and calls the LLM to write draft rules. The `--kb` flag accepts any plain-text business document — it generates `accepted_values`, `regex_match`, and `sql_expression` rules from your business logic automatically.

There's also a GitHub Action for CI/CD gates, an MCP server for Claude Desktop, and an Airflow operator.

**Links:**
- GitHub: https://github.com/aegis-dq/aegis-dq
- Docs: https://aegis-dq.dev
- `pip install aegis-dq`

Happy to answer questions about the LangGraph pipeline design, the LLM prompting strategy, or the SQL verification approach.

---

## Pre-post checklist

- [ ] Star count is visible (reach out to network 24h before posting to get seed stars)
- [ ] Demo GIF is embedded in README (it is — `docs/demo.gif`)
- [ ] PyPI release is live (v0.6.0)
- [ ] aegis-dq.dev is live and loads correctly
- [ ] Respond to ALL comments within the first 2 hours — this is critical for HN ranking
- [ ] Do not post on Friday, Saturday, Sunday or US holidays

## Anticipated questions + answers

**"How is this different from Great Expectations?"**
> GE validates data and tells you pass/fail. Aegis adds an LLM layer that diagnoses *why* it failed, traces the root cause upstream, and proposes a SQL fix. GE also has no audit trail of the diagnostic reasoning.

**"Why not just prompt an LLM directly?"**
> The LangGraph pipeline is deterministic and auditable — every LLM call, cost, and decision is logged. You can replay, search, and export the audit trail. A raw LLM call gives you no traceability.

**"What does it cost to run?"**
> With `--no-llm` it's free — pure rule validation. With Anthropic Claude Haiku, the RetailCo demo (12 rules, 4 tables) costs $0.005. With Ollama it's $0 at any scale.

**"Is it production-ready?"**
> v0.6.0, 601 tests, Apache 2.0. Used in production at a retail analytics team. Not yet v1.0 — banking/healthcare packs and VS Code extension are in progress.
