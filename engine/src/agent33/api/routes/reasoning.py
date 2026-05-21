"""Reasoning protocol API endpoints (Phase 29.1-29.2)."""

from __future__ import annotations

import logging
import re
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from agent33.agents.isc import ISCCriterion, ISCManager
from agent33.agents.reasoning import (
    ReasoningConfig,
    ReasoningProtocol,
    ReasoningStep,
)
from agent33.agents.registry import AgentRegistry
from agent33.agents.runtime import _build_system_prompt
from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig
from agent33.security.permissions import require_scope

if TYPE_CHECKING:
    from agent33.services.orchestration_state import OrchestrationStateStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/reasoning", tags=["reasoning"])

# ---------------------------------------------------------------------------
# In-memory state stores (per EvaluationService pattern)
# ---------------------------------------------------------------------------

_reasoning_states: dict[str, dict[str, Any]] = {}
_isc_managers: dict[str, ISCManager] = {}
_isc_criteria_store: dict[str, dict[str, Any]] = {}

_reasoning_state_store: OrchestrationStateStore | None = None
_REASONING_NAMESPACE = "reasoning"


def set_reasoning_state_store(store: OrchestrationStateStore | None) -> None:
    """Wire the OrchestrationStateStore for ISC criteria persistence."""
    global _reasoning_state_store  # noqa: PLW0603
    _reasoning_state_store = store
    _load_isc_criteria()


def _persist_isc_criteria() -> None:
    """Serialize ISC criteria (without check_fn callables) to the state store."""
    if _reasoning_state_store is None:
        return
    serializable: dict[str, dict[str, Any]] = {}
    for cid, entry in _isc_criteria_store.items():
        criterion: ISCCriterion = entry["criterion"]
        serializable[cid] = {
            "name": criterion.name,
            "description": criterion.description,
            "is_anti": criterion.is_anti,
            "check_type": entry["check_type"],
            "check_params": entry["check_params"],
        }
    _reasoning_state_store.write_namespace(_REASONING_NAMESPACE, {"criteria": serializable})


def _load_isc_criteria() -> None:
    """Deserialize ISC criteria from state store and repopulate in-memory stores."""
    if _reasoning_state_store is None:
        return
    payload = _reasoning_state_store.read_namespace(_REASONING_NAMESPACE)
    criteria_data = payload.get("criteria", {})
    if not isinstance(criteria_data, dict):
        return

    global_key = "global:default"
    for cid, data in criteria_data.items():
        if not isinstance(data, dict):
            continue
        try:
            check_type = CheckType(data["check_type"])
            check_params: dict[str, Any] = data.get("check_params", {})
            check_fn = _build_check_fn(check_type, check_params)
            criterion = ISCCriterion(
                name=data["name"],
                description=data["description"],
                check_fn=check_fn,
                is_anti=data.get("is_anti", False),
                criterion_id=cid,
            )
            _isc_criteria_store[cid] = {
                "criterion": criterion,
                "check_type": data["check_type"],
                "check_params": check_params,
            }
            if global_key not in _isc_managers:
                _isc_managers[global_key] = ISCManager()
            _isc_managers[global_key].add(criterion)
        except Exception as exc:
            logger.warning("isc_criteria_restore_failed cid=%s error=%s", cid, exc)


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------


def _get_registry(request: Request) -> AgentRegistry:
    registry = getattr(request.app.state, "agent_registry", None)
    if registry is None:
        registry = AgentRegistry()
    return registry


# ---------------------------------------------------------------------------
# Built-in check functions for API-created criteria
# ---------------------------------------------------------------------------


class CheckType(StrEnum):
    CONTAINS = "contains"
    REGEX = "regex"
    RANGE = "range"


def _build_check_fn(check_type: CheckType, params: dict[str, Any]) -> Any:
    """Create a callable from a predefined check type + params."""
    if check_type == CheckType.CONTAINS:
        target = str(params.get("target", ""))

        def _contains(ctx: dict[str, Any]) -> bool:
            text = str(ctx.get("task_input", ""))
            return target.lower() in text.lower()

        return _contains

    if check_type == CheckType.REGEX:
        pattern = str(params.get("pattern", ""))

        def _regex(ctx: dict[str, Any]) -> bool:
            text = str(ctx.get("task_input", ""))
            return bool(re.search(pattern, text))

        return _regex

    if check_type == CheckType.RANGE:
        key = str(params.get("key", "value"))
        min_val = float(params.get("min", float("-inf")))
        max_val = float(params.get("max", float("inf")))

        def _range(ctx: dict[str, Any]) -> bool:
            val = ctx.get(key)
            if val is None:
                return False
            return min_val <= float(val) <= max_val

        return _range

    raise ValueError(f"Unknown check type: {check_type}")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class InvokeReasoningRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    temperature: float = 0.7
    max_steps: int = 25
    quality_gate_threshold: float = 0.7
    enable_anti_criteria: bool = True


class InvokeReasoningResponse(BaseModel):
    agent: str
    output: str
    steps: list[ReasoningStep]
    termination_reason: str
    total_steps: int
    phase_artifacts: dict[str, Any] = Field(default_factory=dict)


class ISCCriterionRequest(BaseModel):
    name: str
    description: str
    is_anti: bool = False
    check_type: CheckType = CheckType.CONTAINS
    check_params: dict[str, Any] = Field(default_factory=dict)


class ISCCriterionResponse(BaseModel):
    criterion_id: str
    name: str
    description: str
    is_anti: bool


class ISCSetResponse(BaseModel):
    criteria: list[ISCCriterionResponse]
    total: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/{agent_name}/invoke",
    dependencies=[require_scope("agents:invoke")],
)
async def invoke_reasoning(
    agent_name: str,
    body: InvokeReasoningRequest,
    request: Request,
    registry: AgentRegistry = Depends(_get_registry),  # noqa: B008
) -> InvokeReasoningResponse:
    """Invoke an agent with the 5-phase reasoning protocol."""
    definition = registry.get(agent_name)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

    model_router = getattr(request.app.state, "model_router", None)
    if model_router is None:
        raise HTTPException(status_code=503, detail="Model router not initialized")

    tool_registry = getattr(request.app.state, "tool_registry", None)
    if tool_registry is None:
        raise HTTPException(status_code=503, detail="Tool registry not initialized")

    # Build system prompt
    system_prompt = _build_system_prompt(definition)

    # Create tool loop
    loop_config = ToolLoopConfig()
    tool_loop = ToolLoop(
        router=model_router,
        tool_registry=tool_registry,
        config=loop_config,
        agent_name=agent_name,
    )

    # Get or create ISC manager for this session
    session_key = f"{agent_name}:default"
    isc_manager = _isc_managers.get(session_key)

    # Create reasoning protocol
    reasoning_config = ReasoningConfig(
        max_steps=body.max_steps,
        quality_gate_threshold=body.quality_gate_threshold,
        enable_anti_criteria=body.enable_anti_criteria,
    )
    protocol = ReasoningProtocol(
        config=reasoning_config,
        isc_manager=isc_manager,
    )

    model = body.model or definition.constraints.max_tokens and "llama3.2" or "llama3.2"

    import json

    task_input = json.dumps(body.inputs, indent=2)

    try:
        result = await protocol.run(
            task_input=task_input,
            tool_loop=tool_loop,
            model=model,
            router=model_router,
            temperature=body.temperature,
            system_prompt=system_prompt,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Store state for status lookups
    _reasoning_states[session_key] = {
        "agent": agent_name,
        "total_steps": result.total_steps,
        "termination_reason": result.termination_reason,
        "status": "completed",
    }

    # Serialize phase artifacts (only serializable parts)
    serialized_artifacts: dict[str, Any] = {}
    for key, artifact in result.phase_artifacts.items():
        try:
            import dataclasses as dc

            if dc.is_dataclass(artifact) and not isinstance(artifact, type):
                serialized_artifacts[key] = dc.asdict(artifact)
            else:
                serialized_artifacts[key] = str(artifact)
        except Exception:
            serialized_artifacts[key] = str(artifact)

    return InvokeReasoningResponse(
        agent=agent_name,
        output=result.final_output,
        steps=result.steps,
        termination_reason=result.termination_reason,
        total_steps=result.total_steps,
        phase_artifacts=serialized_artifacts,
    )


@router.get(
    "/{agent_name}/status",
    dependencies=[require_scope("agents:read")],
)
async def reasoning_status(agent_name: str) -> dict[str, Any]:
    """Get the status of the most recent reasoning session for an agent."""
    session_key = f"{agent_name}:default"
    state = _reasoning_states.get(session_key)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"No reasoning session found for agent '{agent_name}'",
        )
    return state


@router.post(
    "/isc",
    status_code=201,
    dependencies=[require_scope("agents:write")],
)
async def create_isc_criteria(body: ISCCriterionRequest) -> ISCCriterionResponse:
    """Create an ISC criterion with a built-in check function."""
    try:
        check_fn = _build_check_fn(body.check_type, body.check_params)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    criterion = ISCCriterion(
        name=body.name,
        description=body.description,
        check_fn=check_fn,
        is_anti=body.is_anti,
    )

    _isc_criteria_store[criterion.criterion_id] = {
        "criterion": criterion,
        "check_type": body.check_type.value,
        "check_params": body.check_params,
    }

    # Also register in a global ISC manager so it's available to reasoning sessions
    global_key = "global:default"
    if global_key not in _isc_managers:
        _isc_managers[global_key] = ISCManager()
    _isc_managers[global_key].add(criterion)

    _persist_isc_criteria()

    return ISCCriterionResponse(
        criterion_id=criterion.criterion_id,
        name=criterion.name,
        description=criterion.description,
        is_anti=criterion.is_anti,
    )


@router.get(
    "/isc/{criteria_id}",
    dependencies=[require_scope("agents:read")],
)
async def get_isc_criteria(criteria_id: str) -> ISCCriterionResponse:
    """Retrieve an ISC criterion by ID."""
    entry = _isc_criteria_store.get(criteria_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"ISC criterion '{criteria_id}' not found",
        )
    criterion = entry["criterion"]
    return ISCCriterionResponse(
        criterion_id=criterion.criterion_id,
        name=criterion.name,
        description=criterion.description,
        is_anti=criterion.is_anti,
    )
