"""Tests for the Slack output adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from thota_dq.adapters.output.slack import (
    NotifyOn,
    _build_payload,
    _should_notify,
    post_to_slack,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _report(failed: int = 0, severities: list[str] | None = None) -> dict:
    failures = []
    for i, sev in enumerate(severities or []):
        failures.append({
            "rule_id": f"rule_{i}",
            "table": "orders",
            "severity": sev,
            "rows_failed": 1,
            "rows_checked": 100,
        })
    return {
        "run_id": "abc123-run",
        "timestamp": "2026-05-12T00:00:00+00:00",
        "triggered_by": "cli",
        "summary": {
            "total_rules": max(4, failed),
            "passed": max(4, failed) - failed,
            "failed": failed,
            "pass_rate": 100.0 if failed == 0 else round((max(4, failed) - failed) / max(4, failed) * 100, 1),
        },
        "failures": failures,
        "cost_usd": 0.0,
        "tokens_total": 0,
    }


# ── _should_notify ─────────────────────────────────────────────────────────────

def test_notify_all_fires_on_pass():
    assert _should_notify(_report(failed=0), NotifyOn.ALL) is True


def test_notify_all_fires_on_failure():
    assert _should_notify(_report(failed=1, severities=["high"]), NotifyOn.ALL) is True


def test_notify_failures_silent_on_pass():
    assert _should_notify(_report(failed=0), NotifyOn.FAILURES) is False


def test_notify_failures_fires_on_any_failure():
    assert _should_notify(_report(failed=1, severities=["low"]), NotifyOn.FAILURES) is True


def test_notify_critical_silent_on_high_only():
    assert _should_notify(_report(failed=1, severities=["high"]), NotifyOn.CRITICAL) is False


def test_notify_critical_fires_on_critical():
    assert _should_notify(_report(failed=1, severities=["critical"]), NotifyOn.CRITICAL) is True


def test_notify_critical_fires_on_mixed():
    r = _report(failed=2, severities=["high", "critical"])
    assert _should_notify(r, NotifyOn.CRITICAL) is True


# ── _build_payload ─────────────────────────────────────────────────────────────

def test_payload_has_blocks():
    payload = _build_payload(_report(failed=0))
    assert "blocks" in payload
    assert len(payload["blocks"]) >= 2


def test_payload_header_shows_passed_on_clean_run():
    payload = _build_payload(_report(failed=0))
    header = payload["blocks"][0]
    assert header["type"] == "header"
    assert "passed" in header["text"]["text"].lower() or "✅" in header["text"]["text"] or "check_mark" in header["text"]["text"]


def test_payload_header_shows_failed_count():
    payload = _build_payload(_report(failed=2, severities=["high", "critical"]))
    header_text = payload["blocks"][0]["text"]["text"]
    assert "2" in header_text or "failed" in header_text.lower()


def test_payload_includes_failure_details():
    r = _report(failed=1, severities=["critical"])
    r["failures"][0]["diagnosis"] = {
        "explanation": "Revenue column has negative values.",
        "likely_cause": "Refund logic error.",
        "suggested_action": "Check ETL job.",
    }
    payload = _build_payload(r)
    full_text = str(payload)
    assert "rule_0" in full_text
    assert "Revenue column" in full_text


def test_payload_caps_failures_at_10():
    severities = ["high"] * 15
    r = _report(failed=15, severities=severities)
    payload = _build_payload(r)
    full_text = str(payload)
    assert "5 more" in full_text


def test_payload_run_id_truncated():
    payload = _build_payload(_report())
    full_text = str(payload)
    assert "abc123" in full_text  # first 8 chars of "abc123-run"


def test_payload_shows_cost_when_nonzero():
    r = _report()
    r["cost_usd"] = 0.001234
    payload = _build_payload(r)
    assert "0.001234" in str(payload)


def test_payload_no_cost_block_when_zero():
    payload = _build_payload(_report())
    # cost block only appears when cost > 0
    text = str(payload)
    assert "LLM cost" not in text


# ── post_to_slack ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_returns_false_without_webhook():
    sent = await post_to_slack(_report(failed=1, severities=["critical"]), webhook_url=None)
    assert sent is False


@pytest.mark.asyncio
async def test_post_returns_false_when_threshold_not_met():
    # notify_on=failures but no failures
    sent = await post_to_slack(
        _report(failed=0),
        webhook_url="https://hooks.slack.com/fake",
        notify_on=NotifyOn.FAILURES,
    )
    assert sent is False


@pytest.mark.asyncio
async def test_post_sends_request_on_failure(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    mock_post = AsyncMock(return_value=mock_resp)

    with patch("thota_dq.adapters.output.slack.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        sent = await post_to_slack(
            _report(failed=1, severities=["high"]),
            webhook_url="https://hooks.slack.com/fake",
            notify_on=NotifyOn.FAILURES,
        )

    assert sent is True
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[0][0] == "https://hooks.slack.com/fake"
    payload = call_kwargs[1]["json"]
    assert "blocks" in payload


@pytest.mark.asyncio
async def test_post_reads_webhook_from_env(monkeypatch):
    monkeypatch.setenv("AEGIS_SLACK_WEBHOOK", "https://hooks.slack.com/env-url")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("thota_dq.adapters.output.slack.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        sent = await post_to_slack(
            _report(failed=1, severities=["high"]),
            webhook_url=None,   # no explicit URL — should fall back to env
            notify_on=NotifyOn.ALL,
        )

    assert sent is True


@pytest.mark.asyncio
async def test_post_notify_on_all_sends_on_clean_run():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("thota_dq.adapters.output.slack.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        sent = await post_to_slack(
            _report(failed=0),
            webhook_url="https://hooks.slack.com/fake",
            notify_on=NotifyOn.ALL,
        )

    assert sent is True
