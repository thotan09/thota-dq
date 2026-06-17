# Audit Trail

Every Aegis run writes a complete decision log to a local SQLite database at `~/.aegis/history.db`.

---

## What gets logged

For every run, Aegis logs:

| Field | Description |
|---|---|
| `run_id` | Unique run identifier |
| `node` | Pipeline node (`plan`, `classify`, `diagnose`, `rca`, `remediate`) |
| `rule_id` | Which rule triggered this entry |
| `prompt` | Exact prompt sent to the LLM |
| `response` | Exact LLM response |
| `model` | Model used (e.g. `claude-haiku-4-5`) |
| `input_tokens` | Prompt token count |
| `output_tokens` | Completion token count |
| `cost_usd` | Cost of this call in USD |
| `latency_ms` | Response time in milliseconds |
| `timestamp` | When the call was made |

---

## CLI commands

```bash title="Terminal"
# List all runs, newest first
aegis audit list-runs

# Full node-by-node trajectory for a run
aegis audit trajectory run_20260511_143022_a1b2c3

# Full-text search across all LLM decisions
aegis audit search "null order_id"
aegis audit search "customer deleted"

# Export as ShareGPT JSONL for fine-tuning
aegis audit export-dataset output.jsonl
aegis audit export-dataset output.jsonl --run-id run_20260511_143022_a1b2c3
```

---

## Fine-tuning export

`aegis audit export-dataset` produces ShareGPT-format JSONL — one conversation turn per line:

- **User message**: the rule context (rule definition, failing rows, schema)
- **Assistant message**: the LLM diagnosis

Use this to fine-tune a smaller model on your own data quality patterns.

---

## Why this matters

- **Reproducibility** — replay any diagnosis with the exact same prompt
- **Cost tracking** — see total spend per run across all LLM calls
- **Compliance** — regulated industries can audit every AI decision
- **Debugging** — if a diagnosis is wrong, inspect the exact prompt that produced it
