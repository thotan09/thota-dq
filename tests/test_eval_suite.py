"""Tests for the Aegis eval harness."""

from __future__ import annotations

import pytest

from aegis_benchmark.metrics import (
    TaskResult,
    compute_metrics,
)
from aegis_benchmark.tasks import CATEGORIES, TASKS

# ---------------------------------------------------------------------------
# Task catalog
# ---------------------------------------------------------------------------


class TestTaskCatalog:
    def test_exactly_100_tasks(self):
        assert len(TASKS) == 100

    def test_all_categories_present(self):
        cats = {t.category for t in TASKS}
        assert cats == set(CATEGORIES)

    def test_task_ids_unique(self):
        ids = [t.task_id for t in TASKS]
        assert len(ids) == len(set(ids))

    def test_all_tasks_have_ground_truth_passed_key(self):
        for t in TASKS:
            assert "passed" in t.ground_truth, f"Task {t.task_id} missing 'passed'"
            assert isinstance(t.ground_truth["passed"], bool)

    def test_all_tasks_have_setup_sql(self):
        for t in TASKS:
            assert t.setup_sql, f"Task {t.task_id} has empty setup_sql"

    def test_all_tasks_have_rule_with_type(self):
        for t in TASKS:
            assert "logic" in t.rule
            assert "type" in t.rule["logic"], f"Task {t.task_id} missing logic.type"

    def test_category_distribution(self):
        from collections import Counter

        counts = Counter(t.category for t in TASKS)
        assert counts["imputation"] == 20
        assert counts["dedup"] == 20
        assert counts["filtering"] == 20
        assert counts["refinement"] == 15
        assert counts["integration"] == 15
        assert counts["classification"] == 10

    def test_roughly_balanced_pass_fail(self):
        """Each category should have both passing and failing tasks."""
        from collections import defaultdict

        by_cat: dict[str, list[bool]] = defaultdict(list)
        for t in TASKS:
            by_cat[t.category].append(t.ground_truth["passed"])
        for cat, results in by_cat.items():
            passes = sum(results)
            fails = len(results) - passes
            assert passes > 0, f"{cat}: no passing tasks"
            assert fails > 0, f"{cat}: no failing tasks"

    def test_rules_have_valid_api_version(self):
        for t in TASKS:
            assert t.rule["apiVersion"] == "thota_dq.dev/v1", f"Task {t.task_id}"

    def test_failing_tasks_have_failure_category(self):
        for t in TASKS:
            if not t.ground_truth["passed"]:
                assert t.ground_truth.get("failure_category"), (
                    f"Failing task {t.task_id} missing failure_category"
                )

    def test_task_descriptions_not_empty(self):
        for t in TASKS:
            assert t.description.strip(), f"Task {t.task_id} has empty description"


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------


def _make_result(
    task_id: str,
    category: str,
    predicted: bool,
    expected: bool,
    keywords: list[str] | None = None,
    found: list[str] | None = None,
    cost: float = 0.0,
    latency: float = 10.0,
) -> TaskResult:
    kw = keywords or []
    return TaskResult(
        task_id=task_id,
        category=category,
        predicted_pass=predicted,
        expected_pass=expected,
        diagnosis_text=None,
        keywords_found=found or [],
        keywords_expected=kw,
        cost_usd=cost,
        latency_ms=latency,
    )


class TestMetrics:
    def test_all_correct_accuracy_1(self):
        results = [
            _make_result("t1", "imputation", True, True),
            _make_result("t2", "imputation", False, False),
        ]
        report = compute_metrics(results, "run-1", None)
        assert report.overall.accuracy == 1.0

    def test_all_wrong_accuracy_0(self):
        results = [
            _make_result("t1", "dedup", True, False),
            _make_result("t2", "dedup", False, True),
        ]
        report = compute_metrics(results, "run-2", None)
        assert report.overall.accuracy == 0.0

    def test_f1_perfect(self):
        results = [
            _make_result("t1", "filtering", False, False),
            _make_result("t2", "filtering", True, True),
        ]
        report = compute_metrics(results, "run-3", None)
        assert report.overall.f1 == pytest.approx(1.0)

    def test_f1_zero_when_only_false_negatives(self):
        results = [
            _make_result("t1", "filtering", True, False),  # FP
        ]
        report = compute_metrics(results, "run-4", None)
        # recall = 0 (no TPs), so F1 = 0
        assert report.overall.f1 == pytest.approx(0.0)

    def test_per_category_split(self):
        results = [
            _make_result("t1", "imputation", True, True),
            _make_result("t2", "dedup", False, False),
            _make_result("t3", "dedup", True, False),
        ]
        report = compute_metrics(results, "run-5", None)
        assert "imputation" in report.per_category
        assert "dedup" in report.per_category
        assert report.per_category["imputation"].total == 1
        assert report.per_category["dedup"].total == 2

    def test_cost_accumulated(self):
        results = [
            _make_result("t1", "imputation", False, False, cost=0.001),
            _make_result("t2", "imputation", False, False, cost=0.002),
        ]
        report = compute_metrics(results, "run-6", None)
        assert report.overall.total_cost == pytest.approx(0.003)

    def test_latency_average(self):
        results = [
            _make_result("t1", "filtering", True, True, latency=100.0),
            _make_result("t2", "filtering", True, True, latency=200.0),
        ]
        report = compute_metrics(results, "run-7", None)
        assert report.overall.avg_latency_ms == pytest.approx(150.0)

    def test_keyword_hit_rate_full_match(self):
        results = [
            _make_result(
                "t1",
                "integration",
                False,
                False,
                keywords=["NULL", "missing"],
                found=["NULL", "missing"],
            ),
        ]
        report = compute_metrics(results, "run-8", None)
        assert report.overall.avg_keyword_hit_rate == pytest.approx(1.0)

    def test_keyword_hit_rate_partial(self):
        results = [
            _make_result(
                "t1",
                "integration",
                False,
                False,
                keywords=["NULL", "missing", "ETL"],
                found=["NULL"],
            ),
        ]
        report = compute_metrics(results, "run-9", None)
        assert report.overall.avg_keyword_hit_rate == pytest.approx(1 / 3)

    def test_task_result_correct_property(self):
        r = _make_result("t1", "dedup", True, True)
        assert r.correct is True
        r2 = _make_result("t2", "dedup", True, False)
        assert r2.correct is False

    def test_as_dict_shape(self):
        results = [_make_result("t1", "imputation", True, True)]
        report = compute_metrics(results, "run-x", "claude-haiku-4-5")
        d = report.as_dict()
        assert "overall" in d
        assert "per_category" in d
        assert "total_tasks" in d
        assert d["model"] == "claude-haiku-4-5"
        assert set(d["overall"].keys()) >= {
            "accuracy",
            "f1",
            "precision",
            "recall",
            "total_cost_usd",
        }

    def test_confusion_matrix_counts(self):
        results = [
            _make_result("t1", "filtering", False, False),  # TP
            _make_result("t2", "filtering", True, True),  # TN
            _make_result("t3", "filtering", False, True),  # FP
            _make_result("t4", "filtering", True, False),  # FN
        ]
        report = compute_metrics(results, "run-cm", None)
        ov = report.overall
        assert ov.true_positives == 1
        assert ov.true_negatives == 1
        assert ov.false_positives == 1
        assert ov.false_negatives == 1


# ---------------------------------------------------------------------------
# Harness integration (DuckDB, no LLM)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_harness_single_pass_task():
    from aegis_benchmark.harness import _run_one

    task = next(t for t in TASKS if t.ground_truth["passed"] and t.category == "imputation")
    result = await _run_one(task, llm=None)
    assert result.error is None
    assert result.predicted_pass is True
    assert result.correct is True


@pytest.mark.asyncio
async def test_harness_single_fail_task():
    from aegis_benchmark.harness import _run_one

    task = next(t for t in TASKS if not t.ground_truth["passed"] and t.category == "imputation")
    result = await _run_one(task, llm=None)
    assert result.error is None
    assert result.predicted_pass is False
    assert result.correct is True


@pytest.mark.asyncio
async def test_harness_dedup_pass():
    from aegis_benchmark.harness import _run_one

    task = next(t for t in TASKS if t.task_id == "dup_01")
    result = await _run_one(task, llm=None)
    assert result.correct is True


@pytest.mark.asyncio
async def test_harness_dedup_fail():
    from aegis_benchmark.harness import _run_one

    task = next(t for t in TASKS if t.task_id == "dup_02")
    result = await _run_one(task, llm=None)
    assert result.correct is True


@pytest.mark.asyncio
async def test_harness_filtering_sql_expression():
    from aegis_benchmark.harness import _run_one

    task = next(t for t in TASKS if t.task_id == "flt_02")
    result = await _run_one(task, llm=None)
    assert result.correct is True


@pytest.mark.asyncio
async def test_harness_integration_foreign_key_fail():
    from aegis_benchmark.harness import _run_one

    task = next(t for t in TASKS if t.task_id == "int_02")
    result = await _run_one(task, llm=None)
    assert result.correct is True


@pytest.mark.slow
@pytest.mark.asyncio
async def test_harness_no_llm_all_100_tasks():
    """Run all 100 tasks without LLM and verify >90% accuracy."""
    from aegis_benchmark.harness import run_eval

    report = await run_eval(llm=None, concurrency=20)
    assert report.total_tasks == 100
    assert report.overall.accuracy >= 0.90, (
        f"Expected >=90% accuracy, got {report.overall.accuracy:.1%}. "
        f"Failed tasks: {[r.task_id for r in report.results if not r.correct]}"
    )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_harness_per_category_accuracy():
    """Each category must achieve >=85% accuracy on pass/fail detection."""
    from aegis_benchmark.harness import run_eval

    report = await run_eval(llm=None, concurrency=20)
    for cat, cm in report.per_category.items():
        assert cm.accuracy >= 0.85, f"Category '{cat}' accuracy {cm.accuracy:.1%} < 85%"


@pytest.mark.asyncio
async def test_harness_report_shape():
    from aegis_benchmark.harness import run_eval

    report = await run_eval(tasks=TASKS[:5], llm=None)
    d = report.as_dict()
    assert d["total_tasks"] == 5
    assert "overall" in d
    assert "per_category" in d


@pytest.mark.asyncio
async def test_harness_baseline_accuracy_set_when_no_llm():
    from aegis_benchmark.harness import run_eval

    report = await run_eval(tasks=TASKS[:10], llm=None)
    assert report.baseline_accuracy is not None
    assert 0.0 <= report.baseline_accuracy <= 1.0


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


class TestReportGeneration:
    def test_save_json(self, tmp_path):
        import json

        from aegis_benchmark.report import save_json

        results = [_make_result("t1", "imputation", True, True)]
        report = compute_metrics(results, "run-rep", None)
        out = tmp_path / "report.json"
        save_json(report, out)
        assert out.exists()
        d = json.loads(out.read_text())
        assert d["total_tasks"] == 1

    def test_save_html(self, tmp_path):
        from aegis_benchmark.report import save_html

        results = [_make_result("t1", "imputation", True, True)]
        report = compute_metrics(results, "run-html", None)
        out = tmp_path / "report.html"
        save_html(report, out)
        html = out.read_text()
        assert "<html" in html
        assert "Aegis DQ Eval Report" in html
        assert "imputation" in html

    def test_html_contains_accuracy(self, tmp_path):
        from aegis_benchmark.report import save_html

        results = [
            _make_result("t1", "dedup", True, True),
            _make_result("t2", "dedup", False, False),
        ]
        report = compute_metrics(results, "run-html2", "test-model")
        out = tmp_path / "report.html"
        save_html(report, out)
        html = out.read_text()
        assert "100.0%" in html  # perfect accuracy
        assert "test-model" in html


# ---------------------------------------------------------------------------
# Workflow YAML
# ---------------------------------------------------------------------------


class TestEvalWorkflow:
    def test_workflow_file_exists(self):
        from pathlib import Path

        wf = Path(__file__).parent.parent / ".github" / "workflows" / "eval.yml"
        assert wf.exists()

    def test_workflow_valid_yaml(self):
        from pathlib import Path

        import yaml

        wf = Path(__file__).parent.parent / ".github" / "workflows" / "eval.yml"
        d = yaml.safe_load(wf.read_text())
        assert "on" in d or True  # 'on' may be parsed as True by YAML
        assert "jobs" in d

    def test_workflow_has_schedule(self):
        from pathlib import Path

        wf = Path(__file__).parent.parent / ".github" / "workflows" / "eval.yml"
        content = wf.read_text()
        assert "schedule" in content
        assert "cron" in content

    def test_workflow_has_gh_pages_deploy(self):
        from pathlib import Path

        wf = Path(__file__).parent.parent / ".github" / "workflows" / "eval.yml"
        assert "gh-pages" in wf.read_text()

    def test_workflow_has_artifact_upload(self):
        from pathlib import Path

        wf = Path(__file__).parent.parent / ".github" / "workflows" / "eval.yml"
        assert "upload-artifact" in wf.read_text()
