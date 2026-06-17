"""Structural tests for action.yml — validates the GitHub Action definition."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ACTION_PATH = Path(__file__).parent.parent / "action.yml"

REQUIRED_INPUTS = {
    "rules-file",
    "db",
    "warehouse",
    "pg-dsn",
    "no-llm",
    "llm",
    "llm-model",
    "fail-on-failure",
    "version",
    "anthropic-api-key",
    "openai-api-key",
}

REQUIRED_OUTPUTS = {
    "rules-checked",
    "passed",
    "failed",
    "pass-rate",
    "report-json",
}


@pytest.fixture(scope="module")
def action() -> dict:
    return yaml.safe_load(ACTION_PATH.read_text())


def test_action_file_exists():
    assert ACTION_PATH.exists(), "action.yml not found in repo root"


def test_action_has_name(action):
    assert "name" in action
    assert action["name"]


def test_action_uses_composite_runner(action):
    assert action["runs"]["using"] == "composite"


def test_required_inputs_present(action):
    defined = set(action.get("inputs", {}).keys())
    missing = REQUIRED_INPUTS - defined
    assert not missing, f"Missing inputs: {missing}"


def test_required_outputs_present(action):
    defined = set(action.get("outputs", {}).keys())
    missing = REQUIRED_OUTPUTS - defined
    assert not missing, f"Missing outputs: {missing}"


def test_all_inputs_have_descriptions(action):
    for name, cfg in action.get("inputs", {}).items():
        assert cfg.get("description"), f"Input '{name}' has no description"


def test_all_outputs_have_descriptions(action):
    for name, cfg in action.get("outputs", {}).items():
        assert cfg.get("description"), f"Output '{name}' has no description"


def test_default_warehouse_is_duckdb(action):
    assert action["inputs"]["warehouse"]["default"] == "duckdb"


def test_default_fail_on_failure_is_true(action):
    assert action["inputs"]["fail-on-failure"]["default"] == "true"


def test_default_no_llm_is_false(action):
    assert action["inputs"]["no-llm"]["default"] == "false"


def test_default_llm_is_anthropic(action):
    assert action["inputs"]["llm"]["default"] == "anthropic"


def test_composite_steps_include_setup_python(action):
    step_names = [s.get("name", "") for s in action["runs"]["steps"]]
    assert any("Set up Python" in n for n in step_names)


def test_composite_steps_include_install(action):
    step_names = [s.get("name", "") for s in action["runs"]["steps"]]
    assert any("Install" in n for n in step_names)


def test_composite_steps_include_run(action):
    step_names = [s.get("name", "") for s in action["runs"]["steps"]]
    assert any("Run thota-dq" in n or "run" in n.lower() for n in step_names)


def test_composite_steps_include_parse(action):
    step_names = [s.get("name", "") for s in action["runs"]["steps"]]
    assert any("Parse" in n or "parse" in n.lower() for n in step_names)


def test_run_step_passes_anthropic_key_as_env(action):
    steps = action["runs"]["steps"]
    run_step = next((s for s in steps if s.get("id") == "run"), None)
    assert run_step is not None, "Step with id='run' not found"
    env = run_step.get("env", {})
    assert "ANTHROPIC_API_KEY" in env


def test_run_step_passes_openai_key_as_env(action):
    steps = action["runs"]["steps"]
    run_step = next((s for s in steps if s.get("id") == "run"), None)
    assert run_step is not None
    env = run_step.get("env", {})
    assert "OPENAI_API_KEY" in env


def test_output_values_reference_parse_step(action):
    outputs = action.get("outputs", {})
    for name, cfg in outputs.items():
        if name != "report-json":
            assert "steps.parse.outputs" in cfg.get("value", ""), (
                f"Output '{name}' should reference steps.parse.outputs"
            )


def test_report_json_output_references_run_step(action):
    value = action["outputs"]["report-json"]["value"]
    assert "steps.run.outputs" in value


def test_parse_step_runs_on_always(action):
    steps = action["runs"]["steps"]
    parse_step = next((s for s in steps if s.get("id") == "parse"), None)
    assert parse_step is not None, "Step with id='parse' not found"
    assert parse_step.get("if") == "always()"


def test_branding_present(action):
    assert "branding" in action
    assert action["branding"].get("icon")
    assert action["branding"].get("color")
