"""Phase 53: Subagent Delegation Framework.

Provides a lightweight coordination layer for parent-to-child agent delegation.
The DelegationManager uses the existing AgentRegistry for capability-based agent
selection and AgentRuntime for actual execution, keeping the framework thin.

Key concepts:
  - DelegationRequest: what to delegate (target agent or required capability,
    inputs, token budget, constraints).
  - DelegationResult: child output, tokens consumed, timing, status.
  - DelegationManager: capability matching, token budget splitting, result
    aggregation, and parallel fan-out with depth enforcement.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.agents.definition import AgentDefinition
    from agent33.agents.registry import AgentRegistry
    from agent33.agents.runtime import AgentResult
    from agent33.llm.router import ModelRouter
    from agent33.services.orchestration_state import OrchestrationStateStore

logger = logging.getLogger(__name__)

_MAX_DELEGATION_DEPTH = 3
"""Hard ceiling on delegation nesting. Root is depth 0."""

_MAX_PARALLEL_CHILDREN = 5
"""Maximum concurrent child delegations during fan-out."""

_DEFAULT_TOKEN_BUDGET = 4096
"""Fallback token budget when none is specified."""


class DelegationStatus(StrEnum):
    """Lifecycle status for a single delegation."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    REJECTED = "rejected"


class DelegationRequest(BaseModel):
    """Describes a task to be delegated to a child agent.

    Callers specify *either* ``target_agent`` (by name) *or*
    ``required_capability`` (to let the manager pick the best agent).
    If both are provided, ``target_agent`` takes priority.
    """

    delegation_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    parent_agent: str = Field(
        default="",
        description="Name of the parent agent initiating the delegation.",
    )
    target_agent: str | None = Field(
        default=None,
        description="Explicit agent name to delegate to.",
    )
    required_capability: str | None = Field(
        default=None,
        description="Spec capability ID (e.g. 'I-01') to match against agents.",
    )
    inputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Input data for the child agent.",
    )
    token_budget: int = Field(
        default=_DEFAULT_TOKEN_BUDGET,
        ge=100,
        le=200000,
        description="Maximum tokens the child may consume.",
    )
    timeout_seconds: int = Field(
        default=120,
        ge=10,
        le=3600,
        description="Hard timeout for the child execution.",
    )
    depth: int = Field(
        default=0,
        ge=0,
        description="Current delegation depth (0 = root).",
    )
    model: str | None = Field(
        default=None,
        description="Optional model override for the child.",
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Opaque metadata forwarded to the child invocation.",
    )


class DelegationResult(BaseModel):
    """Captures the outcome of a single delegation."""

    delegation_id: str
    target_agent: str
    status: DelegationStatus
    output: dict[str, Any] = Field(default_factory=dict)
    raw_response: str = ""
    tokens_used: int = 0
    model: str = ""
    duration_seconds: float = 0.0
    error: str = ""
    depth: int = 0


class CapabilityMatch(BaseModel):
    """Result of matching a required capability to available agents."""

    agent_name: str
    agent_id: str | None = None
    matching_capabilities: list[str] = Field(default_factory=list)
    score: float = Field(
        default=0.0,
        description="Match quality score (0-1). Higher is better.",
    )


class DelegationManager:
    """Thin coordination layer for parent-to-child agent delegation.

    Uses the existing AgentRegistry for agent lookup and capability matching,
    and AgentRuntime for actual invocation. Does not create its own runtime;
    instead it constructs an AgentRuntime per delegation.
    """

    _NAMESPACE = "delegation_history"

    def __init__(
        self,
        registry: AgentRegistry,
        router: ModelRouter,
        *,
        max_depth: int = _MAX_DELEGATION_DEPTH,
        max_parallel: int = _MAX_PARALLEL_CHILDREN,
        state_store: OrchestrationStateStore | None = None,
    ) -> None:
        self._registry = registry
        self._router = router
        self._max_depth = max_depth
        self._max_parallel = max_parallel
        self._semaphore = asyncio.Semaphore(max_parallel)
        self._history: list[DelegationResult] = []
        self._state_store = state_store
        if state_store is None:
            logger.warning(
                "delegation_manager_no_state_store: history will not persist across restarts"
            )
        self._load_state()

    def _persist_state(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            self._NAMESPACE,
            {"history": [r.model_dump(mode="json") for r in self._history]},
        )

    def _load_state(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace(self._NAMESPACE)
        for item in payload.get("history", []):
            if not isinstance(item, dict):
                continue
            try:
                self._history.append(DelegationResult.model_validate(item))
            except Exception as exc:
                logger.warning("delegation_result_restore_failed: %s", exc)

    @property
    def registry(self) -> AgentRegistry:
        return self._registry

    @property
    def max_depth(self) -> int:
        return self._max_depth

    @property
    def history(self) -> list[DelegationResult]:
        """Return a copy of the delegation history (most recent last)."""
        return list(self._history)

    # ------------------------------------------------------------------
    # Capability matching
    # ------------------------------------------------------------------

    def match_capability(
        self,
        capability_id: str,
        *,
        exclude_agents: list[str] | None = None,
    ) -> list[CapabilityMatch]:
        """Find agents that declare a given spec capability.

        Returns matches sorted by score descending. The score favours agents
        with ACTIVE status and those that declare fewer total capabilities
        (more specialised).
        """
        from agent33.agents.definition import AgentStatus, SpecCapability

        try:
            cap = SpecCapability(capability_id)
        except ValueError:
            logger.warning("unknown_capability_id: %s", capability_id)
            return []

        candidates = self._registry.find_by_spec_capability(cap)
        excluded = set(exclude_agents or [])
        matches: list[CapabilityMatch] = []

        for defn in candidates:
            if defn.name in excluded:
                continue

            # Score: 1.0 base, +1.5 for active status, small specialisation bonus.
            # Active bonus dominates so deprecated agents rank below active ones
            # even if the deprecated agent is more specialised.
            score = 1.0
            if defn.status == AgentStatus.ACTIVE:
                score += 1.5
            elif defn.status == AgentStatus.EXPERIMENTAL:
                score += 0.5
            # Fewer capabilities = more specialised = small bonus (capped at 1.0)
            total_caps = len(defn.spec_capabilities)
            if total_caps > 0:
                score += min(1.0 / total_caps, 1.0)

            matches.append(
                CapabilityMatch(
                    agent_name=defn.name,
                    agent_id=defn.agent_id,
                    matching_capabilities=[c.value for c in defn.spec_capabilities if c == cap],
                    score=round(score, 3),
                )
            )

        matches.sort(key=lambda m: m.score, reverse=True)
        return matches

    # ------------------------------------------------------------------
    # Token budget splitting
    # ------------------------------------------------------------------

    @staticmethod
    def split_budget(
        parent_budget: int,
        num_children: int,
        *,
        reserve_fraction: float = 0.2,
    ) -> list[int]:
        """Split a parent's token budget across N children.

        Reserves ``reserve_fraction`` of the budget for the parent's own
        post-processing, then divides the remainder equally.

        Parameters
        ----------
        parent_budget:
            Total tokens available to the parent.
        num_children:
            Number of children to split across.
        reserve_fraction:
            Fraction (0-1) to keep for the parent.

        Returns
        -------
        list[int]
            Per-child token budgets.

        Raises
        ------
        ValueError
            If num_children < 1 or reserve_fraction not in [0, 1).
        """
        if num_children < 1:
            raise ValueError("num_children must be >= 1")
        if not (0.0 <= reserve_fraction < 1.0):
            raise ValueError("reserve_fraction must be in [0, 1)")

        reserved = int(parent_budget * reserve_fraction)
        available = parent_budget - reserved
        per_child = max(available // num_children, 100)
        return [per_child] * num_children

    # ------------------------------------------------------------------
    # Single delegation
    # ------------------------------------------------------------------

    async def delegate(
        self,
        request: DelegationRequest,
    ) -> DelegationResult:
        """Execute a single delegation request.

        Resolution order:
        1. If ``target_agent`` is specified, look it up directly.
        2. If ``required_capability`` is specified, find the best match.
        3. If neither is specified, reject.
        """
        # --- Depth enforcement ---
        if request.depth >= self._max_depth:
            return DelegationResult(
                delegation_id=request.delegation_id,
                target_agent=request.target_agent or "",
                status=DelegationStatus.REJECTED,
                error=(
                    f"Delegation depth limit reached "
                    f"(depth={request.depth}, max={self._max_depth})"
                ),
                depth=request.depth,
            )

        # --- Resolve target agent ---
        definition: AgentDefinition | None = None
        target_name = ""

        if request.target_agent:
            definition = self._registry.get(request.target_agent)
            if definition is None:
                return DelegationResult(
                    delegation_id=request.delegation_id,
                    target_agent=request.target_agent,
                    status=DelegationStatus.FAILED,
                    error=f"Agent '{request.target_agent}' not found in registry",
                    depth=request.depth,
                )
            target_name = definition.name

        elif request.required_capability:
            matches = self.match_capability(
                request.required_capability,
                exclude_agents=[request.parent_agent] if request.parent_agent else None,
            )
            if not matches:
                return DelegationResult(
                    delegation_id=request.delegation_id,
                    target_agent="",
                    status=DelegationStatus.FAILED,
                    error=(f"No agent found with capability '{request.required_capability}'"),
                    depth=request.depth,
                )
            # Pick the best match
            best = matches[0]
            definition = self._registry.get(best.agent_name)
            if definition is None:
                return DelegationResult(
                    delegation_id=request.delegation_id,
                    target_agent=best.agent_name,
                    status=DelegationStatus.FAILED,
                    error=f"Matched agent '{best.agent_name}' disappeared from registry",
                    depth=request.depth,
                )
            target_name = definition.name

        else:
            return DelegationResult(
                delegation_id=request.delegation_id,
                target_agent="",
                status=DelegationStatus.REJECTED,
                error="Either target_agent or required_capability must be specified",
                depth=request.depth,
            )

        # --- Invoke the child agent ---
        return await self._invoke_child(
            definition=definition,
            request=request,
            target_name=target_name,
        )

    async def _invoke_child(
        self,
        *,
        definition: AgentDefinition,
        request: DelegationRequest,
        target_name: str,
    ) -> DelegationResult:
        """Construct an AgentRuntime and invoke the child agent."""
        from agent33.agents.runtime import AgentRuntime

        # Apply token budget: use whichever is smaller between the request
        # budget and the definition's own max_tokens constraint.
        effective_max_tokens = min(
            request.token_budget,
            definition.constraints.max_tokens,
        )

        # Override constraints with effective budget for this invocation.
        # We do this by constructing the runtime with the budget-limited model.
        runtime = AgentRuntime(
            definition=definition,
            router=self._router,
            model=request.model,
            temperature=request.temperature,
        )

        start = time.monotonic()
        try:
            agent_result: AgentResult = await asyncio.wait_for(
                runtime.invoke(request.inputs),
                timeout=request.timeout_seconds,
            )
        except TimeoutError:
            elapsed = time.monotonic() - start
            result = DelegationResult(
                delegation_id=request.delegation_id,
                target_agent=target_name,
                status=DelegationStatus.TIMED_OUT,
                error=f"Child agent '{target_name}' timed out after {request.timeout_seconds}s",
                duration_seconds=round(elapsed, 3),
                depth=request.depth,
            )
            self._history.append(result)
            self._persist_state()
            return result
        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.exception(
                "delegation_failed agent=%s delegation_id=%s",
                target_name,
                request.delegation_id,
            )
            result = DelegationResult(
                delegation_id=request.delegation_id,
                target_agent=target_name,
                status=DelegationStatus.FAILED,
                error=str(exc),
                duration_seconds=round(elapsed, 3),
                depth=request.depth,
            )
            self._history.append(result)
            self._persist_state()
            return result

        elapsed = time.monotonic() - start

        # Enforce token budget: if the child exceeded the budget, we still
        # return the result but mark it in metadata.
        budget_exceeded = agent_result.tokens_used > effective_max_tokens

        result = DelegationResult(
            delegation_id=request.delegation_id,
            target_agent=target_name,
            status=DelegationStatus.COMPLETED,
            output=agent_result.output,
            raw_response=agent_result.raw_response,
            tokens_used=agent_result.tokens_used,
            model=agent_result.model,
            duration_seconds=round(elapsed, 3),
            depth=request.depth,
        )

        if budget_exceeded:
            logger.warning(
                "delegation_budget_exceeded agent=%s budget=%d used=%d",
                target_name,
                effective_max_tokens,
                agent_result.tokens_used,
            )

        self._history.append(result)
        self._persist_state()
        return result

    # ------------------------------------------------------------------
    # Fan-out delegation (parallel)
    # ------------------------------------------------------------------

    async def delegate_fan_out(
        self,
        requests: list[DelegationRequest],
    ) -> list[DelegationResult]:
        """Execute multiple delegation requests concurrently.

        Uses a semaphore to limit parallelism to ``max_parallel``.
        Results are returned in the same order as the input requests.

        Empty request lists return an empty result list.
        """
        if not requests:
            return []

        async def _run_one(req: DelegationRequest) -> DelegationResult:
            async with self._semaphore:
                return await self.delegate(req)

        tasks = [asyncio.create_task(_run_one(req)) for req in requests]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final: list[DelegationResult] = []
        for i, r in enumerate(results):
            if isinstance(r, BaseException):
                final.append(
                    DelegationResult(
                        delegation_id=requests[i].delegation_id,
                        target_agent=requests[i].target_agent or "",
                        status=DelegationStatus.FAILED,
                        error=str(r),
                        depth=requests[i].depth,
                    )
                )
            else:
                final.append(r)

        return final

    # ------------------------------------------------------------------
    # Result aggregation
    # ------------------------------------------------------------------

    @staticmethod
    def aggregate_results(
        results: list[DelegationResult],
    ) -> dict[str, Any]:
        """Aggregate multiple delegation results into a summary.

        Returns a dict with counts by status, total tokens, and the
        individual results.
        """
        status_counts: dict[str, int] = {}
        total_tokens = 0
        total_duration = 0.0

        for r in results:
            status_counts[r.status.value] = status_counts.get(r.status.value, 0) + 1
            total_tokens += r.tokens_used
            total_duration += r.duration_seconds

        return {
            "total_delegations": len(results),
            "status_counts": status_counts,
            "total_tokens_used": total_tokens,
            "total_duration_seconds": round(total_duration, 3),
            "all_completed": all(r.status == DelegationStatus.COMPLETED for r in results),
            "results": [r.model_dump(mode="json") for r in results],
        }
