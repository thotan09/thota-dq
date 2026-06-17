"""Report generator — JSON + HTML for GitHub Pages publishing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .metrics import EvalReport


def save_json(report: EvalReport, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.as_dict(), indent=2))


def save_html(report: EvalReport, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_html(report))


def _bar(value: float, max_val: float = 1.0, width: int = 200) -> str:
    pct = min(value / max_val, 1.0) * 100
    color = "#22c55e" if value >= 0.9 else "#f59e0b" if value >= 0.7 else "#ef4444"
    return (
        f'<div style="background:#e5e7eb;border-radius:4px;height:12px;width:{width}px;display:inline-block">'
        f'<div style="background:{color};width:{pct:.1f}%;height:100%;border-radius:4px"></div></div>'
        f' <span style="font-size:12px;color:#374151">{value:.1%}</span>'
    )


def _render_html(report: EvalReport) -> str:
    d = report.as_dict()
    ov = d["overall"]
    run_date = _utc_now()

    rows = ""
    for cat, cm in d["per_category"].items():
        acc_bar = _bar(cm["accuracy"])
        f1_bar = _bar(cm["f1"])
        kw_bar = _bar(cm["avg_keyword_hit_rate"])
        rows += f"""
        <tr>
          <td style="padding:8px 12px;font-weight:600">{cat}</td>
          <td style="padding:8px 12px;text-align:center">{cm['total']}</td>
          <td style="padding:8px 12px">{acc_bar}</td>
          <td style="padding:8px 12px">{f1_bar}</td>
          <td style="padding:8px 12px">{kw_bar}</td>
          <td style="padding:8px 12px;text-align:right">${cm['avg_cost_per_task_usd']:.6f}</td>
          <td style="padding:8px 12px;text-align:right">{cm['avg_latency_ms']:.0f} ms</td>
        </tr>"""

    baseline_row = ""
    if d.get("baseline_accuracy") is not None:
        b = d["baseline_accuracy"]
        baseline_row = f"""
        <tr style="border-top:2px solid #e5e7eb">
          <td style="padding:8px 12px;color:#6b7280">Baseline (no LLM)</td>
          <td colspan="6" style="padding:8px 12px">{_bar(b)} accuracy</td>
        </tr>"""

    model_str = d["model"] or "no-LLM baseline"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Thota DQ Eval Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            color: #111827; margin: 0; padding: 24px; background: #f9fafb; }}
    h1 {{ font-size: 1.5rem; margin-bottom: 4px; }}
    .meta {{ color: #6b7280; font-size: 0.875rem; margin-bottom: 24px; }}
    .summary {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 32px; }}
    .card {{ background: white; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
    .card .label {{ font-size: 0.75rem; color: #6b7280; text-transform: uppercase; letter-spacing: .05em; }}
    .card .value {{ font-size: 1.75rem; font-weight: 700; margin-top: 4px; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px;
             box-shadow: 0 1px 3px rgba(0,0,0,.1); overflow: hidden; }}
    th {{ background: #f3f4f6; padding: 10px 12px; text-align: left;
          font-size: 0.75rem; color: #6b7280; text-transform: uppercase; letter-spacing: .05em; }}
    tr:nth-child(even) {{ background: #f9fafb; }}
  </style>
</head>
<body>
  <h1>Thota DQ Eval Report</h1>
  <div class="meta">Run: {d['run_id']} &nbsp;·&nbsp; Model: {model_str} &nbsp;·&nbsp; {run_date} &nbsp;·&nbsp; {d['total_tasks']} tasks</div>

  <div class="summary">
    <div class="card">
      <div class="label">Overall Accuracy</div>
      <div class="value">{ov['accuracy']:.1%}</div>
    </div>
    <div class="card">
      <div class="label">F1 Score</div>
      <div class="value">{ov['f1']:.3f}</div>
    </div>
    <div class="card">
      <div class="label">Total Cost</div>
      <div class="value">${ov['total_cost_usd']:.4f}</div>
    </div>
    <div class="card">
      <div class="label">Avg Latency</div>
      <div class="value">{ov['avg_latency_ms']:.0f} ms</div>
    </div>
  </div>

  <table>
    <thead>
      <tr>
        <th>Category</th><th>Tasks</th><th>Accuracy</th><th>F1</th>
        <th>Keyword Hit Rate</th><th>Cost/Task</th><th>Latency</th>
      </tr>
    </thead>
    <tbody>
      {rows}
      {baseline_row}
    </tbody>
  </table>
</body>
</html>"""


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
