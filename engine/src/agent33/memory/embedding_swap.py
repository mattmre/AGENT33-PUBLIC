"""Embedding model hot-swap with validation, rollback, and audit history.

Allows runtime switching of the active embedding model without restart.
Validates model compatibility before swap, tracks swap history for audit,
and triggers cache invalidation on model change.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.memory.cache import EmbeddingCache
    from agent33.memory.embeddings import EmbeddingProvider

logger = structlog.get_logger()


class SwapStatus(StrEnum):
    """Status of an embedding model swap operation."""

    PENDING = "pending"
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class EmbeddingModelInfo(BaseModel):
    """Metadata describing an available embedding model."""

    model_id: str = Field(description="Unique identifier for this model")
    provider: str = Field(description="Provider name (e.g., 'ollama', 'jina', 'openai')")
    dimensions: int = Field(description="Embedding vector dimension count", gt=0)
    max_tokens: int = Field(
        default=8192,
        description="Maximum input token length supported by the model",
    )
    version: str = Field(default="1.0", description="Model version string")
    description: str = Field(default="", description="Human-readable model description")


class SwapRecord(BaseModel):
    """Audit record of a single swap operation."""

    swap_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    from_model: str = Field(description="Source model ID before swap")
    to_model: str = Field(description="Target model ID after swap")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    initiated_by: str = Field(description="Who initiated the swap")
    status: SwapStatus = Field(default=SwapStatus.PENDING)
    duration_ms: float = Field(default=0.0, description="Swap duration in milliseconds")
    error: str = Field(default="", description="Error message if swap failed")


class EmbeddingSwapManager:
    """Manages runtime embedding model hot-swap with thread-safe state.

    Parameters
    ----------
    current_model:
        The model info describing the currently active embedding model.
    max_history:
        Maximum number of swap records to retain in the audit history.
    """

    def __init__(
        self,
        current_model: EmbeddingModelInfo,
        max_history: int = 100,
    ) -> None:
        self._current_model = current_model
        self._models: dict[str, EmbeddingModelInfo] = {current_model.model_id: current_model}
        self._history: deque[SwapRecord] = deque(maxlen=max(1, max_history))
        self._lock = asyncio.Lock()
        self._swap_count: int = 0
        self._rollback_count: int = 0
        self._failed_count: int = 0
        self._embedding_cache: EmbeddingCache | None = None
        self._embedding_provider: EmbeddingProvider | None = None
        self._started_at = datetime.now(UTC)

    # -- Cache / provider wiring -------------------------------------------

    def set_embedding_cache(self, cache: EmbeddingCache | None) -> None:
        """Wire the embedding cache for invalidation on swap."""
        self._embedding_cache = cache

    def set_embedding_provider(self, provider: EmbeddingProvider | None) -> None:
        """Wire the embedding provider for model switching."""
        self._embedding_provider = provider

    async def _invalidate_cache(self) -> None:
        """Clear the embedding cache, acquiring its internal lock if present.

        This prevents races between cache invalidation during a swap and
        in-flight ``embed()`` calls that hold the cache lock.
        """
        if self._embedding_cache is None:
            return
        cache_lock = getattr(self._embedding_cache, "_lock", None)
        if cache_lock is not None:
            async with cache_lock:
                self._embedding_cache.clear()
        else:
            self._embedding_cache.clear()

    # -- Read operations (no lock needed for atomicity) --------------------

    def get_current_model(self) -> EmbeddingModelInfo:
        """Return the currently active embedding model info."""
        return self._current_model

    def list_available_models(self) -> list[EmbeddingModelInfo]:
        """Return all registered embedding models sorted by model_id."""
        return sorted(self._models.values(), key=lambda m: m.model_id)

    def get_model(self, model_id: str) -> EmbeddingModelInfo | None:
        """Look up a registered model by its ID."""
        return self._models.get(model_id)

    def get_swap_history(self, limit: int = 50) -> list[SwapRecord]:
        """Return swap history, most recent first, limited to *limit* entries."""
        entries = list(self._history)
        entries.reverse()
        return entries[:limit]

    def get_current_stats(self) -> dict[str, Any]:
        """Return usage statistics for the swap manager."""
        return {
            "current_model": self._current_model.model_id,
            "current_provider": self._current_model.provider,
            "current_dimensions": self._current_model.dimensions,
            "registered_models": len(self._models),
            "total_swaps": self._swap_count,
            "total_rollbacks": self._rollback_count,
            "total_failures": self._failed_count,
            "history_size": len(self._history),
            "cache_size": self._embedding_cache.size if self._embedding_cache else 0,
            "cache_hit_rate": self._embedding_cache.hit_rate if self._embedding_cache else 0.0,
            "uptime_since": self._started_at.isoformat(),
        }

    # -- Write operations (locked) -----------------------------------------

    async def register_model(self, model_info: EmbeddingModelInfo) -> None:
        """Register a model as available for swapping.

        If a model with the same ``model_id`` already exists, it is replaced.
        """
        async with self._lock:
            self._models[model_info.model_id] = model_info
            logger.info(
                "embedding_model_registered",
                model_id=model_info.model_id,
                provider=model_info.provider,
                dimensions=model_info.dimensions,
            )

    async def validate_swap(self, target_model_id: str) -> tuple[bool, str]:
        """Validate whether swapping to *target_model_id* is safe.

        Returns a tuple of (is_valid, message). Dimension mismatches produce
        a warning but do not block the swap (the caller decides). Unknown
        models are rejected.
        """
        if target_model_id not in self._models:
            return False, f"Model '{target_model_id}' is not registered"

        if target_model_id == self._current_model.model_id:
            return False, f"Model '{target_model_id}' is already the active model"

        target = self._models[target_model_id]

        if target.dimensions != self._current_model.dimensions:
            return True, (
                f"Dimension mismatch: current={self._current_model.dimensions}, "
                f"target={target.dimensions}. Existing embeddings in storage will "
                f"be incompatible and must be re-indexed."
            )

        return True, "Swap is compatible"

    async def execute_swap(
        self,
        target_model_id: str,
        initiated_by: str,
    ) -> SwapRecord:
        """Execute an embedding model swap to *target_model_id*.

        The swap creates a record, updates internal state, invalidates the
        embedding cache, and updates the underlying provider model reference.

        Raises
        ------
        ValueError
            If the target model is not registered or is already active.
        """
        async with self._lock:
            if target_model_id not in self._models:
                raise ValueError(f"Model '{target_model_id}' is not registered")

            if target_model_id == self._current_model.model_id:
                raise ValueError(f"Model '{target_model_id}' is already active")

            target = self._models[target_model_id]
            from_model_id = self._current_model.model_id

            record = SwapRecord(
                from_model=from_model_id,
                to_model=target_model_id,
                initiated_by=initiated_by,
                status=SwapStatus.PENDING,
            )

            previous_model = self._current_model
            start = time.monotonic()
            try:
                # Update provider model name if wired
                if self._embedding_provider is not None:
                    self._embedding_provider._model = target.model_id

                # Invalidate cache -- all cached embeddings are from old model
                await self._invalidate_cache()

                # Only update current model after all side effects succeed
                self._current_model = target

                elapsed_ms = (time.monotonic() - start) * 1000
                record.status = SwapStatus.COMPLETED
                record.duration_ms = elapsed_ms
                self._swap_count += 1

                logger.info(
                    "embedding_model_swapped",
                    from_model=from_model_id,
                    to_model=target_model_id,
                    initiated_by=initiated_by,
                    duration_ms=elapsed_ms,
                    dimension_change=(previous_model.dimensions != target.dimensions),
                )
            except Exception as exc:
                # Revert to previous model on failure
                self._current_model = previous_model
                if self._embedding_provider is not None:
                    self._embedding_provider._model = previous_model.model_id

                elapsed_ms = (time.monotonic() - start) * 1000
                record.status = SwapStatus.FAILED
                record.duration_ms = elapsed_ms
                record.error = str(exc)
                self._failed_count += 1
                logger.error(
                    "embedding_model_swap_failed",
                    from_model=from_model_id,
                    to_model=target_model_id,
                    error=str(exc),
                )

            self._history.append(record)
            return record

    async def rollback_last_swap(self) -> SwapRecord | None:
        """Rollback the last completed swap, reverting to the previous model.

        Returns the rollback swap record, or ``None`` if there is nothing to
        roll back (no history, or last swap was already rolled back / failed).
        """
        async with self._lock:
            # Find the most recent completed swap
            last_completed: SwapRecord | None = None
            for record in reversed(self._history):
                if record.status == SwapStatus.COMPLETED:
                    last_completed = record
                    break

            if last_completed is None:
                return None

            # The model to rollback to is the from_model of the last completed swap
            rollback_model_id = last_completed.from_model
            if rollback_model_id not in self._models:
                logger.warning(
                    "rollback_model_not_found",
                    model_id=rollback_model_id,
                )
                return None

            rollback_target = self._models[rollback_model_id]
            from_model_id = self._current_model.model_id

            rollback_record = SwapRecord(
                from_model=from_model_id,
                to_model=rollback_model_id,
                initiated_by="system:rollback",
                status=SwapStatus.PENDING,
            )

            previous_model = self._current_model
            start = time.monotonic()
            try:
                if self._embedding_provider is not None:
                    self._embedding_provider._model = rollback_target.model_id

                await self._invalidate_cache()

                # Only update current model after all side effects succeed
                self._current_model = rollback_target

                elapsed_ms = (time.monotonic() - start) * 1000
                rollback_record.status = SwapStatus.ROLLED_BACK
                rollback_record.duration_ms = elapsed_ms
                self._rollback_count += 1

                # Mark the original swap as rolled back
                last_completed.status = SwapStatus.ROLLED_BACK

                logger.info(
                    "embedding_model_rolled_back",
                    from_model=from_model_id,
                    to_model=rollback_model_id,
                    duration_ms=elapsed_ms,
                )
            except Exception as exc:
                # Revert to previous model on failure
                self._current_model = previous_model
                if self._embedding_provider is not None:
                    self._embedding_provider._model = previous_model.model_id

                elapsed_ms = (time.monotonic() - start) * 1000
                rollback_record.status = SwapStatus.FAILED
                rollback_record.duration_ms = elapsed_ms
                rollback_record.error = str(exc)
                self._failed_count += 1
                logger.error(
                    "embedding_model_rollback_failed",
                    from_model=from_model_id,
                    to_model=rollback_model_id,
                    error=str(exc),
                )

            self._history.append(rollback_record)
            return rollback_record
