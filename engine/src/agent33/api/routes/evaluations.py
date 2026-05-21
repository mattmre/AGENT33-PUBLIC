"""FastAPI router for evaluation suite and regression gates."""

# NOTE: no ``from __future__ import annotations`` — Pydantic needs these
# types at runtime for request-body validation.

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent33.evaluation.models import (
    GateType,
    TaskResult,
    TriageStatus,
)
from agent33.evaluation.service import EvaluationService
from agent33.security.permissions import require_scope

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/evaluations", tags=["evaluations"])

# Singleton service
_service = EvaluationService()


def get_evaluation_service() -> EvaluationService:
    """Return the evaluation service singleton (for testing injection)."""
    return _service


def set_evaluation_service(service: EvaluationService) -> None:
    """Inject a shared evaluation service instance (called during app lifespan)."""
    global _service  # noqa: PLW0603
    _service = service


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateRunRequest(BaseModel):
    gate: GateType = GateType.G_PR
    commit_hash: str = ""
    branch: str = ""


class TaskResultInput(BaseModel):
    item_id: str
    result: TaskResult = TaskResult.PASS
    checks_passed: int = 0
    checks_total: int = 0
    duration_ms: int = 0
    notes: str = ""


class SubmitResultsRequest(BaseModel):
    task_results: list[TaskResultInput] = Field(default_factory=list)
    rework_count: int = 0
    scope_violations: int = 0


class SaveBaselineRequest(BaseModel):
    commit_hash: str = ""
    branch: str = ""


class UpdateTriageRequest(BaseModel):
    status: TriageStatus
    assignee: str = ""


class ResolveRegressionRequest(BaseModel):
    resolved_by: str = ""
    fix_commit: str = ""


# ---------------------------------------------------------------------------
# Golden task routes
# ---------------------------------------------------------------------------


@router.get(
    "/golden-tasks",
    dependencies=[require_scope("workflows:read")],
)
async def list_golden_tasks() -> list[dict[str, Any]]:
    """List all golden task definitions."""
    return _service.list_golden_tasks()


@router.get(
    "/golden-cases",
    dependencies=[require_scope("workflows:read")],
)
async def list_golden_cases() -> list[dict[str, Any]]:
    """List all golden case definitions."""
    return _service.list_golden_cases()


@router.get(
    "/gates/{gate}/tasks",
    dependencies=[require_scope("workflows:read")],
)
async def get_tasks_for_gate(gate: GateType) -> list[str]:
    """Get golden task IDs required for a specific gate."""
    return _service.get_tasks_for_gate(gate)


# ---------------------------------------------------------------------------
# Evaluation run routes
# ---------------------------------------------------------------------------


@router.post(
    "/runs",
    status_code=201,
    dependencies=[require_scope("tools:execute")],
)
async def create_run(body: CreateRunRequest) -> dict[str, Any]:
    """Create a new evaluation run."""
    run = _service.create_run(
        gate=body.gate,
        commit_hash=body.commit_hash,
        branch=body.branch,
    )
    return {"run_id": run.run_id, "gate": run.gate.value}


@router.get(
    "/runs",
    dependencies=[require_scope("workflows:read")],
)
async def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    """List evaluation runs."""
    runs = _service.list_runs(limit=limit)
    return [
        {
            "run_id": r.run_id,
            "gate": r.gate.value,
            "started_at": r.started_at.isoformat(),
            "completed": r.completed_at is not None,
        }
        for r in runs
    ]


@router.get(
    "/runs/{run_id}",
    dependencies=[require_scope("workflows:read")],
)
async def get_run(run_id: str) -> dict[str, Any]:
    """Get evaluation run details."""
    run = _service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return run.model_dump(mode="json")


@router.post(
    "/runs/{run_id}/results",
    dependencies=[require_scope("tools:execute")],
)
async def submit_results(run_id: str, body: SubmitResultsRequest) -> dict[str, Any]:
    """Submit golden task results to an evaluation run."""
    from agent33.evaluation.models import TaskRunResult

    task_results = [
        TaskRunResult(
            item_id=tr.item_id,
            result=tr.result,
            checks_passed=tr.checks_passed,
            checks_total=tr.checks_total,
            duration_ms=tr.duration_ms,
            notes=tr.notes,
        )
        for tr in body.task_results
    ]
    run = _service.submit_results(
        run_id=run_id,
        task_results=task_results,
        rework_count=body.rework_count,
        scope_violations=body.scope_violations,
    )
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return {
        "run_id": run.run_id,
        "gate_result": run.gate_report.overall.value if run.gate_report else None,
        "metrics": [m.model_dump() for m in run.metrics],
        "regressions_found": len(run.regressions),
    }


# ---------------------------------------------------------------------------
# Baseline routes
# ---------------------------------------------------------------------------


@router.post(
    "/runs/{run_id}/baseline",
    status_code=201,
    dependencies=[require_scope("tools:execute")],
)
async def save_baseline_from_run(run_id: str, body: SaveBaselineRequest) -> dict[str, Any]:
    """Save the results of a completed run as a baseline."""
    run = _service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    if run.completed_at is None:
        raise HTTPException(status_code=409, detail="Run not yet completed")
    baseline = _service.save_baseline(
        metrics=run.metrics,
        task_results=run.task_results,
        commit_hash=body.commit_hash or run.commit_hash,
        branch=body.branch or run.branch,
    )
    return {"baseline_id": baseline.baseline_id}


@router.get(
    "/baselines",
    dependencies=[require_scope("workflows:read")],
)
async def list_baselines(limit: int = 20) -> list[dict[str, Any]]:
    """List baseline snapshots."""
    baselines = _service.list_baselines(limit=limit)
    return [
        {
            "baseline_id": b.baseline_id,
            "commit_hash": b.commit_hash,
            "branch": b.branch,
            "created_at": b.created_at.isoformat(),
        }
        for b in baselines
    ]


# ---------------------------------------------------------------------------
# Regression routes
# ---------------------------------------------------------------------------


@router.get(
    "/regressions",
    dependencies=[require_scope("workflows:read")],
)
async def list_regressions(
    status: str | None = None,
    severity: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List regression records."""
    from agent33.evaluation.models import RegressionSeverity

    status_filter = TriageStatus(status) if status else None
    severity_filter = RegressionSeverity(severity) if severity else None
    records = _service.recorder.list_all(
        status=status_filter, severity=severity_filter, limit=limit
    )
    return [r.model_dump(mode="json") for r in records]


@router.patch(
    "/regressions/{regression_id}/triage",
    dependencies=[require_scope("tools:execute")],
)
async def update_triage(regression_id: str, body: UpdateTriageRequest) -> dict[str, Any]:
    """Update triage status for a regression."""
    record = _service.recorder.update_triage(
        regression_id=regression_id,
        status=body.status,
        assignee=body.assignee,
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"Regression not found: {regression_id}")
    return {"regression_id": record.regression_id, "status": record.triage_status.value}


@router.post(
    "/regressions/{regression_id}/resolve",
    dependencies=[require_scope("tools:execute")],
)
async def resolve_regression(regression_id: str, body: ResolveRegressionRequest) -> dict[str, Any]:
    """Mark a regression as resolved."""
    record = _service.recorder.resolve(
        regression_id=regression_id,
        resolved_by=body.resolved_by,
        fix_commit=body.fix_commit,
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"Regression not found: {regression_id}")
    return {
        "regression_id": record.regression_id,
        "status": record.triage_status.value,
    }


# ---------------------------------------------------------------------------
# Multi-trial experiment routes
# ---------------------------------------------------------------------------


class StartExperimentRequest(BaseModel):
    tasks: list[str] = Field(min_length=1, max_length=50)
    agents: list[str] = Field(min_length=1, max_length=20)
    models: list[str] = Field(min_length=1, max_length=20)
    trials_per_combination: int = Field(default=5, ge=1, le=100)
    skills_modes: list[bool] = Field(default_factory=lambda: [True, False])
    timeout_per_trial_seconds: int = Field(default=300, ge=1)
    parallel_trials: int = Field(default=1, ge=1)


@router.post(
    "/experiments",
    status_code=201,
    dependencies=[require_scope("tools:execute")],
)
async def start_experiment(body: StartExperimentRequest) -> dict[str, Any]:
    """Start a multi-trial experiment."""
    from agent33.evaluation.multi_trial import ExperimentConfig

    config = ExperimentConfig(
        tasks=body.tasks,
        agents=body.agents,
        models=body.models,
        trials_per_combination=body.trials_per_combination,
        skills_modes=body.skills_modes,
        timeout_per_trial_seconds=body.timeout_per_trial_seconds,
        parallel_trials=body.parallel_trials,
    )
    run = await _service.start_multi_trial_run(config)
    return {
        "run_id": run.run_id,
        "status": run.status,
        "results_count": len(run.results),
        "skills_impacts_count": len(run.skills_impacts),
    }


@router.get(
    "/experiments/{run_id}",
    dependencies=[require_scope("workflows:read")],
)
async def get_experiment(run_id: str) -> dict[str, Any]:
    """Get multi-trial experiment status and results."""
    run = _service.get_multi_trial_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Experiment not found: {run_id}")
    return run.model_dump(mode="json")


@router.get(
    "/experiments/{run_id}/ctrf",
    dependencies=[require_scope("workflows:read")],
)
async def get_experiment_ctrf(run_id: str) -> dict[str, Any]:
    """Export multi-trial experiment as a CTRF report."""
    report = _service.export_ctrf(run_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Experiment not found: {run_id}")
    return report


@router.get(
    "/experiments/{run_id}/skills-impact",
    dependencies=[require_scope("workflows:read")],
)
async def get_experiment_skills_impact(run_id: str) -> dict[str, Any]:
    """Get skills impact data for a multi-trial experiment."""
    run = _service.get_multi_trial_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Experiment not found: {run_id}")
    return {
        "run_id": run.run_id,
        "impacts": [i.model_dump(mode="json") for i in run.skills_impacts],
    }


# ---------------------------------------------------------------------------
# CTRF reporting routes
# ---------------------------------------------------------------------------


@router.get(
    "/ctrf/latest",
    dependencies=[require_scope("agents:read")],
)
async def get_latest_ctrf() -> dict[str, Any]:
    """Get the latest completed evaluation run as a CTRF JSON report."""
    report = _service.get_latest_ctrf()
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="No completed evaluation runs found",
        )
    return report.model_dump(mode="json")


class GenerateCTRFRequest(BaseModel):
    run_id: str = ""
    report_type: str = "evaluation"  # evaluation | gate | golden-task


@router.post(
    "/ctrf/generate",
    dependencies=[require_scope("admin")],
)
async def generate_ctrf(body: GenerateCTRFRequest) -> dict[str, Any]:
    """Generate a CTRF report from an evaluation run.

    If ``run_id`` is empty, the latest completed run is used.
    ``report_type`` controls which data is included in the report:
    ``"evaluation"`` (default), ``"gate"``, or ``"golden-task"``.
    """
    report = None

    if body.run_id:
        if body.report_type == "gate":
            report = _service.generate_ctrf_for_gate(body.run_id)
        elif body.report_type == "golden-task":
            report = _service.generate_ctrf_for_golden_tasks(body.run_id)
        else:
            report = _service.generate_ctrf_for_run(body.run_id)
    else:
        report = _service.get_latest_ctrf()

    if report is None:
        raise HTTPException(
            status_code=404,
            detail="No completed evaluation run found for CTRF generation",
        )

    return report.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Benchmark harness routes (S26)
# ---------------------------------------------------------------------------

_benchmark_harness: Any = None


def set_benchmark_harness(harness: Any) -> None:
    """Set the benchmark harness instance (called from lifespan)."""
    global _benchmark_harness  # noqa: PLW0603
    _benchmark_harness = harness


def _get_harness() -> Any:
    """Return the benchmark harness or raise 503."""
    if _benchmark_harness is None:
        raise HTTPException(
            status_code=503,
            detail="Benchmark harness not initialized",
        )
    return _benchmark_harness


class BenchmarkConfigRequest(BaseModel):
    trials_per_task: int = 5
    categories: list[str] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)
    timeout_seconds: int = 300
    with_skills: bool = True
    model_id: str = ""
    agent_id: str = ""


class BenchmarkCompareRequest(BaseModel):
    run_a_id: str
    run_b_id: str


@router.get(
    "/benchmark/catalog",
    dependencies=[require_scope("agents:read")],
)
async def list_benchmark_catalog(
    category: str | None = None,
) -> list[dict[str, Any]]:
    """List available benchmark tasks with optional category filter."""
    from agent33.evaluation.benchmark import BenchmarkConfig

    harness = _get_harness()
    config = BenchmarkConfig(
        categories=[category] if category else None,
    )
    tasks = harness.filter_catalog(config)
    return [t.model_dump() for t in tasks]


@router.post(
    "/benchmark/run",
    status_code=201,
    dependencies=[require_scope("admin")],
)
async def start_benchmark_run(body: BenchmarkConfigRequest) -> dict[str, Any]:
    """Start a benchmark run with the given configuration."""
    from agent33.evaluation.benchmark import BenchmarkConfig

    harness = _get_harness()
    config = BenchmarkConfig(
        trials_per_task=body.trials_per_task,
        categories=body.categories if body.categories else None,
        task_ids=body.task_ids if body.task_ids else None,
        timeout_seconds=body.timeout_seconds,
        with_skills=body.with_skills,
    )
    run = harness.run_benchmark(config, model_id=body.model_id, agent_id=body.agent_id)
    return {
        "run_id": run.run_id,
        "status": run.status,
        "total_tasks": run.total_tasks,
        "passed_tasks": run.passed_tasks,
        "failed_tasks": run.failed_tasks,
        "overall_pass_rate": run.overall_pass_rate,
    }


@router.get(
    "/benchmark/runs",
    dependencies=[require_scope("agents:read")],
)
async def list_benchmark_runs(limit: int = 50) -> list[dict[str, Any]]:
    """List benchmark runs, most recent first."""
    harness = _get_harness()
    runs = harness.list_runs(limit=limit)
    return [
        {
            "run_id": r.run_id,
            "status": r.status,
            "model_id": r.model_id,
            "agent_id": r.agent_id,
            "with_skills": r.with_skills,
            "total_tasks": r.total_tasks,
            "overall_pass_rate": r.overall_pass_rate,
            "started_at": r.started_at.isoformat(),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in runs
    ]


@router.get(
    "/benchmark/runs/{run_id}",
    dependencies=[require_scope("agents:read")],
)
async def get_benchmark_run(run_id: str) -> dict[str, Any]:
    """Get detailed benchmark run results."""
    harness = _get_harness()
    run = harness.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Benchmark run not found: {run_id}")
    result: dict[str, Any] = run.model_dump(mode="json")
    return result


@router.get(
    "/benchmark/runs/{run_id}/ctrf",
    dependencies=[require_scope("agents:read")],
)
async def get_benchmark_run_ctrf(run_id: str) -> dict[str, Any]:
    """Get CTRF report for a benchmark run."""
    harness = _get_harness()
    run = harness.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Benchmark run not found: {run_id}")
    report = harness.to_ctrf(run)
    result: dict[str, Any] = report.model_dump(mode="json")
    return result


@router.post(
    "/benchmark/compare",
    dependencies=[require_scope("agents:read")],
)
async def compare_benchmark_runs(body: BenchmarkCompareRequest) -> dict[str, Any]:
    """Compare two benchmark runs."""
    from agent33.evaluation.benchmark import BenchmarkHarness

    harness = _get_harness()
    run_a = harness.get_run(body.run_a_id)
    if run_a is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {body.run_a_id}")
    run_b = harness.get_run(body.run_b_id)
    if run_b is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {body.run_b_id}")
    return BenchmarkHarness.compare_runs(run_a, run_b)
