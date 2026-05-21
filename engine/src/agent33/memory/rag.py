"""Retrieval-Augmented Generation pipeline.

Supports both vector-only and hybrid (BM25 + vector) retrieval modes.
When a :class:`HybridSearcher` is provided, the pipeline uses Reciprocal
Rank Fusion for higher-quality retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import TYPE_CHECKING, Any

from agent33.security.redaction import redact_secrets

if TYPE_CHECKING:
    from agent33.memory.embeddings import EmbeddingProvider
    from agent33.memory.hybrid import HybridSearcher
    from agent33.memory.long_term import LongTermMemory
    from agent33.memory.query_expansion import QueryExpander


@dataclass
class RAGResult:
    """Result of a RAG query."""

    augmented_prompt: str
    sources: list[RAGSource]


@dataclass
class RAGSource:
    """A single source document from RAG retrieval."""

    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    retrieval_method: str = "vector"


@dataclass
class RetrievalStageDiagnostic:
    """Timing/count diagnostics for a single retrieval stage."""

    stage: str
    duration_ms: int
    input_count: int = 0
    output_count: int = 0


@dataclass
class RetrievalDiagnostics:
    """Execution diagnostics for a modular retrieval pipeline run."""

    retrieval_method: str
    stages: list[RetrievalStageDiagnostic] = field(default_factory=list)
    total_duration_ms: int = 0


@dataclass
class RAGQueryWithDiagnostics:
    """RAG result plus retrieval-stage diagnostics."""

    result: RAGResult
    diagnostics: RetrievalDiagnostics


class RAGPipeline:
    """Query long-term memory and produce augmented context.

    Parameters
    ----------
    embedding_provider:
        Used to embed queries for vector search.
    long_term_memory:
        The pgvector-backed semantic memory store.
    top_k:
        Number of results to retrieve (default 5).
    similarity_threshold:
        Minimum score to include a result (default 0.3).
        Applied to vector scores in vector-only mode; in hybrid mode
        all RRF results above 0 are included.
    hybrid_searcher:
        Optional hybrid searcher.  When provided, the pipeline uses
        hybrid BM25 + vector retrieval instead of vector-only.
    query_expander:
        Optional query expander.  When provided, queries are expanded
        with LLM-generated keywords and sub-queries before search.
    """

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        long_term_memory: LongTermMemory,
        top_k: int = 5,
        similarity_threshold: float = 0.3,
        hybrid_searcher: HybridSearcher | None = None,
        query_expander: QueryExpander | None = None,
        *,
        redact_enabled: bool = True,
    ) -> None:
        self._embedder = embedding_provider
        self._memory = long_term_memory
        self._top_k = top_k
        self._threshold = similarity_threshold
        self._hybrid = hybrid_searcher
        self._expander = query_expander
        self._redact_enabled = redact_enabled

    async def query(self, text: str) -> RAGResult:
        """Embed *text*, search memory, and return augmented context."""
        outcome = await self.query_with_diagnostics(text)
        return outcome.result

    async def query_with_diagnostics(self, text: str) -> RAGQueryWithDiagnostics:
        """Run the modular retrieval pipeline and return stage diagnostics."""
        total_start = perf_counter()
        diagnostics = RetrievalDiagnostics(
            retrieval_method="hybrid" if self._hybrid is not None else "vector",
        )

        # ── Optional query expansion ─────────────────────────────────
        search_text = text
        if self._expander is not None:
            expand_start = perf_counter()
            expanded = await self._expander.expand(text)
            search_text = expanded.expanded_text
            self._add_stage_diagnostic(
                diagnostics,
                "query-expansion",
                expand_start,
                input_count=1,
                output_count=len(expanded.keywords) + len(expanded.sub_queries),
            )

        if self._hybrid is not None:
            result = await self._query_hybrid(search_text, diagnostics)
        else:
            result = await self._query_vector(search_text, diagnostics)
        diagnostics.total_duration_ms = int((perf_counter() - total_start) * 1000)
        return RAGQueryWithDiagnostics(result=result, diagnostics=diagnostics)

    # ── Vector-only retrieval ────────────────────────────────────────

    def _add_stage_diagnostic(
        self,
        diagnostics: RetrievalDiagnostics,
        stage_name: str,
        start_time: float,
        input_count: int = 0,
        output_count: int = 0,
    ) -> None:
        """Append a stage diagnostic entry with timing."""
        duration_ms = int((perf_counter() - start_time) * 1000)
        diagnostics.stages.append(
            RetrievalStageDiagnostic(
                stage=stage_name,
                duration_ms=duration_ms,
                input_count=input_count,
                output_count=output_count,
            )
        )

    async def _query_vector(self, text: str, diagnostics: RetrievalDiagnostics) -> RAGResult:
        """Original vector-only retrieval path."""
        vector_start = perf_counter()
        query_embedding = await self._embedder.embed(text)
        results = await self._memory.search(query_embedding, top_k=self._top_k)
        self._add_stage_diagnostic(
            diagnostics, "vector-search", vector_start, output_count=len(results)
        )

        filter_start = perf_counter()
        relevant = [r for r in results if r.score >= self._threshold]
        self._add_stage_diagnostic(
            diagnostics,
            "threshold-filter",
            filter_start,
            input_count=len(results),
            output_count=len(relevant),
        )
        if not relevant:
            return RAGResult(augmented_prompt=text, sources=[])

        source_start = perf_counter()
        sources = [
            RAGSource(
                text=r.text,
                score=r.score,
                metadata=r.metadata,
                retrieval_method="vector",
            )
            for r in relevant
        ]
        self._add_stage_diagnostic(
            diagnostics,
            "source-map",
            source_start,
            input_count=len(relevant),
            output_count=len(sources),
        )
        prompt_start = perf_counter()
        augmented_prompt = self._format_prompt(text, sources)
        self._add_stage_diagnostic(
            diagnostics, "prompt-assembly", prompt_start, input_count=len(sources), output_count=1
        )
        return RAGResult(
            augmented_prompt=augmented_prompt,
            sources=sources,
        )

    # ── Hybrid retrieval ─────────────────────────────────────────────

    async def _query_hybrid(self, text: str, diagnostics: RetrievalDiagnostics) -> RAGResult:
        """Hybrid BM25 + vector retrieval path."""
        assert self._hybrid is not None
        search_start = perf_counter()
        results = await self._hybrid.search(text, top_k=self._top_k)
        self._add_stage_diagnostic(
            diagnostics, "hybrid-search", search_start, output_count=len(results)
        )

        if not results:
            return RAGResult(augmented_prompt=text, sources=[])

        source_start = perf_counter()
        sources = [
            RAGSource(
                text=r.text,
                score=r.score,
                metadata=r.metadata,
                retrieval_method="hybrid",
            )
            for r in results
        ]
        self._add_stage_diagnostic(
            diagnostics,
            "source-map",
            source_start,
            input_count=len(results),
            output_count=len(sources),
        )
        prompt_start = perf_counter()
        augmented_prompt = self._format_prompt(text, sources)
        self._add_stage_diagnostic(
            diagnostics, "prompt-assembly", prompt_start, input_count=len(sources), output_count=1
        )
        return RAGResult(
            augmented_prompt=augmented_prompt,
            sources=sources,
        )

    # ── Prompt formatting ────────────────────────────────────────────

    _PROMPT_DELIMITERS = ("---Context---", "---End Context---")

    @staticmethod
    def _sanitize_for_prompt(text: str) -> str:
        """Strip prompt delimiter strings to prevent injection attacks."""
        for delimiter in RAGPipeline._PROMPT_DELIMITERS:
            text = text.replace(delimiter, "")
        return text

    def _format_prompt(self, question: str, sources: list[RAGSource]) -> str:
        """Build the augmented prompt with context block.

        Applies secret redaction to retrieved source texts before they
        enter the augmented prompt (Phase 52 gap-close).
        """
        clean_question = RAGPipeline._sanitize_for_prompt(question)
        context_parts: list[str] = []
        for i, src in enumerate(sources, 1):
            sanitized = RAGPipeline._sanitize_for_prompt(src.text)
            safe_text = redact_secrets(sanitized, enabled=self._redact_enabled)
            context_parts.append(f"[Source {i}] {safe_text}")

        context_block = "\n\n".join(context_parts)
        return (
            f"Use the following context to answer the question.\n\n"
            f"---Context---\n{context_block}\n---End Context---\n\n"
            f"Question: {clean_question}"
        )
