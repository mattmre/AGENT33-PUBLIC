"""Phase 17 — Evaluation Suite Expansion & Regression Gates.

Tests cover:
- Golden task/case registry (definitions, tags, lookups)
- Metrics calculator (M-01..M-05)
- Gate enforcer (thresholds, golden task gating)
- Regression detector (RI-01, RI-02, RI-04)
- Regression recorder (CRUD, triage, resolution)
- Evaluation service (full pipeline)
- API endpoints (REST lifecycle)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agent33.evaluation.gates import DEFAULT_THRESHOLDS, GateEnforcer

if TYPE_CHECKING:
    from starlette.testclient import TestClient
from agent33.evaluation.golden_tasks import (
    GOLDEN_CASES,
    GOLDEN_TASKS,
    cases_by_tag,
    get_case,
    get_task,
    tasks_by_tag,
    tasks_for_gate,
)
from agent33.evaluation.metrics import MetricsCalculator
from agent33.evaluation.models import (
    BaselineSnapshot,
    GateResult,
    GateType,
    GoldenTag,
    MetricId,
    MetricValue,
    RegressionIndicator,
    RegressionRecord,
    RegressionSeverity,
    TaskResult,
    TaskRunResult,
    TriageStatus,
)
from agent33.evaluation.regression import RegressionDetector, RegressionRecorder
from agent33.evaluation.service import EvaluationService

# ===================================================================
# Golden Tasks & Cases
# ===================================================================


class TestGoldenTaskRegistry:
    """Test golden task and case definitions."""

    def test_all_seven_tasks_defined(self):
        assert len(GOLDEN_TASKS) == 7
        for i in range(1, 8):
            task_id = f"GT-0{i}"
            assert task_id in GOLDEN_TASKS
            assert GOLDEN_TASKS[task_id].name != ""

    def test_all_four_cases_defined(self):
        assert len(GOLDEN_CASES) == 4
        for i in range(1, 5):
            case_id = f"GC-0{i}"
            assert case_id in GOLDEN_CASES
            assert GOLDEN_CASES[case_id].name != ""

    def test_get_task(self):
        task = get_task("GT-01")
        assert task is not None
        assert task.name == "Documentation-Only Task"
        assert GoldenTag.GT_SMOKE in task.tags
        assert GoldenTag.GT_CRITICAL in task.tags

    def test_get_task_not_found(self):
        assert get_task("GT-99") is None

    def test_get_case(self):
        case = get_case("GC-03")
        assert case is not None
        assert case.name == "Out-of-Scope PR Rejection"
        assert GoldenTag.GT_CRITICAL in case.tags

    def test_get_case_not_found(self):
        assert get_case("GC-99") is None

    def test_tasks_by_smoke_tag(self):
        smoke_tasks = tasks_by_tag(GoldenTag.GT_SMOKE)
        task_ids = {t.task_id for t in smoke_tasks}
        assert "GT-01" in task_ids
        assert "GT-04" in task_ids

    def test_tasks_by_critical_tag(self):
        critical_tasks = tasks_by_tag(GoldenTag.GT_CRITICAL)
        task_ids = {t.task_id for t in critical_tasks}
        assert "GT-01" in task_ids
        assert "GT-02" in task_ids
        assert "GT-05" in task_ids
        assert "GT-06" in task_ids

    def test_tasks_by_release_tag(self):
        release_tasks = tasks_by_tag(GoldenTag.GT_RELEASE)
        task_ids = {t.task_id for t in release_tasks}
        assert "GT-03" in task_ids
        assert "GT-04" in task_ids
        assert "GT-07" in task_ids

    def test_cases_by_tag(self):
        critical_cases = cases_by_tag(GoldenTag.GT_CRITICAL)
        case_ids = {c.case_id for c in critical_cases}
        assert "GC-02" in case_ids
        assert "GC-03" in case_ids

    def test_tasks_for_gate(self):
        pr_tasks = tasks_for_gate(GoldenTag.GT_SMOKE)
        assert "GT-01" in pr_tasks
        assert "GT-04" in pr_tasks
        # Cases too
        assert "GC-01" in pr_tasks

    def test_each_task_has_checks(self):
        for task in GOLDEN_TASKS.values():
            assert len(task.checks) >= 3, f"{task.task_id} has too few checks"

    def test_each_case_has_checks(self):
        for case in GOLDEN_CASES.values():
            assert len(case.checks) >= 3, f"{case.case_id} has too few checks"


# ===================================================================
# Metrics Calculator
# ===================================================================


class TestMetricsCalculator:
    """Test metrics computation (M-01 through M-05)."""

    def setup_method(self):
        self.calc = MetricsCalculator()
        self.results = [
            TaskRunResult(
                item_id="GT-01",
                result=TaskResult.PASS,
                duration_ms=100,
                checks_total=4,
            ),
            TaskRunResult(
                item_id="GT-02",
                result=TaskResult.PASS,
                duration_ms=200,
                checks_total=4,
            ),
            TaskRunResult(
                item_id="GT-03",
                result=TaskResult.FAIL,
                duration_ms=300,
                checks_total=4,
            ),
            TaskRunResult(
                item_id="GT-04",
                result=TaskResult.PASS,
                duration_ms=150,
                checks_total=4,
            ),
        ]

    def test_success_rate(self):
        m = self.calc.success_rate(self.results)
        assert m.metric_id == MetricId.M_01
        assert m.value == 75.0  # 3 of 4 pass

    def test_success_rate_all_pass(self):
        all_pass = [TaskRunResult(item_id="GT-01", result=TaskResult.PASS)]
        m = self.calc.success_rate(all_pass)
        assert m.value == 100.0

    def test_success_rate_empty(self):
        m = self.calc.success_rate([])
        assert m.value == 0.0

    def test_time_to_green(self):
        m = self.calc.time_to_green(self.results)
        assert m.metric_id == MetricId.M_02
        assert m.value == 187.5  # (100+200+300+150)/4

    def test_time_to_green_empty(self):
        m = self.calc.time_to_green([])
        assert m.value == 0.0

    def test_rework_rate(self):
        m = self.calc.rework_rate(self.results, rework_count=1)
        assert m.metric_id == MetricId.M_03
        assert m.value == 25.0  # 1 of 4

    def test_rework_rate_zero(self):
        m = self.calc.rework_rate(self.results, rework_count=0)
        assert m.value == 0.0

    def test_diff_size(self):
        m = self.calc.diff_size(self.results)
        assert m.metric_id == MetricId.M_04
        assert m.value == 4.0  # all checks_total=4

    def test_scope_adherence(self):
        m = self.calc.scope_adherence(self.results, scope_violations=1)
        assert m.metric_id == MetricId.M_05
        assert m.value == 75.0  # 3 of 4 within scope

    def test_scope_adherence_perfect(self):
        m = self.calc.scope_adherence(self.results, scope_violations=0)
        assert m.value == 100.0

    def test_compute_all(self):
        metrics = self.calc.compute_all(self.results, rework_count=1, scope_violations=0)
        assert len(metrics) == 5
        ids = {m.metric_id for m in metrics}
        assert ids == {MetricId.M_01, MetricId.M_02, MetricId.M_03, MetricId.M_04, MetricId.M_05}


# ===================================================================
# Gate Enforcer
# ===================================================================


class TestGateEnforcer:
    """Test gate threshold checking."""

    def setup_method(self):
        self.enforcer = GateEnforcer()

    def test_default_thresholds_exist(self):
        assert len(DEFAULT_THRESHOLDS) == 10

    def test_pr_gate_pass(self):
        metrics = {MetricId.M_01: 85.0, MetricId.M_03: 20.0, MetricId.M_05: 95.0}
        report = self.enforcer.check_gate(GateType.G_PR, metrics)
        assert report.overall == GateResult.PASS

    def test_pr_gate_fail_success_rate(self):
        metrics = {MetricId.M_01: 70.0, MetricId.M_03: 20.0, MetricId.M_05: 95.0}
        report = self.enforcer.check_gate(GateType.G_PR, metrics)
        assert report.overall == GateResult.FAIL

    def test_pr_gate_warn_rework_rate(self):
        # M-03 threshold for G-PR is ≤30% with WARN action
        metrics = {MetricId.M_01: 85.0, MetricId.M_03: 35.0, MetricId.M_05: 95.0}
        report = self.enforcer.check_gate(GateType.G_PR, metrics)
        assert report.overall == GateResult.WARN

    def test_merge_gate_pass(self):
        metrics = {MetricId.M_01: 95.0, MetricId.M_03: 15.0, MetricId.M_05: 100.0}
        report = self.enforcer.check_gate(GateType.G_MRG, metrics)
        assert report.overall == GateResult.PASS

    def test_merge_gate_fail_scope(self):
        metrics = {MetricId.M_01: 95.0, MetricId.M_03: 15.0, MetricId.M_05: 99.0}
        report = self.enforcer.check_gate(GateType.G_MRG, metrics)
        assert report.overall == GateResult.FAIL  # M-05 must be exactly 100%

    def test_release_gate_pass(self):
        metrics = {MetricId.M_01: 96.0, MetricId.M_03: 8.0}
        report = self.enforcer.check_gate(GateType.G_REL, metrics)
        assert report.overall == GateResult.PASS

    def test_release_gate_fail_rework(self):
        metrics = {MetricId.M_01: 96.0, MetricId.M_03: 15.0}
        report = self.enforcer.check_gate(GateType.G_REL, metrics)
        assert report.overall == GateResult.FAIL

    def test_golden_task_failures_block_merge(self):
        metrics = {MetricId.M_01: 95.0, MetricId.M_03: 10.0, MetricId.M_05: 100.0}
        failed_results = [
            TaskRunResult(item_id="GT-05", result=TaskResult.FAIL),
        ]
        report = self.enforcer.check_gate(GateType.G_MRG, metrics, failed_results)
        assert report.overall == GateResult.FAIL

    def test_golden_task_pass_at_merge(self):
        metrics = {MetricId.M_01: 95.0, MetricId.M_03: 10.0, MetricId.M_05: 100.0}
        passing_results = [
            TaskRunResult(item_id="GT-01", result=TaskResult.PASS),
            TaskRunResult(item_id="GT-02", result=TaskResult.PASS),
        ]
        report = self.enforcer.check_gate(GateType.G_MRG, metrics, passing_results)
        assert report.overall == GateResult.PASS

    def test_skipped_tasks_dont_block(self):
        metrics = {MetricId.M_01: 95.0, MetricId.M_03: 10.0, MetricId.M_05: 100.0}
        results = [
            TaskRunResult(item_id="GT-01", result=TaskResult.PASS),
            TaskRunResult(item_id="GT-03", result=TaskResult.SKIP),
        ]
        report = self.enforcer.check_gate(GateType.G_MRG, metrics, results)
        assert report.overall == GateResult.PASS

    def test_get_thresholds_for_gate(self):
        pr_thresholds = self.enforcer.get_thresholds_for_gate(GateType.G_PR)
        assert len(pr_thresholds) == 3  # M-01, M-03, M-05

    def test_get_required_tag(self):
        assert self.enforcer.get_required_tag(GateType.G_PR) == GoldenTag.GT_SMOKE
        assert self.enforcer.get_required_tag(GateType.G_MRG) == GoldenTag.GT_CRITICAL
        assert self.enforcer.get_required_tag(GateType.G_REL) == GoldenTag.GT_RELEASE


# ===================================================================
# Regression Detection
# ===================================================================


class TestRegressionDetector:
    """Test regression detection (RI-01, RI-02, RI-04)."""

    def setup_method(self):
        self.detector = RegressionDetector()

    def test_ri01_task_regression(self):
        baseline = BaselineSnapshot(
            task_results=[
                TaskRunResult(item_id="GT-01", result=TaskResult.PASS),
                TaskRunResult(item_id="GT-02", result=TaskResult.PASS),
            ],
        )
        current_results = [
            TaskRunResult(item_id="GT-01", result=TaskResult.FAIL, notes="broken"),
            TaskRunResult(item_id="GT-02", result=TaskResult.PASS),
        ]
        regressions = self.detector.detect(baseline, [], current_results)
        assert len(regressions) == 1
        assert regressions[0].indicator == RegressionIndicator.RI_01
        assert regressions[0].severity == RegressionSeverity.HIGH
        assert "GT-01" in regressions[0].affected_tasks

    def test_ri01_no_regression_when_both_fail(self):
        baseline = BaselineSnapshot(
            task_results=[
                TaskRunResult(item_id="GT-01", result=TaskResult.FAIL),
            ],
        )
        current = [TaskRunResult(item_id="GT-01", result=TaskResult.FAIL)]
        regressions = self.detector.detect(baseline, [], current)
        assert len(regressions) == 0

    def test_ri02_metric_threshold_breach(self):
        baseline = BaselineSnapshot(
            metrics=[MetricValue(metric_id=MetricId.M_01, value=92.0)],
        )
        current_metrics = [MetricValue(metric_id=MetricId.M_01, value=78.0)]
        thresholds = {MetricId.M_01: 80.0}
        regressions = self.detector.detect(baseline, current_metrics, [], thresholds)
        assert len(regressions) == 1
        assert regressions[0].indicator == RegressionIndicator.RI_02
        assert regressions[0].metric_id == MetricId.M_01

    def test_ri02_no_breach_when_baseline_already_below(self):
        baseline = BaselineSnapshot(
            metrics=[MetricValue(metric_id=MetricId.M_01, value=75.0)],
        )
        current_metrics = [MetricValue(metric_id=MetricId.M_01, value=70.0)]
        thresholds = {MetricId.M_01: 80.0}
        regressions = self.detector.detect(baseline, current_metrics, [], thresholds)
        assert len(regressions) == 0  # baseline was already below threshold

    def test_ri02_rework_rate_breach(self):
        baseline = BaselineSnapshot(
            metrics=[MetricValue(metric_id=MetricId.M_03, value=15.0)],
        )
        current_metrics = [MetricValue(metric_id=MetricId.M_03, value=25.0)]
        thresholds = {MetricId.M_03: 20.0}
        regressions = self.detector.detect(baseline, current_metrics, [], thresholds)
        assert len(regressions) == 1
        assert regressions[0].indicator == RegressionIndicator.RI_02

    def test_ri04_ttg_increase(self):
        baseline = BaselineSnapshot(
            metrics=[MetricValue(metric_id=MetricId.M_02, value=100.0, unit="ms")],
        )
        current_metrics = [
            MetricValue(metric_id=MetricId.M_02, value=200.0, unit="ms"),
        ]
        regressions = self.detector.detect(baseline, current_metrics, [])
        assert len(regressions) == 1
        assert regressions[0].indicator == RegressionIndicator.RI_04

    def test_ri04_no_regression_when_small_increase(self):
        baseline = BaselineSnapshot(
            metrics=[MetricValue(metric_id=MetricId.M_02, value=100.0, unit="ms")],
        )
        current_metrics = [
            MetricValue(metric_id=MetricId.M_02, value=130.0, unit="ms"),
        ]
        regressions = self.detector.detect(baseline, current_metrics, [])
        assert len(regressions) == 0  # 30% increase is below 50% threshold

    def test_no_regressions_without_baseline_data(self):
        baseline = BaselineSnapshot()
        regressions = self.detector.detect(baseline, [], [])
        assert len(regressions) == 0


# ===================================================================
# Regression Recorder
# ===================================================================


class TestRegressionRecorder:
    """Test regression record CRUD and triage lifecycle."""

    def setup_method(self):
        self.recorder = RegressionRecorder()

    def test_record_and_get(self):
        reg = RegressionRecord(
            indicator=RegressionIndicator.RI_01,
            description="GT-01 failed",
        )
        self.recorder.record(reg)
        found = self.recorder.get(reg.regression_id)
        assert found is not None
        assert found.indicator == RegressionIndicator.RI_01

    def test_record_many(self):
        regs = [
            RegressionRecord(indicator=RegressionIndicator.RI_01),
            RegressionRecord(indicator=RegressionIndicator.RI_02),
        ]
        count = self.recorder.record_many(regs)
        assert count == 2
        assert len(self.recorder.list_all()) == 2

    def test_list_by_status(self):
        r1 = RegressionRecord(triage_status=TriageStatus.NEW)
        r2 = RegressionRecord(triage_status=TriageStatus.INVESTIGATING)
        self.recorder.record(r1)
        self.recorder.record(r2)
        new_only = self.recorder.list_all(status=TriageStatus.NEW)
        assert len(new_only) == 1

    def test_list_by_severity(self):
        r1 = RegressionRecord(severity=RegressionSeverity.HIGH)
        r2 = RegressionRecord(severity=RegressionSeverity.LOW)
        self.recorder.record(r1)
        self.recorder.record(r2)
        high_only = self.recorder.list_all(severity=RegressionSeverity.HIGH)
        assert len(high_only) == 1

    def test_update_triage(self):
        reg = RegressionRecord()
        self.recorder.record(reg)
        updated = self.recorder.update_triage(
            reg.regression_id,
            status=TriageStatus.INVESTIGATING,
            assignee="qa-agent",
        )
        assert updated is not None
        assert updated.triage_status == TriageStatus.INVESTIGATING
        assert updated.assignee == "qa-agent"

    def test_update_triage_not_found(self):
        result = self.recorder.update_triage("nonexistent", TriageStatus.NEW)
        assert result is None

    def test_resolve(self):
        reg = RegressionRecord()
        self.recorder.record(reg)
        resolved = self.recorder.resolve(
            reg.regression_id,
            resolved_by="developer",
            fix_commit="abc123",
        )
        assert resolved is not None
        assert resolved.triage_status == TriageStatus.RESOLVED
        assert resolved.resolved_by == "developer"
        assert resolved.fix_commit == "abc123"
        assert resolved.resolved_at is not None

    def test_resolve_not_found(self):
        result = self.recorder.resolve("nonexistent")
        assert result is None


# ===================================================================
# Evaluation Service
# ===================================================================


class TestEvaluationService:
    """Test the evaluation service orchestration."""

    def setup_method(self):
        self.service = EvaluationService()

    def test_list_golden_tasks(self):
        tasks = self.service.list_golden_tasks()
        assert len(tasks) == 7

    def test_list_golden_cases(self):
        cases = self.service.list_golden_cases()
        assert len(cases) == 4

    def test_get_tasks_for_pr_gate(self):
        task_ids = self.service.get_tasks_for_gate(GateType.G_PR)
        assert "GT-01" in task_ids  # GT-SMOKE
        assert "GT-04" in task_ids  # GT-SMOKE

    def test_create_and_get_run(self):
        run = self.service.create_run(GateType.G_PR, commit_hash="abc123")
        assert run.run_id.startswith("EVAL-")
        found = self.service.get_run(run.run_id)
        assert found is not None
        assert found.gate == GateType.G_PR

    def test_list_runs(self):
        self.service.create_run(GateType.G_PR)
        self.service.create_run(GateType.G_MRG)
        runs = self.service.list_runs()
        assert len(runs) == 2

    def test_submit_results_computes_metrics(self):
        run = self.service.create_run(GateType.G_PR)
        results = [
            TaskRunResult(item_id="GT-01", result=TaskResult.PASS, duration_ms=100),
            TaskRunResult(item_id="GT-04", result=TaskResult.PASS, duration_ms=150),
        ]
        completed = self.service.submit_results(run.run_id, results)
        assert completed is not None
        assert completed.completed_at is not None
        assert len(completed.metrics) == 5
        # All pass → 100% success rate
        m01 = next(m for m in completed.metrics if m.metric_id == MetricId.M_01)
        assert m01.value == 100.0

    def test_submit_results_checks_gate(self):
        run = self.service.create_run(GateType.G_PR)
        results = [
            TaskRunResult(item_id="GT-01", result=TaskResult.PASS),
            TaskRunResult(item_id="GT-04", result=TaskResult.PASS),
        ]
        completed = self.service.submit_results(run.run_id, results)
        assert completed is not None
        assert completed.gate_report is not None
        assert completed.gate_report.overall == GateResult.PASS

    def test_submit_results_detects_regressions(self):
        # First, save a baseline with GT-01 passing
        baseline_results = [
            TaskRunResult(item_id="GT-01", result=TaskResult.PASS),
        ]
        baseline_metrics = [
            MetricValue(metric_id=MetricId.M_01, value=100.0),
            MetricValue(metric_id=MetricId.M_02, value=100.0, unit="ms"),
        ]
        self.service.save_baseline(baseline_metrics, baseline_results)

        # Now run with GT-01 failing
        run = self.service.create_run(GateType.G_PR)
        current_results = [
            TaskRunResult(item_id="GT-01", result=TaskResult.FAIL, notes="broken"),
        ]
        completed = self.service.submit_results(run.run_id, current_results)
        assert completed is not None
        assert len(completed.regressions) >= 1
        assert any(r.indicator == RegressionIndicator.RI_01 for r in completed.regressions)

    def test_submit_results_not_found(self):
        result = self.service.submit_results("nonexistent", [])
        assert result is None

    def test_baseline_crud(self):
        metrics = [MetricValue(metric_id=MetricId.M_01, value=95.0)]
        results = [TaskRunResult(item_id="GT-01", result=TaskResult.PASS)]
        baseline = self.service.save_baseline(metrics, results, commit_hash="abc")
        assert baseline.baseline_id.startswith("BSL-")

        found = self.service.get_baseline(baseline.baseline_id)
        assert found is not None

        latest = self.service.get_latest_baseline()
        assert latest is not None
        assert latest.baseline_id == baseline.baseline_id

        all_baselines = self.service.list_baselines()
        assert len(all_baselines) == 1

    def test_no_baseline_returns_none(self):
        assert self.service.get_latest_baseline() is None


# ===================================================================
# API Endpoints
# ===================================================================


class TestEvaluationAPI:
    """Test evaluation REST endpoints via TestClient."""

    @pytest.fixture(autouse=True)
    def _setup(self, client: TestClient):
        self.client = client

    def test_list_golden_tasks(self):
        resp = self.client.get("/v1/evaluations/golden-tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 7

    def test_list_golden_cases(self):
        resp = self.client.get("/v1/evaluations/golden-cases")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 4

    def test_get_tasks_for_gate(self):
        resp = self.client.get("/v1/evaluations/gates/G-PR/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert "GT-01" in data

    def test_create_run(self):
        resp = self.client.post(
            "/v1/evaluations/runs",
            json={"gate": "G-PR", "commit_hash": "abc123"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "run_id" in data
        assert data["gate"] == "G-PR"

    def test_list_runs(self):
        self.client.post("/v1/evaluations/runs", json={"gate": "G-PR"})
        resp = self.client.get("/v1/evaluations/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

    def test_get_run(self):
        create_resp = self.client.post("/v1/evaluations/runs", json={"gate": "G-MRG"})
        run_id = create_resp.json()["run_id"]
        resp = self.client.get(f"/v1/evaluations/runs/{run_id}")
        assert resp.status_code == 200
        assert resp.json()["gate"] == "G-MRG"

    def test_get_run_not_found(self):
        resp = self.client.get("/v1/evaluations/runs/nonexistent")
        assert resp.status_code == 404

    def test_submit_results(self):
        create_resp = self.client.post("/v1/evaluations/runs", json={"gate": "G-PR"})
        run_id = create_resp.json()["run_id"]
        resp = self.client.post(
            f"/v1/evaluations/runs/{run_id}/results",
            json={
                "task_results": [
                    {"item_id": "GT-01", "result": "pass", "duration_ms": 100},
                    {"item_id": "GT-04", "result": "pass", "duration_ms": 200},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["gate_result"] == "pass"
        assert len(data["metrics"]) == 5

    def test_submit_results_not_found(self):
        resp = self.client.post(
            "/v1/evaluations/runs/nonexistent/results",
            json={"task_results": []},
        )
        assert resp.status_code == 404

    def test_save_baseline_from_run(self):
        # Create and complete a run
        create_resp = self.client.post("/v1/evaluations/runs", json={"gate": "G-PR"})
        run_id = create_resp.json()["run_id"]
        self.client.post(
            f"/v1/evaluations/runs/{run_id}/results",
            json={"task_results": [{"item_id": "GT-01", "result": "pass"}]},
        )
        # Save as baseline
        resp = self.client.post(
            f"/v1/evaluations/runs/{run_id}/baseline",
            json={"commit_hash": "def456"},
        )
        assert resp.status_code == 201
        assert "baseline_id" in resp.json()

    def test_save_baseline_incomplete_run(self):
        create_resp = self.client.post("/v1/evaluations/runs", json={"gate": "G-PR"})
        run_id = create_resp.json()["run_id"]
        resp = self.client.post(
            f"/v1/evaluations/runs/{run_id}/baseline",
            json={},
        )
        assert resp.status_code == 409  # Run not yet completed

    def test_list_baselines(self):
        resp = self.client.get("/v1/evaluations/baselines")
        assert resp.status_code == 200

    def test_list_regressions(self):
        resp = self.client.get("/v1/evaluations/regressions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
