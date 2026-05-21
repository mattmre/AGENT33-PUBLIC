"""Tests for Phase 53: Subagent Delegation Framework.

Covers:
  - DelegationRequest / DelegationResult model validation
  - DelegationManager capability matching against real registry entries
  - Token budget splitting with various reserve fractions
  - Single delegation with target_agent (found / not found)
  - Single delegation with required_capability (match / no match)
  - Depth enforcement (reject at max_depth)
  - Timeout enforcement (child exceeds timeout)
  - Child invocation error handling
  - Fan-out parallel delegation with partial failures
  - Result aggregation logic
  - API route integration (delegate, fan-out, match, split-budget, history)
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from agent33.agents.definition import (
    AgentConstraints,
    AgentDefinition,
    AgentStatus,
    SpecCapability,
)
from agent33.agents.delegation import (
    DelegationManager,
    DelegationRequest,
    DelegationResult,
    DelegationStatus,
)
from agent33.agents.registry import AgentRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_definition(
    name: str,
    *,
    spec_caps: list[str] | None = None,
    max_tokens: int = 4096,
    status: str = "active",
) -> AgentDefinition:
    """Create a minimal AgentDefinition for testing."""
    return AgentDefinition(
        name=name,
        version="1.0.0",
        role="implementer",
        description=f"Test agent {name}",
        spec_capabilities=[SpecCapability(c) for c in (spec_caps or [])],
        constraints=AgentConstraints(max_tokens=max_tokens),
        status=AgentStatus(status),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry() -> AgentRegistry:
    """Registry with several agents having distinct capabilities."""
    reg = AgentRegistry()
    reg.register(
        _make_definition("code-worker", spec_caps=["I-01", "I-02", "I-03", "I-04", "I-05"])
    )
    reg.register(
        _make_definition("researcher", spec_caps=["X-01", "X-02", "X-03", "X-04", "X-05"])
    )
    reg.register(_make_definition("qa-agent", spec_caps=["V-01", "V-02", "V-03", "V-04", "V-05"]))
    reg.register(
        _make_definition(
            "deprecated-agent",
            spec_caps=["I-01"],
            status="deprecated",
        )
    )
    return reg


@pytest.fixture()
def mock_router() -> MagicMock:
    router = MagicMock()
    router.complete = AsyncMock()
    return router


@pytest.fixture()
def manager(registry: AgentRegistry, mock_router: MagicMock) -> DelegationManager:
    return DelegationManager(registry=registry, router=mock_router)


# ===========================================================================
# Model validation tests
# ===========================================================================


class TestDelegationRequestModel:
    """Validate DelegationRequest constraints."""

    def test_default_values(self) -> None:
        req = DelegationRequest()
        assert req.token_budget == 4096
        assert req.timeout_seconds == 120
        assert req.depth == 0
        assert req.delegation_id  # auto-generated

    def test_token_budget_minimum(self) -> None:
        with pytest.raises(ValidationError, match="token_budget"):
            DelegationRequest(token_budget=50)

    def test_token_budget_maximum(self) -> None:
        with pytest.raises(ValidationError, match="token_budget"):
            DelegationRequest(token_budget=300000)

    def test_timeout_minimum(self) -> None:
        with pytest.raises(ValidationError, match="timeout_seconds"):
            DelegationRequest(timeout_seconds=5)

    def test_custom_delegation_id(self) -> None:
        req = DelegationRequest(delegation_id="my-id-123")
        assert req.delegation_id == "my-id-123"

    def test_inputs_default_to_empty_dict(self) -> None:
        req = DelegationRequest()
        assert req.inputs == {}


class TestDelegationResultModel:
    """Validate DelegationResult structure."""

    def test_completed_result(self) -> None:
        r = DelegationResult(
            delegation_id="abc",
            target_agent="worker",
            status=DelegationStatus.COMPLETED,
            output={"code": "print('hi')"},
            tokens_used=150,
            model="gpt-4",
            duration_seconds=2.5,
        )
        assert r.status == DelegationStatus.COMPLETED
        assert r.tokens_used == 150

    def test_failed_result_with_error(self) -> None:
        r = DelegationResult(
            delegation_id="def",
            target_agent="missing",
            status=DelegationStatus.FAILED,
            error="Agent not found",
        )
        assert r.error == "Agent not found"
        assert r.output == {}


# ===========================================================================
# Capability matching tests
# ===========================================================================


class TestCapabilityMatching:
    """Test DelegationManager.match_capability()."""

    def test_match_implementation_capability(self, manager: DelegationManager) -> None:
        """I-01 should match code-worker (active) and deprecated-agent."""
        matches = manager.match_capability("I-01")
        names = [m.agent_name for m in matches]
        assert "code-worker" in names
        assert "deprecated-agent" in names

    def test_active_agent_scores_higher_than_deprecated(self, manager: DelegationManager) -> None:
        """Active agents should score higher than deprecated ones."""
        matches = manager.match_capability("I-01")
        scores = {m.agent_name: m.score for m in matches}
        assert scores["code-worker"] > scores["deprecated-agent"]

    def test_specialised_agent_scores_higher(
        self, registry: AgentRegistry, mock_router: MagicMock
    ) -> None:
        """An agent with fewer total capabilities (more specialised) scores higher."""
        # Add a specialist with only 1 capability
        registry.register(_make_definition("specialist", spec_caps=["I-01"]))
        mgr = DelegationManager(registry=registry, router=mock_router)
        matches = mgr.match_capability("I-01")
        scores = {m.agent_name: m.score for m in matches}
        assert scores["specialist"] > scores["code-worker"]

    def test_match_research_capability(self, manager: DelegationManager) -> None:
        matches = manager.match_capability("X-01")
        assert len(matches) == 1
        assert matches[0].agent_name == "researcher"

    def test_match_unknown_capability_returns_empty(self, manager: DelegationManager) -> None:
        matches = manager.match_capability("Z-99")
        assert matches == []

    def test_exclude_agents_filters_results(self, manager: DelegationManager) -> None:
        matches = manager.match_capability("I-01", exclude_agents=["code-worker"])
        names = [m.agent_name for m in matches]
        assert "code-worker" not in names
        assert "deprecated-agent" in names

    def test_match_returns_matching_capabilities_list(self, manager: DelegationManager) -> None:
        matches = manager.match_capability("V-01")
        assert len(matches) == 1
        assert "V-01" in matches[0].matching_capabilities

    def test_match_includes_agent_id(
        self, registry: AgentRegistry, mock_router: MagicMock
    ) -> None:
        """If the agent has an agent_id, it should appear in the match."""
        defn = _make_definition("id-agent", spec_caps=["I-01"])
        # Manually set agent_id (bypasses pattern validation if we use model_validate)
        defn_data = defn.model_dump()
        defn_data["agent_id"] = "AGT-099"
        defn_with_id = AgentDefinition.model_validate(defn_data)
        registry.register(defn_with_id)
        mgr = DelegationManager(registry=registry, router=mock_router)
        matches = mgr.match_capability("I-01")
        id_agent_match = next(m for m in matches if m.agent_name == "id-agent")
        assert id_agent_match.agent_id == "AGT-099"


# ===========================================================================
# Token budget splitting tests
# ===========================================================================


class TestBudgetSplitting:
    """Test DelegationManager.split_budget()."""

    def test_equal_split_no_reserve(self) -> None:
        budgets = DelegationManager.split_budget(1000, 4, reserve_fraction=0.0)
        assert len(budgets) == 4
        assert all(b == 250 for b in budgets)

    def test_default_reserve_fraction(self) -> None:
        budgets = DelegationManager.split_budget(1000, 2)
        # Default reserve is 20%, so 800 available, 400 each
        assert budgets == [400, 400]

    def test_large_reserve(self) -> None:
        budgets = DelegationManager.split_budget(1000, 2, reserve_fraction=0.5)
        assert budgets == [250, 250]

    def test_single_child(self) -> None:
        budgets = DelegationManager.split_budget(1000, 1, reserve_fraction=0.2)
        assert budgets == [800]

    def test_minimum_budget_is_100(self) -> None:
        """Even with tiny parent budget, each child gets at least 100."""
        budgets = DelegationManager.split_budget(200, 10, reserve_fraction=0.0)
        assert all(b >= 100 for b in budgets)

    def test_zero_children_raises(self) -> None:
        with pytest.raises(ValueError, match="num_children must be >= 1"):
            DelegationManager.split_budget(1000, 0)

    def test_reserve_fraction_1_raises(self) -> None:
        with pytest.raises(ValueError, match="reserve_fraction"):
            DelegationManager.split_budget(1000, 2, reserve_fraction=1.0)

    def test_reserve_fraction_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="reserve_fraction"):
            DelegationManager.split_budget(1000, 2, reserve_fraction=-0.1)


# ===========================================================================
# Single delegation tests
# ===========================================================================


class TestSingleDelegation:
    """Test DelegationManager.delegate()."""

    async def test_delegate_by_target_agent_success(
        self, manager: DelegationManager, mock_router: MagicMock
    ) -> None:
        """Delegating to a named agent should invoke it and return result."""
        from agent33.llm.base import LLMResponse

        mock_router.complete.return_value = LLMResponse(
            content='{"code": "print(42)"}',
            model="test-model",
            prompt_tokens=50,
            completion_tokens=30,
        )

        req = DelegationRequest(
            target_agent="code-worker",
            inputs={"instruction": "Write a hello world"},
            token_budget=8000,
        )
        result = await manager.delegate(req)

        assert result.status == DelegationStatus.COMPLETED
        assert result.target_agent == "code-worker"
        assert result.tokens_used > 0
        assert result.duration_seconds >= 0
        assert result.delegation_id == req.delegation_id

    async def test_delegate_by_target_agent_not_found(self, manager: DelegationManager) -> None:
        req = DelegationRequest(target_agent="nonexistent-agent")
        result = await manager.delegate(req)

        assert result.status == DelegationStatus.FAILED
        assert "not found" in result.error

    async def test_delegate_by_capability_success(
        self, manager: DelegationManager, mock_router: MagicMock
    ) -> None:
        """Delegating by capability should match and invoke the best agent."""
        from agent33.llm.base import LLMResponse

        mock_router.complete.return_value = LLMResponse(
            content='{"answer": "Python is great"}',
            model="test-model",
            prompt_tokens=50,
            completion_tokens=30,
        )

        req = DelegationRequest(
            required_capability="X-01",
            inputs={"query": "What is Python?"},
        )
        result = await manager.delegate(req)

        assert result.status == DelegationStatus.COMPLETED
        assert result.target_agent == "researcher"

    async def test_delegate_by_capability_no_match(self, manager: DelegationManager) -> None:
        req = DelegationRequest(required_capability="Z-99")
        result = await manager.delegate(req)

        assert result.status == DelegationStatus.FAILED
        assert "No agent found" in result.error

    async def test_delegate_neither_target_nor_capability(
        self, manager: DelegationManager
    ) -> None:
        """Must specify at least one of target_agent or required_capability."""
        req = DelegationRequest(inputs={"data": "something"})
        result = await manager.delegate(req)

        assert result.status == DelegationStatus.REJECTED
        assert "Either target_agent or required_capability" in result.error

    async def test_delegate_capability_excludes_parent(
        self, manager: DelegationManager, mock_router: MagicMock
    ) -> None:
        """When parent_agent matches a candidate, it should be excluded."""
        from agent33.llm.base import LLMResponse

        mock_router.complete.return_value = LLMResponse(
            content='{"result": "ok"}',
            model="test-model",
            prompt_tokens=10,
            completion_tokens=10,
        )

        # code-worker has I-01. If parent is code-worker, it should pick
        # deprecated-agent as fallback (the only other I-01 agent)
        req = DelegationRequest(
            parent_agent="code-worker",
            required_capability="I-01",
        )
        result = await manager.delegate(req)

        assert result.status == DelegationStatus.COMPLETED
        assert result.target_agent == "deprecated-agent"


# ===========================================================================
# Depth enforcement tests
# ===========================================================================


class TestDepthEnforcement:
    """Verify max delegation depth is enforced."""

    async def test_depth_0_allowed(
        self, manager: DelegationManager, mock_router: MagicMock
    ) -> None:
        from agent33.llm.base import LLMResponse

        mock_router.complete.return_value = LLMResponse(
            content='{"result": "ok"}',
            model="m",
            prompt_tokens=10,
            completion_tokens=10,
        )
        req = DelegationRequest(target_agent="code-worker", depth=0)
        result = await manager.delegate(req)
        assert result.status == DelegationStatus.COMPLETED

    async def test_depth_at_max_rejected(self, manager: DelegationManager) -> None:
        req = DelegationRequest(
            target_agent="code-worker",
            depth=manager.max_depth,
        )
        result = await manager.delegate(req)
        assert result.status == DelegationStatus.REJECTED
        assert "depth limit" in result.error.lower()

    async def test_depth_exceeding_max_rejected(self, manager: DelegationManager) -> None:
        req = DelegationRequest(
            target_agent="code-worker",
            depth=manager.max_depth + 5,
        )
        result = await manager.delegate(req)
        assert result.status == DelegationStatus.REJECTED

    async def test_custom_max_depth(self, registry: AgentRegistry, mock_router: MagicMock) -> None:
        mgr = DelegationManager(registry=registry, router=mock_router, max_depth=1)
        req = DelegationRequest(target_agent="code-worker", depth=1)
        result = await mgr.delegate(req)
        assert result.status == DelegationStatus.REJECTED


# ===========================================================================
# Timeout tests
# ===========================================================================


class TestTimeoutEnforcement:
    """Verify child agent timeout is enforced."""

    async def test_timeout_produces_timed_out_status(
        self, manager: DelegationManager, mock_router: MagicMock
    ) -> None:
        """A child that exceeds the timeout should get TIMED_OUT status."""

        async def slow_complete(*args: Any, **kwargs: Any) -> None:
            await asyncio.sleep(10)

        mock_router.complete = AsyncMock(side_effect=slow_complete)

        req = DelegationRequest(
            target_agent="code-worker",
            timeout_seconds=10,  # minimum allowed
        )
        # Patch asyncio.wait_for to use a short timeout
        with patch(
            "agent33.agents.delegation.asyncio.wait_for",
            side_effect=TimeoutError("timed out"),
        ):
            result = await manager.delegate(req)

        assert result.status == DelegationStatus.TIMED_OUT
        assert "timed out" in result.error.lower()

    async def test_timeout_records_duration(
        self, manager: DelegationManager, mock_router: MagicMock
    ) -> None:
        with patch(
            "agent33.agents.delegation.asyncio.wait_for",
            side_effect=TimeoutError("timed out"),
        ):
            req = DelegationRequest(target_agent="code-worker", timeout_seconds=10)
            result = await manager.delegate(req)

        assert result.duration_seconds >= 0


# ===========================================================================
# Error handling tests
# ===========================================================================


class TestErrorHandling:
    """Verify graceful handling of child execution errors."""

    async def test_child_runtime_error_produces_failed(
        self, manager: DelegationManager, mock_router: MagicMock
    ) -> None:
        mock_router.complete = AsyncMock(side_effect=RuntimeError("LLM connection refused"))

        req = DelegationRequest(target_agent="code-worker")
        result = await manager.delegate(req)

        assert result.status == DelegationStatus.FAILED
        # AgentRuntime exhausts retries and wraps into "failed after N attempts"
        assert "failed after" in result.error

    async def test_child_error_recorded_in_history(
        self, manager: DelegationManager, mock_router: MagicMock
    ) -> None:
        mock_router.complete = AsyncMock(side_effect=RuntimeError("boom"))

        req = DelegationRequest(target_agent="code-worker")
        await manager.delegate(req)

        assert len(manager.history) == 1
        assert manager.history[0].status == DelegationStatus.FAILED


# ===========================================================================
# Fan-out delegation tests
# ===========================================================================


class TestFanOutDelegation:
    """Test DelegationManager.delegate_fan_out()."""

    async def test_fan_out_multiple_agents(
        self, manager: DelegationManager, mock_router: MagicMock
    ) -> None:
        from agent33.llm.base import LLMResponse

        mock_router.complete.return_value = LLMResponse(
            content='{"result": "ok"}',
            model="test-model",
            prompt_tokens=10,
            completion_tokens=10,
        )

        requests = [
            DelegationRequest(target_agent="code-worker", inputs={"task": "A"}),
            DelegationRequest(target_agent="researcher", inputs={"task": "B"}),
            DelegationRequest(target_agent="qa-agent", inputs={"task": "C"}),
        ]
        results = await manager.delegate_fan_out(requests)

        assert len(results) == 3
        assert all(r.status == DelegationStatus.COMPLETED for r in results)
        targets = {r.target_agent for r in results}
        assert targets == {"code-worker", "researcher", "qa-agent"}

    async def test_fan_out_preserves_order(
        self, manager: DelegationManager, mock_router: MagicMock
    ) -> None:
        from agent33.llm.base import LLMResponse

        mock_router.complete.return_value = LLMResponse(
            content='{"result": "ok"}',
            model="m",
            prompt_tokens=10,
            completion_tokens=10,
        )

        requests = [
            DelegationRequest(
                delegation_id=f"req-{i}",
                target_agent="code-worker",
            )
            for i in range(3)
        ]
        results = await manager.delegate_fan_out(requests)

        for i, r in enumerate(results):
            assert r.delegation_id == f"req-{i}"

    async def test_fan_out_partial_failure(
        self, manager: DelegationManager, mock_router: MagicMock
    ) -> None:
        """Some tasks succeed, some fail (agent not found)."""
        from agent33.llm.base import LLMResponse

        mock_router.complete.return_value = LLMResponse(
            content='{"result": "ok"}',
            model="m",
            prompt_tokens=10,
            completion_tokens=10,
        )

        requests = [
            DelegationRequest(target_agent="code-worker"),
            DelegationRequest(target_agent="nonexistent"),
            DelegationRequest(target_agent="researcher"),
        ]
        results = await manager.delegate_fan_out(requests)

        assert results[0].status == DelegationStatus.COMPLETED
        assert results[1].status == DelegationStatus.FAILED
        assert results[2].status == DelegationStatus.COMPLETED

    async def test_fan_out_empty_list(self, manager: DelegationManager) -> None:
        results = await manager.delegate_fan_out([])
        assert results == []

    async def test_fan_out_respects_depth(self, manager: DelegationManager) -> None:
        """Fan-out should also enforce depth limits."""
        requests = [
            DelegationRequest(
                target_agent="code-worker",
                depth=manager.max_depth,
            ),
        ]
        results = await manager.delegate_fan_out(requests)
        assert results[0].status == DelegationStatus.REJECTED


# ===========================================================================
# Result aggregation tests
# ===========================================================================


class TestResultAggregation:
    """Test DelegationManager.aggregate_results()."""

    def test_all_completed(self) -> None:
        results = [
            DelegationResult(
                delegation_id="a",
                target_agent="w1",
                status=DelegationStatus.COMPLETED,
                tokens_used=100,
                duration_seconds=1.0,
            ),
            DelegationResult(
                delegation_id="b",
                target_agent="w2",
                status=DelegationStatus.COMPLETED,
                tokens_used=200,
                duration_seconds=2.0,
            ),
        ]
        agg = DelegationManager.aggregate_results(results)
        assert agg["total_delegations"] == 2
        assert agg["all_completed"] is True
        assert agg["total_tokens_used"] == 300
        assert agg["total_duration_seconds"] == 3.0
        assert agg["status_counts"]["completed"] == 2

    def test_mixed_statuses(self) -> None:
        results = [
            DelegationResult(
                delegation_id="a",
                target_agent="w1",
                status=DelegationStatus.COMPLETED,
                tokens_used=100,
                duration_seconds=1.0,
            ),
            DelegationResult(
                delegation_id="b",
                target_agent="w2",
                status=DelegationStatus.FAILED,
                error="boom",
                duration_seconds=0.5,
            ),
        ]
        agg = DelegationManager.aggregate_results(results)
        assert agg["all_completed"] is False
        assert agg["status_counts"]["completed"] == 1
        assert agg["status_counts"]["failed"] == 1

    def test_empty_results(self) -> None:
        agg = DelegationManager.aggregate_results([])
        assert agg["total_delegations"] == 0
        assert agg["all_completed"] is True
        assert agg["total_tokens_used"] == 0


# ===========================================================================
# History tracking tests
# ===========================================================================


class TestHistoryTracking:
    """Verify delegation results are recorded in history."""

    async def test_successful_delegation_recorded(
        self, manager: DelegationManager, mock_router: MagicMock
    ) -> None:
        from agent33.llm.base import LLMResponse

        mock_router.complete.return_value = LLMResponse(
            content='{"result": "ok"}',
            model="m",
            prompt_tokens=10,
            completion_tokens=10,
        )

        req = DelegationRequest(target_agent="code-worker")
        await manager.delegate(req)

        assert len(manager.history) == 1
        assert manager.history[0].status == DelegationStatus.COMPLETED

    async def test_history_is_append_only(
        self, manager: DelegationManager, mock_router: MagicMock
    ) -> None:
        from agent33.llm.base import LLMResponse

        mock_router.complete.return_value = LLMResponse(
            content='{"result": "ok"}',
            model="m",
            prompt_tokens=10,
            completion_tokens=10,
        )

        for _ in range(3):
            await manager.delegate(DelegationRequest(target_agent="code-worker"))

        assert len(manager.history) == 3

    async def test_rejected_not_in_history(self, manager: DelegationManager) -> None:
        """Rejected delegations (depth limit) should NOT appear in history
        because they never reached the invocation stage."""
        req = DelegationRequest(
            target_agent="code-worker",
            depth=manager.max_depth,
        )
        await manager.delegate(req)
        assert len(manager.history) == 0

    async def test_history_returns_copy(
        self, manager: DelegationManager, mock_router: MagicMock
    ) -> None:
        from agent33.llm.base import LLMResponse

        mock_router.complete.return_value = LLMResponse(
            content='{"result": "ok"}',
            model="m",
            prompt_tokens=10,
            completion_tokens=10,
        )

        await manager.delegate(DelegationRequest(target_agent="code-worker"))
        history = manager.history
        history.clear()
        # Original should not be affected
        assert len(manager.history) == 1


# ===========================================================================
# API route integration tests
# ===========================================================================


class TestDelegationAPIRoutes:
    """Integration tests for the delegation API routes.

    These use httpx.AsyncClient with ASGITransport to test the actual
    FastAPI route handlers, with mocked DelegationManager and auth.
    """

    @pytest.fixture()
    def app_with_delegation(self, registry: AgentRegistry, mock_router: MagicMock) -> Any:
        """Create a minimal FastAPI app with delegation routes and auth bypass."""
        from fastapi import FastAPI

        from agent33.api.routes.delegation import router

        app = FastAPI()
        app.include_router(router)

        # Install DelegationManager on app state
        mgr = DelegationManager(registry=registry, router=mock_router)
        app.state.delegation_manager = mgr
        app.state._mock_router = mock_router

        # Bypass auth middleware for testing
        from agent33.security.auth import TokenPayload

        @app.middleware("http")
        async def bypass_auth(request: Any, call_next: Any) -> Any:
            request.state.user = TokenPayload(
                sub="test-user",
                scopes=["agents:invoke", "agents:read"],
                tenant_id="test-tenant",
            )
            return await call_next(request)

        return app

    async def test_delegate_endpoint_success(self, app_with_delegation: Any) -> None:
        import httpx

        from agent33.llm.base import LLMResponse

        mock_router = app_with_delegation.state._mock_router
        mock_router.complete.return_value = LLMResponse(
            content='{"result": "delegation works"}',
            model="test-model",
            prompt_tokens=50,
            completion_tokens=30,
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_with_delegation),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/v1/delegation/delegate",
                json={
                    "target_agent": "code-worker",
                    "inputs": {"instruction": "Hello"},
                    "token_budget": 4096,
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["target_agent"] == "code-worker"

    async def test_delegate_endpoint_agent_not_found(self, app_with_delegation: Any) -> None:
        import httpx

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_with_delegation),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/v1/delegation/delegate",
                json={"target_agent": "nonexistent"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert "not found" in data["error"]

    async def test_match_capability_endpoint(self, app_with_delegation: Any) -> None:
        import httpx

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_with_delegation),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/v1/delegation/match-capability",
                json={"capability_id": "I-01"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        names = [m["agent_name"] for m in data]
        assert "code-worker" in names

    async def test_split_budget_endpoint(self, app_with_delegation: Any) -> None:
        import httpx

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_with_delegation),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/v1/delegation/split-budget",
                json={
                    "parent_budget": 10000,
                    "num_children": 4,
                    "reserve_fraction": 0.2,
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["parent_budget"] == 10000
        assert data["reserved_for_parent"] == 2000
        assert data["per_child_budget"] == 2000
        assert len(data["child_budgets"]) == 4

    async def test_fan_out_endpoint(self, app_with_delegation: Any) -> None:
        import httpx

        from agent33.llm.base import LLMResponse

        mock_router = app_with_delegation.state._mock_router
        mock_router.complete.return_value = LLMResponse(
            content='{"result": "ok"}',
            model="m",
            prompt_tokens=10,
            completion_tokens=10,
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_with_delegation),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/v1/delegation/fan-out",
                json={
                    "requests": [
                        {"target_agent": "code-worker", "inputs": {"task": "A"}},
                        {"target_agent": "researcher", "inputs": {"task": "B"}},
                    ]
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_delegations"] == 2
        assert data["all_completed"] is True

    async def test_history_endpoint(self, app_with_delegation: Any) -> None:
        import httpx

        from agent33.llm.base import LLMResponse

        mock_router = app_with_delegation.state._mock_router
        mock_router.complete.return_value = LLMResponse(
            content='{"result": "ok"}',
            model="m",
            prompt_tokens=10,
            completion_tokens=10,
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_with_delegation),
            base_url="http://test",
        ) as client:
            # First, create a delegation
            await client.post(
                "/v1/delegation/delegate",
                json={"target_agent": "code-worker"},
            )
            # Then check history
            resp = await client.get("/v1/delegation/history")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["target_agent"] == "code-worker"

    async def test_delegation_manager_not_initialized(self) -> None:
        """Without DelegationManager on app.state, routes should return 503."""
        import httpx
        from fastapi import FastAPI

        from agent33.api.routes.delegation import router
        from agent33.security.auth import TokenPayload

        app = FastAPI()
        app.include_router(router)

        @app.middleware("http")
        async def bypass_auth(request: Any, call_next: Any) -> Any:
            request.state.user = TokenPayload(
                sub="test-user",
                scopes=["agents:invoke", "agents:read"],
                tenant_id="t",
            )
            return await call_next(request)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/v1/delegation/delegate",
                json={"target_agent": "code-worker"},
            )

        assert resp.status_code == 503
        assert "not initialized" in resp.json()["detail"]
