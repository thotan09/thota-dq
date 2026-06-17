"""Tests for the per-model pricing registry."""

from __future__ import annotations

from thota_dq.adapters.llm.pricing import cost_usd


def test_exact_model_match():
    # claude-haiku-4-5: $0.80/M input, $4.00/M output
    cost = cost_usd("claude-haiku-4-5", 1_000_000, 0)
    assert abs(cost - 0.80) < 1e-9
    cost = cost_usd("claude-haiku-4-5", 0, 1_000_000)
    assert abs(cost - 4.00) < 1e-9


def test_prefix_match_with_date_suffix():
    # claude-haiku-4-5-20251001 should match prefix "claude-haiku-4-5"
    cost = cost_usd("claude-haiku-4-5-20251001", 1_000_000, 0)
    assert abs(cost - 0.80) < 1e-9


def test_prefix_match_sonnet():
    cost = cost_usd("claude-sonnet-4-6-20260101", 1_000_000, 1_000_000)
    expected = 3.00 + 15.00
    assert abs(cost - expected) < 1e-6


def test_prefix_match_opus():
    cost = cost_usd("claude-opus-4-7-latest", 1_000_000, 0)
    assert abs(cost - 15.00) < 1e-9


def test_openai_gpt4o_mini():
    cost = cost_usd("gpt-4o-mini", 1_000_000, 1_000_000)
    expected = 0.15 + 0.60
    assert abs(cost - expected) < 1e-9


def test_nova_pro():
    cost = cost_usd("amazon.nova-pro", 1_000_000, 0)
    assert abs(cost - 0.80) < 1e-9


def test_ollama_free():
    assert cost_usd("llama3", 1_000_000, 1_000_000) == 0.0
    assert cost_usd("mistral-7b", 500_000, 300_000) == 0.0


def test_none_model_fallback():
    # None → fallback Haiku pricing
    cost = cost_usd(None, 1_000_000, 0)
    assert abs(cost - 0.80) < 1e-9


def test_unknown_model_fallback():
    cost = cost_usd("some-unknown-model-v99", 1_000_000, 0)
    assert abs(cost - 0.80) < 1e-9


def test_zero_tokens():
    assert cost_usd("claude-haiku-4-5", 0, 0) == 0.0


def test_case_insensitive():
    cost_lower = cost_usd("claude-haiku-4-5", 100_000, 50_000)
    cost_upper = cost_usd("Claude-Haiku-4-5", 100_000, 50_000)
    assert abs(cost_lower - cost_upper) < 1e-12


def test_longest_prefix_wins():
    # "us.anthropic.claude-sonnet-4" is a longer prefix than "claude-sonnet-4" would be
    # Both should resolve correctly to sonnet pricing
    cost = cost_usd("us.anthropic.claude-sonnet-4-20260101", 1_000_000, 0)
    assert abs(cost - 3.00) < 1e-9
