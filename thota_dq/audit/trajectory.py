"""Trajectory export — converts run decisions to portable fine-tuning formats.

ShareGPT schema (industry standard for SFT datasets):
  {
    "id": "<run_id>",
    "conversations": [
      {"from": "system",  "value": "<system prompt>"},
      {"from": "human",   "value": "<user turn>"},
      {"from": "gpt",     "value": "<assistant turn>"},
      ...
    ],
    "metadata": { ... }
  }

Each Aegis run produces one ShareGPT sample per LLM step (classify, diagnose,
rca). The system prompt establishes the agent role; human turn = what the agent
observed; gpt turn = what the LLM returned.

Batch export assembles multiple run samples into a JSONL file ready for
fine-tuning with tools like LLaMA-Factory, Axolotl, or OpenAI fine-tuning API.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..memory.store import DB_PATH, _connect
from .logger import get_decisions

# System prompts per step — mirrors the prompts used at inference time
_SYSTEM_PROMPTS: dict[str, str] = {
    "classify": (
        "You are a senior data quality engineer performing severity triage. "
        "Given a rule failure, decide if its severity should be escalated based on "
        "the blast radius (how many rows failed vs total rows checked). "
        "Respond with ONLY one word: the final severity level. "
        "Valid values: critical, high, medium, low, info"
    ),
    "diagnose": (
        "You are a senior data engineer performing data quality diagnosis. "
        "Given a failed data quality rule, explain: "
        "1. What the failure means in plain English "
        "2. The most likely root cause "
        "3. A concrete next step to investigate or fix it. "
        "Be concise (3-5 sentences total). Output in this exact format:\n"
        "EXPLANATION: <one sentence>\n"
        "LIKELY_CAUSE: <one sentence>\n"
        "SUGGESTED_ACTION: <one sentence>"
    ),
    "rca": (
        "You are a senior data platform engineer performing root cause analysis (RCA) "
        "on a data quality failure. You have access to lineage information showing which "
        "upstream tables and pipelines feed the failing table. "
        "Output in this exact format:\n"
        "ROOT_CAUSE: <one sentence — the underlying cause>\n"
        "ORIGIN: <upstream table or job name>\n"
        "PROPAGATION: <one sentence — how the issue flowed downstream>\n"
        "FIX: <one concrete action>"
    ),
}

_DEFAULT_SYSTEM = (
    "You are an agentic data quality assistant built on the Aegis framework. "
    "Your role is to validate data, diagnose failures, and identify root causes."
)


def _step_system_prompt(step: str) -> str:
    return _SYSTEM_PROMPTS.get(step, _DEFAULT_SYSTEM)


async def export_json(run_id: str, db_path: Path = DB_PATH) -> list[dict]:
    """Return raw decisions list for a run as JSON-serialisable dicts."""
    return await get_decisions(run_id, db_path)


def _decision_to_turns(decision: dict) -> list[dict] | None:
    """Convert one decision row to a (system, human, gpt) turn triple.

    Returns None for non-LLM steps (no model field).
    """
    if not decision.get("model"):
        return None
    step = decision.get("step", "unknown")
    return [
        {"from": "system", "value": _step_system_prompt(step)},
        {"from": "human", "value": decision["input_summary"]},
        {"from": "gpt", "value": decision["output_summary"]},
    ]


async def export_sharegpt(run_id: str, db_path: Path = DB_PATH) -> dict:
    """Export a single run as one ShareGPT conversation.

    The conversation is a flat sequence of (system, human, gpt) triples,
    one per LLM step. Non-LLM steps are omitted from the conversation but
    counted in metadata.
    """
    decisions = await get_decisions(run_id, db_path)
    conversations: list[dict] = []
    llm_steps: list[str] = []

    for d in decisions:
        turns = _decision_to_turns(d)
        if turns:
            conversations.extend(turns)
            llm_steps.append(d.get("step", "unknown"))

    total_cost = sum(d.get("cost_usd", 0.0) for d in decisions)
    total_tokens = sum(d.get("input_tokens", 0) + d.get("output_tokens", 0) for d in decisions)

    return {
        "id": run_id,
        "conversations": conversations,
        "metadata": {
            "source": "thota-dq",
            "total_decisions": len(decisions),
            "llm_decisions": len(llm_steps),
            "llm_steps": llm_steps,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 6),
        },
    }


def _is_quality_sample(sample: dict, min_llm_turns: int) -> bool:
    """Return True if a sample meets minimum quality criteria."""
    if sample["metadata"]["llm_decisions"] < min_llm_turns:
        return False
    for turn in sample["conversations"]:
        if turn["from"] == "gpt" and len(turn["value"].strip()) < 10:
            return False
    return True


async def export_dataset(
    run_ids: list[str],
    output_path: Path | str,
    *,
    db_path: Path = DB_PATH,
    min_llm_turns: int = 1,
    filter_quality: bool = True,
    fmt: str = "jsonl",
) -> dict:
    """Export multiple runs into a fine-tuning dataset file.

    Args:
        run_ids: List of run IDs to include.
        output_path: Path to write the output file (.jsonl or .json).
        db_path: SQLite audit database path.
        min_llm_turns: Minimum number of LLM steps a run must have to be included.
        filter_quality: Drop samples with very short LLM outputs (likely errors).
        fmt: "jsonl" (one JSON object per line) or "json" (array).

    Returns:
        Dict with export statistics.
    """
    samples = []
    skipped = 0

    for run_id in run_ids:
        sample = await export_sharegpt(run_id, db_path)
        if filter_quality and not _is_quality_sample(sample, min_llm_turns):
            skipped += 1
            continue
        samples.append(sample)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "jsonl":
        output_path.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in samples) + "\n")
    else:
        output_path.write_text(json.dumps(samples, indent=2, ensure_ascii=False))

    return {
        "total_runs": len(run_ids),
        "exported": len(samples),
        "skipped": skipped,
        "output_path": str(output_path),
        "format": fmt,
        "total_turns": sum(len(s["conversations"]) for s in samples),
        "total_tokens": sum(s["metadata"]["total_tokens"] for s in samples),
    }


async def list_run_ids(db_path: Path = DB_PATH) -> list[str]:
    """Return all distinct run IDs in the audit database, newest first."""
    if not db_path.exists():
        return []
    async with _connect(db_path) as db:
        cursor = await db.execute(
            "SELECT run_id FROM decisions GROUP BY run_id ORDER BY MAX(id) DESC"
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]
