"""Regression comparison helpers for SkillsBench CTRF reports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field


class SkillsBenchRegressionThresholds(BaseModel):
    """Deterministic thresholds for SkillsBench regression detection."""

    overall_pass_rate_drop_pp: float = Field(default=5.0, ge=0.0)
    task_pass_rate_drop_pp: float = Field(default=20.0, ge=0.0)
    category_pass_rate_drop_pp: float = Field(default=5.0, ge=0.0)


class SkillsBenchRateSnapshot(BaseModel):
    """Normalized pass-rate snapshot for overall, task, or category results."""

    id: str
    category: str = ""
    total: int = Field(default=0, ge=0)
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    pass_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0)


class SkillsBenchRegressionEntry(BaseModel):
    """A single detected regression."""

    scope: str
    id: str
    category: str = ""
    baseline: SkillsBenchRateSnapshot
    current: SkillsBenchRateSnapshot
    drop_pp: float = Field(default=0.0, ge=0.0)
    threshold_pp: float = Field(default=0.0, ge=0.0)
    message: str = ""


class SkillsBenchOverallComparison(BaseModel):
    """Overall current-vs-baseline comparison."""

    baseline: SkillsBenchRateSnapshot
    current: SkillsBenchRateSnapshot
    drop_pp: float = Field(default=0.0, ge=0.0)
    threshold_pp: float = Field(default=0.0, ge=0.0)
    regressed: bool = False


class SkillsBenchRegressionReport(BaseModel):
    """Structured SkillsBench baseline comparison report."""

    thresholds: SkillsBenchRegressionThresholds = Field(
        default_factory=SkillsBenchRegressionThresholds
    )
    overall: SkillsBenchOverallComparison
    task_regressions: list[SkillsBenchRegressionEntry] = Field(default_factory=list)
    category_regressions: list[SkillsBenchRegressionEntry] = Field(default_factory=list)

    @property
    def has_regressions(self) -> bool:
        """Return whether any regression threshold was tripped."""
        return (
            self.overall.regressed
            or bool(self.task_regressions)
            or bool(self.category_regressions)
        )

    def to_text(self) -> str:
        """Render a concise human-readable summary."""
        lines = [
            (
                "Baseline comparison: "
                f"current {self.overall.current.pass_rate_pct:.1f}% "
                f"vs baseline {self.overall.baseline.pass_rate_pct:.1f}% "
                f"(drop {self.overall.drop_pp:.1f}pp)"
            ),
            (
                "Thresholds: "
                f"overall>{self.thresholds.overall_pass_rate_drop_pp:.1f}pp, "
                f"task>{self.thresholds.task_pass_rate_drop_pp:.1f}pp, "
                f"category>{self.thresholds.category_pass_rate_drop_pp:.1f}pp"
            ),
        ]

        if self.has_regressions:
            lines.append(
                "Detected regressions: "
                f"{len(self.task_regressions)} task, {len(self.category_regressions)} category"
            )
            for entry in self.task_regressions[:5]:
                lines.append(
                    f"  - task {entry.id}: {entry.current.pass_rate_pct:.1f}% vs "
                    f"{entry.baseline.pass_rate_pct:.1f}% ({entry.drop_pp:.1f}pp)"
                )
            for entry in self.category_regressions[:5]:
                lines.append(
                    f"  - category {entry.id}: {entry.current.pass_rate_pct:.1f}% vs "
                    f"{entry.baseline.pass_rate_pct:.1f}% ({entry.drop_pp:.1f}pp)"
                )
        else:
            lines.append("No regression detected.")

        return "\n".join(lines)

    def to_markdown(self, title: str = "SkillsBench regression report") -> str:
        """Render a GitHub-friendly markdown summary."""
        lines = [
            f"## {title}",
            "",
            "| Metric | Current | Baseline | Delta | Threshold | Status |",
            "| --- | --- | --- | --- | --- | --- |",
            (
                f"| Overall pass rate | {self.overall.current.pass_rate_pct:.1f}% "
                f"({self.overall.current.passed}/{self.overall.current.total}) | "
                f"{self.overall.baseline.pass_rate_pct:.1f}% "
                f"({self.overall.baseline.passed}/{self.overall.baseline.total}) | "
                f"-{self.overall.drop_pp:.1f}pp | "
                f"{self.overall.threshold_pp:.1f}pp | "
                f"{'REGRESSION' if self.overall.regressed else 'OK'} |"
            ),
            "",
        ]

        if self.task_regressions:
            lines.extend(
                [
                    "### Task regressions",
                    "",
                    "| Task | Current | Baseline | Delta | Reason |",
                    "| --- | --- | --- | --- | --- |",
                ]
            )
            for entry in self.task_regressions:
                lines.append(
                    f"| `{entry.id}` | {entry.current.pass_rate_pct:.1f}% "
                    f"({entry.current.passed}/{entry.current.total}) | "
                    f"{entry.baseline.pass_rate_pct:.1f}% "
                    f"({entry.baseline.passed}/{entry.baseline.total}) | "
                    f"-{entry.drop_pp:.1f}pp | {_escape_markdown_cell(entry.message)} |"
                )
            lines.append("")

        if self.category_regressions:
            lines.extend(
                [
                    "### Category regressions",
                    "",
                    "| Category | Current | Baseline | Delta | Reason |",
                    "| --- | --- | --- | --- | --- |",
                ]
            )
            for entry in self.category_regressions:
                lines.append(
                    f"| `{entry.id}` | {entry.current.pass_rate_pct:.1f}% "
                    f"({entry.current.passed}/{entry.current.total}) | "
                    f"{entry.baseline.pass_rate_pct:.1f}% "
                    f"({entry.baseline.passed}/{entry.baseline.total}) | "
                    f"-{entry.drop_pp:.1f}pp | {_escape_markdown_cell(entry.message)} |"
                )
            lines.append("")

        if not self.has_regressions:
            lines.append("- No regression detected.")

        return "\n".join(lines).rstrip() + "\n"


def compare_ctrf_reports(
    current: Mapping[str, Any],
    baseline: Mapping[str, Any],
    thresholds: SkillsBenchRegressionThresholds | None = None,
) -> SkillsBenchRegressionReport:
    """Compare a current CTRF report against a baseline."""
    resolved_thresholds = thresholds or SkillsBenchRegressionThresholds()
    current_overall = _extract_overall_snapshot(current)
    baseline_overall = _extract_overall_snapshot(baseline)
    overall_drop = round(
        max(0.0, baseline_overall.pass_rate_pct - current_overall.pass_rate_pct),
        1,
    )

    current_tasks = _extract_task_snapshots(current)
    baseline_tasks = _extract_task_snapshots(baseline)
    current_categories = _aggregate_categories(current_tasks)
    baseline_categories = _aggregate_categories(baseline_tasks)

    overall = SkillsBenchOverallComparison(
        baseline=baseline_overall,
        current=current_overall,
        drop_pp=overall_drop,
        threshold_pp=resolved_thresholds.overall_pass_rate_drop_pp,
        regressed=overall_drop > resolved_thresholds.overall_pass_rate_drop_pp,
    )

    return SkillsBenchRegressionReport(
        thresholds=resolved_thresholds,
        overall=overall,
        task_regressions=_build_regressions(
            current_snapshots=current_tasks,
            baseline_snapshots=baseline_tasks,
            threshold_pp=resolved_thresholds.task_pass_rate_drop_pp,
            scope="task",
        ),
        category_regressions=_build_regressions(
            current_snapshots=current_categories,
            baseline_snapshots=baseline_categories,
            threshold_pp=resolved_thresholds.category_pass_rate_drop_pp,
            scope="category",
        ),
    )


def attach_baseline_comparison(
    current: dict[str, Any],
    baseline: Mapping[str, Any],
    thresholds: SkillsBenchRegressionThresholds | None = None,
) -> SkillsBenchRegressionReport:
    """Attach a structured baseline comparison to a CTRF report."""
    comparison = compare_ctrf_reports(current, baseline, thresholds=thresholds)
    results = current.setdefault("results", {})
    if not isinstance(results, dict):
        msg = "CTRF report results payload must be a dictionary."
        raise ValueError(msg)

    extra = results.get("extra")
    if not isinstance(extra, dict):
        extra = {}
        results["extra"] = extra

    skillsbench = extra.get("skillsbench")
    if not isinstance(skillsbench, dict):
        skillsbench = {}
        extra["skillsbench"] = skillsbench

    skillsbench["baseline_comparison"] = comparison.model_dump(mode="json")
    return comparison


def _extract_overall_snapshot(report: Mapping[str, Any]) -> SkillsBenchRateSnapshot:
    summary = _get_summary(report)
    total = _safe_int(summary.get("tests"))
    passed = _safe_int(summary.get("passed"))
    skipped = _safe_int(summary.get("skipped"))
    failed = max(0, total - passed - skipped)
    return SkillsBenchRateSnapshot(
        id="overall",
        total=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        pass_rate_pct=_pass_rate_pct(passed, total),
    )


def _extract_task_snapshots(report: Mapping[str, Any]) -> dict[str, SkillsBenchRateSnapshot]:
    task_summaries = _get_task_summaries(report)
    if task_summaries:
        return {
            snapshot.id: snapshot
            for snapshot in (_task_snapshot_from_summary(summary) for summary in task_summaries)
        }

    tests = _get_tests(report)
    grouped: dict[str, dict[str, Any]] = {}
    for test in tests:
        task_id = _extract_task_id(test)
        category = _extract_category(test, task_id)
        record = grouped.setdefault(
            task_id,
            {
                "id": task_id,
                "category": category,
                "total": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
            },
        )
        record["total"] = _safe_int(record.get("total")) + 1
        status = str(test.get("status", "")).lower()
        if status == "passed":
            record["passed"] = _safe_int(record.get("passed")) + 1
        elif status == "skipped":
            record["skipped"] = _safe_int(record.get("skipped")) + 1
        else:
            record["failed"] = _safe_int(record.get("failed")) + 1

    return {
        task_id: SkillsBenchRateSnapshot(
            id=task_id,
            category=str(values.get("category", "")),
            total=_safe_int(values.get("total")),
            passed=_safe_int(values.get("passed")),
            failed=_safe_int(values.get("failed")),
            skipped=_safe_int(values.get("skipped")),
            pass_rate_pct=_pass_rate_pct(
                _safe_int(values.get("passed")),
                _safe_int(values.get("total")),
            ),
        )
        for task_id, values in grouped.items()
    }


def _build_regressions(
    *,
    current_snapshots: dict[str, SkillsBenchRateSnapshot],
    baseline_snapshots: dict[str, SkillsBenchRateSnapshot],
    threshold_pp: float,
    scope: str,
) -> list[SkillsBenchRegressionEntry]:
    regressions: list[SkillsBenchRegressionEntry] = []

    for snapshot_id in sorted(set(baseline_snapshots) | set(current_snapshots)):
        baseline = baseline_snapshots.get(snapshot_id)
        if baseline is None or baseline.total == 0:
            continue
        current = current_snapshots.get(snapshot_id)
        if current is None:
            current = SkillsBenchRateSnapshot(id=snapshot_id, category=baseline.category)

        drop_pp = round(max(0.0, baseline.pass_rate_pct - current.pass_rate_pct), 1)
        if drop_pp < threshold_pp:
            continue

        regressions.append(
            SkillsBenchRegressionEntry(
                scope=scope,
                id=snapshot_id,
                category=current.category or baseline.category,
                baseline=baseline,
                current=current,
                drop_pp=drop_pp,
                threshold_pp=threshold_pp,
                message=_describe_regression(scope=scope, baseline=baseline, current=current),
            )
        )

    regressions.sort(key=lambda entry: (-entry.drop_pp, entry.id))
    return regressions


def _aggregate_categories(
    task_snapshots: dict[str, SkillsBenchRateSnapshot],
) -> dict[str, SkillsBenchRateSnapshot]:
    grouped: dict[str, dict[str, int | str]] = {}
    for snapshot in task_snapshots.values():
        category = snapshot.category
        if not category:
            continue
        record = grouped.setdefault(
            category,
            {"category": category, "total": 0, "passed": 0, "failed": 0, "skipped": 0},
        )
        record["total"] = _safe_int(record.get("total")) + snapshot.total
        record["passed"] = _safe_int(record.get("passed")) + snapshot.passed
        record["failed"] = _safe_int(record.get("failed")) + snapshot.failed
        record["skipped"] = _safe_int(record.get("skipped")) + snapshot.skipped

    return {
        category: SkillsBenchRateSnapshot(
            id=category,
            category=category,
            total=_safe_int(values.get("total")),
            passed=_safe_int(values.get("passed")),
            failed=_safe_int(values.get("failed")),
            skipped=_safe_int(values.get("skipped")),
            pass_rate_pct=_pass_rate_pct(
                _safe_int(values.get("passed")),
                _safe_int(values.get("total")),
            ),
        )
        for category, values in grouped.items()
    }


def _task_snapshot_from_summary(summary: Mapping[str, Any]) -> SkillsBenchRateSnapshot:
    task_id = str(summary.get("task_id", "unknown"))
    total = _safe_int(summary.get("total_trials"))
    passed = _safe_int(summary.get("passed_trials"))
    failed = _safe_int(summary.get("failed_trials")) + _safe_int(summary.get("error_trials"))
    skipped = _safe_int(summary.get("skipped_trials"))
    pass_rate_raw = summary.get("pass_rate", 0.0)
    pass_rate_pct = (
        round(float(pass_rate_raw) * 100, 1)
        if isinstance(pass_rate_raw, (int, float))
        else _pass_rate_pct(passed, total)
    )
    return SkillsBenchRateSnapshot(
        id=task_id,
        category=str(summary.get("category", "")),
        total=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        pass_rate_pct=pass_rate_pct,
    )


def _get_summary(report: Mapping[str, Any]) -> Mapping[str, Any]:
    results = report.get("results")
    if isinstance(results, Mapping):
        summary = results.get("summary")
        if isinstance(summary, Mapping):
            return summary
    return {}


def _get_tests(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    results = report.get("results")
    if isinstance(results, Mapping):
        tests = results.get("tests")
        if isinstance(tests, list):
            return [test for test in tests if isinstance(test, Mapping)]
    return []


def _get_task_summaries(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    results = report.get("results")
    if not isinstance(results, Mapping):
        return []
    extra = results.get("extra")
    if not isinstance(extra, Mapping):
        return []
    skillsbench = extra.get("skillsbench")
    if not isinstance(skillsbench, Mapping):
        return []
    task_summaries = skillsbench.get("task_summaries")
    if not isinstance(task_summaries, list):
        return []
    return [summary for summary in task_summaries if isinstance(summary, Mapping)]


def _extract_task_id(test: Mapping[str, Any]) -> str:
    extra = test.get("extra")
    if isinstance(extra, Mapping):
        skillsbench = extra.get("skillsbench")
        if isinstance(skillsbench, Mapping):
            task_id = skillsbench.get("task_id")
            if isinstance(task_id, str) and task_id:
                return task_id
    name = test.get("name")
    if isinstance(name, str) and name:
        return name
    return "unknown"


def _extract_category(test: Mapping[str, Any], task_id: str) -> str:
    extra = test.get("extra")
    if isinstance(extra, Mapping):
        skillsbench = extra.get("skillsbench")
        if isinstance(skillsbench, Mapping):
            category = skillsbench.get("category")
            if isinstance(category, str) and category:
                return category
    if "/" in task_id:
        return task_id.split("/", 1)[0]
    return ""


def _describe_regression(
    *,
    scope: str,
    baseline: SkillsBenchRateSnapshot,
    current: SkillsBenchRateSnapshot,
) -> str:
    if current.total == 0:
        return f"{scope} missing from current report"
    if baseline.failed == 0 and current.failed > 0:
        return f"new failing {scope} results introduced"
    return f"{scope} pass rate dropped by {baseline.pass_rate_pct - current.pass_rate_pct:.1f}pp"


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|")


def _pass_rate_pct(passed: int, total: int) -> float:
    return round((passed / total * 100) if total else 0.0, 1)


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0
