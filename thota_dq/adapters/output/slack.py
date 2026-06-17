"""Slack output adapter — posts validation results via incoming webhook."""

from __future__ import annotations

import os
from enum import StrEnum

import httpx


class NotifyOn(StrEnum):
    ALL = "all"          # post on every run
    FAILURES = "failures"  # post only when any rule fails (default)
    CRITICAL = "critical"  # post only when a CRITICAL rule fails


_SEVERITY_EMOJI = {
    "critical": ":red_circle:",
    "high": ":large_orange_circle:",
    "medium": ":large_yellow_circle:",
    "low": ":white_circle:",
    "info": ":information_source:",
}


def _should_notify(report: dict, notify_on: NotifyOn) -> bool:
    if notify_on == NotifyOn.ALL:
        return True
    failures = report.get("failures", [])
    if notify_on == NotifyOn.FAILURES:
        return len(failures) > 0
    # CRITICAL only
    return any(f.get("severity") == "critical" for f in failures)


def _build_payload(report: dict) -> dict:
    """Build a Slack Block Kit payload from a validation report."""
    s = report["summary"]
    run_id = report["run_id"][:8]
    pass_rate = s["pass_rate"]
    passed = s["passed"]
    total = s["total_rules"]
    failed = s["failed"]
    triggered_by = report.get("triggered_by", "unknown")

    status_emoji = ":white_check_mark:" if failed == 0 else ":x:"
    status_text = "All checks passed" if failed == 0 else f"{failed} check(s) failed"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{status_emoji} Thota DQ — {status_text}",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Rules checked:*\n{total}"},
                {"type": "mrkdwn", "text": f"*Pass rate:*\n{pass_rate}%"},
                {"type": "mrkdwn", "text": f"*Passed:*\n{passed}"},
                {"type": "mrkdwn", "text": f"*Failed:*\n{failed}"},
                {"type": "mrkdwn", "text": f"*Triggered by:*\n{triggered_by}"},
                {"type": "mrkdwn", "text": f"*Run ID:*\n`{run_id}…`"},
            ],
        },
    ]

    failures = report.get("failures", [])
    if failures:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Failures:*"},
        })
        # Show up to 10 failures — Slack has a 50-block limit
        for f in failures[:10]:
            sev = f.get("severity", "medium")
            emoji = _SEVERITY_EMOJI.get(sev, ":white_circle:")
            rule_id = f["rule_id"]
            table = f.get("table", "unknown")
            rows_failed = f.get("rows_failed", 0)
            rows_checked = f.get("rows_checked", 0)

            text = f"{emoji} *{rule_id}* ({sev}) — `{table}`\n_{rows_failed} / {rows_checked} rows failed_"

            diag = f.get("diagnosis")
            if diag:
                text += f"\n> {diag.get('explanation', '')}"

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
            })

        if len(failures) > 10:
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"…and {len(failures) - 10} more failure(s) — see full report.",
                }],
            })

    cost = report.get("cost_usd", 0)
    if cost > 0:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"LLM cost: ${cost:.6f}"}],
        })

    return {"blocks": blocks}


async def post_to_slack(
    report: dict,
    webhook_url: str | None = None,
    notify_on: NotifyOn = NotifyOn.FAILURES,
    timeout: float = 10.0,
) -> bool:
    """
    Post a validation report to Slack via incoming webhook.

    Args:
        report:      The report dict produced by the report_node.
        webhook_url: Slack incoming webhook URL. Falls back to
                     AEGIS_SLACK_WEBHOOK env var if not provided.
        notify_on:   When to fire — all|failures|critical (default: failures).
        timeout:     HTTP timeout in seconds.

    Returns:
        True if the message was sent, False if skipped (notify_on threshold
        not met) or if no webhook URL is configured.
    """
    url = webhook_url or os.environ.get("AEGIS_SLACK_WEBHOOK", "")
    if not url:
        return False

    if not _should_notify(report, notify_on):
        return False

    payload = _build_payload(report)

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()

    return True
