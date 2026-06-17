"""CLI entry: python -m aegis_benchmark [options]

Examples:
  python -m aegis_benchmark                     # no-LLM baseline, all 100 tasks
  python -m aegis_benchmark --llm               # Anthropic LLM diagnosis
  python -m aegis_benchmark --category dedup    # single category
  python -m aegis_benchmark --output results/   # write JSON + HTML
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Thota DQ eval harness")
    p.add_argument("--llm", action="store_true", help="Use Anthropic LLM for diagnosis evals")
    p.add_argument("--llm-model", default=None, help="Override LLM model name")
    p.add_argument("--category", default=None,
                   choices=["imputation", "dedup", "filtering", "refinement", "integration", "classification"],
                   help="Run only tasks in this category")
    p.add_argument("--output", default=None, metavar="DIR",
                   help="Directory to write report.json and report.html (default: stdout only)")
    p.add_argument("--concurrency", type=int, default=10, help="Parallel task concurrency (default: 10)")
    return p.parse_args()


async def _main(args: argparse.Namespace) -> None:
    from aegis_benchmark.harness import run_eval
    from aegis_benchmark.report import save_html, save_json
    from aegis_benchmark.tasks import TASKS

    tasks = TASKS
    if args.category:
        tasks = [t for t in TASKS if t.category == args.category]
        if not tasks:
            print(f"No tasks found for category '{args.category}'", file=sys.stderr)
            sys.exit(1)

    llm = None
    if args.llm:
        from thota_dq.adapters.llm.anthropic import AnthropicAdapter
        llm = AnthropicAdapter(model=args.llm_model) if args.llm_model else AnthropicAdapter()

    print(f"Running {len(tasks)} tasks (LLM: {'yes' if llm else 'no'}) ...", file=sys.stderr)
    report = await run_eval(tasks=tasks, llm=llm, concurrency=args.concurrency)

    d = report.as_dict()
    print(json.dumps(d, indent=2))

    if args.output:
        out = Path(args.output)
        save_json(report, out / "report.json")
        save_html(report, out / "report.html")
        print(f"\nReport written to {out}/report.{{json,html}}", file=sys.stderr)

    ov = d["overall"]
    print(
        f"\nOverall: accuracy={ov['accuracy']:.1%}  F1={ov['f1']:.3f}  "
        f"cost=${ov['total_cost_usd']:.4f}  latency={ov['avg_latency_ms']:.0f}ms",
        file=sys.stderr,
    )


def main() -> None:
    asyncio.run(_main(_parse_args()))


if __name__ == "__main__":
    main()
