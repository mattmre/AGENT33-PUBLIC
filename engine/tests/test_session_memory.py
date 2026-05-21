"""Tests for session memory: observation, summarization, progressive recall."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agent33.memory.observation import Observation, ObservationCapture


class TestObservation:
    """Test Observation dataclass."""

    def test_defaults(self) -> None:
        obs = Observation()
        assert obs.id
        assert obs.session_id == ""
        assert obs.event_type == ""
        assert obs.tags == []

    def test_with_fields(self) -> None:
        obs = Observation(
            session_id="s1",
            agent_name="coder",
            event_type="llm_response",
            content="hello",
            tags=["test"],
        )
        assert obs.session_id == "s1"
        assert obs.agent_name == "coder"
        assert "test" in obs.tags


class TestObservationCapture:
    """Test ObservationCapture recording and filtering."""

    @pytest.mark.asyncio
    async def test_record_and_flush(self) -> None:
        capture = ObservationCapture()
        obs = Observation(content="test content")
        obs_id = await capture.record(obs)
        assert obs_id == obs.id
        assert capture.buffer_size == 1

        flushed = await capture.flush()
        assert len(flushed) == 1
        assert capture.buffer_size == 0

    @pytest.mark.asyncio
    async def test_private_tags_not_stored(self) -> None:
        """Observations with private tags are buffered but not stored in LTM."""
        mock_memory = AsyncMock()
        mock_embed = AsyncMock()
        mock_embed.embed.return_value = [0.1] * 1536

        capture = ObservationCapture(
            long_term_memory=mock_memory,
            embedding_provider=mock_embed,
        )
        obs = Observation(content="secret data", tags=["sensitive"])
        await capture.record(obs)

        # Should be buffered
        assert capture.buffer_size == 1
        # Should NOT be stored in long-term memory
        mock_memory.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_public_obs_stored_in_ltm(self) -> None:
        """Non-private observations are stored with embedding."""
        mock_memory = AsyncMock()
        mock_embed = AsyncMock()
        mock_embed.embed.return_value = [0.1] * 1536

        capture = ObservationCapture(
            long_term_memory=mock_memory,
            embedding_provider=mock_embed,
        )
        obs = Observation(content="public data", tags=["general"])
        await capture.record(obs)

        mock_embed.embed.assert_called_once_with("public data")
        mock_memory.store.assert_called_once()


class TestObservationCaptureNATS:
    """Test NATS publish path in ObservationCapture."""

    @pytest.mark.asyncio
    async def test_nats_publish_on_record(self) -> None:
        """Recording a public observation publishes to NATS bus."""
        mock_nats = AsyncMock()
        capture = ObservationCapture(nats_bus=mock_nats)
        obs = Observation(content="event data", event_type="tool_call", agent_name="coder")
        await capture.record(obs)

        mock_nats.publish.assert_called_once()
        call_args = mock_nats.publish.call_args
        assert call_args[0][0] == "agent.observation"
        payload = call_args[0][1]
        assert payload["id"] == obs.id
        assert payload["content"] == "event data"
        assert payload["agent_name"] == "coder"
        assert payload["event_type"] == "tool_call"

    @pytest.mark.asyncio
    async def test_nats_publish_failure_silenced(self) -> None:
        """NATS publish failure does not propagate; observation is still buffered."""
        mock_nats = AsyncMock()
        mock_nats.publish.side_effect = ConnectionError("NATS down")
        capture = ObservationCapture(nats_bus=mock_nats)
        obs = Observation(content="should still buffer")
        obs_id = await capture.record(obs)

        assert obs_id == obs.id
        assert capture.buffer_size == 1

    @pytest.mark.asyncio
    async def test_nats_and_ltm_both_fire(self) -> None:
        """Both LTM store and NATS publish are called for public observations."""
        mock_memory = AsyncMock()
        mock_embed = AsyncMock()
        mock_embed.embed.return_value = [0.1] * 1536
        mock_nats = AsyncMock()

        capture = ObservationCapture(
            long_term_memory=mock_memory,
            embedding_provider=mock_embed,
            nats_bus=mock_nats,
        )
        obs = Observation(content="dual path test")
        await capture.record(obs)

        mock_memory.store.assert_called_once()
        mock_nats.publish.assert_called_once()


class TestSessionSummarizer:
    """Test SessionSummarizer."""

    @pytest.mark.asyncio
    async def test_summarize(self) -> None:
        from agent33.llm.base import LLMResponse
        from agent33.memory.summarizer import SessionSummarizer

        mock_router = AsyncMock()
        mock_router.complete.return_value = LLMResponse(
            content='{"summary": "Agent did things", "key_facts": ["fact1"], "tags": ["coding"]}',
            model="test",
            prompt_tokens=10,
            completion_tokens=20,
        )

        summarizer = SessionSummarizer(router=mock_router)
        observations = [
            Observation(event_type="llm_response", agent_name="coder", content="wrote code"),
            Observation(event_type="tool_call", agent_name="coder", content="ran tests"),
        ]
        result = await summarizer.summarize(observations)

        assert result["summary"] == "Agent did things"
        assert "fact1" in result["key_facts"]
        assert "coding" in result["tags"]

    @pytest.mark.asyncio
    async def test_summarize_json_error_fallback(self) -> None:
        from agent33.llm.base import LLMResponse
        from agent33.memory.summarizer import SessionSummarizer

        mock_router = AsyncMock()
        mock_router.complete.return_value = LLMResponse(
            content="Not valid JSON at all",
            model="test",
            prompt_tokens=10,
            completion_tokens=20,
        )

        summarizer = SessionSummarizer(router=mock_router)
        result = await summarizer.summarize([Observation(content="test")])
        assert "summary" in result
        assert result["key_facts"] == []


class TestAutoSummarize:
    """Test SessionSummarizer.auto_summarize() LTM storage path."""

    @pytest.mark.asyncio
    async def test_auto_summarize_stores_in_ltm(self) -> None:
        """auto_summarize() should call summarize and then store in LTM."""
        from agent33.llm.base import LLMResponse
        from agent33.memory.summarizer import SessionSummarizer

        mock_router = AsyncMock()
        mock_router.complete.return_value = LLMResponse(
            content='{"summary": "session recap", "key_facts": ["f1"], "tags": ["t1"]}',
            model="test",
            prompt_tokens=10,
            completion_tokens=20,
        )
        mock_memory = AsyncMock()
        mock_embed = AsyncMock()
        mock_embed.embed.return_value = [0.1] * 1536

        summarizer = SessionSummarizer(
            router=mock_router,
            long_term_memory=mock_memory,
            embedding_provider=mock_embed,
        )
        observations = [
            Observation(content="did stuff", event_type="tool_call", agent_name="coder"),
        ]
        result = await summarizer.auto_summarize("sess-1", observations)

        assert result["summary"] == "session recap"
        mock_embed.embed.assert_called_once_with("session recap")
        mock_memory.store.assert_called_once()
        store_kwargs = mock_memory.store.call_args
        assert "session_summary" in str(store_kwargs)

    @pytest.mark.asyncio
    async def test_auto_summarize_ltm_failure_graceful(self) -> None:
        """LTM failure during auto_summarize does not raise; result is returned."""
        from agent33.llm.base import LLMResponse
        from agent33.memory.summarizer import SessionSummarizer

        mock_router = AsyncMock()
        mock_router.complete.return_value = LLMResponse(
            content='{"summary": "ok", "key_facts": [], "tags": []}',
            model="test",
            prompt_tokens=10,
            completion_tokens=20,
        )
        mock_memory = AsyncMock()
        mock_memory.store.side_effect = RuntimeError("LTM unavailable")
        mock_embed = AsyncMock()
        mock_embed.embed.return_value = [0.1] * 1536

        summarizer = SessionSummarizer(
            router=mock_router,
            long_term_memory=mock_memory,
            embedding_provider=mock_embed,
        )
        result = await summarizer.auto_summarize("sess-2", [Observation(content="test")])

        # Summary result is still returned despite LTM failure
        assert result["summary"] == "ok"

    @pytest.mark.asyncio
    async def test_auto_summarize_without_ltm(self) -> None:
        """auto_summarize() without LTM configured returns the summary without storing."""
        from agent33.llm.base import LLMResponse
        from agent33.memory.summarizer import SessionSummarizer

        mock_router = AsyncMock()
        mock_router.complete.return_value = LLMResponse(
            content='{"summary": "no ltm", "key_facts": ["a"], "tags": ["b"]}',
            model="test",
            prompt_tokens=10,
            completion_tokens=20,
        )

        summarizer = SessionSummarizer(router=mock_router)
        result = await summarizer.auto_summarize("sess-3", [Observation(content="test")])
        assert result["summary"] == "no ltm"


class TestProgressiveRecall:
    """Test ProgressiveRecall at different detail levels."""

    @pytest.mark.asyncio
    async def test_index_level(self) -> None:
        from agent33.memory.long_term import SearchResult
        from agent33.memory.progressive_recall import ProgressiveRecall

        mock_memory = AsyncMock()
        mock_memory.search.return_value = [
            SearchResult(
                text="Some observation content here",
                score=0.9,
                metadata={
                    "observation_id": "obs1",
                    "agent_name": "coder",
                    "event_type": "llm_response",
                    "tags": ["coding"],
                },
            )
        ]
        mock_embed = AsyncMock()
        mock_embed.embed.return_value = [0.1] * 1536

        recall = ProgressiveRecall(mock_memory, mock_embed)
        results = await recall.search("code", level="index")

        assert len(results) == 1
        assert results[0].level == "index"
        assert "coder" in results[0].content
        assert results[0].token_estimate < 100

    @pytest.mark.asyncio
    async def test_full_level(self) -> None:
        from agent33.memory.long_term import SearchResult
        from agent33.memory.progressive_recall import ProgressiveRecall

        mock_memory = AsyncMock()
        mock_memory.search.return_value = [
            SearchResult(
                text="Full detailed content of the observation",
                score=0.8,
                metadata={"observation_id": "obs2"},
            )
        ]
        mock_embed = AsyncMock()
        mock_embed.embed.return_value = [0.1] * 1536

        recall = ProgressiveRecall(mock_memory, mock_embed)
        results = await recall.search("detail", level="full")

        assert len(results) == 1
        assert results[0].level == "full"
        assert "Full detailed content" in results[0].content
