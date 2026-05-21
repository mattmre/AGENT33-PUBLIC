"""Progressive recall - 3-layer token-efficient context retrieval."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent33.observability.query_profiling import track_query

if TYPE_CHECKING:
    from agent33.memory.embeddings import EmbeddingProvider
    from agent33.memory.long_term import LongTermMemory

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RecallResult:
    """A single recall result at a specific detail level."""

    level: str  # index, timeline, full
    content: str
    citations: list[str] = field(default_factory=list)  # observation IDs
    token_estimate: int = 0


class ProgressiveRecall:
    """Three-layer token-efficient retrieval from long-term memory.

    Layer 1 (index):    Compact topic list, ~50 tokens per result
    Layer 2 (timeline): Chronological context, ~200 tokens per result
    Layer 3 (full):     Full observation details, ~1000 tokens per result

    This provides ~10x token savings by letting callers filter at low
    detail before fetching full context.
    """

    def __init__(
        self,
        long_term_memory: LongTermMemory,
        embedding_provider: EmbeddingProvider,
        top_k: int = 10,
    ) -> None:
        self._memory = long_term_memory
        self._embeddings = embedding_provider
        self._top_k = top_k

    async def search(
        self,
        query: str,
        level: str = "index",
        top_k: int | None = None,
    ) -> list[RecallResult]:
        """Search memory at the specified detail level.

        Args:
            query: Search query text
            level: Detail level - "index", "timeline", or "full"
            top_k: Max results (defaults to instance top_k)
        """
        async with track_query("progressive_recall_search", table="memory_records"):
            k = top_k or self._top_k
            query_embedding = await self._embeddings.embed(query)
            results = await self._memory.search(query_embedding, top_k=k)

            recall_results: list[RecallResult] = []
            for r in results:
                meta: dict[str, Any] = r.metadata or {}
                obs_id = meta.get("observation_id", "")
                citation = [obs_id] if obs_id else []

                if level == "index":
                    # Compact: just topic + agent name + event type
                    agent = meta.get("agent_name", "unknown")
                    event = meta.get("event_type", "")
                    tags = meta.get("tags", [])
                    tag_str = ", ".join(tags[:3]) if tags else ""
                    content = f"[{agent}/{event}] {tag_str}: {r.text[:80]}..."
                    token_est = max(10, len(content.split()))
                elif level == "timeline":
                    # Chronological: timestamp + summary content
                    ts = meta.get("timestamp", "")
                    agent = meta.get("agent_name", "unknown")
                    content = f"[{ts}] {agent}: {r.text[:300]}"
                    token_est = max(30, len(content.split()))
                else:  # full
                    content = r.text
                    token_est = max(50, len(content.split()))

                recall_results.append(
                    RecallResult(
                        level=level,
                        content=content,
                        citations=citation,
                        token_estimate=token_est,
                    )
                )

            return recall_results
