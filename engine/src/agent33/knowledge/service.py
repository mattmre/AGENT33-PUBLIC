"""Knowledge ingestion service orchestrating sources, scheduler, and memory writes."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from agent33.knowledge.ingestion import get_adapter
from agent33.knowledge.models import IngestionResult, KnowledgeSource, SourceType
from agent33.knowledge.scheduler import KnowledgeIngestionScheduler

if TYPE_CHECKING:
    from agent33.memory.embeddings import EmbeddingProvider
    from agent33.memory.long_term import LongTermMemory

logger = structlog.get_logger()

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """Generate a URL-safe slug from a source name."""
    return _SLUG_RE.sub("-", name.lower()).strip("-")[:64]


class KnowledgeIngestionService:
    """Orchestrates knowledge source management, scheduling, and ingestion.

    Holds an in-memory registry of :class:`KnowledgeSource` objects. Each
    enabled source is scheduled in the :class:`KnowledgeIngestionScheduler`.
    On each ingestion run the service:

    1. Fetches raw chunks via the appropriate adapter.
    2. Computes a content hash for staleness detection.
    3. If content changed, embeds each chunk and stores in long-term memory.
    4. Records the result in the source's last_ingested_at / last_content_hash.
    """

    def __init__(
        self,
        long_term_memory: LongTermMemory | None,
        embedding_provider: EmbeddingProvider | None,
        default_tenant_id: str = "system",
    ) -> None:
        self._ltm = long_term_memory
        self._embedder = embedding_provider
        self._default_tenant = default_tenant_id
        self._sources: dict[str, KnowledgeSource] = {}
        self._results: dict[str, IngestionResult] = {}
        self._scheduler = KnowledgeIngestionScheduler(on_ingest=self.ingest_source)

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Start the background scheduler."""
        self._scheduler.start()

    def stop(self) -> None:
        """Stop the background scheduler."""
        self._scheduler.stop()

    # -- source management ---------------------------------------------------

    def add_source(
        self,
        name: str,
        source_type: str | SourceType,
        url: str | None = None,
        local_path: str | None = None,
        cron_expression: str = "0 */6 * * *",
        enabled: bool = True,
        tenant_id: str | None = None,
    ) -> KnowledgeSource:
        """Register a new knowledge source.

        Returns the created :class:`KnowledgeSource`.
        """
        source_id = _slugify(name)
        # Ensure uniqueness by appending counter if needed
        base_id = source_id
        counter = 1
        while source_id in self._sources:
            source_id = f"{base_id}-{counter}"
            counter += 1

        source = KnowledgeSource(
            id=source_id,
            name=name,
            source_type=SourceType(source_type),
            url=url,
            local_path=local_path,
            cron_expression=cron_expression,
            enabled=enabled,
            tenant_id=tenant_id or self._default_tenant,
        )
        self._sources[source_id] = source

        if enabled:
            self._scheduler.add_source(source_id, cron_expression)

        logger.info(
            "knowledge_source_added",
            source_id=source_id,
            source_type=source_type,
            enabled=enabled,
        )
        return source

    def remove_source(self, source_id: str) -> bool:
        """Remove a knowledge source. Returns True if it existed."""
        if source_id not in self._sources:
            return False
        self._scheduler.remove_source(source_id)
        del self._sources[source_id]
        self._results.pop(source_id, None)
        logger.info("knowledge_source_removed", source_id=source_id)
        return True

    def get_source(self, source_id: str) -> KnowledgeSource | None:
        """Look up a source by ID."""
        return self._sources.get(source_id)

    def list_sources(self) -> list[KnowledgeSource]:
        """Return all registered sources."""
        return list(self._sources.values())

    def get_last_result(self, source_id: str) -> IngestionResult | None:
        """Return the last ingestion result for a source."""
        return self._results.get(source_id)

    # -- ingestion -----------------------------------------------------------

    async def ingest_source(self, source_id: str) -> IngestionResult:
        """Run ingestion for a single source.

        This is called both by the scheduler (on cron) and by the manual
        trigger API endpoint.
        """
        source = self._sources.get(source_id)
        if source is None:
            result = IngestionResult(
                source_id=source_id,
                status="error",
                error=f"Source {source_id!r} not found",
            )
            self._results[source_id] = result
            return result

        try:
            adapter = get_adapter(source.source_type)
            chunks = await adapter.fetch(source)

            if not chunks:
                result = IngestionResult(
                    source_id=source_id,
                    status="skipped",
                    error="No content fetched",
                )
                self._results[source_id] = result
                return result

            # Staleness detection via content hash
            raw_content = "\n".join(chunks)
            content_hash = hashlib.sha256(raw_content.encode()).hexdigest()

            if content_hash == source.last_content_hash:
                result = IngestionResult(
                    source_id=source_id,
                    status="skipped",
                )
                self._results[source_id] = result
                logger.info(
                    "knowledge_ingestion_skipped_stale",
                    source_id=source_id,
                )
                return result

            # Write chunks to long-term memory
            chunks_stored = await self._store_chunks(chunks, source)

            # Update source metadata
            now = datetime.now(UTC)
            source.last_ingested_at = now
            source.last_content_hash = content_hash

            result = IngestionResult(
                source_id=source_id,
                status="success",
                chunks_ingested=chunks_stored,
                ingested_at=now,
            )
            self._results[source_id] = result
            logger.info(
                "knowledge_ingestion_success",
                source_id=source_id,
                chunks=chunks_stored,
            )
            return result

        except Exception as exc:
            result = IngestionResult(
                source_id=source_id,
                status="error",
                error=str(exc),
            )
            self._results[source_id] = result
            logger.warning(
                "knowledge_ingestion_error",
                source_id=source_id,
                error=str(exc),
            )
            return result

    async def _store_chunks(self, chunks: list[str], source: KnowledgeSource) -> int:
        """Embed and store chunks in long-term memory. Returns count stored."""
        if self._ltm is None or self._embedder is None:
            logger.warning(
                "knowledge_store_skipped",
                reason="no LTM or embedder",
                source_id=source.id,
            )
            return 0

        stored = 0
        for chunk in chunks:
            if not chunk.strip():
                continue
            try:
                embedding = await self._embedder.embed(chunk)
                metadata: dict[str, Any] = {
                    "source": f"knowledge:{source.source_type}",
                    "source_id": source.id,
                    "source_name": source.name,
                    "tenant_id": source.tenant_id,
                }
                if source.url:
                    metadata["url"] = source.url
                await self._ltm.store(
                    content=chunk,
                    embedding=embedding,
                    metadata=metadata,
                )
                stored += 1
            except Exception as exc:
                logger.warning(
                    "knowledge_chunk_store_failed",
                    source_id=source.id,
                    error=str(exc),
                )
        return stored
