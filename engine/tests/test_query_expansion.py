"""Tests for LLM-based query expansion."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.llm.base import LLMResponse
from agent33.memory.query_expansion import ExpandedQuery, QueryExpander


def _make_mock_router(response_content: str, *, raise_exc: Exception | None = None) -> MagicMock:
    """Create a mock ModelRouter that returns the given content."""
    router = MagicMock()
    if raise_exc is not None:
        router.complete = AsyncMock(side_effect=raise_exc)
    else:
        mock_response = LLMResponse(
            content=response_content,
            model="llama3.2",
            prompt_tokens=50,
            completion_tokens=40,
        )
        router.complete = AsyncMock(return_value=mock_response)
    return router


_GOOD_JSON = json.dumps(
    {
        "keywords": ["python", "programming", "language", "code", "scripting"],
        "sub_queries": [
            "What is the Python programming language?",
            "Explain Python and its uses",
        ],
    }
)


class TestExpandedQueryModel:
    """Test the ExpandedQuery pydantic model."""

    def test_minimal_creation(self) -> None:
        eq = ExpandedQuery(original="hello", expanded_text="hello")
        assert eq.original == "hello"
        assert eq.expanded_text == "hello"
        assert eq.keywords == []
        assert eq.sub_queries == []
        assert eq.expansion_tokens_used == 0

    def test_full_creation(self) -> None:
        eq = ExpandedQuery(
            original="test",
            expanded_text="test rephrased",
            keywords=["a", "b"],
            sub_queries=["rephrased"],
            expansion_tokens_used=42,
        )
        assert eq.keywords == ["a", "b"]
        assert eq.sub_queries == ["rephrased"]
        assert eq.expansion_tokens_used == 42


class TestQueryExpanderDisabled:
    """Test QueryExpander when expansion is disabled."""

    @pytest.mark.asyncio
    async def test_disabled_returns_original(self) -> None:
        router = _make_mock_router(_GOOD_JSON)
        expander = QueryExpander(_router=router, _enabled=False)

        result = await expander.expand("What is Python programming?")

        assert result.original == "What is Python programming?"
        assert result.expanded_text == "What is Python programming?"
        assert result.keywords == []
        assert result.sub_queries == []
        router.complete.assert_not_called()


class TestQueryExpanderShortQuery:
    """Test QueryExpander with queries below minimum length."""

    @pytest.mark.asyncio
    async def test_short_query_returns_original(self) -> None:
        router = _make_mock_router(_GOOD_JSON)
        expander = QueryExpander(_router=router, _min_query_length=10)

        result = await expander.expand("hi")

        assert result.original == "hi"
        assert result.expanded_text == "hi"
        assert result.keywords == []
        router.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_whitespace_only_short_query(self) -> None:
        router = _make_mock_router(_GOOD_JSON)
        expander = QueryExpander(_router=router, _min_query_length=10)

        result = await expander.expand("   ab   ")

        assert result.expanded_text == "   ab   "
        router.complete.assert_not_called()


class TestQueryExpanderSuccess:
    """Test QueryExpander with successful LLM responses."""

    @pytest.mark.asyncio
    async def test_parses_keywords_and_sub_queries(self) -> None:
        router = _make_mock_router(_GOOD_JSON)
        expander = QueryExpander(_router=router)

        result = await expander.expand("What is Python?")

        assert result.original == "What is Python?"
        assert "python" in result.keywords
        assert "programming" in result.keywords
        assert len(result.sub_queries) == 2
        assert "What is the Python programming language?" in result.sub_queries
        router.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_expanded_text_includes_original(self) -> None:
        router = _make_mock_router(_GOOD_JSON)
        expander = QueryExpander(_router=router)

        result = await expander.expand("What is Python?")

        assert result.expanded_text.startswith("What is Python?")
        # Sub-queries are appended
        assert "What is the Python programming language?" in result.expanded_text
        assert "Explain Python and its uses" in result.expanded_text

    @pytest.mark.asyncio
    async def test_tokens_tracked(self) -> None:
        router = _make_mock_router(_GOOD_JSON)
        expander = QueryExpander(_router=router)

        result = await expander.expand("What is Python?")

        # 50 prompt + 40 completion = 90 total
        assert result.expansion_tokens_used == 90

    @pytest.mark.asyncio
    async def test_empty_keywords_from_llm(self) -> None:
        response = json.dumps({"keywords": [], "sub_queries": []})
        router = _make_mock_router(response)
        expander = QueryExpander(_router=router)

        result = await expander.expand("What is Python?")

        assert result.keywords == []
        assert result.sub_queries == []
        assert result.expanded_text == "What is Python?"


class TestQueryExpanderFallback:
    """Test QueryExpander graceful fallback on errors."""

    @pytest.mark.asyncio
    async def test_json_parse_error_falls_back(self) -> None:
        router = _make_mock_router("not valid json at all")
        expander = QueryExpander(_router=router)

        result = await expander.expand("What is Python?")

        assert result.original == "What is Python?"
        assert result.expanded_text == "What is Python?"
        assert result.keywords == []
        assert result.sub_queries == []

    @pytest.mark.asyncio
    async def test_llm_exception_falls_back(self) -> None:
        router = _make_mock_router("", raise_exc=RuntimeError("LLM unavailable"))
        expander = QueryExpander(_router=router)

        result = await expander.expand("What is Python?")

        assert result.original == "What is Python?"
        assert result.expanded_text == "What is Python?"
        assert result.keywords == []

    @pytest.mark.asyncio
    async def test_missing_keys_in_json(self) -> None:
        # Valid JSON but missing expected keys
        router = _make_mock_router('{"other": "data"}')
        expander = QueryExpander(_router=router)

        result = await expander.expand("What is Python?")

        assert result.original == "What is Python?"
        assert result.keywords == []
        assert result.sub_queries == []
        assert result.expanded_text == "What is Python?"


class TestQueryExpanderRAGIntegration:
    """Test that QueryExpander integrates with RAGPipeline diagnostics."""

    @pytest.mark.asyncio
    async def test_rag_pipeline_with_expander_adds_diagnostic_stage(self) -> None:
        from unittest.mock import AsyncMock

        from agent33.memory.long_term import SearchResult
        from agent33.memory.rag import RAGPipeline

        mock_embedder = AsyncMock()
        mock_embedder.embed.return_value = [0.1] * 1536
        mock_memory = AsyncMock()
        mock_memory.search.return_value = [
            SearchResult(text="Relevant context", score=0.8, metadata={}),
        ]

        router = _make_mock_router(_GOOD_JSON)
        expander = QueryExpander(_router=router)

        pipeline = RAGPipeline(
            embedding_provider=mock_embedder,
            long_term_memory=mock_memory,
            query_expander=expander,
        )

        outcome = await pipeline.query_with_diagnostics("What is Python?")

        stage_names = [s.stage for s in outcome.diagnostics.stages]
        assert stage_names[0] == "query-expansion"
        assert "vector-search" in stage_names
        assert len(outcome.result.sources) == 1

    @pytest.mark.asyncio
    async def test_rag_pipeline_without_expander_no_expansion_stage(self) -> None:
        from unittest.mock import AsyncMock

        from agent33.memory.long_term import SearchResult
        from agent33.memory.rag import RAGPipeline

        mock_embedder = AsyncMock()
        mock_embedder.embed.return_value = [0.1] * 1536
        mock_memory = AsyncMock()
        mock_memory.search.return_value = [
            SearchResult(text="Relevant context", score=0.8, metadata={}),
        ]

        pipeline = RAGPipeline(
            embedding_provider=mock_embedder,
            long_term_memory=mock_memory,
        )

        outcome = await pipeline.query_with_diagnostics("What is Python?")

        stage_names = [s.stage for s in outcome.diagnostics.stages]
        assert "query-expansion" not in stage_names
