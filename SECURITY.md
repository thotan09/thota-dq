# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.5.x (latest) | ✅ |
| < 0.5 | ❌ |

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Email **security@aegis-dq.dev** with:

- A description of the vulnerability and its potential impact
- Steps to reproduce or proof-of-concept code
- The affected version(s)

You will receive an acknowledgment within **48 hours** and a resolution timeline within **7 days**. We follow responsible disclosure — we ask that you allow us to patch and release before public disclosure.

## Security considerations for the GitHub Action

- **API keys** — pass provider keys via `${{ secrets.* }}`, never hard-coded in workflow YAML
- **DuckDB files** — the action opens your database in read-only mode; it never writes to it
- **LLM data** — rule failure samples are sent to your configured LLM provider; avoid including PII in column values checked by Aegis, or use `no-llm: 'true'` for offline validation
- **Pinning versions** — for supply-chain safety, pin to a specific SHA:

```yaml
- uses: aegis-dq/aegis-dq@<COMMIT_SHA>   # pin to a specific commit
```

Use [Dependabot](https://docs.github.com/en/code-security/dependabot) to keep pins current automatically.
