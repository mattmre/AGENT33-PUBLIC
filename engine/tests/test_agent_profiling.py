"""Tests for S40: Agent Performance Profiling.

Covers the AgentProfiler core logic (recording, summaries, ring buffer eviction,
bottleneck detection, hot-path identification) and the API endpoints wired via
app.state.agent_profiler.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from agent33.agents.profiling import (
    AgentInvocationProfile,
    AgentPerformanceSummary,
    AgentProfiler,
    _percentile,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    agent_name: str = "test-agent",
    invocation_id: str = "inv-001",
    total_duration_ms: float = 100.0,
    prompt_construction_ms: float = 10.0,
    llm_call_ms: float = 70.0,
    tool_calls_ms: float = 15.0,
    post_processing_ms: float = 5.0,
    token_input: int = 500,
    token_output: int = 200,
    tool_call_count: int = 2,
    model_id: str = "llama3.2",
    success: bool = True,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> AgentInvocationProfile:
    now = started_at or datetime.now(UTC)
    return AgentInvocationProfile(
        agent_name=agent_name,
        invocation_id=invocation_id,
        started_at=now,
        completed_at=completed_at or now + timedelta(milliseconds=total_duration_ms),
        total_duration_ms=total_duration_ms,
        prompt_construction_ms=prompt_construction_ms,
        llm_call_ms=llm_call_ms,
        tool_calls_ms=tool_calls_ms,
        post_processing_ms=post_processing_ms,
        token_input=token_input,
        token_output=token_output,
        tool_call_count=tool_call_count,
        model_id=model_id,
        success=success,
    )


def _auth_headers() -> dict[str, str]:
    """Create valid JWT auth headers with agents:read scope."""
    from agent33.security.auth import create_access_token

    token = create_access_token(
        "test-user",
        scopes=["admin", "agents:read"],
        tenant_id="t-test",
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Percentile helper
# ---------------------------------------------------------------------------


class TestPercentile:
    def test_empty_list(self) -> None:
        assert _percentile([], 95) == 0.0

    def test_single_value(self) -> None:
        assert _percentile([42.0], 95) == 42.0

    def test_p95_two_values(self) -> None:
        # With [10, 20], p95 = 10 + 0.95*(20-10) = 19.5
        result = _percentile([10.0, 20.0], 95)
        assert result == pytest.approx(19.5, abs=0.01)

    def test_p50_is_median(self) -> None:
        result = _percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50)
        assert result == pytest.approx(3.0, abs=0.01)

    def test_p0_is_minimum(self) -> None:
        assert _percentile([5.0, 10.0, 15.0], 0) == 5.0

    def test_p100_is_maximum(self) -> None:
        assert _percentile([5.0, 10.0, 15.0], 100) == 15.0


# ---------------------------------------------------------------------------
# Profile recording
# ---------------------------------------------------------------------------


class TestProfileRecording:
    def test_record_single_profile(self) -> None:
        profiler = AgentProfiler()
        profile = _make_profile()
        profiler.record_profile(profile)

        retrieved = profiler.get_profiles()
        assert len(retrieved) == 1
        assert retrieved[0].agent_name == "test-agent"
        assert retrieved[0].invocation_id == "inv-001"

    def test_record_multiple_profiles(self) -> None:
        profiler = AgentProfiler()
        for i in range(5):
            profiler.record_profile(_make_profile(invocation_id=f"inv-{i:03d}"))

        retrieved = profiler.get_profiles()
        assert len(retrieved) == 5

    def test_profiles_returned_newest_first(self) -> None:
        profiler = AgentProfiler()
        profiler.record_profile(_make_profile(invocation_id="old"))
        profiler.record_profile(_make_profile(invocation_id="new"))

        retrieved = profiler.get_profiles()
        assert retrieved[0].invocation_id == "new"
        assert retrieved[1].invocation_id == "old"

    def test_profiles_filtered_by_agent_name(self) -> None:
        profiler = AgentProfiler()
        profiler.record_profile(_make_profile(agent_name="alpha"))
        profiler.record_profile(_make_profile(agent_name="beta"))
        profiler.record_profile(_make_profile(agent_name="alpha"))

        alpha_profiles = profiler.get_profiles(agent_name="alpha")
        assert len(alpha_profiles) == 2
        assert all(p.agent_name == "alpha" for p in alpha_profiles)

    def test_profiles_limit_respected(self) -> None:
        profiler = AgentProfiler()
        for i in range(10):
            profiler.record_profile(_make_profile(invocation_id=f"inv-{i:03d}"))

        retrieved = profiler.get_profiles(limit=3)
        assert len(retrieved) == 3
        # Newest first
        assert retrieved[0].invocation_id == "inv-009"


# ---------------------------------------------------------------------------
# Ring buffer eviction
# ---------------------------------------------------------------------------


class TestRingBufferEviction:
    def test_evicts_oldest_when_full(self) -> None:
        profiler = AgentProfiler(max_profiles=3)
        profiler.record_profile(_make_profile(invocation_id="first"))
        profiler.record_profile(_make_profile(invocation_id="second"))
        profiler.record_profile(_make_profile(invocation_id="third"))
        profiler.record_profile(_make_profile(invocation_id="fourth"))

        all_profiles = profiler.get_profiles(limit=100)
        assert len(all_profiles) == 3
        ids = {p.invocation_id for p in all_profiles}
        assert "first" not in ids
        assert "fourth" in ids
        assert "second" in ids
        assert "third" in ids

    def test_max_profiles_minimum_is_one(self) -> None:
        profiler = AgentProfiler(max_profiles=0)
        profiler.record_profile(_make_profile(invocation_id="only"))

        all_profiles = profiler.get_profiles(limit=100)
        assert len(all_profiles) == 1

    def test_eviction_preserves_order(self) -> None:
        profiler = AgentProfiler(max_profiles=2)
        profiler.record_profile(_make_profile(invocation_id="a"))
        profiler.record_profile(_make_profile(invocation_id="b"))
        profiler.record_profile(_make_profile(invocation_id="c"))

        profiles = profiler.get_profiles(limit=100)
        assert profiles[0].invocation_id == "c"  # newest
        assert profiles[1].invocation_id == "b"


# ---------------------------------------------------------------------------
# Summary computation
# ---------------------------------------------------------------------------


class TestSummaryComputation:
    def test_single_profile_summary(self) -> None:
        profiler = AgentProfiler()
        profiler.record_profile(
            _make_profile(
                total_duration_ms=100.0,
                prompt_construction_ms=10.0,
                llm_call_ms=70.0,
                tool_calls_ms=15.0,
                post_processing_ms=5.0,
                token_input=500,
                token_output=200,
                success=True,
            )
        )

        summary = profiler.get_agent_summary("test-agent")
        assert summary.agent_name == "test-agent"
        assert summary.total_invocations == 1
        assert summary.avg_duration_ms == 100.0
        assert summary.p95_duration_ms == 100.0
        assert summary.avg_llm_ms == 70.0
        assert summary.avg_tool_ms == 15.0
        assert summary.success_rate == 1.0
        assert summary.avg_token_input == 500.0
        assert summary.avg_token_output == 200.0
        assert summary.bottleneck == "llm"

    def test_average_computation(self) -> None:
        profiler = AgentProfiler()
        profiler.record_profile(_make_profile(total_duration_ms=100.0))
        profiler.record_profile(_make_profile(total_duration_ms=200.0))
        profiler.record_profile(_make_profile(total_duration_ms=300.0))

        summary = profiler.get_agent_summary("test-agent")
        assert summary.avg_duration_ms == 200.0

    def test_p95_computation(self) -> None:
        profiler = AgentProfiler()
        for dur in [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]:
            profiler.record_profile(_make_profile(total_duration_ms=dur))

        summary = profiler.get_agent_summary("test-agent")
        # p95 of [10, 20, ..., 100] with linear interpolation
        # rank = 0.95 * 9 = 8.55, between index 8 (90) and 9 (100)
        # p95 = 90 + 0.55 * 10 = 95.5
        assert summary.p95_duration_ms == pytest.approx(95.5, abs=0.1)

    def test_success_rate_with_failures(self) -> None:
        profiler = AgentProfiler()
        profiler.record_profile(_make_profile(success=True))
        profiler.record_profile(_make_profile(success=True))
        profiler.record_profile(_make_profile(success=False))
        profiler.record_profile(_make_profile(success=False))

        summary = profiler.get_agent_summary("test-agent")
        assert summary.success_rate == pytest.approx(0.5, abs=0.001)

    def test_all_failures(self) -> None:
        profiler = AgentProfiler()
        profiler.record_profile(_make_profile(success=False))
        profiler.record_profile(_make_profile(success=False))

        summary = profiler.get_agent_summary("test-agent")
        assert summary.success_rate == 0.0

    def test_bottleneck_is_tools_when_dominant(self) -> None:
        profiler = AgentProfiler()
        profiler.record_profile(
            _make_profile(
                prompt_construction_ms=5.0,
                llm_call_ms=10.0,
                tool_calls_ms=80.0,
                post_processing_ms=5.0,
            )
        )

        summary = profiler.get_agent_summary("test-agent")
        assert summary.bottleneck == "tools"

    def test_bottleneck_is_prompt_when_dominant(self) -> None:
        profiler = AgentProfiler()
        profiler.record_profile(
            _make_profile(
                prompt_construction_ms=90.0,
                llm_call_ms=5.0,
                tool_calls_ms=3.0,
                post_processing_ms=2.0,
            )
        )

        summary = profiler.get_agent_summary("test-agent")
        assert summary.bottleneck == "prompt"

    def test_bottleneck_is_post_when_dominant(self) -> None:
        profiler = AgentProfiler()
        profiler.record_profile(
            _make_profile(
                prompt_construction_ms=2.0,
                llm_call_ms=3.0,
                tool_calls_ms=5.0,
                post_processing_ms=90.0,
            )
        )

        summary = profiler.get_agent_summary("test-agent")
        assert summary.bottleneck == "post"

    def test_agent_not_found_raises_key_error(self) -> None:
        profiler = AgentProfiler()
        with pytest.raises(KeyError, match="No profiles for agent"):
            profiler.get_agent_summary("nonexistent")


# ---------------------------------------------------------------------------
# Multiple agent summaries
# ---------------------------------------------------------------------------


class TestMultipleAgentSummaries:
    def test_get_all_summaries_empty(self) -> None:
        profiler = AgentProfiler()
        assert profiler.get_all_summaries() == []

    def test_get_all_summaries_multiple_agents(self) -> None:
        profiler = AgentProfiler()
        profiler.record_profile(_make_profile(agent_name="alpha"))
        profiler.record_profile(_make_profile(agent_name="beta"))
        profiler.record_profile(_make_profile(agent_name="alpha"))

        summaries = profiler.get_all_summaries()
        assert len(summaries) == 2
        names = [s.agent_name for s in summaries]
        assert names == ["alpha", "beta"]  # sorted by name

    def test_summaries_have_correct_counts(self) -> None:
        profiler = AgentProfiler()
        profiler.record_profile(_make_profile(agent_name="alpha"))
        profiler.record_profile(_make_profile(agent_name="alpha"))
        profiler.record_profile(_make_profile(agent_name="alpha"))
        profiler.record_profile(_make_profile(agent_name="beta"))

        summaries = profiler.get_all_summaries()
        alpha_summary = next(s for s in summaries if s.agent_name == "alpha")
        beta_summary = next(s for s in summaries if s.agent_name == "beta")
        assert alpha_summary.total_invocations == 3
        assert beta_summary.total_invocations == 1


# ---------------------------------------------------------------------------
# Bottleneck detection
# ---------------------------------------------------------------------------


class TestBottleneckDetection:
    def test_llm_bound_bottleneck(self) -> None:
        profiler = AgentProfiler()
        # LLM takes 80/100 = 80% > 60% threshold
        profiler.record_profile(
            _make_profile(
                agent_name="llm-heavy",
                total_duration_ms=100.0,
                prompt_construction_ms=5.0,
                llm_call_ms=80.0,
                tool_calls_ms=10.0,
                post_processing_ms=5.0,
            )
        )

        bottlenecks = profiler.detect_bottlenecks()
        assert len(bottlenecks) == 1
        assert bottlenecks[0]["agent_name"] == "llm-heavy"
        assert bottlenecks[0]["bottleneck_phase"] == "llm"
        assert bottlenecks[0]["ratio"] > 0.6

    def test_tool_bound_bottleneck(self) -> None:
        profiler = AgentProfiler()
        # Tools take 75/100 = 75% > 60% threshold
        profiler.record_profile(
            _make_profile(
                agent_name="tool-heavy",
                total_duration_ms=100.0,
                prompt_construction_ms=5.0,
                llm_call_ms=10.0,
                tool_calls_ms=75.0,
                post_processing_ms=10.0,
            )
        )

        bottlenecks = profiler.detect_bottlenecks()
        assert len(bottlenecks) == 1
        assert bottlenecks[0]["agent_name"] == "tool-heavy"
        assert bottlenecks[0]["bottleneck_phase"] == "tools"

    def test_no_bottleneck_when_balanced(self) -> None:
        profiler = AgentProfiler()
        # Each phase ~25%, none > 60%
        profiler.record_profile(
            _make_profile(
                agent_name="balanced",
                total_duration_ms=100.0,
                prompt_construction_ms=25.0,
                llm_call_ms=25.0,
                tool_calls_ms=25.0,
                post_processing_ms=25.0,
            )
        )

        bottlenecks = profiler.detect_bottlenecks()
        assert len(bottlenecks) == 0

    def test_multiple_agents_bottlenecks(self) -> None:
        profiler = AgentProfiler()
        # Agent A: LLM-bound
        profiler.record_profile(
            _make_profile(
                agent_name="agent-a",
                total_duration_ms=100.0,
                prompt_construction_ms=5.0,
                llm_call_ms=85.0,
                tool_calls_ms=5.0,
                post_processing_ms=5.0,
            )
        )
        # Agent B: balanced (no bottleneck)
        profiler.record_profile(
            _make_profile(
                agent_name="agent-b",
                total_duration_ms=100.0,
                prompt_construction_ms=25.0,
                llm_call_ms=25.0,
                tool_calls_ms=25.0,
                post_processing_ms=25.0,
            )
        )
        # Agent C: tool-bound
        profiler.record_profile(
            _make_profile(
                agent_name="agent-c",
                total_duration_ms=100.0,
                prompt_construction_ms=5.0,
                llm_call_ms=10.0,
                tool_calls_ms=80.0,
                post_processing_ms=5.0,
            )
        )

        bottlenecks = profiler.detect_bottlenecks()
        assert len(bottlenecks) == 2
        agent_phases = {b["agent_name"]: b["bottleneck_phase"] for b in bottlenecks}
        assert agent_phases["agent-a"] == "llm"
        assert agent_phases["agent-c"] == "tools"

    def test_empty_profiler_no_bottlenecks(self) -> None:
        profiler = AgentProfiler()
        assert profiler.detect_bottlenecks() == []


# ---------------------------------------------------------------------------
# Hot path identification
# ---------------------------------------------------------------------------


class TestHotPaths:
    def test_single_hot_path(self) -> None:
        profiler = AgentProfiler()
        profiler.record_profile(
            _make_profile(agent_name="slow", model_id="gpt-4", total_duration_ms=500.0)
        )
        profiler.record_profile(
            _make_profile(agent_name="slow", model_id="gpt-4", total_duration_ms=600.0)
        )

        hot_paths = profiler.get_hot_paths()
        assert len(hot_paths) == 1
        assert hot_paths[0]["agent_name"] == "slow"
        assert hot_paths[0]["model_id"] == "gpt-4"
        assert hot_paths[0]["invocations"] == 2
        assert hot_paths[0]["avg_duration_ms"] == pytest.approx(550.0, abs=0.1)
        assert hot_paths[0]["max_duration_ms"] == 600.0

    def test_sorted_by_avg_duration_descending(self) -> None:
        profiler = AgentProfiler()
        profiler.record_profile(
            _make_profile(agent_name="fast", model_id="llama3.2", total_duration_ms=50.0)
        )
        profiler.record_profile(
            _make_profile(agent_name="slow", model_id="gpt-4", total_duration_ms=500.0)
        )
        profiler.record_profile(
            _make_profile(agent_name="medium", model_id="claude-3", total_duration_ms=200.0)
        )

        hot_paths = profiler.get_hot_paths()
        assert len(hot_paths) == 3
        assert hot_paths[0]["agent_name"] == "slow"
        assert hot_paths[1]["agent_name"] == "medium"
        assert hot_paths[2]["agent_name"] == "fast"

    def test_same_agent_different_models(self) -> None:
        profiler = AgentProfiler()
        profiler.record_profile(
            _make_profile(agent_name="multi", model_id="llama3.2", total_duration_ms=50.0)
        )
        profiler.record_profile(
            _make_profile(agent_name="multi", model_id="gpt-4", total_duration_ms=500.0)
        )

        hot_paths = profiler.get_hot_paths()
        assert len(hot_paths) == 2
        # The GPT-4 path should be first (slower)
        assert hot_paths[0]["model_id"] == "gpt-4"
        assert hot_paths[1]["model_id"] == "llama3.2"

    def test_empty_profiler_no_hot_paths(self) -> None:
        profiler = AgentProfiler()
        assert profiler.get_hot_paths() == []


# ---------------------------------------------------------------------------
# Empty profiler edge cases
# ---------------------------------------------------------------------------


class TestEmptyProfiler:
    def test_get_profiles_empty(self) -> None:
        profiler = AgentProfiler()
        assert profiler.get_profiles() == []

    def test_get_profiles_no_match(self) -> None:
        profiler = AgentProfiler()
        profiler.record_profile(_make_profile(agent_name="alpha"))
        assert profiler.get_profiles(agent_name="beta") == []

    def test_get_all_summaries_empty(self) -> None:
        profiler = AgentProfiler()
        assert profiler.get_all_summaries() == []

    def test_detect_bottlenecks_empty(self) -> None:
        profiler = AgentProfiler()
        assert profiler.detect_bottlenecks() == []

    def test_get_hot_paths_empty(self) -> None:
        profiler = AgentProfiler()
        assert profiler.get_hot_paths() == []


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------


class TestModelValidation:
    def test_profile_model_serialization(self) -> None:
        profile = _make_profile()
        data = profile.model_dump(mode="json")
        assert data["agent_name"] == "test-agent"
        assert data["total_duration_ms"] == 100.0
        assert isinstance(data["started_at"], str)  # ISO format

    def test_summary_model_serialization(self) -> None:
        summary = AgentPerformanceSummary(
            agent_name="test",
            total_invocations=10,
            avg_duration_ms=150.0,
            p95_duration_ms=250.0,
            avg_llm_ms=100.0,
            avg_tool_ms=30.0,
            success_rate=0.9,
            avg_token_input=500.0,
            avg_token_output=200.0,
            bottleneck="llm",
        )
        data = summary.model_dump(mode="json")
        assert data["bottleneck"] == "llm"
        assert data["success_rate"] == 0.9

    def test_profile_with_none_completed_at(self) -> None:
        profile = _make_profile()
        profile_no_completed = profile.model_copy(update={"completed_at": None})
        assert profile_no_completed.completed_at is None


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


class TestProfilingRoutes:
    """Test the profiling API endpoints with real JWT auth."""

    @pytest.fixture(autouse=True)
    def _restore_profiler(self) -> None:  # type: ignore[misc]
        """Save and restore app.state.agent_profiler to prevent test pollution."""
        from agent33.main import app

        original = getattr(app.state, "agent_profiler", None)
        yield  # type: ignore[misc]
        if original is not None:
            app.state.agent_profiler = original
        elif hasattr(app.state, "agent_profiler"):
            del app.state.agent_profiler

    async def test_summaries_empty(self) -> None:
        from agent33.main import app

        app.state.agent_profiler = AgentProfiler()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/agents/profiling/summaries", headers=_auth_headers())

        assert resp.status_code == 200
        assert resp.json() == []

    async def test_summaries_with_data(self) -> None:
        from agent33.main import app

        profiler = AgentProfiler()
        profiler.record_profile(_make_profile(agent_name="agent-x"))
        profiler.record_profile(_make_profile(agent_name="agent-y"))
        app.state.agent_profiler = profiler

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/agents/profiling/summaries", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["agent_name"] == "agent-x"
        assert data[1]["agent_name"] == "agent-y"
        assert "avg_duration_ms" in data[0]
        assert "bottleneck" in data[0]

    async def test_single_agent_summary(self) -> None:
        from agent33.main import app

        profiler = AgentProfiler()
        profiler.record_profile(
            _make_profile(agent_name="my-agent", llm_call_ms=80.0, total_duration_ms=100.0)
        )
        app.state.agent_profiler = profiler

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/agents/profiling/my-agent", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_name"] == "my-agent"
        assert data["total_invocations"] == 1
        assert data["avg_llm_ms"] == 80.0

    async def test_single_agent_not_found(self) -> None:
        from agent33.main import app

        app.state.agent_profiler = AgentProfiler()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/agents/profiling/nonexistent", headers=_auth_headers())

        assert resp.status_code == 404
        assert "No profiles for agent" in resp.json()["detail"]

    async def test_bottlenecks_endpoint(self) -> None:
        from agent33.main import app

        profiler = AgentProfiler()
        profiler.record_profile(
            _make_profile(
                agent_name="llm-heavy",
                total_duration_ms=100.0,
                llm_call_ms=80.0,
                prompt_construction_ms=5.0,
                tool_calls_ms=10.0,
                post_processing_ms=5.0,
            )
        )
        app.state.agent_profiler = profiler

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/agents/profiling/bottlenecks", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["bottleneck_phase"] == "llm"
        assert data[0]["ratio"] > 0.6

    async def test_hot_paths_endpoint(self) -> None:
        from agent33.main import app

        profiler = AgentProfiler()
        profiler.record_profile(
            _make_profile(agent_name="slow", model_id="gpt-4", total_duration_ms=500.0)
        )
        profiler.record_profile(
            _make_profile(agent_name="fast", model_id="llama3.2", total_duration_ms=50.0)
        )
        app.state.agent_profiler = profiler

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/agents/profiling/hot-paths", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Sorted by avg_duration_ms descending
        assert data[0]["agent_name"] == "slow"
        assert data[1]["agent_name"] == "fast"

    async def test_profiles_endpoint(self) -> None:
        from agent33.main import app

        profiler = AgentProfiler()
        profiler.record_profile(_make_profile(invocation_id="p1", agent_name="alpha"))
        profiler.record_profile(_make_profile(invocation_id="p2", agent_name="beta"))
        profiler.record_profile(_make_profile(invocation_id="p3", agent_name="alpha"))
        app.state.agent_profiler = profiler

        headers = _auth_headers()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # All profiles
            resp = await client.get("/v1/agents/profiling/profiles", headers=headers)
            assert resp.status_code == 200
            assert len(resp.json()) == 3

            # Filtered by agent_name
            resp = await client.get(
                "/v1/agents/profiling/profiles",
                params={"agent_name": "alpha"},
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2
            assert all(p["agent_name"] == "alpha" for p in data)

            # With limit
            resp = await client.get(
                "/v1/agents/profiling/profiles",
                params={"limit": 1},
                headers=headers,
            )
            assert resp.status_code == 200
            assert len(resp.json()) == 1

    async def test_no_profiler_returns_empty(self) -> None:
        from agent33.main import app

        # Remove profiler from state
        if hasattr(app.state, "agent_profiler"):
            del app.state.agent_profiler

        headers = _auth_headers()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/agents/profiling/summaries", headers=headers)
            assert resp.status_code == 200
            assert resp.json() == []

            resp = await client.get("/v1/agents/profiling/bottlenecks", headers=headers)
            assert resp.status_code == 200
            assert resp.json() == []

            resp = await client.get("/v1/agents/profiling/profiles", headers=headers)
            assert resp.status_code == 200
            assert resp.json() == []

            resp = await client.get("/v1/agents/profiling/hot-paths", headers=headers)
            assert resp.status_code == 200
            assert resp.json() == []

    async def test_no_profiler_single_agent_returns_404(self) -> None:
        from agent33.main import app

        if hasattr(app.state, "agent_profiler"):
            del app.state.agent_profiler

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/agents/profiling/my-agent", headers=_auth_headers())
            assert resp.status_code == 404
            assert "Profiler not initialized" in resp.json()["detail"]

    async def test_unauthenticated_request_rejected(self) -> None:
        from agent33.main import app

        app.state.agent_profiler = AgentProfiler()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/agents/profiling/summaries")

        assert resp.status_code == 401
