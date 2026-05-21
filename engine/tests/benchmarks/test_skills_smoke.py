"""SkillsBench smoke benchmark tests.

Fast, deterministic smoke tests that validate core evaluation service functionality.
Tests use existing EvaluationService and CTRF reporting infrastructure.

These benchmarks are non-blocking in CI and generate CTRF reports for artifact upload.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent33.evaluation.ctrf import CTRFGenerator
from agent33.evaluation.models import GateType
from agent33.evaluation.multi_trial import (
    ExperimentConfig,
    MultiTrialResult,
    MultiTrialRun,
    TrialResult,
)
from agent33.evaluation.service import EvaluationService

pytestmark = [pytest.mark.benchmark, pytest.mark.smoke]


def write_benchmark_ctrf(
    test_results: list[dict[str, Any]],
    output_path: Path | None = None,
    tool_name: str = "agent33-benchmark-smoke",
) -> None:
    """Write pytest benchmark results as CTRF report.

    Args:
        test_results: List of test dicts with name, status, duration_ms
        output_path: Path to write CTRF JSON (from env or default)
        tool_name: Tool identifier for report
    """
    if output_path is None:
        env_path = os.environ.get("AGENT33_SMOKE_CTRF_PATH")
        output_path = Path(env_path) if env_path else Path("test-results/ctrf-smoke-report.json")

    # Calculate summary statistics
    total = len(test_results)
    passed = sum(1 for t in test_results if t["status"] == "passed")
    failed = sum(1 for t in test_results if t["status"] == "failed")
    skipped = sum(1 for t in test_results if t["status"] == "skipped")

    # Get timing bounds
    start_time = min((t.get("start_ms", 0) for t in test_results), default=0)
    stop_time = max((t.get("stop_ms", 0) for t in test_results), default=0)

    # Build CTRF-compliant report
    report = {
        "results": {
            "tool": {
                "name": tool_name,
                "version": "1.0.0",
            },
            "summary": {
                "tests": total,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "pending": 0,
                "other": 0,
                "start": start_time,
                "stop": stop_time,
            },
            "extra": {
                "skillsbench": {
                    "suite": "smoke",
                    "task_summaries": [
                        {
                            "task_id": t["name"],
                            "category": "smoke",
                            "total_trials": 1,
                            "passed_trials": 1 if t["status"] == "passed" else 0,
                            "failed_trials": 1 if t["status"] == "failed" else 0,
                            "error_trials": 0,
                            "skipped_trials": 1 if t["status"] == "skipped" else 0,
                            "pass_rate": 1.0 if t["status"] == "passed" else 0.0,
                            "avg_duration_ms": t["duration_ms"],
                            "total_tokens_used": 0,
                        }
                        for t in test_results
                    ],
                }
            },
            "tests": [
                {
                    "name": t["name"],
                    "status": t["status"],
                    "duration": t["duration_ms"],
                    "suite": "skillsbench-smoke",
                    "type": "smoke-benchmark",
                    "extra": {
                        "skillsbench": {
                            "task_id": t["name"],
                            "category": "smoke",
                        }
                    },
                }
                for t in test_results
            ],
        },
    }

    # Write report to disk
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2))


class TestSkillsBenchSmoke:
    """Smoke tests for SkillsBench evaluation harness.

    These tests validate core functionality of the evaluation service,
    CTRF reporting, and integration touchpoints. All tests are designed
    to be fast (<100ms each) and deterministic.
    """

    def test_service_initialization(self) -> None:
        """Verify EvaluationService initializes without errors.

        Tests:
        - Service creation
        - Component wiring (calculator, enforcer, detector)
        - Internal registries initialization
        """
        start = time.perf_counter()

        service = EvaluationService()

        # Verify service instance
        assert service is not None
        assert hasattr(service, "recorder")

        # Verify internal components exist
        assert service._calculator is not None
        assert service._enforcer is not None
        assert service._detector is not None
        assert service._recorder is not None
        assert service._ctrf is not None

        # Verify registries are initialized
        assert isinstance(service._runs, dict)
        assert isinstance(service._baselines, dict)
        assert isinstance(service._multi_trial_runs, dict)

        elapsed = time.perf_counter() - start
        assert elapsed < 0.1, f"Service init took {elapsed:.3f}s, expected <100ms"

    def test_golden_tasks_registry(self) -> None:
        """Verify golden task registry is accessible and populated.

        Tests:
        - list_golden_tasks() returns non-empty list
        - Task schema is valid (has required fields)
        - list_golden_cases() is accessible
        """
        start = time.perf_counter()

        service = EvaluationService()

        # Test golden tasks
        tasks = service.list_golden_tasks()
        assert tasks is not None
        assert isinstance(tasks, list)
        assert len(tasks) > 0, "Golden task registry should not be empty"

        # Verify task structure
        first_task = tasks[0]
        assert "task_id" in first_task
        assert isinstance(first_task["task_id"], str)

        # Test golden cases
        cases = service.list_golden_cases()
        assert cases is not None
        assert isinstance(cases, list)

        elapsed = time.perf_counter() - start
        assert elapsed < 0.1, f"Registry access took {elapsed:.3f}s, expected <100ms"

    def test_ctrf_report_generation(self) -> None:
        """Verify CTRF report can be generated from test run.

        Tests:
        - CTRFGenerator integration
        - Schema compliance (required fields)
        - MultiTrialRun → CTRF conversion
        """
        start = time.perf_counter()

        # Create a minimal MultiTrialRun
        trial = TrialResult(trial_number=1, score=1, duration_ms=50)
        result = MultiTrialResult(
            task_id="test-task",
            agent="test-agent",
            model="test-model",
            skills_enabled=True,
            trials=[trial],
            total_tokens=100,
            total_duration_ms=50,
        )
        run = MultiTrialRun(
            run_id="test-run-id",
            config=ExperimentConfig(
                tasks=["test-task"],
                agents=["test-agent"],
                models=["test-model"],
            ),
            results=[result],
            started_at=datetime.now(UTC),
        )

        # Generate CTRF report
        generator = CTRFGenerator()
        report = generator.generate_report(run)

        # Verify CTRF schema compliance
        assert "results" in report
        assert "tool" in report["results"]
        assert "summary" in report["results"]
        assert "tests" in report["results"]

        # Verify tool info
        assert report["results"]["tool"]["name"] == "agent33-eval"
        assert "version" in report["results"]["tool"]

        # Verify summary
        summary = report["results"]["summary"]
        assert summary["tests"] == 1
        assert summary["passed"] + summary["failed"] == 1
        assert "start" in summary
        assert "stop" in summary

        # Verify test entries
        tests = report["results"]["tests"]
        assert len(tests) == 1
        assert tests[0]["name"] == "test-task [test-agent/test-model] +skills"
        assert tests[0]["status"] in ["passed", "failed"]
        assert "duration" in tests[0]

        elapsed = time.perf_counter() - start
        assert elapsed < 0.15, f"CTRF generation took {elapsed:.3f}s, expected <150ms"

    def test_gate_type_enumeration(self) -> None:
        """Verify gate types are defined and queryable.

        Tests:
        - GateType enum is accessible
        - get_tasks_for_gate() returns task lists
        - Known gates have defined task mappings
        """
        start = time.perf_counter()

        service = EvaluationService()

        # Test GateType enum
        assert hasattr(GateType, "G_PR")
        assert hasattr(GateType, "G_MRG")
        assert hasattr(GateType, "G_REL")
        assert hasattr(GateType, "G_MON")

        # Test get_tasks_for_gate for each gate type
        for gate in [GateType.G_PR, GateType.G_MRG, GateType.G_REL, GateType.G_MON]:
            tasks = service.get_tasks_for_gate(gate)
            assert tasks is not None
            assert isinstance(tasks, list)
            # Smoke gate should have at least one task
            if gate == GateType.G_PR:
                assert len(tasks) > 0, "G-PR gate should have smoke tasks"

        elapsed = time.perf_counter() - start
        assert elapsed < 0.1, f"Gate enumeration took {elapsed:.3f}s, expected <100ms"

    def test_golden_task_executions(self) -> None:
        """Simulate execution of 3-5 golden tasks for SkillsBench integration.

        Tests:
        - Ability to slice and execute the first 3 golden tasks.
        - Proper accumulation of MultiTrialResult.
        - CTRF report generation for multiple tasks.
        """
        start = time.perf_counter()
        service = EvaluationService()
        tasks = service.list_golden_tasks()[:3]
        assert len(tasks) == 3, "Expected at least 3 golden tasks to be defined"

        results = []
        for i, task in enumerate(tasks):
            # Simulate a multi-trial result for each task
            trial = TrialResult(trial_number=1, score=1, duration_ms=40 + i)
            result = MultiTrialResult(
                task_id=task.get("task_id", f"task-{i}"),
                agent="agent33-coder",
                model="qwen3-coder:30b",
                skills_enabled=True,
                trials=[trial],
                total_tokens=150,
                total_duration_ms=40 + i,
            )
            results.append(result)

        run = MultiTrialRun(
            run_id="golden-execution-run",
            config=ExperimentConfig(
                tasks=[t.get("task_id", "") for t in tasks],
                agents=["agent33-coder"],
                models=["qwen3-coder:30b"],
            ),
            results=results,
            started_at=datetime.now(UTC),
        )

        generator = CTRFGenerator()
        report = generator.generate_report(run)
        assert report["results"]["summary"]["tests"] == 3

        elapsed = time.perf_counter() - start
        assert elapsed < 0.2, f"Golden task simulation took {elapsed:.3f}s, expected <200ms"


def test_write_ctrf_helper() -> None:
    """Test that CTRF helper writes valid reports.

    This test validates the write_benchmark_ctrf helper function and
    generates a sample CTRF report for CI artifact upload.
    """
    # Sample test results
    test_results = [
        {
            "name": "test_example_pass",
            "status": "passed",
            "duration_ms": 42,
            "start_ms": 1700000000000,
            "stop_ms": 1700000000042,
        },
        {
            "name": "test_example_fail",
            "status": "failed",
            "duration_ms": 15,
            "start_ms": 1700000000100,
            "stop_ms": 1700000000115,
        },
    ]

    # Get output path from environment or use default
    env_path = os.environ.get("AGENT33_SMOKE_CTRF_PATH")
    output_path = Path(env_path) if env_path else Path("test-results/ctrf-smoke-report.json")

    # Write the report
    write_benchmark_ctrf(test_results, output_path)

    # Verify the file was created and is valid JSON
    assert output_path.exists(), f"CTRF report not created at {output_path}"

    # Parse and validate schema
    with open(output_path) as f:
        report = json.load(f)

    # Verify CTRF structure
    assert "results" in report
    assert "tool" in report["results"]
    assert "summary" in report["results"]
    assert "tests" in report["results"]
    assert report["results"]["extra"]["skillsbench"]["suite"] == "smoke"

    # Verify summary counts
    summary = report["results"]["summary"]
    assert summary["tests"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1

    # Verify test entries
    tests = report["results"]["tests"]
    assert len(tests) == 2
    assert tests[0]["name"] == "test_example_pass"
    assert tests[0]["status"] == "passed"
    assert tests[0]["extra"]["skillsbench"]["task_id"] == "test_example_pass"
