"""Metrics computation for the Aegis eval harness."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskResult:
    task_id: str
    category: str
    predicted_pass: bool
    expected_pass: bool
    diagnosis_text: str | None
    keywords_found: list[str]
    keywords_expected: list[str]
    cost_usd: float
    latency_ms: float
    error: str | None = None

    @property
    def correct(self) -> bool:
        return self.predicted_pass == self.expected_pass

    @property
    def keyword_hit_rate(self) -> float:
        if not self.keywords_expected:
            return 1.0
        return len(self.keywords_found) / len(self.keywords_expected)


@dataclass
class CategoryMetrics:
    category: str
    total: int = 0
    correct: int = 0
    true_positives: int = 0   # predicted fail, actually fail
    false_positives: int = 0  # predicted fail, actually pass
    false_negatives: int = 0  # predicted pass, actually fail
    true_negatives: int = 0   # predicted pass, actually pass
    total_cost: float = 0.0
    total_latency_ms: float = 0.0
    keyword_hit_rates: list[float] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def avg_cost_per_task(self) -> float:
        return self.total_cost / self.total if self.total else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.total if self.total else 0.0

    @property
    def avg_keyword_hit_rate(self) -> float:
        return sum(self.keyword_hit_rates) / len(self.keyword_hit_rates) if self.keyword_hit_rates else 0.0


@dataclass
class EvalReport:
    run_id: str
    model: str | None
    total_tasks: int
    results: list[TaskResult]
    per_category: dict[str, CategoryMetrics]
    overall: CategoryMetrics
    baseline_accuracy: float | None = None  # accuracy without LLM

    def as_dict(self) -> dict[str, Any]:
        cat_dicts = {}
        for cat, cm in self.per_category.items():
            cat_dicts[cat] = {
                "total": cm.total,
                "accuracy": round(cm.accuracy, 4),
                "precision": round(cm.precision, 4),
                "recall": round(cm.recall, 4),
                "f1": round(cm.f1, 4),
                "avg_cost_per_task_usd": round(cm.avg_cost_per_task, 6),
                "avg_latency_ms": round(cm.avg_latency_ms, 1),
                "avg_keyword_hit_rate": round(cm.avg_keyword_hit_rate, 4),
            }
        return {
            "run_id": self.run_id,
            "model": self.model,
            "total_tasks": self.total_tasks,
            "overall": {
                "accuracy": round(self.overall.accuracy, 4),
                "precision": round(self.overall.precision, 4),
                "recall": round(self.overall.recall, 4),
                "f1": round(self.overall.f1, 4),
                "total_cost_usd": round(self.overall.total_cost, 6),
                "avg_cost_per_task_usd": round(self.overall.avg_cost_per_task, 6),
                "avg_latency_ms": round(self.overall.avg_latency_ms, 1),
                "avg_keyword_hit_rate": round(self.overall.avg_keyword_hit_rate, 4),
            },
            "per_category": cat_dicts,
            "baseline_accuracy": self.baseline_accuracy,
        }


def compute_metrics(results: list[TaskResult], run_id: str, model: str | None) -> EvalReport:
    """Aggregate TaskResults into an EvalReport with per-category and overall metrics."""
    per_category: dict[str, CategoryMetrics] = {}
    overall = CategoryMetrics(category="overall")

    for r in results:
        cm = per_category.setdefault(r.category, CategoryMetrics(category=r.category))

        for metric in (cm, overall):
            metric.total += 1
            if r.correct:
                metric.correct += 1
            metric.total_cost += r.cost_usd
            metric.total_latency_ms += r.latency_ms
            if r.keywords_expected:
                metric.keyword_hit_rates.append(r.keyword_hit_rate)

            predicted_fail = not r.predicted_pass
            actual_fail = not r.expected_pass

            if predicted_fail and actual_fail:
                metric.true_positives += 1
            elif predicted_fail and not actual_fail:
                metric.false_positives += 1
            elif not predicted_fail and actual_fail:
                metric.false_negatives += 1
            else:
                metric.true_negatives += 1

    return EvalReport(
        run_id=run_id,
        model=model,
        total_tasks=len(results),
        results=results,
        per_category=per_category,
        overall=overall,
    )
