"""Tests for ShareGPT trajectory export and fine-tuning dataset assembly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thota_dq.audit.logger import log_decision
from thota_dq.audit.trajectory import (
    _decision_to_turns,
    _is_quality_sample,
    export_dataset,
    export_json,
    export_sharegpt,
    list_run_ids,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_run(run_id: str, db_path: Path, steps: list[dict]) -> None:
    for s in steps:
        await log_decision(
            run_id=run_id,
            step=s["step"],
            input_summary=s.get("input", "some input"),
            output_summary=s.get("output", "some output"),
            model=s.get("model"),
            input_tokens=s.get("in_tok", 10),
            output_tokens=s.get("out_tok", 20),
            cost_usd=s.get("cost", 0.0001),
            duration_ms=s.get("ms", 50.0),
            db_path=db_path,
        )


# ---------------------------------------------------------------------------
# _decision_to_turns
# ---------------------------------------------------------------------------

def test_decision_to_turns_llm_step():
    d = {
        "step": "diagnose",
        "model": "claude-haiku-4-5",
        "input_summary": "Rule failed with 5 nulls",
        "output_summary": "EXPLANATION: Nulls in order_id\nLIKELY_CAUSE: ETL bug\nSUGGESTED_ACTION: Rerun",
    }
    turns = _decision_to_turns(d)
    assert turns is not None
    assert len(turns) == 3
    assert turns[0]["from"] == "system"
    assert turns[1]["from"] == "human"
    assert turns[1]["value"] == "Rule failed with 5 nulls"
    assert turns[2]["from"] == "gpt"


def test_decision_to_turns_non_llm_step():
    d = {"step": "execute", "model": None, "input_summary": "x", "output_summary": "y"}
    assert _decision_to_turns(d) is None


def test_decision_to_turns_classify_uses_correct_system():
    d = {"step": "classify", "model": "gpt-4o-mini", "input_summary": "x", "output_summary": "critical"}
    turns = _decision_to_turns(d)
    assert "severity" in turns[0]["value"].lower()


def test_decision_to_turns_rca_uses_correct_system():
    d = {"step": "rca", "model": "claude-haiku-4-5", "input_summary": "x", "output_summary": "ROOT_CAUSE: y"}
    turns = _decision_to_turns(d)
    assert "root cause" in turns[0]["value"].lower()


def test_decision_to_turns_unknown_step_uses_default_system():
    d = {"step": "custom_step", "model": "gpt-4", "input_summary": "x", "output_summary": "y"}
    turns = _decision_to_turns(d)
    assert turns[0]["from"] == "system"
    assert len(turns[0]["value"]) > 0


# ---------------------------------------------------------------------------
# _is_quality_sample
# ---------------------------------------------------------------------------

def _sample(llm_decisions: int, gpt_values: list[str]) -> dict:
    conversations = []
    for v in gpt_values:
        conversations += [
            {"from": "human", "value": "question"},
            {"from": "gpt", "value": v},
        ]
    return {
        "conversations": conversations,
        "metadata": {"llm_decisions": llm_decisions},
    }


def test_quality_filter_passes_good_sample():
    s = _sample(2, ["EXPLANATION: x\nLIKELY_CAUSE: y\nSUGGESTED_ACTION: z"] * 2)
    assert _is_quality_sample(s, min_llm_turns=1)


def test_quality_filter_rejects_too_few_turns():
    s = _sample(0, [])
    assert not _is_quality_sample(s, min_llm_turns=1)


def test_quality_filter_rejects_short_gpt_output():
    s = _sample(1, ["ok"])  # too short
    assert not _is_quality_sample(s, min_llm_turns=1)


def test_quality_filter_passes_exactly_min_turns():
    s = _sample(1, ["EXPLANATION: this is a proper response"])
    assert _is_quality_sample(s, min_llm_turns=1)


# ---------------------------------------------------------------------------
# export_json
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_json_empty(tmp_path):
    db = tmp_path / "test.db"
    result = await export_json("nonexistent-run", db_path=db)
    assert result == []


@pytest.mark.asyncio
async def test_export_json_returns_decisions(tmp_path):
    db = tmp_path / "test.db"
    await _seed_run("run1", db, [
        {"step": "diagnose", "model": "haiku", "input": "inp", "output": "out"},
    ])
    result = await export_json("run1", db_path=db)
    assert len(result) == 1
    assert result[0]["step"] == "diagnose"


# ---------------------------------------------------------------------------
# export_sharegpt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_sharegpt_structure(tmp_path):
    db = tmp_path / "test.db"
    await _seed_run("run1", db, [
        {"step": "execute", "model": None},
        {"step": "diagnose", "model": "haiku", "input": "rule failed", "output": "EXPLANATION: x\nLIKELY_CAUSE: y\nSUGGESTED_ACTION: z"},
        {"step": "rca", "model": "haiku", "input": "lineage context", "output": "ROOT_CAUSE: a\nORIGIN: b\nPROPAGATION: c\nFIX: d"},
    ])
    sample = await export_sharegpt("run1", db_path=db)

    assert sample["id"] == "run1"
    assert "conversations" in sample
    assert sample["metadata"]["llm_decisions"] == 2
    assert sample["metadata"]["total_decisions"] == 3

    # Two LLM steps → 6 turns (system+human+gpt × 2)
    assert len(sample["conversations"]) == 6
    froms = [t["from"] for t in sample["conversations"]]
    assert froms == ["system", "human", "gpt", "system", "human", "gpt"]


@pytest.mark.asyncio
async def test_export_sharegpt_no_llm_steps(tmp_path):
    db = tmp_path / "test.db"
    await _seed_run("run1", db, [
        {"step": "execute", "model": None},
        {"step": "report", "model": None},
    ])
    sample = await export_sharegpt("run1", db_path=db)
    assert sample["conversations"] == []
    assert sample["metadata"]["llm_decisions"] == 0


@pytest.mark.asyncio
async def test_export_sharegpt_metadata_costs(tmp_path):
    db = tmp_path / "test.db"
    await _seed_run("run1", db, [
        {"step": "diagnose", "model": "haiku", "cost": 0.0005, "in_tok": 100, "out_tok": 50},
    ])
    sample = await export_sharegpt("run1", db_path=db)
    assert sample["metadata"]["total_cost_usd"] == pytest.approx(0.0005, abs=1e-7)
    assert sample["metadata"]["total_tokens"] == 150


# ---------------------------------------------------------------------------
# list_run_ids
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_run_ids_empty(tmp_path):
    db = tmp_path / "test.db"
    result = await list_run_ids(db_path=db)
    assert result == []


@pytest.mark.asyncio
async def test_list_run_ids_multiple(tmp_path):
    db = tmp_path / "test.db"
    await _seed_run("run-a", db, [{"step": "diagnose", "model": "haiku"}])
    await _seed_run("run-b", db, [{"step": "diagnose", "model": "haiku"}])
    result = await list_run_ids(db_path=db)
    assert set(result) == {"run-a", "run-b"}


# ---------------------------------------------------------------------------
# export_dataset
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_dataset_jsonl(tmp_path):
    db = tmp_path / "test.db"
    await _seed_run("run1", db, [
        {"step": "diagnose", "model": "haiku", "output": "EXPLANATION: long enough output here for quality filter"},
    ])
    out = tmp_path / "dataset.jsonl"
    stats = await export_dataset(["run1"], out, db_path=db, fmt="jsonl")

    assert stats["exported"] == 1
    assert stats["skipped"] == 0
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 1
    sample = json.loads(lines[0])
    assert sample["id"] == "run1"


@pytest.mark.asyncio
async def test_export_dataset_json_array(tmp_path):
    db = tmp_path / "test.db"
    await _seed_run("run1", db, [
        {"step": "diagnose", "model": "haiku", "output": "EXPLANATION: good output for the test case here"},
    ])
    out = tmp_path / "dataset.json"
    stats = await export_dataset(["run1"], out, db_path=db, fmt="json")

    data = json.loads(out.read_text())
    assert isinstance(data, list)
    assert len(data) == 1
    assert stats["format"] == "json"


@pytest.mark.asyncio
async def test_export_dataset_quality_filter(tmp_path):
    db = tmp_path / "test.db"
    # run1: has LLM steps with good output → passes
    await _seed_run("run1", db, [
        {"step": "diagnose", "model": "haiku", "output": "EXPLANATION: proper long explanation here"},
    ])
    # run2: no LLM steps → skipped by quality filter
    await _seed_run("run2", db, [
        {"step": "execute", "model": None},
    ])
    out = tmp_path / "dataset.jsonl"
    stats = await export_dataset(["run1", "run2"], out, db_path=db, min_llm_turns=1)

    assert stats["exported"] == 1
    assert stats["skipped"] == 1


@pytest.mark.asyncio
async def test_export_dataset_no_filter(tmp_path):
    db = tmp_path / "test.db"
    await _seed_run("run1", db, [{"step": "execute", "model": None}])
    out = tmp_path / "dataset.jsonl"
    stats = await export_dataset(["run1"], out, db_path=db, filter_quality=False)
    assert stats["exported"] == 1
    assert stats["skipped"] == 0


@pytest.mark.asyncio
async def test_export_dataset_creates_parent_dirs(tmp_path):
    db = tmp_path / "test.db"
    await _seed_run("run1", db, [
        {"step": "diagnose", "model": "haiku", "output": "EXPLANATION: sufficient output for quality test"},
    ])
    out = tmp_path / "nested" / "deep" / "dataset.jsonl"
    await export_dataset(["run1"], out, db_path=db)
    assert out.exists()


@pytest.mark.asyncio
async def test_export_dataset_stats_token_count(tmp_path):
    db = tmp_path / "test.db"
    await _seed_run("run1", db, [
        {"step": "diagnose", "model": "haiku", "in_tok": 200, "out_tok": 80,
         "output": "EXPLANATION: good detailed output for quality filtering here"},
    ])
    out = tmp_path / "dataset.jsonl"
    stats = await export_dataset(["run1"], out, db_path=db)
    assert stats["total_tokens"] == 280
