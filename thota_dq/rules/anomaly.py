"""Statistical and ML-based anomaly detection helpers for Aegis rule types."""
from __future__ import annotations

import math
from typing import Any


def zscore_outlier_sql(table: str, col: str, threshold: float) -> tuple[str, str]:
    """Return (count_sql, sample_sql) for rows whose |z-score| > threshold."""
    inner = (
        f"SELECT *, "
        f"({col} - AVG({col}) OVER ()) / NULLIF(STDDEV_POP({col}) OVER (), 0) AS _zscore "
        f"FROM {table} WHERE {col} IS NOT NULL"
    )
    count_sql = f"SELECT COUNT(*) FROM ({inner}) _t WHERE ABS(_zscore) > {threshold}"
    sample_sql = f"SELECT * FROM ({inner}) _t WHERE ABS(_zscore) > {threshold} LIMIT 5"
    return count_sql, sample_sql


def isolation_forest_detect(
    values: list[float],
    contamination: float = 0.1,
) -> list[bool]:
    """Return a boolean mask — True means the row is an anomaly.

    Requires scikit-learn: pip install 'thota-dq[ml]'
    """
    try:
        import numpy as np
        from sklearn.ensemble import IsolationForest
    except ImportError as exc:
        raise RuntimeError(
            "scikit-learn and numpy are required for isolation_forest rules. "
            "Install them with: pip install 'thota-dq[ml]'"
        ) from exc

    n = len(values)
    if n < 10:
        return [False] * n

    arr = np.array(values, dtype=float).reshape(-1, 1)
    clf = IsolationForest(contamination=contamination, random_state=42)
    labels = clf.fit_predict(arr)  # -1 = anomaly, 1 = normal
    return [int(lbl) == -1 for lbl in labels]


def check_learned_threshold(
    current_mean: float,
    history_means: list[float],
    zscore_threshold: float = 3.0,
) -> tuple[bool, dict[str, Any]]:
    """Check whether current_mean is anomalous vs the historical distribution.

    Returns (passed, details_dict).
    """
    if len(history_means) < 2:
        return True, {
            "reason": "insufficient_history",
            "history_count": len(history_means),
            "required": 2,
        }

    hist_mean = sum(history_means) / len(history_means)
    variance = sum((x - hist_mean) ** 2 for x in history_means) / (len(history_means) - 1)
    hist_stddev = math.sqrt(variance)

    if hist_stddev == 0.0:
        passed = math.isclose(current_mean, hist_mean, rel_tol=1e-9)
        z = 0.0 if passed else float("inf")
    else:
        z = abs(current_mean - hist_mean) / hist_stddev
        passed = z <= zscore_threshold

    return passed, {
        "current_mean": current_mean,
        "historical_mean": hist_mean,
        "historical_stddev": hist_stddev,
        "zscore": round(z, 4),
        "threshold": zscore_threshold,
        "history_count": len(history_means),
    }
