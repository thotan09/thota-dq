Output docs/demo.gif

Set Shell "bash"
Set FontSize 13
Set Width 1200
Set Height 750
Set Theme "Catppuccin Mocha"
Set Padding 20
Set PlaybackSpeed 1.5
Set TypingSpeed 40ms

# ── Clean start ────────────────────────────────────────────────────────────
Type "clear" Enter
Sleep 400ms

# ── Phase 1: no-LLM — show rule execution and structural failures ──────────
Type "# Phase 1: validation-only (no LLM cost) — rule execution across 4 tables" Sleep 30ms Enter
Sleep 700ms

Type "python demo/realworld_demo.py --no-llm" Sleep 30ms Enter
Sleep 6s

Sleep 2500ms

# ── Phase 2: full agentic run with AWS Bedrock ─────────────────────────────
Type "clear" Enter
Sleep 400ms

Type "# Phase 2: full pipeline — diagnose + RCA + remediation via AWS Bedrock Nova Pro" Sleep 30ms Enter
Sleep 700ms

Type "python demo/realworld_demo.py --aws-profile mcal-research" Sleep 30ms Enter

# Wait for: database setup + pipeline + 11x (diagnose+RCA+remediate) LLM calls (~7-9s)
Sleep 20s

# Hold on the remediation proposals at the end
Sleep 5s
