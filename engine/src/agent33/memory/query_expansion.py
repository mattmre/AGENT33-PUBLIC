"""LLM-based query expansion for RAG retrieval improvement.

Generates synonyms, keywords, and alternative phrasings before search
to improve both embedding similarity and BM25 keyword recall.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.llm.router import ModelRouter

logger = logging.getLogger(__name__)

_EXPANSION_PROMPT = """You are a search query expander. Given a user query, generate:
1. A list of 5-8 keywords and synonyms relevant to the query
2. 2-3 alternative phrasings of the query

Respond ONLY with valid JSON in this exact format:
{{"keywords": ["kw1", "kw2", ...], "sub_queries": ["rephrased 1", "rephrased 2"]}}

User query: {query}"""


class ExpandedQuery(BaseModel):
    """Result of query expansion."""

    original: str
    expanded_text: str
    keywords: list[str] = Field(default_factory=list)
    sub_queries: list[str] = Field(default_factory=list)
    expansion_tokens_used: int = 0


@dataclass
class QueryExpander:
    """Expands queries using an LLM before RAG retrieval."""

    _router: ModelRouter
    _model: str = "llama3.2"
    _enabled: bool = True
    _max_tokens: int = 200
    _min_query_length: int = 10

    async def expand(self, query: str) -> ExpandedQuery:
        """Expand a query with keywords and alternative phrasings."""
        if not self._enabled or len(query.strip()) < self._min_query_length:
            return ExpandedQuery(
                original=query,
                expanded_text=query,
            )

        try:
            from agent33.llm.base import ChatMessage

            messages = [
                ChatMessage(role="user", content=_EXPANSION_PROMPT.format(query=query)),
            ]
            response = await self._router.complete(
                messages=messages,
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=0.3,
            )

            data = json.loads(response.content)
            keywords = data.get("keywords", [])
            sub_queries = data.get("sub_queries", [])

            # Build expanded text: original + sub_queries for richer embedding
            expanded_parts = [query] + sub_queries
            expanded_text = " ".join(expanded_parts)

            return ExpandedQuery(
                original=query,
                expanded_text=expanded_text,
                keywords=keywords,
                sub_queries=sub_queries,
                expansion_tokens_used=response.total_tokens,
            )
        except Exception:
            logger.warning("Query expansion failed, using original query", exc_info=True)
            return ExpandedQuery(original=query, expanded_text=query)
