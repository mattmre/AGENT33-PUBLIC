"""Tests for ToolLoopScorer service (Gate 4.3)."""

from __future__ import annotations

import concurrent.futures
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent33.agents.tool_loop_scoring import ToolLoopScorer

# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_record_iteration_accumulates() -> None:
    scorer = ToolLoopScorer()
    scorer.record_iteration("agent-a", tool_calls=3, success=True)
    scorer.record_iteration("agent-a", tool_calls=1, success=False)
    scorer.record_iteration("agent-b", tool_calls=0, success=True)

    summary = scorer.get_loop_summary()
    assert summary["total_iterations"] == 3
    assert summary["total_tool_calls"] == 4  # 3 + 1 + 0
    assert summary["unique_agents"] == 2
    assert len(summary["iterations"]) == 3


def test_get_loop_summary_empty() -> None:
    scorer = ToolLoopScorer()
    summary = scorer.get_loop_summary()

    assert summary["total_iterations"] == 0
    assert summary["total_tool_calls"] == 0
    assert summary["unique_agents"] == 0
    assert summary["overall_success_rate"] == 0.0
    assert summary["convergence_rate"] == 0.0
    assert summary["iterations"] == []


def test_get_loop_summary_with_data() -> None:
    scorer = ToolLoopScorer()
    # 2 successes, 1 failure
    scorer.record_iteration("agent-x", tool_calls=2, success=True)
    scorer.record_iteration("agent-x", tool_calls=0, success=True)  # converged
    scorer.record_iteration("agent-x", tool_calls=5, success=False)

    summary = scorer.get_loop_summary()
    assert summary["total_iterations"] == 3
    assert summary["total_tool_calls"] == 7
    assert summary["unique_agents"] == 1
    # Overall success rate: 2/3 ≈ 0.6667
    assert abs(summary["overall_success_rate"] - round(2 / 3, 4)) < 1e-6
    # Convergence: only the 0-tool-call success converged
    assert abs(summary["convergence_rate"] - round(1 / 3, 4)) < 1e-6


def test_success_rate_calculation() -> None:
    scorer = ToolLoopScorer()
    for _ in range(4):
        scorer.record_iteration("a", tool_calls=1, success=True)
    scorer.record_iteration("a", tool_calls=1, success=False)

    summary = scorer.get_loop_summary()
    assert summary["overall_success_rate"] == round(4 / 5, 4)


def test_convergence_requires_zero_tool_calls_and_success() -> None:
    scorer = ToolLoopScorer()
    # success=True but tool_calls > 0 → NOT converged
    scorer.record_iteration("a", tool_calls=1, success=True)
    # success=False with tool_calls=0 → NOT converged
    scorer.record_iteration("a", tool_calls=0, success=False)
    # success=True with tool_calls=0 → converged
    scorer.record_iteration("a", tool_calls=0, success=True)

    summary = scorer.get_loop_summary()
    assert summary["convergence_rate"] == round(1 / 3, 4)


def test_iterations_capped_at_100() -> None:
    scorer = ToolLoopScorer()
    for i in range(150):
        scorer.record_iteration(f"agent-{i}", tool_calls=i % 5, success=True)

    summary = scorer.get_loop_summary()
    # total_iterations should reflect all 150
    assert summary["total_iterations"] == 150
    # but returned list is capped at 100
    assert len(summary["iterations"]) == 100


def test_iteration_record_shape() -> None:
    scorer = ToolLoopScorer()
    scorer.record_iteration("myagent", tool_calls=7, success=True)

    record = scorer.get_loop_summary()["iterations"][0]
    assert record["agent_id"] == "myagent"
    assert record["tool_calls"] == 7
    assert record["success"] is True
    assert record["converged"] is False  # tool_calls > 0
    assert "recorded_at" in record


def test_thread_safety() -> None:
    """Concurrent record_iteration calls must not corrupt internal state."""
    scorer = ToolLoopScorer()

    def _record_many(agent_id: str, count: int) -> None:
        for _ in range(count):
            scorer.record_iteration(agent_id, tool_calls=1, success=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_record_many, f"agent-{i}", 50) for i in range(8)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    summary = scorer.get_loop_summary()
    assert summary["total_iterations"] == 400  # 8 threads × 50 each
    assert summary["total_tool_calls"] == 400
    assert summary["overall_success_rate"] == 1.0


# ---------------------------------------------------------------------------
# Route integration tests
# ---------------------------------------------------------------------------


def _make_app(*, with_scorer: bool = True, with_profiler: bool = True) -> FastAPI:
    """Build a minimal FastAPI app with optional scorer/profiler on app.state.

    A fake auth middleware injects ``request.state.user`` so that
    ``require_scope("agents:read")`` passes without a real JWT.
    """
    from agent33.api.routes.agents import router as agents_router

    app = FastAPI()

    @app.middleware("http")  # type: ignore[misc]
    async def _fake_auth(request: Any, call_next: Any) -> Any:
        request.state.user = MagicMock(scopes=["agents:read", "agents:invoke"])
        return await call_next(request)

    app.include_router(agents_router)

    if with_scorer:
        scorer = ToolLoopScorer()
        scorer.record_iteration("test-agent", tool_calls=3, success=True)
        scorer.record_iteration("test-agent", tool_calls=0, success=True)
        app.state.tool_loop_scorer = scorer
    # intentionally omit when with_scorer=False

    if with_profiler:
        app.state.agent_profiler = MagicMock()
    # intentionally omit when with_profiler=False

    return app


@pytest.mark.asyncio
async def test_tool_loop_scores_route_returns_200_with_real_data() -> None:
    app = _make_app(with_scorer=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/agents/tool-loop/scores")
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    assert body["total_iterations"] == 2
    assert body["total_tool_calls"] == 3
    assert body["unique_agents"] == 1
    assert "overall_success_rate" in body
    assert "convergence_rate" in body
    assert isinstance(body["iterations"], list)


@pytest.mark.asyncio
async def test_tool_loop_scores_route_returns_503_when_scorer_absent() -> None:
    app = _make_app(with_scorer=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/agents/tool-loop/scores")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Service not initialized"


@pytest.mark.asyncio
async def test_profiling_summaries_returns_empty_when_profiler_absent() -> None:
    app = _make_app(with_profiler=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/agents/profiling/summaries")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_profiling_bottlenecks_returns_empty_when_profiler_absent() -> None:
    app = _make_app(with_profiler=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/agents/profiling/bottlenecks")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_profiling_hot_paths_returns_empty_when_profiler_absent() -> None:
    app = _make_app(with_profiler=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/agents/profiling/hot-paths")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_profiling_profiles_returns_empty_when_profiler_absent() -> None:
    app = _make_app(with_profiler=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/agents/profiling/profiles")
    assert resp.status_code == 200
    assert resp.json() == []
