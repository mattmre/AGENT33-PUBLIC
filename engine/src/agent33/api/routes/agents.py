"""Agent management and invocation endpoints."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from agent33.evaluation.ppack_ab_service import PPackABService
    from agent33.llm.router import ModelRouter
    from agent33.outcomes.service import OutcomesService

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from agent33.agents.capabilities import get_catalog_by_category
from agent33.agents.definition import (
    AgentDefinition,
    AgentRole,
    AgentStatus,
    CapabilityCategory,
    SpecCapability,
)
from agent33.agents.effort import AgentEffort, AgentEffortRouter
from agent33.agents.registry import AgentRegistry
from agent33.agents.runtime import AgentRuntime
from agent33.api.route_approvals import require_route_mutation_approval
from agent33.config import settings
from agent33.evaluation.ppack_ab_models import PPackABAssignment
from agent33.llm.runtime_config import (
    build_model_router,
    resolve_default_model,
)
from agent33.llm.runtime_config import (
    llamacpp_enabled as _runtime_llamacpp_enabled,
)
from agent33.observability.effort_telemetry import (
    EffortTelemetryExporter,
    EffortTelemetryExportError,
    NoopEffortTelemetryExporter,
)
from agent33.observability.metrics import MetricsCollector
from agent33.outcomes.models import OutcomeEventCreate, OutcomeMetricType
from agent33.security.injection import scan_inputs_recursive
from agent33.security.permissions import _get_token_payload, require_scope
from agent33.tools.approvals import ApprovalRiskTier

router = APIRouter(prefix="/v1/agents", tags=["agents"])
logger = logging.getLogger(__name__)

# -- singletons ----------------------------------------------------------


def _default_agent_model() -> str:
    """Return the default model name for agent invocations."""
    return resolve_default_model()


def _llamacpp_enabled() -> bool:
    """Backwards-compatible llama.cpp helper used by provider tests."""
    return _runtime_llamacpp_enabled()


_model_router = build_model_router()


def _parse_effort_policy(raw: str) -> dict[str, str]:
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Effort policy config must be valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("Effort policy config must be a JSON object")
    parsed: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, str):
            parsed[key] = value
    return parsed


def _resolve_domain_context(request: Request, body_domain: str | None) -> str:
    if body_domain and body_domain.strip():
        return body_domain.strip().lower()
    header_domain = request.headers.get("x-agent-domain", "")
    if header_domain.strip():
        return header_domain.strip().lower()
    host = request.headers.get("host", "")
    return host.split(":", 1)[0].strip().lower() if host else ""


def _resolve_runtime_session_id(request: Request) -> str:
    for candidate in (
        request.headers.get("x-agent-session-id", ""),
        request.headers.get("x-session-id", ""),
        getattr(request.state, "session_id", ""),
    ):
        normalized = str(candidate).strip()
        if normalized:
            return normalized
    return ""


def _build_skill_match_query(definition: AgentDefinition, inputs: dict[str, Any]) -> str:
    """Build a compact query for skill matching from agent + request context."""
    user_payload = json.dumps(inputs, ensure_ascii=False)
    return f"{definition.description}\n\nUser request:\n{user_payload}"


async def _resolve_active_skills(
    *,
    request: Request,
    definition: AgentDefinition,
    model_router: ModelRouter,
    inputs: dict[str, Any],
) -> list[str]:
    """Resolve active skills for an invocation with feature-flagged matching."""
    configured_skills = list(definition.skills)
    if not configured_skills:
        return []
    if not settings.skillsbench_skill_matcher_enabled:
        return configured_skills

    skill_matcher = getattr(request.app.state, "skill_matcher", None)
    if skill_matcher is None:
        skill_registry = getattr(request.app.state, "skill_registry", None)
        if skill_registry is None:
            return configured_skills
        from agent33.skills.matching import SkillMatcher

        skill_matcher = SkillMatcher(
            registry=skill_registry,
            router=model_router,
            model=settings.skillsbench_skill_matcher_model or resolve_default_model(),
            top_k=settings.skillsbench_skill_matcher_top_k,
            skip_llm_below=settings.skillsbench_skill_matcher_skip_llm_below,
        )
        request.app.state.skill_matcher = skill_matcher

    allowed = set(configured_skills)
    try:
        match_result = await skill_matcher.match(
            _build_skill_match_query(definition, inputs),
        )
    except Exception:
        logger.warning("skill_match_failed agent=%s", definition.name, exc_info=True)
        return configured_skills

    matched = [skill.name for skill in match_result.skills if skill.name in allowed]
    return matched or configured_skills


_effort_router = AgentEffortRouter(
    enabled=settings.agent_effort_routing_enabled,
    default_effort=settings.agent_effort_default,
    low_model=settings.agent_effort_low_model or None,
    medium_model=settings.agent_effort_medium_model or None,
    high_model=settings.agent_effort_high_model or None,
    low_token_multiplier=settings.agent_effort_low_token_multiplier,
    medium_token_multiplier=settings.agent_effort_medium_token_multiplier,
    high_token_multiplier=settings.agent_effort_high_token_multiplier,
    heuristic_enabled=settings.agent_effort_heuristic_enabled,
    tenant_policies=_parse_effort_policy(settings.agent_effort_policy_tenant),
    domain_policies=_parse_effort_policy(settings.agent_effort_policy_domain),
    tenant_domain_policies=_parse_effort_policy(settings.agent_effort_policy_tenant_domain),
    cost_per_1k_tokens=settings.agent_effort_cost_per_1k_tokens,
    heuristic_low_score_threshold=settings.agent_effort_heuristic_low_score_threshold,
    heuristic_high_score_threshold=settings.agent_effort_heuristic_high_score_threshold,
    heuristic_medium_payload_chars=settings.agent_effort_heuristic_medium_payload_chars,
    heuristic_large_payload_chars=settings.agent_effort_heuristic_large_payload_chars,
    heuristic_many_input_fields_threshold=(
        settings.agent_effort_heuristic_many_input_fields_threshold
    ),
    heuristic_high_iteration_threshold=settings.agent_effort_heuristic_high_iteration_threshold,
    heuristic_simple_max_chars=settings.heuristic_simple_max_chars,
    heuristic_simple_max_words=settings.heuristic_simple_max_words,
)
_metrics = MetricsCollector()
_effort_exporter: EffortTelemetryExporter = NoopEffortTelemetryExporter()


def set_metrics(collector: MetricsCollector) -> None:
    """Swap the global metrics collector (called during app init)."""
    global _metrics
    _metrics = collector


def set_effort_telemetry_exporter(exporter: EffortTelemetryExporter) -> None:
    """Swap the global effort telemetry exporter (called during app init)."""
    global _effort_exporter
    _effort_exporter = exporter


def _record_effort_routing_metrics(routing: dict[str, Any] | None) -> None:
    if not routing:
        return
    effort = str(routing.get("effort") or "unknown")
    source = str(routing.get("source") or routing.get("effort_source") or "unknown")
    labels = {"effort": effort, "source": source}
    _metrics.increment("effort_routing_decisions_total", labels=labels)

    if effort == AgentEffort.HIGH.value:
        _metrics.increment("effort_routing_high_effort_total")

    estimated_token_budget = routing.get("estimated_token_budget")
    if isinstance(estimated_token_budget, int | float):
        _metrics.observe(
            "effort_routing_estimated_token_budget",
            float(estimated_token_budget),
            labels=labels,
        )
        _metrics.observe(
            "effort_routing_estimated_token_budget",
            float(estimated_token_budget),
        )

    estimated_cost = routing.get("estimated_cost")
    if isinstance(estimated_cost, int | float):
        _metrics.observe(
            "effort_routing_estimated_cost_usd",
            float(estimated_cost),
            labels=labels,
        )
        _metrics.observe(
            "effort_routing_estimated_cost_usd",
            float(estimated_cost),
        )

    event = {
        "timestamp": datetime.now(UTC).isoformat(),
        "routing": routing,
    }
    try:
        _effort_exporter.export(event)
    except EffortTelemetryExportError:
        _metrics.increment("effort_routing_export_failures_total")
        logger.warning("effort_routing_telemetry_export_failed", exc_info=True)
        if settings.observability_effort_export_fail_closed:
            raise HTTPException(status_code=503, detail="Effort telemetry export failed") from None


# -- dependency injection -------------------------------------------------


def get_registry(request: Request) -> AgentRegistry:
    """Return the shared registry from app state, or a fresh empty one."""
    registry = getattr(request.app.state, "agent_registry", None)
    if registry is None:
        registry = AgentRegistry()
    return registry


def _get_outcomes_service(request: Request) -> OutcomesService | None:
    """Return the outcomes service from app.state, or None if unavailable."""
    return getattr(request.app.state, "outcomes_service", None)


def _get_ppack_ab_service(request: Request) -> PPackABService | None:
    """Return the P-PACK A/B service from app.state, or None if unavailable."""
    return getattr(request.app.state, "ppack_ab_service", None)


def _get_cached_ppack_assignment(
    request: Request,
    *,
    tenant_id: str,
    session_id: str,
) -> PPackABAssignment | None:
    if not session_id:
        return None
    cached_assignment = getattr(request.state, "ppack_assignment", None)
    cached_tenant_id = getattr(request.state, "ppack_assignment_tenant_id", "")
    cached_session_id = getattr(request.state, "ppack_assignment_session_id", "")
    if (
        isinstance(cached_assignment, PPackABAssignment)
        and cached_tenant_id == tenant_id
        and cached_session_id == session_id
    ):
        return cached_assignment
    return None


async def _resolve_ppack_assignment(
    request: Request,
    *,
    tenant_id: str,
    session_id: str,
) -> PPackABAssignment | None:
    """Resolve and cache the active P-PACK assignment for the current request."""
    cached_assignment = _get_cached_ppack_assignment(
        request,
        tenant_id=tenant_id,
        session_id=session_id,
    )
    if cached_assignment is not None:
        return cached_assignment

    ab_service = _get_ppack_ab_service(request)
    if ab_service is None:
        return None
    try:
        assignment = await run_in_threadpool(
            ab_service.assign_variant,
            tenant_id=tenant_id,
            session_id=session_id,
        )
    except Exception:
        logger.warning("ppack_variant_assignment_failed", exc_info=True)
        return None

    request.state.ppack_assignment = assignment
    request.state.ppack_assignment_tenant_id = tenant_id
    request.state.ppack_assignment_session_id = session_id
    return assignment


def _resolve_ppack_variant(
    request: Request,
    *,
    tenant_id: str,
    session_id: str,
) -> str:
    """Return the cached P-PACK variant for runtime behavior selection."""
    assignment = _get_cached_ppack_assignment(
        request,
        tenant_id=tenant_id,
        session_id=session_id,
    )
    return assignment.variant.value if assignment is not None else ""


def _build_outcome_metadata(
    request: Request,
    *,
    tenant_id: str,
    session_id: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(metadata or {})
    if session_id:
        payload.setdefault("session_id", session_id)
        assignment = _get_cached_ppack_assignment(
            request,
            tenant_id=tenant_id,
            session_id=session_id,
        )
        if assignment is not None:
            payload.setdefault("experiment_key", assignment.experiment_key)
            payload.setdefault("ppack_variant", assignment.variant.value)
    return payload


def _record_outcome_safe(
    outcomes_svc: OutcomesService | None,
    *,
    tenant_id: str,
    domain: str,
    event_type: str,
    metric_type: OutcomeMetricType,
    value: float,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record an outcome event without blocking the response on failure.

    This is intentionally fire-and-forget.  If the service is unavailable
    or the recording raises, we log a warning and move on so the agent
    invocation response is never degraded.
    """
    if outcomes_svc is None:
        return
    try:
        outcomes_svc.record_event(
            tenant_id=tenant_id,
            event=OutcomeEventCreate(
                domain=domain,
                event_type=event_type,
                metric_type=metric_type,
                value=value,
                metadata=metadata or {},
            ),
        )
    except Exception:
        logger.warning("outcome_recording_failed", exc_info=True)


# -- request / response models -------------------------------------------


class InvokeRequest(BaseModel):
    """Body for the invoke endpoint."""

    inputs: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    temperature: float = 0.7
    effort: AgentEffort | None = None
    domain: str | None = None


class InvokeResponse(BaseModel):
    """Response from the invoke endpoint."""

    agent: str
    output: dict[str, Any]
    tokens_used: int
    model: str
    routing: dict[str, Any] | None = None
    cadre_profile: dict[str, Any]


class InvokeIterativeRequest(BaseModel):
    """Body for the iterative invoke endpoint."""

    inputs: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    temperature: float = 0.7
    effort: AgentEffort | None = None
    domain: str | None = None
    max_iterations: int = 20
    max_tool_calls_per_iteration: int = 5
    enable_double_confirmation: bool = True
    loop_detection_threshold: int = 3
    autonomy_level: int | None = Field(
        default=None,
        ge=0,
        le=3,
        description="P67 autonomy level (0=supervised, 1=default, 2=auto, 3=full). "
        "When set, overrides the constructor-injected RuntimeEnforcer with a "
        "level-derived AutonomyBudget.",
    )


class InvokeIterativeResponse(BaseModel):
    """Response from the iterative invoke endpoint."""

    agent: str
    output: dict[str, Any]
    tokens_used: int
    model: str
    iterations: int
    tool_calls_made: int
    tools_used: list[str]
    termination_reason: str
    routing: dict[str, Any] | None = None
    cadre_profile: dict[str, Any]


# -- routes ---------------------------------------------------------------


@router.get("/capabilities/catalog")
async def capabilities_catalog() -> dict[str, list[dict[str, str]]]:
    """Return the full spec capability taxonomy grouped by category."""
    return get_catalog_by_category()


@router.get("/search", dependencies=[require_scope("agents:read")])
async def search_agents(
    registry: AgentRegistry = Depends(get_registry),  # noqa: B008
    role: str | None = Query(default=None, description="Filter by role"),
    spec_capability: str | None = Query(
        default=None,
        description="Filter by spec capability ID",
    ),
    category: str | None = Query(
        default=None,
        description="Filter by capability category",
    ),
    status: str | None = Query(
        default=None,
        description="Filter by lifecycle status",
    ),
) -> list[dict[str, Any]]:
    """Search agents with multi-criteria AND filtering."""
    try:
        parsed_role = AgentRole(role) if role else None
        parsed_cap = SpecCapability(spec_capability) if spec_capability else None
        parsed_cat = CapabilityCategory(category) if category else None
        parsed_status = AgentStatus(status) if status else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    results = registry.search(
        role=parsed_role,
        spec_capability=parsed_cap,
        category=parsed_cat,
        status=parsed_status,
    )
    return [_agent_summary(d) for d in results]


@router.get("/by-id/{agent_id}", dependencies=[require_scope("agents:read")])
async def get_agent_by_id(
    agent_id: str,
    registry: AgentRegistry = Depends(get_registry),  # noqa: B008
) -> dict[str, Any]:
    """Look up an agent by its spec ID (e.g. AGT-001)."""
    definition = registry.get_by_agent_id(agent_id)
    if definition is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent with ID '{agent_id}' not found",
        )
    return definition.model_dump(mode="json")


@router.get("/tool-loop/scores", dependencies=[require_scope("agents:read")])
async def get_tool_loop_scores(
    request: Request,
) -> dict[str, Any]:
    """Return current tool loop scoring data.

    Requires a ``ToolLoopScorer`` installed on ``app.state.tool_loop_scorer``.
    Returns 503 if the scorer service has not been initialized.
    """
    scorer = getattr(request.app.state, "tool_loop_scorer", None)
    if scorer is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    try:
        summary: dict[str, Any] = scorer.get_loop_summary()
        return summary
    except Exception:
        logger.debug("tool_loop_scorer.get_loop_summary() failed", exc_info=True)
        raise HTTPException(status_code=503, detail="Service not initialized") from None


# -- profiling endpoints ---------------------------------------------------


@router.get("/profiling/summaries", dependencies=[require_scope("agents:read")])
async def profiling_summaries(
    request: Request,
) -> list[dict[str, Any]]:
    """Return performance summaries for all profiled agents."""
    profiler = getattr(request.app.state, "agent_profiler", None)
    if profiler is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    summaries = profiler.get_all_summaries()
    return [s.model_dump(mode="json") for s in summaries]


@router.get("/profiling/bottlenecks", dependencies=[require_scope("agents:read")])
async def profiling_bottlenecks(
    request: Request,
) -> list[dict[str, Any]]:
    """Detect agents with performance bottlenecks (one phase > 60% of duration)."""
    profiler = getattr(request.app.state, "agent_profiler", None)
    if profiler is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    result: list[dict[str, Any]] = profiler.detect_bottlenecks()
    return result


@router.get("/profiling/hot-paths", dependencies=[require_scope("agents:read")])
async def profiling_hot_paths(
    request: Request,
) -> list[dict[str, Any]]:
    """Identify the slowest agent/model combinations."""
    profiler = getattr(request.app.state, "agent_profiler", None)
    if profiler is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    result: list[dict[str, Any]] = profiler.get_hot_paths()
    return result


@router.get("/profiling/profiles", dependencies=[require_scope("agents:read")])
async def profiling_profiles(
    request: Request,
    agent_name: str | None = Query(default=None, description="Filter by agent name"),
    limit: int = Query(default=50, ge=1, le=500, description="Max profiles to return"),
) -> list[dict[str, Any]]:
    """Return raw invocation profiles, newest first."""
    profiler = getattr(request.app.state, "agent_profiler", None)
    if profiler is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    profiles = profiler.get_profiles(agent_name=agent_name, limit=limit)
    return [p.model_dump(mode="json") for p in profiles]


@router.get("/profiling/{agent_name}", dependencies=[require_scope("agents:read")])
async def profiling_agent_summary(
    agent_name: str,
    request: Request,
) -> dict[str, Any]:
    """Return the performance summary for a single agent."""
    profiler = getattr(request.app.state, "agent_profiler", None)
    if profiler is None:
        raise HTTPException(status_code=404, detail="Profiler not initialized")
    try:
        summary = profiler.get_agent_summary(agent_name)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"No profiles for agent '{agent_name}'",
        ) from None
    result: dict[str, Any] = summary.model_dump(mode="json")
    return result


@router.post("/preview-prompt", dependencies=[require_scope("agents:read")])
async def preview_agent_prompt(
    definition: AgentDefinition,
) -> dict[str, str]:
    """Return the system prompt that would be generated for this agent definition."""
    from agent33.agents.runtime import _build_system_prompt

    prompt = _build_system_prompt(definition)
    return {"system_prompt": prompt}


@router.post("/validate")
async def validate_agent_definition(
    definition: dict[str, Any],
) -> dict[str, Any]:
    """Validate an agent definition without registering it. Returns errors if invalid."""
    try:
        agent_def = AgentDefinition.model_validate(definition)
        return {"valid": True, "name": agent_def.name, "errors": []}
    except Exception as exc:
        return {"valid": False, "name": None, "errors": [str(exc)]}


@router.get("/", dependencies=[require_scope("agents:read")])
async def list_agents(
    registry: AgentRegistry = Depends(get_registry),  # noqa: B008
) -> list[dict[str, Any]]:
    """List all registered agent definitions."""
    return [_agent_summary(d) for d in registry.list_all()]


@router.get("/{name}", dependencies=[require_scope("agents:read")])
async def get_agent(
    name: str,
    registry: AgentRegistry = Depends(get_registry),  # noqa: B008
) -> dict[str, Any]:
    """Return the full definition for a single agent."""
    definition = registry.get(name)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    payload = definition.model_dump(mode="json")
    payload["cadre_profile"] = definition.cadre_profile().model_dump(mode="json")
    return payload


@router.put("/{name}", dependencies=[require_scope("agents:write")])
async def update_agent(
    name: str,
    definition: AgentDefinition,
    request: Request,
    registry: AgentRegistry = Depends(get_registry),  # noqa: B008
) -> dict[str, Any]:
    """Update an existing agent definition."""
    require_route_mutation_approval(
        request,
        route_name="agents.update",
        operation="update",
        arguments={
            "name": name,
            "definition": definition.model_dump(mode="json"),
        },
        details="Agent definition updates require explicit operator approval.",
        risk_tier=ApprovalRiskTier.MEDIUM,
    )
    existing = registry.get(name)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    registry.register(definition)
    updated = registry.get(definition.name)
    if updated is None:
        raise HTTPException(status_code=500, detail="Failed to update agent")
    return updated.model_dump(mode="json")


@router.delete(
    "/{name}",
    status_code=204,
    response_model=None,
    dependencies=[require_scope("agents:write")],
)
async def delete_agent(
    name: str,
    request: Request,
    registry: AgentRegistry = Depends(get_registry),  # noqa: B008
) -> None:
    """Remove an agent definition from the registry."""
    require_route_mutation_approval(
        request,
        route_name="agents.delete",
        operation="delete",
        arguments={"name": name},
        details="Agent definition deletion requires explicit operator approval.",
        risk_tier=ApprovalRiskTier.MEDIUM,
    )
    existing = registry.get(name)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    registry.remove(name)


@router.post("/", status_code=201, dependencies=[require_scope("agents:write")])
async def register_agent(
    definition: AgentDefinition,
    request: Request,
    registry: AgentRegistry = Depends(get_registry),  # noqa: B008
) -> dict[str, str]:
    """Register a new agent definition."""
    require_route_mutation_approval(
        request,
        route_name="agents.create",
        operation="create",
        arguments=definition.model_dump(mode="json"),
        details="Agent definition creation requires explicit operator approval.",
        risk_tier=ApprovalRiskTier.MEDIUM,
    )
    registry.register(definition)
    return {"status": "registered", "name": definition.name}


@router.post("/{name}/invoke", dependencies=[require_scope("agents:invoke")])
async def invoke_agent(
    name: str,
    body: InvokeRequest,
    request: Request,
    registry: AgentRegistry = Depends(get_registry),  # noqa: B008
) -> InvokeResponse:
    """Invoke a registered agent with the given inputs."""
    definition = registry.get(name)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    # Scan inputs for prompt injection (recursive to catch nested payloads)
    scan = scan_inputs_recursive(body.inputs)
    if not scan.is_safe:
        raise HTTPException(
            status_code=400,
            detail=f"Input rejected: {', '.join(scan.threats)}",
        )

    # Pull subsystems from app state for agent runtime, falling back to
    # module-level singleton for backward compatibility.
    model_router = getattr(request.app.state, "model_router", _model_router)
    effort_router = getattr(request.app.state, "effort_router", _effort_router)
    skill_injector = getattr(request.app.state, "skill_injector", None)
    progressive_recall = getattr(request.app.state, "progressive_recall", None)
    token_payload = _get_token_payload(request)
    tenant_id = token_payload.tenant_id or ""
    domain = _resolve_domain_context(request, body.domain)
    active_skills = await _resolve_active_skills(
        request=request,
        definition=definition,
        model_router=model_router,
        inputs=body.inputs,
    )

    hook_registry = getattr(request.app.state, "hook_registry", None)
    cost_tracker = getattr(request.app.state, "cost_tracker", None)
    metrics_collector = getattr(request.app.state, "metrics_collector", None)
    pack_registry = getattr(request.app.state, "pack_registry", None)
    invoke_session_id = _resolve_runtime_session_id(request)
    await _resolve_ppack_assignment(
        request,
        tenant_id=tenant_id,
        session_id=invoke_session_id,
    )
    invoke_ppack_variant = _resolve_ppack_variant(
        request,
        tenant_id=tenant_id,
        session_id=invoke_session_id,
    )

    runtime = AgentRuntime(
        definition=definition,
        router=model_router,
        model=body.model or _default_agent_model(),
        temperature=body.temperature,
        session_id=invoke_session_id,
        invocation_mode="invoke",
        effort=body.effort,
        effort_router=effort_router,
        routing_metrics_emitter=_record_effort_routing_metrics,
        skill_injector=skill_injector,
        active_skills=active_skills,
        progressive_recall=progressive_recall,
        tenant_id=tenant_id,
        domain=domain,
        hook_registry=hook_registry,
        cost_tracker=cost_tracker,
        metrics_collector=metrics_collector,
        pack_registry=pack_registry,
        ppack_variant=invoke_ppack_variant,
    )

    outcomes_svc = _get_outcomes_service(request)
    invoke_start = time.monotonic()

    try:
        result = await runtime.invoke(body.inputs)
    except ValueError as exc:
        _record_outcome_safe(
            outcomes_svc,
            tenant_id=tenant_id,
            domain=name,
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=0.0,
            metadata=_build_outcome_metadata(
                request,
                tenant_id=tenant_id,
                session_id=invoke_session_id,
                metadata={
                    "error": str(exc),
                    "termination": "validation_error",
                },
            ),
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        _record_outcome_safe(
            outcomes_svc,
            tenant_id=tenant_id,
            domain=name,
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=0.0,
            metadata=_build_outcome_metadata(
                request,
                tenant_id=tenant_id,
                session_id=invoke_session_id,
                metadata={
                    "error": str(exc),
                    "termination": "runtime_error",
                },
            ),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        _record_outcome_safe(
            outcomes_svc,
            tenant_id=tenant_id,
            domain=name,
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=0.0,
            metadata=_build_outcome_metadata(
                request,
                tenant_id=tenant_id,
                session_id=invoke_session_id,
                metadata={
                    "error": str(exc),
                    "termination": "error",
                },
            ),
        )
        # Handle HookAbortError without hard import dependency
        if type(exc).__name__ == "HookAbortError":
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        raise

    latency_ms = (time.monotonic() - invoke_start) * 1000
    _record_outcome_safe(
        outcomes_svc,
        tenant_id=tenant_id,
        domain=name,
        event_type="invoke",
        metric_type=OutcomeMetricType.SUCCESS_RATE,
        value=1.0,
        metadata=_build_outcome_metadata(
            request,
            tenant_id=tenant_id,
            session_id=invoke_session_id,
            metadata={
                "model": result.model,
                "tokens": result.tokens_used,
                "termination": "success",
            },
        ),
    )
    _record_outcome_safe(
        outcomes_svc,
        tenant_id=tenant_id,
        domain=name,
        event_type="invoke",
        metric_type=OutcomeMetricType.LATENCY_MS,
        value=latency_ms,
        metadata=_build_outcome_metadata(
            request,
            tenant_id=tenant_id,
            session_id=invoke_session_id,
            metadata={
                "agent": name,
                "model": result.model,
            },
        ),
    )

    return InvokeResponse(
        agent=name,
        output=result.output,
        tokens_used=result.tokens_used,
        model=result.model,
        routing=result.routing_decision,
        cadre_profile=definition.cadre_profile().model_dump(mode="json"),
    )


@router.post(
    "/{name}/invoke-iterative",
    dependencies=[require_scope("agents:invoke")],
)
async def invoke_agent_iterative(
    name: str,
    body: InvokeIterativeRequest,
    request: Request,
    registry: AgentRegistry = Depends(get_registry),  # noqa: B008
) -> InvokeIterativeResponse:
    """Invoke a registered agent with the iterative tool-use loop.

    Unlike the standard invoke, this endpoint repeatedly calls the LLM,
    parsing and executing tool calls until the task is complete or a
    limit is reached.
    """
    definition = registry.get(name)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    scan = scan_inputs_recursive(body.inputs)
    if not scan.is_safe:
        raise HTTPException(
            status_code=400,
            detail=f"Input rejected: {', '.join(scan.threats)}",
        )

    # Pull subsystems from app state
    model_router = getattr(request.app.state, "model_router", None)
    if model_router is None:
        raise HTTPException(
            status_code=503,
            detail="Model router not initialized",
        )
    tool_registry = getattr(request.app.state, "tool_registry", None)
    if tool_registry is None:
        raise HTTPException(
            status_code=503,
            detail="Tool registry not initialized",
        )
    tool_governance = getattr(request.app.state, "tool_governance", None)
    effort_router = getattr(request.app.state, "effort_router", _effort_router)
    skill_injector = getattr(request.app.state, "skill_injector", None)
    progressive_recall = getattr(request.app.state, "progressive_recall", None)

    # Build ToolContext from authenticated user and definition governance
    from agent33.tools.base import ToolContext

    token_payload = _get_token_payload(request)
    user_scopes = token_payload.scopes
    domain = _resolve_domain_context(request, body.domain)
    session_id = _resolve_runtime_session_id(request)
    active_skills = await _resolve_active_skills(
        request=request,
        definition=definition,
        model_router=model_router,
        inputs=body.inputs,
    )

    # Extract tool_policies from definition governance
    tool_policies = definition.governance.tool_policies if definition.governance else {}

    tool_context = ToolContext(
        user_scopes=user_scopes,
        tool_policies=tool_policies,
        requested_by=token_payload.sub,
        tenant_id=token_payload.tenant_id or "",
        session_id=session_id,
    )

    from agent33.agents.tool_loop import ToolLoopConfig

    loop_config = ToolLoopConfig(
        max_iterations=body.max_iterations,
        max_tool_calls_per_iteration=body.max_tool_calls_per_iteration,
        enable_double_confirmation=body.enable_double_confirmation,
        loop_detection_threshold=body.loop_detection_threshold,
    )
    context_compressor = getattr(request.app.state, "context_compressor", None)
    context_manager = getattr(request.app.state, "context_manager", None)
    if context_manager is None and settings.skillsbench_context_manager_enabled:
        from agent33.agents.context_manager import ContextManager, budget_for_model

        selected_model = body.model or resolve_default_model()
        context_manager = ContextManager(
            budget=budget_for_model(selected_model),
            router=model_router,
            summarize_model=selected_model,
            skip_summarization=context_compressor is not None,
        )

    hook_registry = getattr(request.app.state, "hook_registry", None)
    tool_activation_manager = getattr(request.app.state, "tool_activation_manager", None)
    cost_tracker = getattr(request.app.state, "cost_tracker", None)
    metrics_collector_iter = getattr(request.app.state, "metrics_collector", None)
    pack_registry_iter = getattr(request.app.state, "pack_registry", None)
    tool_loop_scorer_iter = getattr(request.app.state, "tool_loop_scorer", None)
    await _resolve_ppack_assignment(
        request,
        tenant_id=token_payload.tenant_id or "",
        session_id=session_id,
    )
    iterative_ppack_variant = _resolve_ppack_variant(
        request,
        tenant_id=token_payload.tenant_id or "",
        session_id=session_id,
    )

    runtime = AgentRuntime(
        definition=definition,
        router=model_router,
        model=body.model or _default_agent_model(),
        temperature=body.temperature,
        session_id=session_id,
        invocation_mode="iterative",
        effort=body.effort,
        effort_router=effort_router,
        routing_metrics_emitter=_record_effort_routing_metrics,
        skill_injector=skill_injector,
        active_skills=active_skills,
        progressive_recall=progressive_recall,
        tool_registry=tool_registry,
        tool_governance=tool_governance,
        tool_context=tool_context,
        tool_activation_manager=tool_activation_manager,
        tool_discovery_mode=settings.tool_discovery_mode,
        context_manager=context_manager,
        tenant_id=token_payload.tenant_id or "",
        domain=domain,
        hook_registry=hook_registry,
        context_compressor=context_compressor,
        cost_tracker=cost_tracker,
        metrics_collector=metrics_collector_iter,
        pack_registry=pack_registry_iter,
        ppack_variant=iterative_ppack_variant,
        tool_loop_scorer=tool_loop_scorer_iter,
    )

    outcomes_svc = _get_outcomes_service(request)
    iter_tenant_id = token_payload.tenant_id or ""
    iter_session_id = session_id
    iter_start = time.monotonic()

    try:
        result = await runtime.invoke_iterative(
            body.inputs,
            config=loop_config,
            autonomy_level=body.autonomy_level,
        )
    except ValueError as exc:
        _record_outcome_safe(
            outcomes_svc,
            tenant_id=iter_tenant_id,
            domain=name,
            event_type="invoke_iterative",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=0.0,
            metadata=_build_outcome_metadata(
                request,
                tenant_id=iter_tenant_id,
                session_id=iter_session_id,
                metadata={
                    "error": str(exc),
                    "termination": "validation_error",
                },
            ),
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        _record_outcome_safe(
            outcomes_svc,
            tenant_id=iter_tenant_id,
            domain=name,
            event_type="invoke_iterative",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=0.0,
            metadata=_build_outcome_metadata(
                request,
                tenant_id=iter_tenant_id,
                session_id=iter_session_id,
                metadata={
                    "error": str(exc),
                    "termination": "runtime_error",
                },
            ),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    iter_latency_ms = (time.monotonic() - iter_start) * 1000
    _record_outcome_safe(
        outcomes_svc,
        tenant_id=iter_tenant_id,
        domain=name,
        event_type="invoke_iterative",
        metric_type=OutcomeMetricType.SUCCESS_RATE,
        value=1.0,
        metadata=_build_outcome_metadata(
            request,
            tenant_id=iter_tenant_id,
            session_id=iter_session_id,
            metadata={
                "model": result.model,
                "tokens": result.tokens_used,
                "iterations": result.iterations,
                "tool_calls_made": result.tool_calls_made,
                "termination": result.termination_reason,
            },
        ),
    )
    _record_outcome_safe(
        outcomes_svc,
        tenant_id=iter_tenant_id,
        domain=name,
        event_type="invoke_iterative",
        metric_type=OutcomeMetricType.LATENCY_MS,
        value=iter_latency_ms,
        metadata=_build_outcome_metadata(
            request,
            tenant_id=iter_tenant_id,
            session_id=iter_session_id,
            metadata={
                "agent": name,
                "model": result.model,
            },
        ),
    )
    # Record termination reason as a failure classification when non-successful
    if result.termination_reason not in {"completed"}:
        _record_outcome_safe(
            outcomes_svc,
            tenant_id=iter_tenant_id,
            domain=name,
            event_type="invoke_iterative",
            metric_type=OutcomeMetricType.FAILURE_CLASS,
            value=1.0,
            metadata=_build_outcome_metadata(
                request,
                tenant_id=iter_tenant_id,
                session_id=iter_session_id,
                metadata={
                    "failure_class": result.termination_reason,
                    "iterations": result.iterations,
                    "tool_calls_made": result.tool_calls_made,
                },
            ),
        )

    return InvokeIterativeResponse(
        agent=name,
        output=result.output,
        tokens_used=result.tokens_used,
        model=result.model,
        iterations=result.iterations,
        tool_calls_made=result.tool_calls_made,
        tools_used=result.tools_used,
        termination_reason=result.termination_reason,
        routing=result.routing_decision,
        cadre_profile=definition.cadre_profile().model_dump(mode="json"),
    )


@router.post(
    "/{name}/invoke-iterative/stream",
    dependencies=[require_scope("agents:invoke")],
)
async def invoke_agent_iterative_stream(
    name: str,
    body: InvokeIterativeRequest,
    request: Request,
    registry: AgentRegistry = Depends(get_registry),  # noqa: B008
) -> StreamingResponse:
    """Stream agent iterative execution via SSE."""
    import asyncio
    import time

    definition = registry.get(name)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    scan = scan_inputs_recursive(body.inputs)
    if not scan.is_safe:
        raise HTTPException(
            status_code=400,
            detail=f"Input rejected: {', '.join(scan.threats)}",
        )

    # Pull subsystems from app state
    model_router = getattr(request.app.state, "model_router", None)
    if model_router is None:
        raise HTTPException(status_code=503, detail="Model router not initialized")

    tool_registry = getattr(request.app.state, "tool_registry", None)
    if tool_registry is None:
        raise HTTPException(status_code=503, detail="Tool registry not initialized")

    tool_governance = getattr(request.app.state, "tool_governance", None)
    effort_router = getattr(request.app.state, "effort_router", _effort_router)
    skill_injector = getattr(request.app.state, "skill_injector", None)
    progressive_recall = getattr(request.app.state, "progressive_recall", None)
    observation_capture = getattr(request.app.state, "observation_capture", None)
    context_manager = getattr(request.app.state, "context_manager", None)
    context_compressor = getattr(request.app.state, "context_compressor", None)
    hook_registry = getattr(request.app.state, "hook_registry", None)
    token_payload = _get_token_payload(request)
    domain = _resolve_domain_context(request, body.domain)
    session_id = _resolve_runtime_session_id(request)
    active_skills = await _resolve_active_skills(
        request=request,
        definition=definition,
        model_router=model_router,
        inputs=body.inputs,
    )

    from agent33.tools.base import ToolContext

    tool_context = ToolContext(
        user_scopes=token_payload.scopes,
        tool_policies=definition.governance.tool_policies if definition.governance else {},
        requested_by=token_payload.sub,
        tenant_id=token_payload.tenant_id or "",
        session_id=session_id,
    )

    from agent33.agents.tool_loop import ToolLoopConfig

    loop_config = ToolLoopConfig(
        max_iterations=body.max_iterations,
        max_tool_calls_per_iteration=body.max_tool_calls_per_iteration,
        enable_double_confirmation=body.enable_double_confirmation,
        loop_detection_threshold=body.loop_detection_threshold,
    )

    cost_tracker_stream = getattr(request.app.state, "cost_tracker", None)
    metrics_collector_stream = getattr(request.app.state, "metrics_collector", None)
    pack_registry_stream = getattr(request.app.state, "pack_registry", None)
    tool_loop_scorer_stream = getattr(request.app.state, "tool_loop_scorer", None)
    await _resolve_ppack_assignment(
        request,
        tenant_id=token_payload.tenant_id or "",
        session_id=session_id,
    )
    stream_ppack_variant = _resolve_ppack_variant(
        request,
        tenant_id=token_payload.tenant_id or "",
        session_id=session_id,
    )

    runtime = AgentRuntime(
        definition=definition,
        router=model_router,
        model=body.model or _default_agent_model(),
        temperature=body.temperature,
        observation_capture=observation_capture,
        session_id=session_id,
        invocation_mode="iterative_stream",
        effort=body.effort,
        effort_router=effort_router,
        routing_metrics_emitter=_record_effort_routing_metrics,
        skill_injector=skill_injector,
        active_skills=active_skills,
        progressive_recall=progressive_recall,
        tool_registry=tool_registry,
        tool_governance=tool_governance,
        tool_context=tool_context,
        tool_activation_manager=getattr(request.app.state, "tool_activation_manager", None),
        tool_discovery_mode=settings.tool_discovery_mode,
        context_manager=context_manager,
        tenant_id=token_payload.tenant_id or "",
        domain=domain,
        hook_registry=hook_registry,
        context_compressor=context_compressor,
        cost_tracker=cost_tracker_stream,
        metrics_collector=metrics_collector_stream,
        pack_registry=pack_registry_stream,
        ppack_variant=stream_ppack_variant,
        tool_loop_scorer=tool_loop_scorer_stream,
    )

    outcomes_svc_stream = _get_outcomes_service(request)
    stream_tenant_id = token_payload.tenant_id or ""
    stream_start = time.monotonic()

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for event in runtime.invoke_iterative_stream(body.inputs, config=loop_config):
                if await request.is_disconnected():
                    break
                if event.event_type == "completed":
                    try:
                        _record_effort_routing_metrics(runtime.routing_decision_metadata)
                    except HTTPException as exc:
                        error_payload = {
                            "event_type": "error",
                            "iteration": event.iteration,
                            "timestamp": time.time(),
                            "data": {"error": exc.detail, "phase": "telemetry_export"},
                        }
                        yield f"data: {json.dumps(error_payload)}\n\n"
                        _record_outcome_safe(
                            outcomes_svc_stream,
                            tenant_id=stream_tenant_id,
                            domain=name,
                            event_type="invoke_iterative_stream",
                            metric_type=OutcomeMetricType.SUCCESS_RATE,
                            value=0.0,
                            metadata=_build_outcome_metadata(
                                request,
                                tenant_id=stream_tenant_id,
                                session_id=_resolve_runtime_session_id(request),
                                metadata={
                                    "error": exc.detail,
                                    "termination": "telemetry_export_error",
                                },
                            ),
                        )
                        return
                    # Record successful completion
                    stream_latency_ms = (time.monotonic() - stream_start) * 1000
                    completion_data = event.data if isinstance(event.data, dict) else {}
                    _record_outcome_safe(
                        outcomes_svc_stream,
                        tenant_id=stream_tenant_id,
                        domain=name,
                        event_type="invoke_iterative_stream",
                        metric_type=OutcomeMetricType.SUCCESS_RATE,
                        value=1.0,
                        metadata=_build_outcome_metadata(
                            request,
                            tenant_id=stream_tenant_id,
                            session_id=_resolve_runtime_session_id(request),
                            metadata={
                                "iterations": event.iteration,
                                "termination": completion_data.get(
                                    "termination_reason",
                                    "complete",
                                ),
                            },
                        ),
                    )
                    _record_outcome_safe(
                        outcomes_svc_stream,
                        tenant_id=stream_tenant_id,
                        domain=name,
                        event_type="invoke_iterative_stream",
                        metric_type=OutcomeMetricType.LATENCY_MS,
                        value=stream_latency_ms,
                        metadata=_build_outcome_metadata(
                            request,
                            tenant_id=stream_tenant_id,
                            session_id=_resolve_runtime_session_id(request),
                            metadata={"agent": name},
                        ),
                    )
                yield event.to_sse()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            error_payload = {
                "event_type": "error",
                "iteration": 0,
                "timestamp": time.time(),
                "data": {"error": str(exc), "phase": "endpoint"},
            }
            yield f"data: {json.dumps(error_payload)}\n\n"
            _record_outcome_safe(
                outcomes_svc_stream,
                tenant_id=stream_tenant_id,
                domain=name,
                event_type="invoke_iterative_stream",
                metric_type=OutcomeMetricType.SUCCESS_RATE,
                value=0.0,
                metadata=_build_outcome_metadata(
                    request,
                    tenant_id=stream_tenant_id,
                    session_id=_resolve_runtime_session_id(request),
                    metadata={"error": str(exc), "termination": "error"},
                ),
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get(
    "/{name}/context-budget",
    dependencies=[require_scope("agents:read")],
)
async def get_context_budget(
    name: str,
    request: Request,
    registry: AgentRegistry = Depends(get_registry),  # noqa: B008
) -> dict[str, Any]:
    """Return an estimated context budget for the agent's current configuration.

    Builds the system prompt, collects skill instructions, and estimates
    how many tokens each component consumes relative to the model's
    context window.
    """
    from agent33.agents.context_window import ContextWindowManager
    from agent33.agents.runtime import _build_system_prompt

    definition = registry.get(name)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    # Build system prompt the same way AgentRuntime does
    system_prompt = _build_system_prompt(definition)

    # Collect skill instruction blocks if injector is available
    skill_injector = getattr(request.app.state, "skill_injector", None)
    skill_texts: list[str] = []
    if skill_injector is not None and definition.skills:
        skill_texts.append(skill_injector.build_skill_metadata_block(definition.skills))
        for skill_name in definition.skills:
            skill_texts.append(skill_injector.build_skill_instructions_block(skill_name))

    cwm = getattr(request.app.state, "context_window_manager", None)
    if cwm is None:
        cwm = ContextWindowManager(default_max_tokens=settings.agent_default_context_window)

    budget = cwm.create_budget(
        system_prompt=system_prompt,
        skills=skill_texts if skill_texts else None,
    )
    report = cwm.get_utilization_report(budget)
    report["agent"] = name
    return report


# -- helpers --------------------------------------------------------------


def _agent_summary(d: AgentDefinition) -> dict[str, Any]:
    cadre_profile = d.cadre_profile()
    return {
        "name": d.name,
        "version": d.version,
        "role": d.role.value,
        "description": d.description,
        "agent_id": d.agent_id,
        "spec_capabilities": [c.value for c in d.spec_capabilities],
        "status": d.status.value,
        "cadre": cadre_profile.cadre.value,
        "cadre_label": cadre_profile.label,
        "cadre_required_artifact": cadre_profile.required_artifact,
    }
