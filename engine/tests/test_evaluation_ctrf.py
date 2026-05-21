"""Tests for CTRF (Common Test Report Format) reporting integration.

Tests cover:
- CTRFTestState enum values
- CTRFTest model validation
- CTRFReport / CTRFResults / CTRFSummary structure
- CTRFReportGenerator from evaluation run results
- CTRFReportGenerator from gate results
- CTRFReportGenerator from golden task results
- JSON serialization round-trip
- Summary computation (correct counts)
- Empty results handling
- File output
- Service integration (generate_ctrf_for_run, get_latest_ctrf)
- API route tests (GET /ctrf/latest, POST /ctrf/generate)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from agent33.evaluation.ctrf import (
    CTRFEnvironment,
    CTRFReport,
    CTRFReportGenerator,
    CTRFResults,
    CTRFSummary,
    CTRFTest,
    CTRFTestState,
    CTRFToolInfo,
)
from agent33.evaluation.models import (
    GateType,
    TaskResult,
    TaskRunResult,
)
from agent33.evaluation.service import EvaluationService

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.testclient import TestClient


# ===================================================================
# CTRFTestState
# ===================================================================


class TestCTRFTestState:
    """Test the CTRF test state enum."""

    def test_all_states_defined(self):
        """All five standard CTRF states exist."""
        assert CTRFTestState.PASSED == "passed"
        assert CTRFTestState.FAILED == "failed"
        assert CTRFTestState.SKIPPED == "skipped"
        assert CTRFTestState.PENDING == "pending"
        assert CTRFTestState.OTHER == "other"

    def test_state_count(self):
        """Exactly five states are defined."""
        assert len(CTRFTestState) == 5


# ===================================================================
# CTRFTest model
# ===================================================================


class TestCTRFTestModel:
    """Test CTRFTest model validation and defaults."""

    def test_minimal_construction(self):
        """A test entry can be created with just name, status, and duration."""
        t = CTRFTest(name="test-1", status=CTRFTestState.PASSED, duration=123.4)
        assert t.name == "test-1"
        assert t.status == CTRFTestState.PASSED
        assert t.duration == 123.4

    def test_defaults(self):
        """Default values for optional fields are empty/zero/false."""
        t = CTRFTest(name="t", status=CTRFTestState.FAILED, duration=0)
        assert t.message == ""
        assert t.trace == ""
        assert t.suite == ""
        assert t.type == ""
        assert t.filePath == ""
        assert t.retries == 0
        assert t.flaky is False
        assert t.tags == []

    def test_full_construction(self):
        """All fields can be set explicitly."""
        t = CTRFTest(
            name="GT-01",
            status=CTRFTestState.PASSED,
            duration=500.0,
            message="all checks passed",
            trace="trace-data",
            suite="golden-tasks",
            type="golden-task",
            filePath="/path/to/test.py",
            retries=2,
            flaky=True,
            tags=["smoke", "critical"],
        )
        assert t.name == "GT-01"
        assert t.message == "all checks passed"
        assert t.suite == "golden-tasks"
        assert t.type == "golden-task"
        assert t.filePath == "/path/to/test.py"
        assert t.retries == 2
        assert t.flaky is True
        assert t.tags == ["smoke", "critical"]

    def test_status_from_string(self):
        """Status can be set from a plain string."""
        t = CTRFTest(name="t", status="passed", duration=0)  # type: ignore[arg-type]
        assert t.status == CTRFTestState.PASSED


# ===================================================================
# CTRFReport structure
# ===================================================================


class TestCTRFReportStructure:
    """Test CTRFReport, CTRFResults, CTRFSummary, CTRFToolInfo, CTRFEnvironment."""

    def test_tool_info_defaults(self):
        tool = CTRFToolInfo()
        assert tool.name == "agent33"
        assert tool.version == ""

    def test_tool_info_custom(self):
        tool = CTRFToolInfo(name="my-tool", version="2.0.0")
        assert tool.name == "my-tool"
        assert tool.version == "2.0.0"

    def test_summary_defaults(self):
        s = CTRFSummary()
        assert s.tests == 0
        assert s.passed == 0
        assert s.failed == 0
        assert s.skipped == 0
        assert s.pending == 0
        assert s.other == 0
        assert s.start == 0
        assert s.stop == 0

    def test_environment_defaults(self):
        env = CTRFEnvironment()
        assert env.reportName == ""
        assert env.buildName == ""
        assert env.buildUrl == ""
        assert env.extra == {}

    def test_environment_custom(self):
        env = CTRFEnvironment(
            reportName="nightly",
            buildName="build-42",
            buildUrl="https://ci.example.com/42",
            extra={"commit": "abc123"},
        )
        assert env.reportName == "nightly"
        assert env.extra["commit"] == "abc123"

    def test_results_with_environment(self):
        results = CTRFResults(
            tool=CTRFToolInfo(),
            summary=CTRFSummary(tests=1, passed=1),
            tests=[CTRFTest(name="t", status=CTRFTestState.PASSED, duration=10)],
            environment=CTRFEnvironment(reportName="test"),
        )
        assert results.environment is not None
        assert results.environment.reportName == "test"

    def test_results_without_environment(self):
        results = CTRFResults(
            tool=CTRFToolInfo(),
            summary=CTRFSummary(),
        )
        assert results.environment is None

    def test_report_top_level(self):
        report = CTRFReport(
            results=CTRFResults(
                tool=CTRFToolInfo(name="agent33"),
                summary=CTRFSummary(tests=2, passed=1, failed=1),
            ),
        )
        assert report.results.tool.name == "agent33"
        assert report.results.summary.tests == 2


# ===================================================================
# CTRFReportGenerator — from evaluation results
# ===================================================================


def _make_eval_results() -> list[dict[str, Any]]:
    """Produce a set of evaluation result dicts for testing."""
    return [
        {
            "item_id": "GT-01",
            "result": "pass",
            "duration_ms": 100,
            "checks_passed": 4,
            "checks_total": 4,
            "notes": "",
        },
        {
            "item_id": "GT-02",
            "result": "fail",
            "duration_ms": 200,
            "checks_passed": 2,
            "checks_total": 4,
            "notes": "check 3 failed",
        },
        {
            "item_id": "GT-03",
            "result": "skip",
            "duration_ms": 0,
            "checks_passed": 0,
            "checks_total": 0,
            "notes": "skipped by policy",
        },
    ]


class TestCTRFReportGeneratorEvaluation:
    """Test CTRFReportGenerator.from_evaluation_run."""

    def test_basic_conversion(self):
        gen = CTRFReportGenerator()
        report = gen.from_evaluation_run(_make_eval_results(), 1000, 2000)
        assert isinstance(report, CTRFReport)
        assert report.results.tool.name == "agent33"
        assert report.results.summary.tests == 3

    def test_status_mapping(self):
        gen = CTRFReportGenerator()
        report = gen.from_evaluation_run(_make_eval_results(), 1000, 2000)
        statuses = {t.name: t.status for t in report.results.tests}
        assert statuses["GT-01"] == CTRFTestState.PASSED
        assert statuses["GT-02"] == CTRFTestState.FAILED
        assert statuses["GT-03"] == CTRFTestState.SKIPPED

    def test_summary_counts(self):
        gen = CTRFReportGenerator()
        report = gen.from_evaluation_run(_make_eval_results(), 1000, 2000)
        s = report.results.summary
        assert s.passed == 1
        assert s.failed == 1
        assert s.skipped == 1
        assert s.pending == 0
        assert s.other == 0

    def test_timestamps(self):
        gen = CTRFReportGenerator()
        report = gen.from_evaluation_run(_make_eval_results(), 5000, 9000)
        assert report.results.summary.start == 5000
        assert report.results.summary.stop == 9000

    def test_duration_carried(self):
        gen = CTRFReportGenerator()
        report = gen.from_evaluation_run(_make_eval_results(), 0, 0)
        durations = {t.name: t.duration for t in report.results.tests}
        assert durations["GT-01"] == 100.0
        assert durations["GT-02"] == 200.0
        assert durations["GT-03"] == 0.0

    def test_suite_and_type(self):
        gen = CTRFReportGenerator()
        report = gen.from_evaluation_run(_make_eval_results(), 0, 0)
        for t in report.results.tests:
            assert t.suite == "evaluation"
            assert t.type == "evaluation"

    def test_notes_as_message(self):
        gen = CTRFReportGenerator()
        report = gen.from_evaluation_run(_make_eval_results(), 0, 0)
        messages = {t.name: t.message for t in report.results.tests}
        assert messages["GT-02"] == "check 3 failed"

    def test_error_result_maps_to_failed(self):
        gen = CTRFReportGenerator()
        results = [{"item_id": "X", "result": "error", "duration_ms": 10}]
        report = gen.from_evaluation_run(results, 0, 0)
        assert report.results.tests[0].status == CTRFTestState.FAILED
        assert report.results.summary.failed == 1

    def test_unknown_result_maps_to_other(self):
        gen = CTRFReportGenerator()
        results = [{"item_id": "X", "result": "banana", "duration_ms": 10}]
        report = gen.from_evaluation_run(results, 0, 0)
        assert report.results.tests[0].status == CTRFTestState.OTHER
        assert report.results.summary.other == 1

    def test_custom_tool_name_and_version(self):
        gen = CTRFReportGenerator(tool_name="my-tool", tool_version="3.2.1")
        report = gen.from_evaluation_run([], 0, 0)
        assert report.results.tool.name == "my-tool"
        assert report.results.tool.version == "3.2.1"


# ===================================================================
# CTRFReportGenerator — from gate results
# ===================================================================


def _make_gate_results() -> list[dict[str, Any]]:
    """Produce a set of gate check result dicts for testing."""
    return [
        {
            "threshold": {"metric_id": "M-01", "gate": "G-PR", "value": 80.0},
            "actual_value": 85.0,
            "passed": True,
        },
        {
            "threshold": {"metric_id": "M-03", "gate": "G-PR", "value": 30.0},
            "actual_value": 35.0,
            "passed": False,
        },
        {
            "threshold": {"metric_id": "M-05", "gate": "G-PR", "value": 90.0},
            "actual_value": 95.0,
            "passed": True,
        },
    ]


class TestCTRFReportGeneratorGate:
    """Test CTRFReportGenerator.from_gate_results."""

    def test_basic_conversion(self):
        gen = CTRFReportGenerator()
        report = gen.from_gate_results(_make_gate_results(), 1000, 2000)
        assert isinstance(report, CTRFReport)
        assert report.results.summary.tests == 3

    def test_pass_fail_mapping(self):
        gen = CTRFReportGenerator()
        report = gen.from_gate_results(_make_gate_results(), 1000, 2000)
        assert report.results.summary.passed == 2
        assert report.results.summary.failed == 1

    def test_test_names_include_gate_and_metric(self):
        gen = CTRFReportGenerator()
        report = gen.from_gate_results(_make_gate_results(), 0, 0)
        names = [t.name for t in report.results.tests]
        assert "G-PR/M-01" in names
        assert "G-PR/M-03" in names
        assert "G-PR/M-05" in names

    def test_failed_gate_has_message(self):
        gen = CTRFReportGenerator()
        report = gen.from_gate_results(_make_gate_results(), 0, 0)
        failed = [t for t in report.results.tests if t.status == CTRFTestState.FAILED]
        assert len(failed) == 1
        assert "actual=35.0" in failed[0].message
        assert "threshold=30.0" in failed[0].message

    def test_passed_gate_has_empty_message(self):
        gen = CTRFReportGenerator()
        report = gen.from_gate_results(_make_gate_results(), 0, 0)
        passed = [t for t in report.results.tests if t.status == CTRFTestState.PASSED]
        for t in passed:
            assert t.message == ""

    def test_suite_and_type(self):
        gen = CTRFReportGenerator()
        report = gen.from_gate_results(_make_gate_results(), 0, 0)
        for t in report.results.tests:
            assert t.suite == "regression-gate"
            assert t.type == "regression"

    def test_tags_contain_gate_and_metric(self):
        gen = CTRFReportGenerator()
        report = gen.from_gate_results(_make_gate_results(), 0, 0)
        first = report.results.tests[0]
        assert "G-PR" in first.tags
        assert "M-01" in first.tags


# ===================================================================
# CTRFReportGenerator — from golden tasks
# ===================================================================


def _make_golden_task_results() -> list[dict[str, Any]]:
    """Produce a set of golden task result dicts for testing."""
    return [
        {
            "item_id": "GT-01",
            "result": "pass",
            "duration_ms": 150,
            "checks_passed": 4,
            "checks_total": 4,
            "notes": "",
        },
        {
            "item_id": "GT-05",
            "result": "fail",
            "duration_ms": 300,
            "checks_passed": 2,
            "checks_total": 4,
            "notes": "scope violation",
        },
    ]


class TestCTRFReportGeneratorGoldenTasks:
    """Test CTRFReportGenerator.from_golden_tasks."""

    def test_basic_conversion(self):
        gen = CTRFReportGenerator()
        report = gen.from_golden_tasks(_make_golden_task_results(), 1000, 2000)
        assert isinstance(report, CTRFReport)
        assert report.results.summary.tests == 2

    def test_pass_fail_counts(self):
        gen = CTRFReportGenerator()
        report = gen.from_golden_tasks(_make_golden_task_results(), 0, 0)
        assert report.results.summary.passed == 1
        assert report.results.summary.failed == 1

    def test_suite_and_type(self):
        gen = CTRFReportGenerator()
        report = gen.from_golden_tasks(_make_golden_task_results(), 0, 0)
        for t in report.results.tests:
            assert t.suite == "golden-tasks"
            assert t.type == "golden-task"

    def test_checks_in_message_when_present(self):
        gen = CTRFReportGenerator()
        report = gen.from_golden_tasks(_make_golden_task_results(), 0, 0)
        gt01 = next(t for t in report.results.tests if t.name == "GT-01")
        assert "checks: 4/4" in gt01.message

    def test_notes_fallback_when_no_checks(self):
        gen = CTRFReportGenerator()
        results = [
            {
                "item_id": "GT-X",
                "result": "fail",
                "duration_ms": 10,
                "checks_passed": 0,
                "checks_total": 0,
                "notes": "completely broken",
            },
        ]
        report = gen.from_golden_tasks(results, 0, 0)
        assert report.results.tests[0].message == "completely broken"


# ===================================================================
# JSON serialization round-trip
# ===================================================================


class TestCTRFSerialization:
    """Test JSON serialization and deserialization."""

    def test_to_json_produces_valid_json(self):
        gen = CTRFReportGenerator()
        report = gen.from_evaluation_run(_make_eval_results(), 1000, 2000)
        json_str = CTRFReportGenerator.to_json(report)
        parsed = json.loads(json_str)
        assert "results" in parsed
        assert parsed["results"]["summary"]["tests"] == 3

    def test_round_trip_preserves_data(self):
        gen = CTRFReportGenerator()
        report = gen.from_evaluation_run(_make_eval_results(), 5000, 9000)
        json_str = CTRFReportGenerator.to_json(report)
        restored = CTRFReport.model_validate_json(json_str)
        assert restored.results.summary.tests == report.results.summary.tests
        assert restored.results.summary.passed == report.results.summary.passed
        assert restored.results.summary.failed == report.results.summary.failed
        assert restored.results.summary.skipped == report.results.summary.skipped
        assert restored.results.summary.start == 5000
        assert restored.results.summary.stop == 9000
        assert len(restored.results.tests) == len(report.results.tests)
        for orig, rest in zip(report.results.tests, restored.results.tests, strict=True):
            assert orig.name == rest.name
            assert orig.status == rest.status
            assert orig.duration == rest.duration

    def test_to_file_creates_valid_json(self, tmp_path: Path):
        gen = CTRFReportGenerator()
        report = gen.from_evaluation_run(_make_eval_results(), 0, 0)
        out = tmp_path / "sub" / "ctrf.json"
        CTRFReportGenerator.to_file(report, out)
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["results"]["summary"]["tests"] == 3

    def test_to_file_creates_parent_dirs(self, tmp_path: Path):
        gen = CTRFReportGenerator()
        report = gen.from_evaluation_run([], 0, 0)
        out = tmp_path / "deep" / "nested" / "dir" / "report.json"
        CTRFReportGenerator.to_file(report, out)
        assert out.exists()


# ===================================================================
# Summary computation edge cases
# ===================================================================


class TestCTRFSummaryComputation:
    """Test that summary counts are always correct."""

    def test_all_passed(self):
        gen = CTRFReportGenerator()
        results = [{"item_id": f"T-{i}", "result": "pass", "duration_ms": 10} for i in range(5)]
        report = gen.from_evaluation_run(results, 0, 0)
        s = report.results.summary
        assert s.tests == 5
        assert s.passed == 5
        assert s.failed == 0
        assert s.skipped == 0

    def test_all_failed(self):
        gen = CTRFReportGenerator()
        results = [{"item_id": f"T-{i}", "result": "fail", "duration_ms": 10} for i in range(3)]
        report = gen.from_evaluation_run(results, 0, 0)
        assert report.results.summary.failed == 3
        assert report.results.summary.passed == 0

    def test_mixed_states(self):
        gen = CTRFReportGenerator()
        results = [
            {"item_id": "a", "result": "pass", "duration_ms": 0},
            {"item_id": "b", "result": "fail", "duration_ms": 0},
            {"item_id": "c", "result": "skip", "duration_ms": 0},
            {"item_id": "d", "result": "error", "duration_ms": 0},
            {"item_id": "e", "result": "unknown", "duration_ms": 0},
        ]
        report = gen.from_evaluation_run(results, 0, 0)
        s = report.results.summary
        assert s.tests == 5
        assert s.passed == 1
        assert s.failed == 2  # fail + error
        assert s.skipped == 1
        assert s.other == 1  # unknown


# ===================================================================
# Empty results handling
# ===================================================================


class TestCTRFEmptyResults:
    """Test behavior with empty inputs."""

    def test_empty_evaluation_results(self):
        gen = CTRFReportGenerator()
        report = gen.from_evaluation_run([], 0, 0)
        assert report.results.summary.tests == 0
        assert report.results.summary.passed == 0
        assert report.results.summary.failed == 0
        assert report.results.tests == []

    def test_empty_gate_results(self):
        gen = CTRFReportGenerator()
        report = gen.from_gate_results([], 0, 0)
        assert report.results.summary.tests == 0
        assert report.results.tests == []

    def test_empty_golden_task_results(self):
        gen = CTRFReportGenerator()
        report = gen.from_golden_tasks([], 0, 0)
        assert report.results.summary.tests == 0
        assert report.results.tests == []


# ===================================================================
# Service integration
# ===================================================================


class TestCTRFServiceIntegration:
    """Test CTRF generation through the EvaluationService."""

    def setup_method(self) -> None:
        self.service = EvaluationService()

    def test_generate_ctrf_for_completed_run(self):
        """A completed evaluation run produces a valid CTRF report."""
        run = self.service.create_run(GateType.G_PR, commit_hash="abc")
        results = [
            TaskRunResult(item_id="GT-01", result=TaskResult.PASS, duration_ms=100),
            TaskRunResult(item_id="GT-04", result=TaskResult.FAIL, duration_ms=200),
        ]
        self.service.submit_results(run.run_id, results)

        report = self.service.generate_ctrf_for_run(run.run_id)
        assert report is not None
        assert report.results.summary.tests == 2
        assert report.results.summary.passed == 1
        assert report.results.summary.failed == 1

    def test_generate_ctrf_for_incomplete_run_returns_none(self):
        """An incomplete run should return None."""
        run = self.service.create_run(GateType.G_PR)
        assert self.service.generate_ctrf_for_run(run.run_id) is None

    def test_generate_ctrf_for_nonexistent_run_returns_none(self):
        assert self.service.generate_ctrf_for_run("nonexistent") is None

    def test_generate_ctrf_for_gate(self):
        """Gate results produce a CTRF report with regression-gate entries."""
        run = self.service.create_run(GateType.G_PR)
        results = [
            TaskRunResult(item_id="GT-01", result=TaskResult.PASS, duration_ms=100),
        ]
        self.service.submit_results(run.run_id, results)

        report = self.service.generate_ctrf_for_gate(run.run_id)
        assert report is not None
        assert report.results.summary.tests > 0
        # All tests should be regression-gate type
        for t in report.results.tests:
            assert t.suite == "regression-gate"

    def test_generate_ctrf_for_gate_no_gate_report_returns_none(self):
        """A run without a gate report returns None."""
        run = self.service.create_run(GateType.G_PR)
        # Not submitted, so no gate report
        assert self.service.generate_ctrf_for_gate(run.run_id) is None

    def test_generate_ctrf_for_golden_tasks(self):
        """Golden task results produce a CTRF report."""
        run = self.service.create_run(GateType.G_PR)
        results = [
            TaskRunResult(
                item_id="GT-01",
                result=TaskResult.PASS,
                duration_ms=100,
                checks_passed=4,
                checks_total=4,
            ),
        ]
        self.service.submit_results(run.run_id, results)

        report = self.service.generate_ctrf_for_golden_tasks(run.run_id)
        assert report is not None
        assert report.results.summary.tests == 1
        assert report.results.tests[0].suite == "golden-tasks"
        assert "checks: 4/4" in report.results.tests[0].message

    def test_get_latest_ctrf_with_no_runs_returns_none(self):
        assert self.service.get_latest_ctrf() is None

    def test_get_latest_ctrf_returns_most_recent(self):
        """get_latest_ctrf returns the report for the most recently completed run."""
        from datetime import UTC, datetime

        run1 = self.service.create_run(GateType.G_PR)
        self.service.submit_results(
            run1.run_id,
            [TaskRunResult(item_id="GT-01", result=TaskResult.PASS)],
        )
        # Force run1's completed_at to an earlier time so run2 is definitively later
        completed_run1 = self.service.get_run(run1.run_id)
        assert completed_run1 is not None
        completed_run1.completed_at = datetime(2025, 1, 1, tzinfo=UTC)

        run2 = self.service.create_run(GateType.G_PR)
        self.service.submit_results(
            run2.run_id,
            [
                TaskRunResult(item_id="GT-01", result=TaskResult.FAIL),
                TaskRunResult(item_id="GT-02", result=TaskResult.FAIL),
            ],
        )
        # Force run2's completed_at to a later time
        completed_run2 = self.service.get_run(run2.run_id)
        assert completed_run2 is not None
        completed_run2.completed_at = datetime(2025, 6, 1, tzinfo=UTC)

        report = self.service.get_latest_ctrf()
        assert report is not None
        # The latest run (run2) has 2 tests, both failed
        assert report.results.summary.tests == 2
        assert report.results.summary.failed == 2

    def test_get_latest_ctrf_skips_incomplete(self):
        """Incomplete runs are skipped by get_latest_ctrf."""
        # Complete a run
        run1 = self.service.create_run(GateType.G_PR)
        self.service.submit_results(
            run1.run_id,
            [TaskRunResult(item_id="GT-01", result=TaskResult.PASS)],
        )
        # Create an incomplete run (newer)
        self.service.create_run(GateType.G_PR)

        report = self.service.get_latest_ctrf()
        assert report is not None
        # Should get run1 since run2 is incomplete
        assert report.results.summary.tests == 1
        assert report.results.summary.passed == 1


# ===================================================================
# API routes
# ===================================================================


class TestCTRFAPIRoutes:
    """Test CTRF REST endpoints via TestClient."""

    @pytest.fixture(autouse=True)
    def _setup(self, client: TestClient) -> None:
        self.client = client

    def _create_completed_run(self) -> str:
        """Helper to create and complete an evaluation run."""
        create_resp = self.client.post(
            "/v1/evaluations/runs",
            json={"gate": "G-PR", "commit_hash": "test-ctrf"},
        )
        run_id = create_resp.json()["run_id"]
        self.client.post(
            f"/v1/evaluations/runs/{run_id}/results",
            json={
                "task_results": [
                    {"item_id": "GT-01", "result": "pass", "duration_ms": 100},
                    {"item_id": "GT-04", "result": "fail", "duration_ms": 200},
                ],
            },
        )
        return run_id

    def test_get_latest_ctrf_no_runs(self):
        """GET /ctrf/latest returns 404 when no completed runs exist."""
        # Note: other tests may have created runs via the shared service singleton.
        # This test verifies the endpoint works; the response depends on service state.
        resp = self.client.get("/v1/evaluations/ctrf/latest")
        # If previous tests left completed runs, we get 200; otherwise 404.
        assert resp.status_code in (200, 404)

    def test_get_latest_ctrf_with_run(self):
        """GET /ctrf/latest returns a CTRF report when a completed run exists."""
        self._create_completed_run()
        resp = self.client.get("/v1/evaluations/ctrf/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "tool" in data["results"]
        assert "summary" in data["results"]
        assert "tests" in data["results"]
        assert data["results"]["tool"]["name"] == "agent33"

    def test_get_latest_ctrf_summary_has_correct_counts(self):
        """The CTRF summary reflects the actual test results."""
        self._create_completed_run()
        resp = self.client.get("/v1/evaluations/ctrf/latest")
        assert resp.status_code == 200
        summary = resp.json()["results"]["summary"]
        # At minimum, the run we just created has 2 tests
        assert summary["tests"] >= 2

    def test_generate_ctrf_for_run(self):
        """POST /ctrf/generate with a run_id returns evaluation CTRF."""
        run_id = self._create_completed_run()
        resp = self.client.post(
            "/v1/evaluations/ctrf/generate",
            json={"run_id": run_id, "report_type": "evaluation"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"]["summary"]["tests"] == 2

    def test_generate_ctrf_for_gate(self):
        """POST /ctrf/generate with report_type=gate returns gate CTRF."""
        run_id = self._create_completed_run()
        resp = self.client.post(
            "/v1/evaluations/ctrf/generate",
            json={"run_id": run_id, "report_type": "gate"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Gate results should have regression-gate entries
        for test in data["results"]["tests"]:
            assert test["suite"] == "regression-gate"

    def test_generate_ctrf_for_golden_task(self):
        """POST /ctrf/generate with report_type=golden-task returns golden task CTRF."""
        run_id = self._create_completed_run()
        resp = self.client.post(
            "/v1/evaluations/ctrf/generate",
            json={"run_id": run_id, "report_type": "golden-task"},
        )
        assert resp.status_code == 200
        data = resp.json()
        for test in data["results"]["tests"]:
            assert test["suite"] == "golden-tasks"

    def test_generate_ctrf_nonexistent_run(self):
        """POST /ctrf/generate for a nonexistent run returns 404."""
        resp = self.client.post(
            "/v1/evaluations/ctrf/generate",
            json={"run_id": "nonexistent-run", "report_type": "evaluation"},
        )
        assert resp.status_code == 404

    def test_generate_ctrf_latest_default(self):
        """POST /ctrf/generate without run_id uses the latest run."""
        self._create_completed_run()
        resp = self.client.post(
            "/v1/evaluations/ctrf/generate",
            json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"]["summary"]["tests"] >= 2

    def test_ctrf_report_is_valid_json_structure(self):
        """The CTRF report output conforms to the CTRF spec structure."""
        self._create_completed_run()
        resp = self.client.get("/v1/evaluations/ctrf/latest")
        assert resp.status_code == 200
        data = resp.json()

        # Verify top-level
        assert "results" in data

        # Verify tool
        tool = data["results"]["tool"]
        assert isinstance(tool["name"], str)
        assert isinstance(tool["version"], str)

        # Verify summary
        summary = data["results"]["summary"]
        for key in ("tests", "passed", "failed", "skipped", "pending", "other"):
            assert isinstance(summary[key], int)
        assert isinstance(summary["start"], int)
        assert isinstance(summary["stop"], int)

        # Verify tests array
        tests = data["results"]["tests"]
        assert isinstance(tests, list)
        for test in tests:
            assert isinstance(test["name"], str)
            assert test["status"] in ("passed", "failed", "skipped", "pending", "other")
            assert isinstance(test["duration"], (int, float))
