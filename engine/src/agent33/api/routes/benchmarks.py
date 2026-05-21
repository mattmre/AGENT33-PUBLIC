"""FastAPI router for benchmark run management.

Provides endpoints to trigger SkillsBench benchmark runs, list tasks,
and retrieve results.
"""

# NOTE: no ``from __future__ import annotations`` -- Pydantic needs these
# types at runtime for request-body validation.

from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import PlainTextResponse

from agent33.agents.runtime import AgentRuntime
from agent33.benchmarks.skillsbench.adapter import SkillsBenchAdapter
from agent33.benchmarks.skillsbench.config import SkillsBenchConfig
from agent33.benchmarks.skillsbench.models import (
    BenchmarkRunResult,
    BenchmarkRunStatus,
    TaskFilter,
)
from agent33.benchmarks.skillsbench.reporting import SkillsBenchCTRFGenerator
from agent33.benchmarks.skillsbench.runner import PytestBinaryRewardRunner
from agent33.benchmarks.skillsbench.storage import SkillsBenchArtifactStore
from agent33.benchmarks.skillsbench.task_loader import SkillsBenchTaskLoader
from agent33.config import settings
from agent33.security.permissions import _get_token_payload, require_scope
from agent33.tools.base import ToolContext

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/benchmarks", tags=["benchmarks"])

# In-memory storage for benchmark run results (bounded).
_MAX_STORED_RUNS = 100
_runs: dict[str, BenchmarkRunResult] = {}
_run_order: list[str] = []
_artifact_store: SkillsBenchArtifactStore | None = None
_ctrf = SkillsBenchCTRFGenerator()


def _get_artifact_store() -> SkillsBenchArtifactStore:
    """Return the shared SkillsBench artifact store."""
    global _artifact_store  # noqa: PLW0603
    if _artifact_store is None:
        _artifact_store = SkillsBenchArtifactStore(Path(settings.skillsbench_storage_path))
    return _artifact_store


def _cache_run(run: BenchmarkRunResult) -> None:
    """Cache a benchmark run with bounded retention."""
    _runs[run.run_id] = run
    if run.run_id in _run_order:
        _run_order.remove(run.run_id)
    _run_order.append(run.run_id)
    if len(_run_order) > _MAX_STORED_RUNS:
        oldest = _run_order.pop(0)
        _runs.pop(oldest, None)


def _store_run(run: BenchmarkRunResult) -> None:
    """Persist and cache a benchmark run with bounded retention."""
    _cache_run(run)
    store = _get_artifact_store()
    if not store.has_run(run.run_id):
        store.persist_run(run)


def _get_run(run_id: str) -> BenchmarkRunResult | None:
    """Fetch a run from memory or persisted storage."""
    run = _runs.get(run_id)
    if run is not None:
        return run
    try:
        run = _get_artifact_store().load_run(run_id)
    except ValueError:
        return None
    if run is not None:
        _cache_run(run)
    return run


def _get_state_dependency(request: Request, name: str) -> Any:
    """Fetch a required app.state dependency or raise a 503."""
    dependency = getattr(request.app.state, name, None)
    if dependency is None:
        raise HTTPException(
            status_code=503,
            detail=f"Application dependency not initialized: {name}",
        )
    return dependency


def _build_skillsbench_adapter(
    request: Request,
    config: SkillsBenchConfig,
) -> SkillsBenchAdapter:
    """Construct a fully wired SkillsBench adapter for the current app state."""
    agent_registry = _get_state_dependency(request, "agent_registry")
    model_router = _get_state_dependency(request, "model_router")
    skill_registry = _get_state_dependency(request, "skill_registry")
    tool_registry = _get_state_dependency(request, "tool_registry")

    definition = agent_registry.get(config.agent_name)
    if definition is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent definition not found: {config.agent_name}",
        )

    token_payload = _get_token_payload(request)
    tool_context = ToolContext(
        user_scopes=token_payload.scopes,
        tool_policies=definition.governance.tool_policies,
        requested_by=token_payload.sub,
        tenant_id=token_payload.tenant_id or "",
    )

    runtime = AgentRuntime(
        definition=definition,
        router=model_router,
        model=config.model,
        skill_injector=getattr(request.app.state, "skill_injector", None),
        active_skills=list(definition.skills),
        progressive_recall=getattr(request.app.state, "progressive_recall", None),
        tool_registry=tool_registry,
        tool_governance=getattr(request.app.state, "tool_governance", None),
        tool_context=tool_context,
        tool_activation_manager=getattr(request.app.state, "tool_activation_manager", None),
        tool_discovery_mode=settings.tool_discovery_mode,
        tenant_id=token_payload.tenant_id or "",
        evaluation_mode=True,
    )

    return SkillsBenchAdapter(
        task_loader=SkillsBenchTaskLoader(config.skillsbench_root),
        pytest_runner=PytestBinaryRewardRunner(
            timeout_seconds=config.pytest_timeout_seconds,
        ),
        skill_registry=skill_registry,
        agent_runtime=runtime,
        artifact_store=_get_artifact_store(),
    )


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ListTasksRequest(BaseModel):
    skillsbench_root: str = Field(
        default="./skillsbench",
        description="Root directory of the SkillsBench repository checkout.",
    )
    categories: list[str] = Field(
        default_factory=list,
        description="Filter to specific categories.",
    )
    max_tasks: int = Field(
        default=0,
        ge=0,
        description="Maximum number of tasks to return. 0 = unlimited.",
    )


class TaskSummary(BaseModel):
    task_id: str
    category: str
    instruction_preview: str = Field(
        default="",
        description="First 200 characters of the instruction.",
    )
    has_skills: bool = False


class ListTasksResponse(BaseModel):
    total: int = 0
    categories: list[str] = Field(default_factory=list)
    tasks: list[TaskSummary] = Field(default_factory=list)


class RunBenchmarkRequest(BaseModel):
    skillsbench_root: str = Field(
        default="./skillsbench",
        description="Root directory of the SkillsBench repository checkout.",
    )
    agent_name: str = Field(default="code-worker")
    model: str = Field(default="llama3.2")
    trials_per_task: int = Field(default=5, ge=1, le=100)
    skills_enabled: bool = Field(default=True)
    pytest_timeout_seconds: float = Field(default=300.0, gt=0)
    task_filter: TaskFilter = Field(default_factory=TaskFilter)


class RunSummaryResponse(BaseModel):
    run_id: str
    status: BenchmarkRunStatus
    total_tasks: int = 0
    total_trials: int = 0
    passed_trials: int = 0
    pass_rate: float = 0.0
    total_duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/skillsbench/tasks",
    response_model=ListTasksResponse,
    dependencies=[require_scope("workflows:read")],
)
async def list_skillsbench_tasks(
    request: ListTasksRequest,
) -> dict[str, Any]:
    """List available SkillsBench tasks from a repository checkout."""
    root = Path(request.skillsbench_root)
    if not root.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"SkillsBench root directory not found: {root}",
        )

    loader = SkillsBenchTaskLoader(root)
    task_filter = TaskFilter(
        categories=request.categories,
        max_tasks=request.max_tasks,
    )
    tasks = loader.discover_tasks(task_filter=task_filter)
    categories = loader.list_categories()

    summaries = [
        TaskSummary(
            task_id=t.task_id,
            category=t.category,
            instruction_preview=t.instruction[:200] if t.instruction else "",
            has_skills=t.skills_dir is not None,
        )
        for t in tasks
    ]

    return {
        "total": len(summaries),
        "categories": categories,
        "tasks": summaries,
    }


@router.post(
    "/skillsbench/runs",
    response_model=RunSummaryResponse,
    status_code=201,
    dependencies=[require_scope("tools:execute")],
)
async def run_skillsbench_benchmark(
    request: Request,
    body: RunBenchmarkRequest,
) -> dict[str, Any]:
    """Execute a SkillsBench benchmark run and retain its results in-memory."""
    root = Path(body.skillsbench_root)
    if not root.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"SkillsBench root directory not found: {root}",
        )

    config = SkillsBenchConfig(
        skillsbench_root=root,
        agent_name=body.agent_name,
        model=body.model,
        trials_per_task=body.trials_per_task,
        skills_enabled=body.skills_enabled,
        pytest_timeout_seconds=body.pytest_timeout_seconds,
        task_filter=body.task_filter,
    )
    adapter = _build_skillsbench_adapter(request, config)
    run = await adapter.run_benchmark(config)
    _store_run(run)

    return {
        "run_id": run.run_id,
        "status": run.status,
        "total_tasks": run.total_tasks,
        "total_trials": run.total_trials,
        "passed_trials": run.passed_trials,
        "pass_rate": run.pass_rate,
        "total_duration_ms": run.total_duration_ms,
    }


@router.get(
    "/skillsbench/runs",
    response_model=list[RunSummaryResponse],
    dependencies=[require_scope("workflows:read")],
)
async def list_benchmark_runs(
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List recent SkillsBench benchmark runs."""
    persisted_runs = _get_artifact_store().list_runs(limit=limit)
    if persisted_runs:
        return [
            {
                "run_id": run.run_id,
                "status": run.status,
                "total_tasks": run.total_tasks,
                "total_trials": run.total_trials,
                "passed_trials": run.passed_trials,
                "pass_rate": run.pass_rate,
                "total_duration_ms": run.total_duration_ms,
            }
            for run in persisted_runs
        ]

    result: list[dict[str, Any]] = []
    for run_id in reversed(_run_order):
        run = _get_run(run_id)
        if run is None:
            continue
        result.append(
            {
                "run_id": run.run_id,
                "status": run.status,
                "total_tasks": run.total_tasks,
                "total_trials": run.total_trials,
                "passed_trials": run.passed_trials,
                "pass_rate": run.pass_rate,
                "total_duration_ms": run.total_duration_ms,
            }
        )
        if len(result) >= limit:
            break
    return result


@router.get(
    "/skillsbench/runs/{run_id}",
    dependencies=[require_scope("workflows:read")],
)
async def get_benchmark_run(run_id: str) -> dict[str, Any]:
    """Get detailed results for a specific benchmark run."""
    run = _get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return run.model_dump()


@router.get(
    "/skillsbench/runs/{run_id}/ctrf",
    dependencies=[require_scope("workflows:read")],
)
async def get_benchmark_run_ctrf(run_id: str) -> dict[str, Any]:
    """Export a persisted SkillsBench benchmark run as CTRF."""
    run = _get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    store = _get_artifact_store()
    report = store.load_ctrf_report(run_id)
    if report is None:
        report = _ctrf.generate_report(run)
        ctrf_path = store.persist_ctrf_report(run_id, report)
        run.ctrf_report_path = ctrf_path.relative_to(store.base_path / run.run_id).as_posix()
        store.persist_run(run)
    return report


@router.get(
    "/skillsbench/runs/{run_id}/artifacts/{artifact_path:path}",
    dependencies=[require_scope("workflows:read")],
    response_class=PlainTextResponse,
)
async def get_benchmark_artifact(run_id: str, artifact_path: str) -> str:
    """Return a persisted text artifact for a benchmark run."""
    if _get_run(run_id) is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    content = _get_artifact_store().read_artifact(run_id, artifact_path)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Artifact not found: {artifact_path}")
    return content
