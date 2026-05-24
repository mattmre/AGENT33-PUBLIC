"""Validate the durable Phase 08 GT/GC baseline artifact."""

from __future__ import annotations

import json
from pathlib import Path

from agent33.evaluation.golden_tasks import GOLDEN_CASES, GOLDEN_TASKS
from agent33.evaluation.metrics import MetricsCalculator
from agent33.evaluation.models import MetricValue, TaskResult, TaskRunResult


REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = (
    REPO_ROOT / "_internal" / "reviews" / "phase-08-durable-gt-gc-baseline-2026-05-24.json"
)


def _load_baseline() -> dict[str, object]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def test_phase08_baseline_covers_all_current_golden_items() -> None:
    payload = _load_baseline()
    expected_ids = [*GOLDEN_TASKS.keys(), *GOLDEN_CASES.keys()]
    results = payload["task_results"]
    assert isinstance(results, list)

    observed_ids = [row["item_id"] for row in results]
    assert observed_ids == expected_ids
    assert payload["phase_id"] == "PHASE-08"
    assert payload["baseline_kind"] == "full_gt_gc_local_harness_baseline"


def test_phase08_baseline_results_match_registry_check_counts() -> None:
    payload = _load_baseline()
    definitions = {**GOLDEN_TASKS, **GOLDEN_CASES}

    for row in payload["task_results"]:
        item_id = row["item_id"]
        expected_total = len(definitions[item_id].checks)
        assert row["result"] == TaskResult.PASS.value
        assert row["checks_total"] == expected_total
        assert row["checks_passed"] == expected_total
        assert row["failure_category"] == ""
        assert row["flaky"] is False


def test_phase08_baseline_metrics_are_recomputed_from_results() -> None:
    payload = _load_baseline()
    results = [TaskRunResult.model_validate(row) for row in payload["task_results"]]
    expected_metrics = MetricsCalculator().compute_all(
        results,
        rework_count=int(payload["rework_count"]),
        scope_violations=int(payload["scope_violations"]),
    )
    observed_metrics = [MetricValue.model_validate(row) for row in payload["metrics"]]

    assert [metric.model_dump() for metric in observed_metrics] == [
        metric.model_dump() for metric in expected_metrics
    ]
