"""Eval harness — runs all 100 tasks and aggregates metrics."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from .metrics import EvalReport, TaskResult, compute_metrics
from .tasks import EvalTask, TASKS


async def _run_one(
    task: EvalTask,
    llm: Any | None,
) -> TaskResult:
    """Execute a single eval task and return its result."""
    import duckdb
    from thota_dq.adapters.warehouse.duckdb import DuckDBAdapter
    from thota_dq.rules.schema import DataQualityRule

    # Build an isolated in-memory DuckDB fixture
    adapter = DuckDBAdapter(":memory:")
    loop = asyncio.get_running_loop()

    def _setup():
        conn = adapter._get_conn()
        for sql in task.setup_sql:
            conn.execute(sql)

    await loop.run_in_executor(adapter._executor, _setup)

    rule = DataQualityRule.model_validate(task.rule)
    t0 = time.monotonic()

    try:
        result = await adapter.execute_rule(rule)
    except Exception as exc:
        return TaskResult(
            task_id=task.task_id,
            category=task.category,
            predicted_pass=False,
            expected_pass=task.ground_truth["passed"],
            diagnosis_text=None,
            keywords_found=[],
            keywords_expected=task.ground_truth.get("keywords", []),
            cost_usd=0.0,
            latency_ms=(time.monotonic() - t0) * 1000,
            error=str(exc),
        )

    predicted_pass = result.passed
    diagnosis_text: str | None = None
    cost_usd = 0.0
    keywords_found: list[str] = []
    keywords_expected: list[str] = task.ground_truth.get("keywords", [])

    # If rule failed and LLM is available, run diagnosis and check keyword coverage
    if not result.passed and llm is not None:
        from thota_dq.rules.schema import RuleFailure
        from thota_dq.core.nodes.diagnose import _diagnose_one

        failure = RuleFailure(rule=rule, result=result)
        try:
            run_id = f"eval-{task.task_id}"
            diag, in_tok, out_tok = await _diagnose_one(failure, llm, run_id)
            diagnosis_text = (
                f"{diag.get('explanation', '')} "
                f"{diag.get('likely_cause', '')} "
                f"{diag.get('suggested_action', '')}"
            )
            cost_usd = (in_tok * 0.80 + out_tok * 4.00) / 1_000_000

            diag_lower = diagnosis_text.lower()
            keywords_found = [
                kw for kw in keywords_expected
                if kw.lower() in diag_lower
            ]
        except Exception:
            pass

    latency_ms = (time.monotonic() - t0) * 1000

    return TaskResult(
        task_id=task.task_id,
        category=task.category,
        predicted_pass=predicted_pass,
        expected_pass=task.ground_truth["passed"],
        diagnosis_text=diagnosis_text,
        keywords_found=keywords_found,
        keywords_expected=keywords_expected,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
    )


async def run_eval(
    tasks: list[EvalTask] | None = None,
    llm: Any | None = None,
    run_id: str | None = None,
    concurrency: int = 10,
) -> EvalReport:
    """Run the eval suite and return a full EvalReport.

    Args:
        tasks:       Subset of tasks to run. Defaults to all 100.
        llm:         LLM adapter for diagnosis evaluation. None = no-LLM baseline.
        run_id:      Identifier for this eval run.
        concurrency: Max parallel tasks (default 10 to avoid DuckDB contention).
    """
    tasks = tasks or TASKS
    run_id = run_id or str(uuid.uuid4())
    model = getattr(llm, "_model", None) if llm else None

    semaphore = asyncio.Semaphore(concurrency)

    async def _bounded(task: EvalTask) -> TaskResult:
        async with semaphore:
            return await _run_one(task, llm)

    results = await asyncio.gather(*[_bounded(t) for t in tasks])

    report = compute_metrics(list(results), run_id=run_id, model=model)

    # Compute no-LLM baseline accuracy (pass/fail only, no diagnosis)
    # When llm is None the current run IS the baseline
    if llm is None:
        report.baseline_accuracy = report.overall.accuracy

    return report
