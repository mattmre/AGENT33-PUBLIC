"""Tests for the SearchTool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent33.tools.base import ToolContext
from agent33.tools.builtin.search import SearchTool
from agent33.web_research.models import (
    ResearchSearchResponse,
    ResearchTrustLevel,
    TrustLabel,
    WebResearchCitation,
    WebResearchResult,
)


@pytest.fixture
def tool() -> SearchTool:
    return SearchTool()


@pytest.fixture
def context() -> ToolContext:
    return ToolContext()


async def test_name(tool: SearchTool) -> None:
    assert tool.name == "web_search"


async def test_missing_query(tool: SearchTool, context: ToolContext) -> None:
    result = await tool.execute({}, context)
    assert not result.success


async def test_search_returns_results(tool: SearchTool, context: ToolContext) -> None:
    citation = WebResearchCitation(
        title="Result 1",
        url="https://example.com/1",
        display_url="example.com/1",
        domain="example.com",
        provider_id="searxng",
        trust_level=ResearchTrustLevel.SEARCH_INDEXED,
        trust_reason="Indexed by searxng",
    )
    results = [
        WebResearchResult(
            title="Result 1",
            url="https://example.com/1",
            snippet="Snippet 1",
            provider_id="searxng",
            rank=1,
            domain="example.com",
            display_url="example.com/1",
            trust_level=ResearchTrustLevel.SEARCH_INDEXED,
            trust_reason="Indexed by searxng",
            citation=citation,
            trust_label=TrustLabel.UNKNOWN,
            trust_label_reason="No established reputation",
        ),
        WebResearchResult(
            title="Result 2",
            url="https://example.com/2",
            snippet="Snippet 2",
            provider_id="searxng",
            rank=2,
            domain="example.com",
            display_url="example.com/2",
            trust_level=ResearchTrustLevel.SEARCH_INDEXED,
            trust_reason="Indexed by searxng",
            citation=citation,
            trust_label=TrustLabel.UNKNOWN,
            trust_label_reason="No established reputation",
        ),
    ]
    response = ResearchSearchResponse(query="test query", provider_id="searxng", results=results)

    mock_service = MagicMock()
    mock_service.search = AsyncMock(return_value=response)

    with patch(
        "agent33.tools.builtin.search.create_default_web_research_service",
        return_value=mock_service,
    ):
        result = await tool.execute({"query": "test query"}, context)
        assert result.success
        assert "Result 1" in result.output
        assert "Result 2" in result.output
        assert "UNKNOWN" in result.output


async def test_search_connection_error(tool: SearchTool, context: ToolContext) -> None:
    mock_service = MagicMock()
    mock_service.search = AsyncMock(side_effect=ValueError("Could not connect to SearXNG"))

    with patch(
        "agent33.tools.builtin.search.create_default_web_research_service",
        return_value=mock_service,
    ):
        result = await tool.execute({"query": "test"}, context)
        assert not result.success
        assert "Could not connect" in result.error
