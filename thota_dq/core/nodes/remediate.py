"""Remediation proposal node — LLM generates SQL fix proposals for each failure."""
from __future__ import annotations

import asyncio
import time

from ...adapters.llm.base import LLMAdapter
from ...audit.logger import log_decision
from ..state import AegisState, RemediationProposal

SYSTEM_PROMPT = """You are a senior data engineer. Given a data quality failure and its diagnosis, \
generate a SQL statement to remediate the issue.

Rules:
- Write safe, targeted SQL (prefer UPDATE/DELETE with WHERE clauses, never DROP)
- If the fix is unclear or risky, set CONFIDENCE to low and explain in CAVEAT
- SQL should work on standard SQL warehouses (DuckDB, Postgres, BigQuery, Snowflake)

Output in this EXACT format (no extra text):
SQL: <the complete SQL statement>
CONFIDENCE: <high|medium|low>
CAVEAT: <one sentence about what to verify before running>"""


def _build_user_prompt(
    failure_id: str,
    table: str,
    rule_type: str,
    diagnosis: dict,
    rca: dict | None,
) -> str:
    lines = [
        f"Table: {table}",
        f"Rule type: {rule_type}",
        f"Failure ID: {failure_id}",
        f"Explanation: {diagnosis.get('explanation', 'N/A')}",
        f"Likely cause: {diagnosis.get('likely_cause', 'N/A')}",
        f"Suggested action: {diagnosis.get('suggested_action', 'N/A')}",
    ]
    if rca:
        lines += [
            f"Root cause: {rca.get('root_cause', 'N/A')}",
            f"Origin: {rca.get('origin', 'N/A')}",
            f"Fix suggestion: {rca.get('fix', 'N/A')}",
        ]
    return "\n".join(lines)


def _parse_response(text: str) -> tuple[str, str, str]:
    """Parse LLM response into (sql, confidence, caveat). Returns defaults on parse failure."""
    import re
    sql = confidence = caveat = ""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("SQL:"):
            inline = line[4:].strip()
            if inline.startswith("```"):
                # Multi-line fenced block: collect until closing ```
                i += 1
                sql_lines = []
                while i < len(lines) and not lines[i].startswith("```"):
                    sql_lines.append(lines[i])
                    i += 1
                sql = " ".join(sql_lines).strip()
            elif inline:
                sql = inline
            else:
                # SQL might be on next line(s), grab until CONFIDENCE
                i += 1
                sql_lines = []
                while i < len(lines) and not lines[i].startswith(("CONFIDENCE:", "CAVEAT:", "```")):
                    cleaned = lines[i].strip().strip("`")
                    if cleaned:
                        sql_lines.append(cleaned)
                    i += 1
                sql = " ".join(sql_lines).strip()
                continue
        elif line.startswith("CONFIDENCE:"):
            confidence = line[11:].strip().lower()
        elif line.startswith("CAVEAT:"):
            caveat = line[7:].strip()
        i += 1
    # Strip any residual markdown fences
    sql = re.sub(r"^```\w*\s*", "", sql).rstrip("`").strip()
    if confidence not in ("high", "medium", "low"):
        confidence = "low"
    if not sql:
        sql = "-- Could not generate SQL for this failure"
    if not caveat:
        caveat = "Review carefully before executing."
    return sql, confidence, caveat


def _is_placeholder(sql: str) -> bool:
    return not sql or sql.startswith("--")


async def _verify_and_fix_sql(sql: str, table: str, llm: LLMAdapter) -> tuple[str, int]:
    """Run syntax check; auto-correct via LLM if it fails.

    Returns (final_sql, fixes_applied).  Only syntax is checked here —
    schema and dry-run require a warehouse connection not available in
    this node.
    """
    from ...rules.sql_verify import verify_and_fix

    result = await verify_and_fix(
        sql=sql,
        mode="statement",
        table=table,
        llm=llm,
        conn=None,
        schema=None,
        max_retries=2,
    )
    return result.sql, result.fixes_applied


async def _remediate_one(
    failure_id: str,
    table: str,
    rule_type: str,
    diagnosis: dict,
    rca: dict | None,
    llm: LLMAdapter,
    run_id: str,
) -> RemediationProposal:
    start = time.monotonic()
    user = _build_user_prompt(failure_id, table, rule_type, diagnosis, rca)
    try:
        text, in_tok, out_tok = await llm.complete(SYSTEM_PROMPT, user, max_tokens=512)
    except Exception as e:
        text = f"SQL: -- LLM error: {e}\nCONFIDENCE: low\nCAVEAT: LLM call failed."
        in_tok = out_tok = 0
    sql, confidence, caveat = _parse_response(text)

    # Stage 1 + LLM self-correction: verify SQL syntax and auto-fix if possible
    fixes = 0
    if not _is_placeholder(sql):
        sql, fixes = await _verify_and_fix_sql(sql, table, llm)

    duration = (time.monotonic() - start) * 1000
    cost = (in_tok * 0.00000025) + (out_tok * 0.00000125)
    fix_note = f" (auto-fixed in {fixes} attempt{'s' if fixes != 1 else ''})" if fixes > 0 else ""
    await log_decision(
        run_id=run_id,
        step="remediate",
        input_summary=f"{failure_id} ({table}): {diagnosis.get('likely_cause', '')[:100]}",
        output_summary=f"SQL={sql[:80]} CONFIDENCE={confidence}{fix_note}",
        model=getattr(llm, "_model", None),
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
        duration_ms=duration,
    )
    return RemediationProposal(
        failure_id=failure_id,
        table=table,
        rule_type=rule_type,
        proposed_sql=sql,
        confidence=confidence,
        caveat=caveat,
    )


async def remediate_node(state: AegisState, llm: LLMAdapter | None) -> AegisState:
    """Generate SQL remediation proposals for diagnosed failures."""
    if not llm:
        state["remediation_proposals"] = []
        return state

    diag_map = {d["failure_id"]: d for d in state.get("diagnoses", [])}
    rca_map = {r["failure_id"]: r for r in state.get("rca_results", [])}

    tasks = []
    for f in state["failures"]:
        rid = f.rule.metadata.id
        # Only propose remediation if strategy is not "none"
        strategy = f.rule.remediation.proposal_strategy
        if strategy == "none":
            continue
        if rid not in diag_map:
            continue  # no diagnosis yet — skip
        tasks.append(_remediate_one(
            failure_id=rid,
            table=f.rule.spec_scope.table,
            rule_type=f.rule.spec_logic.type.value,
            diagnosis=diag_map[rid],
            rca=rca_map.get(rid),
            llm=llm,
            run_id=state["run_id"],
        ))

    proposals: list[RemediationProposal] = list(await asyncio.gather(*tasks)) if tasks else []
    state["remediation_proposals"] = proposals
    return state
