"""Tests for tool-use loop scoring infrastructure (S28).

Covers:
- ToolCallRecord model construction and defaults
- Single-tool and multi-tool effectiveness scoring
- Composite score formula verification
- RetryPolicy: within limits, exceeded, specific error filters
- Exponential backoff calculation with cap
- Iteration tracking and convergence detection
- ToolLoopSummary with mixed results
- Input dedup hash detection
- Reset behaviour
- API route: empty state and populated state
- RetryPolicy defaults
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agent33.tools.loop_scoring import (
    LoopIteration,
    RetryPolicy,
    ToolCallRecord,
    ToolEffectivenessScore,
    ToolLoopScorer,
    ToolLoopSummary,
)

if TYPE_CHECKING:
    from starlette.testclient import TestClient


# ===================================================================
# ToolCallRecord model
# ===================================================================


class TestToolCallRecord:
    """Verify ToolCallRecord construction and defaults."""

    def test_minimal_construction(self) -> None:
        rec = ToolCallRecord(tool_name="shell", success=True, duration_ms=42.5)
        assert rec.tool_name == "shell"
        assert rec.success is True
        assert rec.duration_ms == 42.5
        assert rec.retry_count == 0
        assert rec.error is None
        assert rec.input_hash == ""
        # call_id and timestamp should be auto-generated
        assert rec.call_id  # non-empty
        assert rec.timestamp is not None

    def test_full_construction(self) -> None:
        rec = ToolCallRecord(
            tool_name="web_fetch",
            call_id="abc123",
            success=False,
            duration_ms=1500.0,
            retry_count=2,
            error="timeout",
            input_hash="deadbeef",
        )
        assert rec.call_id == "abc123"
        assert rec.success is False
        assert rec.retry_count == 2
        assert rec.error == "timeout"
        assert rec.input_hash == "deadbeef"

    def test_unique_call_ids(self) -> None:
        a = ToolCallRecord(tool_name="t", success=True, duration_ms=1)
        b = ToolCallRecord(tool_name="t", success=True, duration_ms=1)
        assert a.call_id != b.call_id


# ===================================================================
# RetryPolicy defaults
# ===================================================================


class TestRetryPolicy:
    """Verify RetryPolicy model defaults."""

    def test_defaults(self) -> None:
        p = RetryPolicy()
        assert p.max_retries == 3
        assert p.backoff_base_ms == 100
        assert p.backoff_multiplier == 2.0
        assert p.backoff_max_ms == 5000
        assert p.retry_on_errors == []

    def test_custom_values(self) -> None:
        p = RetryPolicy(
            max_retries=5,
            backoff_base_ms=50,
            backoff_multiplier=3.0,
            backoff_max_ms=10000,
            retry_on_errors=["timeout", "rate_limit"],
        )
        assert p.max_retries == 5
        assert p.backoff_base_ms == 50
        assert p.backoff_multiplier == 3.0
        assert p.backoff_max_ms == 10000
        assert p.retry_on_errors == ["timeout", "rate_limit"]


# ===================================================================
# Single-tool scoring
# ===================================================================


class TestSingleToolScore:
    """Record calls for one tool and verify score computation."""

    def test_all_successful(self) -> None:
        scorer = ToolLoopScorer()
        for _ in range(5):
            scorer.record_call("shell", success=True, duration_ms=100.0)

        score = scorer.get_tool_score("shell")
        assert score.tool_name == "shell"
        assert score.total_calls == 5
        assert score.successful_calls == 5
        assert score.failed_calls == 0
        assert score.success_rate == 1.0
        assert score.avg_duration_ms == 100.0
        assert score.retry_rate == 0.0
        # score = 1.0 * 0.4 + (1-0) * 0.3 + (1 - 100/10000) * 0.3
        expected_speed = 1.0 - 100.0 / 10000.0  # 0.99
        expected_score = 1.0 * 0.4 + 1.0 * 0.3 + expected_speed * 0.3
        assert abs(score.score - expected_score) < 0.001

    def test_all_failed(self) -> None:
        scorer = ToolLoopScorer()
        for _ in range(3):
            scorer.record_call("bad_tool", success=False, duration_ms=5000.0, error="crash")

        score = scorer.get_tool_score("bad_tool")
        assert score.successful_calls == 0
        assert score.failed_calls == 3
        assert score.success_rate == 0.0
        # score = 0 * 0.4 + 1.0 * 0.3 + (1 - 5000/10000) * 0.3
        expected_speed = 1.0 - 5000.0 / 10000.0  # 0.5
        expected_score = 0.0 + 0.3 + expected_speed * 0.3
        assert abs(score.score - expected_score) < 0.001

    def test_mixed_results_with_retries(self) -> None:
        scorer = ToolLoopScorer()
        scorer.record_call("fetch", success=True, duration_ms=200.0, retry_count=0)
        scorer.record_call("fetch", success=False, duration_ms=300.0, retry_count=1)
        scorer.record_call("fetch", success=True, duration_ms=250.0, retry_count=2)
        scorer.record_call("fetch", success=True, duration_ms=150.0, retry_count=0)

        score = scorer.get_tool_score("fetch")
        assert score.total_calls == 4
        assert score.successful_calls == 3
        assert score.failed_calls == 1
        assert score.success_rate == 0.75
        # 2 out of 4 calls had retry_count > 0
        assert score.retry_rate == 0.5
        avg_dur = (200 + 300 + 250 + 150) / 4  # 225
        assert abs(score.avg_duration_ms - avg_dur) < 0.01

    def test_unknown_tool_raises_key_error(self) -> None:
        scorer = ToolLoopScorer()
        with pytest.raises(KeyError, match="No records for tool 'missing'"):
            scorer.get_tool_score("missing")

    def test_very_slow_tool_gets_zero_speed_score(self) -> None:
        """Duration >= 10s baseline should clamp speed_score to 0."""
        scorer = ToolLoopScorer()
        scorer.record_call("slow", success=True, duration_ms=15000.0)
        score = scorer.get_tool_score("slow")
        # speed_score = max(0, 1 - 15000/10000) = 0
        expected = 1.0 * 0.4 + 1.0 * 0.3 + 0.0 * 0.3
        assert abs(score.score - expected) < 0.001


# ===================================================================
# Multiple tools with different success rates
# ===================================================================


class TestMultiToolScoring:
    """Verify scoring across multiple tools."""

    def test_get_all_scores(self) -> None:
        scorer = ToolLoopScorer()
        # Tool A: all pass
        for _ in range(3):
            scorer.record_call("tool_a", success=True, duration_ms=50.0)
        # Tool B: all fail
        for _ in range(3):
            scorer.record_call("tool_b", success=False, duration_ms=8000.0, error="err")

        scores = scorer.get_all_scores()
        assert len(scores) == 2
        names = [s.tool_name for s in scores]
        assert "tool_a" in names
        assert "tool_b" in names

        score_a = next(s for s in scores if s.tool_name == "tool_a")
        score_b = next(s for s in scores if s.tool_name == "tool_b")
        assert score_a.score > score_b.score

    def test_scores_sorted_by_name(self) -> None:
        scorer = ToolLoopScorer()
        scorer.record_call("zeta", success=True, duration_ms=10.0)
        scorer.record_call("alpha", success=True, duration_ms=10.0)
        scorer.record_call("mid", success=True, duration_ms=10.0)

        scores = scorer.get_all_scores()
        assert [s.tool_name for s in scores] == ["alpha", "mid", "zeta"]


# ===================================================================
# Retry policy: should_retry
# ===================================================================


class TestShouldRetry:
    """Verify retry decisions and backoff calculation."""

    def test_within_limits(self) -> None:
        scorer = ToolLoopScorer(retry_policy=RetryPolicy(max_retries=3))
        ok, wait = scorer.should_retry("tool", attempt=0, error="timeout")
        assert ok is True
        assert wait > 0

    def test_exceeded_limit(self) -> None:
        scorer = ToolLoopScorer(retry_policy=RetryPolicy(max_retries=3))
        ok, wait = scorer.should_retry("tool", attempt=3, error="timeout")
        assert ok is False
        assert wait == 0.0

    def test_specific_error_match(self) -> None:
        policy = RetryPolicy(retry_on_errors=["timeout", "rate_limit"])
        scorer = ToolLoopScorer(retry_policy=policy)
        ok, _ = scorer.should_retry("tool", attempt=0, error="Connection timeout occurred")
        assert ok is True

    def test_specific_error_no_match(self) -> None:
        policy = RetryPolicy(retry_on_errors=["timeout"])
        scorer = ToolLoopScorer(retry_policy=policy)
        ok, wait = scorer.should_retry("tool", attempt=0, error="permission denied")
        assert ok is False
        assert wait == 0.0

    def test_empty_retry_on_errors_retries_all(self) -> None:
        """Empty retry_on_errors list means retry on any error."""
        policy = RetryPolicy(retry_on_errors=[])
        scorer = ToolLoopScorer(retry_policy=policy)
        ok, _ = scorer.should_retry("tool", attempt=0, error="anything")
        assert ok is True


# ===================================================================
# Backoff calculation
# ===================================================================


class TestBackoffCalculation:
    """Verify exponential backoff with cap."""

    def test_exponential_growth(self) -> None:
        policy = RetryPolicy(
            backoff_base_ms=100,
            backoff_multiplier=2.0,
            backoff_max_ms=5000,
        )
        scorer = ToolLoopScorer(retry_policy=policy)

        _, wait0 = scorer.should_retry("t", attempt=0, error="e")
        _, wait1 = scorer.should_retry("t", attempt=1, error="e")
        _, wait2 = scorer.should_retry("t", attempt=2, error="e")

        assert wait0 == pytest.approx(100.0)  # 100 * 2^0
        assert wait1 == pytest.approx(200.0)  # 100 * 2^1
        assert wait2 == pytest.approx(400.0)  # 100 * 2^2

    def test_cap_at_max(self) -> None:
        policy = RetryPolicy(
            max_retries=10,
            backoff_base_ms=1000,
            backoff_multiplier=10.0,
            backoff_max_ms=5000,
        )
        scorer = ToolLoopScorer(retry_policy=policy)

        _, wait = scorer.should_retry("t", attempt=5, error="e")
        assert wait == 5000.0  # capped


# ===================================================================
# Iteration tracking and convergence
# ===================================================================


class TestIterationTracking:
    """Verify iteration boundaries and convergence detection."""

    def test_single_iteration_no_convergence(self) -> None:
        scorer = ToolLoopScorer()
        scorer.record_call("t", success=True, duration_ms=10.0)
        assert scorer.detect_convergence() is False

    def test_convergence_detected(self) -> None:
        scorer = ToolLoopScorer()

        # Iteration 1: low success rate
        scorer.start_iteration()
        scorer.record_call("t", success=False, duration_ms=10.0)
        scorer.record_call("t", success=False, duration_ms=10.0)

        # Iteration 2: better success rate
        scorer.start_iteration()
        scorer.record_call("t", success=True, duration_ms=10.0)
        scorer.record_call("t", success=True, duration_ms=10.0)

        assert scorer.detect_convergence() is True

    def test_no_convergence_when_degrading(self) -> None:
        scorer = ToolLoopScorer()

        # Iteration 1: good
        scorer.start_iteration()
        scorer.record_call("t", success=True, duration_ms=10.0)
        scorer.record_call("t", success=True, duration_ms=10.0)

        # Iteration 2: worse
        scorer.start_iteration()
        scorer.record_call("t", success=False, duration_ms=10.0)
        scorer.record_call("t", success=False, duration_ms=10.0)

        assert scorer.detect_convergence() is False

    def test_iteration_boundaries_in_summary(self) -> None:
        scorer = ToolLoopScorer()
        scorer.start_iteration()
        scorer.record_call("a", success=True, duration_ms=10.0)
        scorer.start_iteration()
        scorer.record_call("b", success=False, duration_ms=20.0)
        scorer.record_call("b", success=True, duration_ms=15.0)

        summary = scorer.get_loop_summary()
        assert summary.total_iterations == 2
        assert len(summary.iterations) == 2
        assert len(summary.iterations[0].tool_calls) == 1
        assert len(summary.iterations[1].tool_calls) == 2


# ===================================================================
# Loop summary with mixed results
# ===================================================================


class TestLoopSummary:
    """Verify full loop summary computation."""

    def test_empty_summary(self) -> None:
        scorer = ToolLoopScorer()
        summary = scorer.get_loop_summary()
        assert summary.total_iterations == 0
        assert summary.total_tool_calls == 0
        assert summary.unique_tools == 0
        assert summary.overall_success_rate == 0.0
        assert summary.convergence_detected is False
        assert summary.tool_scores == []
        assert summary.iterations == []

    def test_mixed_summary(self) -> None:
        scorer = ToolLoopScorer()
        scorer.start_iteration()
        scorer.record_call("shell", success=True, duration_ms=100.0)
        scorer.record_call("fetch", success=False, duration_ms=2000.0, error="timeout")

        scorer.start_iteration()
        scorer.record_call("shell", success=True, duration_ms=80.0)
        scorer.record_call("fetch", success=True, duration_ms=300.0)
        scorer.record_call("fetch", success=True, duration_ms=250.0)

        summary = scorer.get_loop_summary()
        assert summary.total_iterations == 2
        assert summary.total_tool_calls == 5
        assert summary.unique_tools == 2
        # 4 success / 5 total
        assert summary.overall_success_rate == 0.8
        assert summary.convergence_detected is True  # iter2 better than iter1
        assert len(summary.tool_scores) == 2

    def test_summary_includes_current_iteration(self) -> None:
        """Current iteration (before start_iteration) is included in summary."""
        scorer = ToolLoopScorer()
        scorer.record_call("t", success=True, duration_ms=10.0)
        summary = scorer.get_loop_summary()
        assert summary.total_iterations == 1
        assert summary.total_tool_calls == 1

    def test_cumulative_success_rate_in_iterations(self) -> None:
        scorer = ToolLoopScorer()
        scorer.start_iteration()
        scorer.record_call("t", success=True, duration_ms=10.0)
        scorer.record_call("t", success=False, duration_ms=10.0)

        scorer.start_iteration()
        scorer.record_call("t", success=True, duration_ms=10.0)
        scorer.record_call("t", success=True, duration_ms=10.0)

        summary = scorer.get_loop_summary()
        # Iteration 1: 1/2 cumulative = 0.5
        assert summary.iterations[0].cumulative_success_rate == 0.5
        assert summary.iterations[0].converging is False  # first iteration
        # Iteration 2: 3/4 cumulative = 0.75
        assert summary.iterations[1].cumulative_success_rate == 0.75
        assert summary.iterations[1].converging is True


# ===================================================================
# Input dedup (same hash detection)
# ===================================================================


class TestInputDedup:
    """Verify that input_hash is recorded and can be used for dedup detection."""

    def test_same_hash_recorded(self) -> None:
        scorer = ToolLoopScorer()
        scorer.record_call("t", success=True, duration_ms=10.0, input_hash="abc123")
        scorer.record_call("t", success=True, duration_ms=10.0, input_hash="abc123")
        scorer.record_call("t", success=True, duration_ms=10.0, input_hash="def456")

        summary = scorer.get_loop_summary()
        hashes = [r.input_hash for it in summary.iterations for r in it.tool_calls]
        assert hashes.count("abc123") == 2
        assert hashes.count("def456") == 1

    def test_hash_utility_function(self) -> None:
        from agent33.tools.loop_scoring import _compute_input_hash

        h1 = _compute_input_hash("hello world")
        h2 = _compute_input_hash("hello world")
        h3 = _compute_input_hash("different input")
        assert h1 == h2
        assert h1 != h3
        assert len(h1) == 16  # truncated SHA-256


# ===================================================================
# Reset behaviour
# ===================================================================


class TestReset:
    """Verify that reset clears all state."""

    def test_reset_clears_everything(self) -> None:
        scorer = ToolLoopScorer()
        scorer.start_iteration()
        scorer.record_call("t", success=True, duration_ms=10.0)
        scorer.start_iteration()
        scorer.record_call("t", success=False, duration_ms=20.0)

        scorer.reset()

        summary = scorer.get_loop_summary()
        assert summary.total_iterations == 0
        assert summary.total_tool_calls == 0
        assert summary.tool_scores == []
        assert summary.iterations == []

    def test_reset_allows_fresh_recording(self) -> None:
        scorer = ToolLoopScorer()
        scorer.record_call("old", success=True, duration_ms=10.0)
        scorer.reset()
        scorer.record_call("new", success=False, duration_ms=20.0)

        scores = scorer.get_all_scores()
        assert len(scores) == 1
        assert scores[0].tool_name == "new"


# ===================================================================
# API route: /v1/agents/tool-loop/scores
# ===================================================================


def _make_test_client() -> TestClient:
    """Build a TestClient with JWT auth for the agent routes."""
    from fastapi.testclient import TestClient as _TestClient

    from agent33.main import app
    from agent33.security.auth import create_access_token

    token = create_access_token("test-user", scopes=["admin"])
    return _TestClient(
        app,
        headers={"Authorization": f"Bearer {token}"},
        raise_server_exceptions=False,
    )


class TestToolLoopScoresRoute:
    """API route tests for GET /v1/agents/tool-loop/scores."""

    def test_empty_state(self) -> None:
        """When no scorer is installed on app.state, route returns 503."""
        from unittest.mock import patch

        from agent33.main import app

        # Patch app.state so that getattr(request.app.state, "tool_loop_scorer", None)
        # returns None regardless of what lifespan or other tests may have set.
        with patch.object(app.state, "tool_loop_scorer", None, create=True):
            client = _make_test_client()
            resp = client.get("/v1/agents/tool-loop/scores")
            # Route requires tool_loop_scorer to be initialized; returns 503 when absent
            assert resp.status_code == 503

    def test_populated_state(self) -> None:
        """When an agents.tool_loop_scoring.ToolLoopScorer is installed with data,
        returns the aggregated summary from that scorer."""
        from agent33.agents.tool_loop_scoring import ToolLoopScorer as AgentScorer
        from agent33.main import app

        scorer = AgentScorer()
        scorer.record_iteration(agent_id="agent-a", tool_calls=2, success=True)
        scorer.record_iteration(agent_id="agent-a", tool_calls=1, success=False)
        scorer.record_iteration(agent_id="agent-b", tool_calls=3, success=True)

        app.state.tool_loop_scorer = scorer

        client = _make_test_client()
        resp = client.get("/v1/agents/tool-loop/scores")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_iterations"] == 3
        assert body["total_tool_calls"] == 6  # 2 + 1 + 3
        assert body["unique_agents"] == 2
        assert "overall_success_rate" in body
        assert "convergence_rate" in body
        assert "iterations" in body
        assert len(body["iterations"]) == 3

        # Cleanup
        delattr(app.state, "tool_loop_scorer")


# ===================================================================
# ToolEffectivenessScore and LoopIteration model structure
# ===================================================================


class TestModelStructure:
    """Verify Pydantic model fields and serialization."""

    def test_effectiveness_score_fields(self) -> None:
        score = ToolEffectivenessScore(
            tool_name="t",
            total_calls=10,
            successful_calls=8,
            failed_calls=2,
            success_rate=0.8,
            avg_duration_ms=150.0,
            retry_rate=0.2,
            score=0.85,
        )
        data = score.model_dump()
        assert data["tool_name"] == "t"
        assert data["score"] == 0.85

    def test_loop_iteration_fields(self) -> None:
        rec = ToolCallRecord(tool_name="t", success=True, duration_ms=10.0)
        it = LoopIteration(
            iteration=1,
            tool_calls=[rec],
            cumulative_success_rate=1.0,
            converging=False,
        )
        data = it.model_dump()
        assert data["iteration"] == 1
        assert len(data["tool_calls"]) == 1
        assert data["converging"] is False

    def test_summary_serialization(self) -> None:
        summary = ToolLoopSummary(
            total_iterations=0,
            total_tool_calls=0,
            unique_tools=0,
            overall_success_rate=0.0,
            convergence_detected=False,
            tool_scores=[],
            iterations=[],
        )
        data = summary.model_dump(mode="json")
        assert isinstance(data, dict)
        assert data["total_iterations"] == 0
