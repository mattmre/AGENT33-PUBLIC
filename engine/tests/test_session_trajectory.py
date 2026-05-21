"""Tests for Phase 59: Session trajectories and automatic title generation.

Covers:
- SessionTrajectory model construction and serialization
- SessionTrajectoryTracker lifecycle (start, record events, end)
- Token usage tracking over time
- Event kind counters (user messages, tool calls, errors)
- TitleGenerator heuristic path (no LLM)
- TitleGenerator LLM path (mocked ModelRouter)
- API routes: GET trajectory, GET/PATCH title
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.memory.title_generator import (
    TitleGenerator,
    generate_title_heuristic,
    generate_title_llm,
)
from agent33.memory.trajectory import (
    SessionOutcome,
    SessionTrajectory,
    SessionTrajectoryTracker,
    TrajectoryEvent,
    TrajectoryEventKind,
)

# ---------------------------------------------------------------------------
# TrajectoryEvent model tests
# ---------------------------------------------------------------------------


class TestTrajectoryEvent:
    def test_defaults(self) -> None:
        """TrajectoryEvent has sensible defaults."""
        event = TrajectoryEvent(kind=TrajectoryEventKind.USER_MESSAGE)
        assert event.kind == TrajectoryEventKind.USER_MESSAGE
        assert event.agent_name == ""
        assert event.detail == ""
        assert event.token_count == 0
        assert event.metadata == {}
        assert isinstance(event.timestamp, datetime)

    def test_full_construction(self) -> None:
        """TrajectoryEvent can be fully populated."""
        now = datetime.now(UTC)
        event = TrajectoryEvent(
            kind=TrajectoryEventKind.TOOL_CALL,
            timestamp=now,
            agent_name="code-worker",
            detail="shell(ls -la)",
            token_count=42,
            metadata={"tool": "shell"},
        )
        assert event.kind == TrajectoryEventKind.TOOL_CALL
        assert event.timestamp == now
        assert event.agent_name == "code-worker"
        assert event.detail == "shell(ls -la)"
        assert event.token_count == 42
        assert event.metadata["tool"] == "shell"

    def test_serialization_roundtrip(self) -> None:
        """TrajectoryEvent can be serialized and deserialized."""
        event = TrajectoryEvent(
            kind=TrajectoryEventKind.ERROR,
            detail="Connection timeout",
            token_count=10,
        )
        data = event.model_dump()
        restored = TrajectoryEvent(**data)
        assert restored.kind == event.kind
        assert restored.detail == event.detail
        assert restored.token_count == event.token_count


# ---------------------------------------------------------------------------
# SessionTrajectory model tests
# ---------------------------------------------------------------------------


class TestSessionTrajectory:
    def test_defaults(self) -> None:
        """SessionTrajectory has sensible defaults."""
        trajectory = SessionTrajectory(session_id="test-123")
        assert trajectory.session_id == "test-123"
        assert trajectory.title == ""
        assert trajectory.outcome == SessionOutcome.PENDING
        assert trajectory.events == []
        assert trajectory.token_usage == []
        assert trajectory.total_tokens == 0
        assert trajectory.total_user_messages == 0
        assert trajectory.total_agent_responses == 0
        assert trajectory.total_tool_calls == 0
        assert trajectory.total_errors == 0
        assert trajectory.first_user_message == ""
        assert trajectory.event_count == 0

    def test_event_count_property(self) -> None:
        """event_count reflects the number of events."""
        trajectory = SessionTrajectory(
            session_id="test-456",
            events=[
                TrajectoryEvent(kind=TrajectoryEventKind.SESSION_START),
                TrajectoryEvent(kind=TrajectoryEventKind.USER_MESSAGE),
            ],
        )
        assert trajectory.event_count == 2

    def test_serialization_roundtrip(self) -> None:
        """SessionTrajectory can be serialized and deserialized."""
        trajectory = SessionTrajectory(
            session_id="s1",
            title="Test Session",
            outcome=SessionOutcome.SUCCESS,
            total_tokens=500,
            total_tool_calls=3,
        )
        data = trajectory.model_dump()
        restored = SessionTrajectory(**data)
        assert restored.session_id == "s1"
        assert restored.title == "Test Session"
        assert restored.outcome == SessionOutcome.SUCCESS
        assert restored.total_tokens == 500
        assert restored.total_tool_calls == 3


# ---------------------------------------------------------------------------
# SessionTrajectoryTracker lifecycle tests
# ---------------------------------------------------------------------------


class TestSessionTrajectoryTracker:
    def test_start_session(self) -> None:
        """start_session creates a new trajectory with SESSION_START event."""
        tracker = SessionTrajectoryTracker()
        trajectory = tracker.start_session("s1")

        assert trajectory.session_id == "s1"
        assert trajectory.outcome == SessionOutcome.PENDING
        assert len(trajectory.events) == 1
        assert trajectory.events[0].kind == TrajectoryEventKind.SESSION_START
        assert tracker.session_count == 1

    def test_start_session_idempotent(self) -> None:
        """Calling start_session twice for the same ID returns the same trajectory."""
        tracker = SessionTrajectoryTracker()
        t1 = tracker.start_session("s1")
        t2 = tracker.start_session("s1")
        assert t1 is t2
        assert tracker.session_count == 1

    def test_start_session_with_metadata(self) -> None:
        """start_session stores metadata on the trajectory."""
        tracker = SessionTrajectoryTracker()
        trajectory = tracker.start_session("s1", metadata={"agent": "researcher"})
        assert trajectory.metadata == {"agent": "researcher"}

    def test_end_session(self) -> None:
        """end_session sets outcome, end_time, and duration."""
        tracker = SessionTrajectoryTracker()
        tracker.start_session("s1")
        trajectory = tracker.end_session("s1", SessionOutcome.SUCCESS)

        assert trajectory.outcome == SessionOutcome.SUCCESS
        assert trajectory.end_time is not None
        assert trajectory.duration_seconds >= 0
        # Should have start and end events.
        assert trajectory.events[-1].kind == TrajectoryEventKind.SESSION_END
        assert trajectory.events[-1].detail == "success"

    def test_end_session_not_found_raises(self) -> None:
        """end_session raises KeyError for unknown session."""
        tracker = SessionTrajectoryTracker()
        with pytest.raises(KeyError, match="not found"):
            tracker.end_session("nonexistent")

    def test_end_session_failure_outcome(self) -> None:
        """end_session correctly records failure outcome."""
        tracker = SessionTrajectoryTracker()
        tracker.start_session("s1")
        trajectory = tracker.end_session("s1", SessionOutcome.FAILURE)
        assert trajectory.outcome == SessionOutcome.FAILURE
        assert trajectory.events[-1].detail == "failure"

    def test_end_session_abandoned_outcome(self) -> None:
        """end_session correctly records abandoned outcome."""
        tracker = SessionTrajectoryTracker()
        tracker.start_session("s1")
        trajectory = tracker.end_session("s1", SessionOutcome.ABANDONED)
        assert trajectory.outcome == SessionOutcome.ABANDONED


class TestTrajectoryEventRecording:
    def test_record_user_message(self) -> None:
        """Recording a user message increments the counter and captures first message."""
        tracker = SessionTrajectoryTracker()
        tracker.start_session("s1")

        tracker.record_event(
            "s1",
            TrajectoryEventKind.USER_MESSAGE,
            detail="Hello, how are you?",
            token_count=5,
        )

        trajectory = tracker.get("s1")
        assert trajectory.total_user_messages == 1
        assert trajectory.first_user_message == "Hello, how are you?"
        assert trajectory.total_tokens == 5

    def test_first_user_message_captured_only_once(self) -> None:
        """Only the first user message detail is stored as first_user_message."""
        tracker = SessionTrajectoryTracker()
        tracker.start_session("s1")

        tracker.record_event("s1", TrajectoryEventKind.USER_MESSAGE, detail="First message")
        tracker.record_event("s1", TrajectoryEventKind.USER_MESSAGE, detail="Second message")

        trajectory = tracker.get("s1")
        assert trajectory.total_user_messages == 2
        assert trajectory.first_user_message == "First message"

    def test_record_agent_response(self) -> None:
        """Recording agent responses increments the counter."""
        tracker = SessionTrajectoryTracker()
        tracker.start_session("s1")

        tracker.record_event(
            "s1",
            TrajectoryEventKind.AGENT_RESPONSE,
            agent_name="code-worker",
            token_count=50,
        )

        trajectory = tracker.get("s1")
        assert trajectory.total_agent_responses == 1
        assert trajectory.total_tokens == 50

    def test_record_tool_call(self) -> None:
        """Recording a tool call increments the tool call counter."""
        tracker = SessionTrajectoryTracker()
        tracker.start_session("s1")

        tracker.record_event(
            "s1",
            TrajectoryEventKind.TOOL_CALL,
            detail="shell(git status)",
            agent_name="code-worker",
            metadata={"tool": "shell"},
        )

        trajectory = tracker.get("s1")
        assert trajectory.total_tool_calls == 1
        last_event = trajectory.events[-1]
        assert last_event.kind == TrajectoryEventKind.TOOL_CALL
        assert last_event.metadata["tool"] == "shell"

    def test_record_error(self) -> None:
        """Recording an error increments the error counter."""
        tracker = SessionTrajectoryTracker()
        tracker.start_session("s1")

        tracker.record_event(
            "s1",
            TrajectoryEventKind.ERROR,
            detail="Connection timeout",
        )

        trajectory = tracker.get("s1")
        assert trajectory.total_errors == 1

    def test_record_milestone(self) -> None:
        """Milestones are recorded as events without affecting specific counters."""
        tracker = SessionTrajectoryTracker()
        tracker.start_session("s1")

        tracker.record_event(
            "s1",
            TrajectoryEventKind.MILESTONE,
            detail="All tests passing",
        )

        trajectory = tracker.get("s1")
        # Milestones don't affect counters.
        assert trajectory.total_user_messages == 0
        assert trajectory.total_tool_calls == 0
        assert trajectory.total_errors == 0
        # But they are recorded as events.
        milestone_events = [
            e for e in trajectory.events if e.kind == TrajectoryEventKind.MILESTONE
        ]
        assert len(milestone_events) == 1
        assert milestone_events[0].detail == "All tests passing"

    def test_auto_start_on_record(self) -> None:
        """Recording an event for an untracked session auto-starts it."""
        tracker = SessionTrajectoryTracker()
        tracker.record_event("s1", TrajectoryEventKind.USER_MESSAGE, detail="hello")

        assert tracker.session_count == 1
        trajectory = tracker.get("s1")
        assert trajectory.total_user_messages == 1


class TestTokenUsageTracking:
    def test_token_usage_points_recorded(self) -> None:
        """Token usage points are recorded when events have token_count > 0."""
        tracker = SessionTrajectoryTracker()
        tracker.start_session("s1")

        tracker.record_event("s1", TrajectoryEventKind.USER_MESSAGE, token_count=10)
        tracker.record_event("s1", TrajectoryEventKind.AGENT_RESPONSE, token_count=50)
        tracker.record_event("s1", TrajectoryEventKind.USER_MESSAGE, token_count=15)

        trajectory = tracker.get("s1")
        assert len(trajectory.token_usage) == 3
        assert trajectory.token_usage[0].cumulative_tokens == 10
        assert trajectory.token_usage[1].cumulative_tokens == 60
        assert trajectory.token_usage[2].cumulative_tokens == 75
        assert trajectory.total_tokens == 75

    def test_zero_token_events_skip_usage_point(self) -> None:
        """Events with 0 tokens don't add a token usage point."""
        tracker = SessionTrajectoryTracker()
        tracker.start_session("s1")

        tracker.record_event("s1", TrajectoryEventKind.MILESTONE, token_count=0)

        trajectory = tracker.get("s1")
        assert len(trajectory.token_usage) == 0
        assert trajectory.total_tokens == 0


class TestTrajectoryRetrieval:
    def test_get_existing_session(self) -> None:
        """get() returns the trajectory for a tracked session."""
        tracker = SessionTrajectoryTracker()
        tracker.start_session("s1")
        trajectory = tracker.get("s1")
        assert trajectory.session_id == "s1"

    def test_get_unknown_session_raises(self) -> None:
        """get() raises KeyError for unknown session."""
        tracker = SessionTrajectoryTracker()
        with pytest.raises(KeyError, match="not found"):
            tracker.get("nonexistent")

    def test_get_updates_duration_for_active_session(self) -> None:
        """get() refreshes duration_seconds for sessions that haven't ended."""
        tracker = SessionTrajectoryTracker()
        tracker.start_session("s1")
        trajectory = tracker.get("s1")
        assert trajectory.duration_seconds >= 0
        assert trajectory.end_time is None

    def test_list_sessions(self) -> None:
        """list_sessions returns all tracked session IDs."""
        tracker = SessionTrajectoryTracker()
        tracker.start_session("a")
        tracker.start_session("b")
        tracker.start_session("c")

        ids = tracker.list_sessions()
        assert set(ids) == {"a", "b", "c"}

    def test_remove_session(self) -> None:
        """remove() deletes a tracked session."""
        tracker = SessionTrajectoryTracker()
        tracker.start_session("s1")
        assert tracker.session_count == 1

        tracker.remove("s1")
        assert tracker.session_count == 0
        with pytest.raises(KeyError):
            tracker.get("s1")

    def test_remove_unknown_is_noop(self) -> None:
        """remove() on an unknown session is a no-op."""
        tracker = SessionTrajectoryTracker()
        tracker.remove("nonexistent")  # should not raise


class TestSetTitle:
    def test_set_title(self) -> None:
        """set_title updates the title and records a TITLE_SET event."""
        tracker = SessionTrajectoryTracker()
        tracker.start_session("s1")

        tracker.set_title("s1", "Debugging the auth flow")

        trajectory = tracker.get("s1")
        assert trajectory.title == "Debugging the auth flow"
        title_events = [e for e in trajectory.events if e.kind == TrajectoryEventKind.TITLE_SET]
        assert len(title_events) == 1
        assert title_events[0].detail == "Debugging the auth flow"

    def test_set_title_unknown_raises(self) -> None:
        """set_title raises KeyError for unknown session."""
        tracker = SessionTrajectoryTracker()
        with pytest.raises(KeyError, match="not found"):
            tracker.set_title("nonexistent", "title")


# ---------------------------------------------------------------------------
# Heuristic title generation tests
# ---------------------------------------------------------------------------


class TestGenerateTitleHeuristic:
    def test_simple_message(self) -> None:
        """Extracts first words from a simple message."""
        title = generate_title_heuristic("Can you help me debug the authentication flow?")
        assert title == "Can you help me debug the authentication flow?"

    def test_long_message_truncated_at_word_limit(self) -> None:
        """Messages longer than 10 words are truncated."""
        msg = "one two three four five six seven eight nine ten eleven twelve thirteen"
        title = generate_title_heuristic(msg)
        words = title.split()
        assert len(words) == 10

    def test_empty_message_returns_empty(self) -> None:
        """Empty input returns empty string."""
        assert generate_title_heuristic("") == ""
        assert generate_title_heuristic("   ") == ""

    def test_whitespace_normalized(self) -> None:
        """Excessive whitespace is normalized."""
        title = generate_title_heuristic("  Hello    world  ")
        assert title == "Hello world"

    def test_special_characters_stripped(self) -> None:
        """Control characters are removed but basic punctuation is kept."""
        title = generate_title_heuristic("Hello\x00world! How's it going?")
        assert "Hello" in title
        assert "world!" in title

    def test_very_long_title_truncated_with_ellipsis(self) -> None:
        """Titles exceeding _MAX_TITLE_LENGTH are truncated with ellipsis."""
        # Build a message with very long words within the 10-word limit.
        long_word = "a" * 20
        msg = " ".join([long_word] * 10)
        title = generate_title_heuristic(msg)
        # 10 words of 20 chars + 9 spaces = 209 chars, exceeds 80.
        assert len(title) <= 83  # 80 + "..."
        assert title.endswith("...")


# ---------------------------------------------------------------------------
# LLM title generation tests
# ---------------------------------------------------------------------------


class TestGenerateTitleLLM:
    async def test_llm_title_returned(self) -> None:
        """When the LLM returns a clean title, it is used directly."""
        mock_router = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "Debugging Authentication Flow"
        mock_router.complete = AsyncMock(return_value=mock_response)

        title = await generate_title_llm("Can you debug the auth?", mock_router)
        assert title == "Debugging Authentication Flow"

        # Verify the router was called with the right structure.
        mock_router.complete.assert_called_once()
        call_kwargs = mock_router.complete.call_args
        assert call_kwargs.kwargs["temperature"] == 0.3
        assert call_kwargs.kwargs["max_tokens"] == 30

    async def test_llm_strips_quotes(self) -> None:
        """Wrapping quotes from LLM output are stripped."""
        mock_router = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = '"Fixing Database Migration"'
        mock_router.complete = AsyncMock(return_value=mock_response)

        title = await generate_title_llm("Fix the DB migration", mock_router)
        assert title == "Fixing Database Migration"

    async def test_llm_strips_single_quotes(self) -> None:
        """Single quotes from LLM output are stripped."""
        mock_router = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "'Setting Up CI Pipeline'"
        mock_router.complete = AsyncMock(return_value=mock_response)

        title = await generate_title_llm("Set up CI", mock_router)
        assert title == "Setting Up CI Pipeline"

    async def test_llm_failure_falls_back_to_heuristic(self) -> None:
        """When the LLM call raises, falls back to heuristic."""
        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        title = await generate_title_llm("Can you help debug the auth flow?", mock_router)
        # Should get heuristic output instead.
        assert "debug" in title.lower() or "help" in title.lower()
        assert title != ""

    async def test_llm_empty_response_falls_back(self) -> None:
        """When the LLM returns empty content, falls back to heuristic."""
        mock_router = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "   "
        mock_router.complete = AsyncMock(return_value=mock_response)

        title = await generate_title_llm("Explain kubernetes pods", mock_router)
        # Empty LLM response triggers heuristic fallback.
        assert title != ""
        assert "kubernetes" in title.lower() or "Explain" in title

    async def test_llm_empty_input_returns_empty(self) -> None:
        """Empty input returns empty string without calling LLM."""
        mock_router = AsyncMock()
        title = await generate_title_llm("", mock_router)
        assert title == ""
        mock_router.complete.assert_not_called()

    async def test_llm_long_output_truncated(self) -> None:
        """Overly long LLM titles are truncated."""
        mock_router = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "A" * 200
        mock_router.complete = AsyncMock(return_value=mock_response)

        title = await generate_title_llm("Hello", mock_router)
        assert len(title) <= 83  # 80 + "..."
        assert title.endswith("...")


class TestTitleGenerator:
    async def test_generate_with_router(self) -> None:
        """TitleGenerator uses LLM when a router is provided."""
        mock_router = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "Automated Title"
        mock_router.complete = AsyncMock(return_value=mock_response)

        gen = TitleGenerator(router=mock_router)
        assert gen.has_llm is True

        title = await gen.generate("Test message")
        assert title == "Automated Title"

    async def test_generate_without_router(self) -> None:
        """TitleGenerator falls back to heuristic when no router."""
        gen = TitleGenerator(router=None)
        assert gen.has_llm is False

        title = await gen.generate("Can you help me debug the auth flow?")
        assert title != ""
        assert "debug" in title.lower() or "help" in title.lower()

    async def test_generate_empty_input(self) -> None:
        """Empty input returns empty regardless of mode."""
        gen = TitleGenerator(router=None)
        assert await gen.generate("") == ""


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


class TestTrajectoryAPI:
    """Integration tests for Phase 59 trajectory/title endpoints."""

    @pytest.fixture()
    def tracker(self) -> SessionTrajectoryTracker:
        """Create a fresh trajectory tracker."""
        return SessionTrajectoryTracker()

    @pytest.fixture()
    def title_gen(self) -> TitleGenerator:
        """Create a heuristic-only title generator."""
        return TitleGenerator(router=None)

    @pytest.fixture()
    def _wired_phase59(self, tracker: SessionTrajectoryTracker, title_gen: TitleGenerator) -> Any:
        """Wire Phase 59 services into sessions route module."""
        from agent33.api.routes import sessions as sessions_mod

        sessions_mod.set_trajectory_tracker(tracker)
        sessions_mod.set_title_generator(title_gen)

        yield

        sessions_mod.set_trajectory_tracker(None)
        sessions_mod.set_title_generator(None)

    async def test_get_trajectory(
        self, tracker: SessionTrajectoryTracker, _wired_phase59: Any
    ) -> None:
        """GET /v1/sessions/{id}/trajectory returns the trajectory."""
        import httpx

        from agent33.main import app

        tracker.start_session("test-sess-1")
        tracker.record_event(
            "test-sess-1",
            TrajectoryEventKind.USER_MESSAGE,
            detail="Hello there",
            token_count=5,
        )
        tracker.record_event(
            "test-sess-1",
            TrajectoryEventKind.AGENT_RESPONSE,
            agent_name="code-worker",
            token_count=20,
        )
        tracker.record_event(
            "test-sess-1",
            TrajectoryEventKind.TOOL_CALL,
            detail="shell(ls)",
        )

        app.state.trajectory_tracker = tracker

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.get("/v1/sessions/test-sess-1/trajectory")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "test-sess-1"
        assert data["total_user_messages"] == 1
        assert data["total_agent_responses"] == 1
        assert data["total_tool_calls"] == 1
        assert data["total_tokens"] == 25
        assert data["outcome"] == "pending"
        assert len(data["events"]) == 4  # start + user + agent + tool
        assert len(data["token_usage"]) == 2  # user(5) + agent(20), tool had 0

    async def test_get_trajectory_not_found(self, _wired_phase59: Any) -> None:
        """GET /v1/sessions/{id}/trajectory returns 404 for unknown session."""
        import httpx

        from agent33.main import app

        app.state.trajectory_tracker = SessionTrajectoryTracker()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.get("/v1/sessions/nonexistent/trajectory")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert resp.status_code == 404

    async def test_get_title_auto_generated(
        self,
        tracker: SessionTrajectoryTracker,
        title_gen: TitleGenerator,
        _wired_phase59: Any,
    ) -> None:
        """GET /v1/sessions/{id}/title generates a title from first message."""
        import httpx

        from agent33.main import app

        tracker.start_session("test-sess-2")
        tracker.record_event(
            "test-sess-2",
            TrajectoryEventKind.USER_MESSAGE,
            detail="How do I configure Kubernetes ingress controllers?",
        )

        app.state.trajectory_tracker = tracker
        app.state.title_generator = title_gen

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.get("/v1/sessions/test-sess-2/title")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "test-sess-2"
        assert "Kubernetes" in data["title"] or "configure" in data["title"]
        assert data["source"] == "generated"

    async def test_get_title_stored(
        self, tracker: SessionTrajectoryTracker, _wired_phase59: Any
    ) -> None:
        """GET /v1/sessions/{id}/title returns stored title when available."""
        import httpx

        from agent33.main import app

        tracker.start_session("test-sess-3")
        tracker.set_title("test-sess-3", "My Custom Title")

        app.state.trajectory_tracker = tracker

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.get("/v1/sessions/test-sess-3/title")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "My Custom Title"
        assert data["source"] == "stored"

    async def test_patch_title(
        self, tracker: SessionTrajectoryTracker, _wired_phase59: Any
    ) -> None:
        """PATCH /v1/sessions/{id}/title sets a manual title."""
        import httpx

        from agent33.main import app

        tracker.start_session("test-sess-4")

        app.state.trajectory_tracker = tracker

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.patch(
                "/v1/sessions/test-sess-4/title",
                json={"title": "Manually Set Title"},
            )

        if resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Manually Set Title"
        assert data["source"] == "manual"

        # Verify it persisted on the trajectory.
        trajectory = tracker.get("test-sess-4")
        assert trajectory.title == "Manually Set Title"

    async def test_patch_title_not_found(self, _wired_phase59: Any) -> None:
        """PATCH /v1/sessions/{id}/title returns 404 for unknown session."""
        import httpx

        from agent33.main import app

        app.state.trajectory_tracker = SessionTrajectoryTracker()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.patch(
                "/v1/sessions/nonexistent/title",
                json={"title": "Some Title"},
            )

        if resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert resp.status_code == 404

    async def test_patch_title_empty_rejected(self, _wired_phase59: Any) -> None:
        """PATCH /v1/sessions/{id}/title rejects empty title."""
        import httpx

        from agent33.main import app

        tracker = SessionTrajectoryTracker()
        tracker.start_session("test-sess-5")
        app.state.trajectory_tracker = tracker

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.patch(
                "/v1/sessions/test-sess-5/title",
                json={"title": ""},
            )

        if resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert resp.status_code == 422  # Pydantic validation

    async def test_get_title_not_found(self, _wired_phase59: Any) -> None:
        """GET /v1/sessions/{id}/title returns 404 for unknown session."""
        import httpx

        from agent33.main import app

        app.state.trajectory_tracker = SessionTrajectoryTracker()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.get("/v1/sessions/nonexistent/title")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Full session lifecycle test
# ---------------------------------------------------------------------------


class TestFullSessionLifecycle:
    """End-to-end test for a complete session trajectory."""

    def test_complete_lifecycle(self) -> None:
        """A session goes through start -> events -> title -> end."""
        tracker = SessionTrajectoryTracker()

        # Start.
        tracker.start_session("lifecycle-1", metadata={"agent": "code-worker"})

        # User message.
        tracker.record_event(
            "lifecycle-1",
            TrajectoryEventKind.USER_MESSAGE,
            detail="Help me write a REST API",
            token_count=10,
        )

        # Agent response.
        tracker.record_event(
            "lifecycle-1",
            TrajectoryEventKind.AGENT_RESPONSE,
            agent_name="code-worker",
            token_count=150,
        )

        # Tool calls.
        tracker.record_event(
            "lifecycle-1",
            TrajectoryEventKind.TOOL_CALL,
            detail="file_write(main.py)",
            token_count=5,
        )
        tracker.record_event(
            "lifecycle-1",
            TrajectoryEventKind.TOOL_RESULT,
            detail="file written",
            token_count=2,
        )

        # Error.
        tracker.record_event(
            "lifecycle-1",
            TrajectoryEventKind.ERROR,
            detail="Test failure in test_main.py",
        )

        # Second round.
        tracker.record_event(
            "lifecycle-1",
            TrajectoryEventKind.USER_MESSAGE,
            detail="Fix the test",
            token_count=5,
        )
        tracker.record_event(
            "lifecycle-1",
            TrajectoryEventKind.AGENT_RESPONSE,
            agent_name="code-worker",
            token_count=80,
        )

        # Milestone.
        tracker.record_event(
            "lifecycle-1",
            TrajectoryEventKind.MILESTONE,
            detail="All tests green",
        )

        # Set title.
        tracker.set_title("lifecycle-1", "Building REST API with Tests")

        # End.
        trajectory = tracker.end_session("lifecycle-1", SessionOutcome.SUCCESS)

        # Verify full state.
        assert trajectory.session_id == "lifecycle-1"
        assert trajectory.title == "Building REST API with Tests"
        assert trajectory.outcome == SessionOutcome.SUCCESS
        assert trajectory.total_user_messages == 2
        assert trajectory.total_agent_responses == 2
        assert trajectory.total_tool_calls == 1  # only TOOL_CALL, not TOOL_RESULT
        assert trajectory.total_errors == 1
        assert trajectory.total_tokens == 252  # 10 + 150 + 5 + 2 + 5 + 80
        assert trajectory.first_user_message == "Help me write a REST API"
        assert trajectory.end_time is not None
        assert trajectory.duration_seconds >= 0

        # Verify token usage trajectory (6 events had token_count > 0).
        assert len(trajectory.token_usage) == 6
        assert trajectory.token_usage[-1].cumulative_tokens == 252

        # Verify event count (start + 8 events + title + end = 11).
        assert trajectory.event_count == 11
        assert trajectory.metadata == {"agent": "code-worker"}
