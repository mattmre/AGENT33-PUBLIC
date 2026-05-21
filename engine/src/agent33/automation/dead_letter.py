"""Dead-letter queue for failed trigger executions."""

from __future__ import annotations

import dataclasses
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent33.observability.metrics import MetricsCollector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level metrics collector (wired during app lifespan)
# ---------------------------------------------------------------------------
_metrics: MetricsCollector | None = None


def set_metrics(collector: MetricsCollector) -> None:
    """Install the global metrics collector (called during app lifespan init)."""
    global _metrics  # noqa: PLW0603
    _metrics = collector


@dataclasses.dataclass(slots=True)
class DeadLetterItem:
    """A captured failure from a trigger execution."""

    item_id: str
    trigger_name: str
    payload: dict[str, Any]
    error: str
    captured_at: float
    retried: bool = False


class DeadLetterQueue:
    """In-memory store for failed trigger executions.

    Captures failures so they can be inspected, retried, or purged.
    """

    def __init__(self) -> None:
        self._items: dict[str, DeadLetterItem] = {}

    def capture(
        self,
        trigger_name: str,
        payload: dict[str, Any],
        error: str | Exception,
    ) -> str:
        """Record a failed trigger execution.

        Parameters
        ----------
        trigger_name:
            Name or identifier of the trigger that failed.
        payload:
            The input payload that caused the failure.
        error:
            Error message or exception.

        Returns
        -------
        str:
            The generated item ID.
        """
        item_id = str(uuid.uuid4())
        error_str = str(error)
        self._items[item_id] = DeadLetterItem(
            item_id=item_id,
            trigger_name=trigger_name,
            payload=payload,
            error=error_str,
            captured_at=time.time(),
        )
        logger.warning(
            "Dead-letter captured for trigger %s: %s (id=%s)",
            trigger_name,
            error_str,
            item_id,
        )

        # -- Emit metrics ----------------------------------------------------
        collector = _metrics
        if collector is not None:
            collector.increment("dead_letter_queue_captures_total", {})
            collector.observe("dead_letter_queue_depth", float(len(self._items)), {})

        return item_id

    def list_failed(self, limit: int = 100) -> list[DeadLetterItem]:
        """Return the most recent failed items, newest first.

        Parameters
        ----------
        limit:
            Maximum number of items to return.
        """
        items = sorted(self._items.values(), key=lambda i: i.captured_at, reverse=True)
        return items[:limit]

    def retry(self, item_id: str) -> DeadLetterItem:
        """Mark an item as retried and return it for reprocessing.

        The caller is responsible for actually re-executing the trigger.

        Raises
        ------
        KeyError:
            If the item ID is not found.
        """
        item = self._items.get(item_id)
        if item is None:
            raise KeyError(f"Dead-letter item not found: {item_id}")
        item.retried = True
        logger.info("Marked dead-letter item %s for retry", item_id)
        return item

    def purge(self, older_than_seconds: float) -> int:
        """Remove items older than the given age.

        Parameters
        ----------
        older_than_seconds:
            Items captured more than this many seconds ago will be removed.

        Returns
        -------
        int:
            Number of items purged.
        """
        cutoff = time.time() - older_than_seconds
        to_remove = [item_id for item_id, item in self._items.items() if item.captured_at < cutoff]
        for item_id in to_remove:
            del self._items[item_id]
        if to_remove:
            logger.info(
                "Purged %d dead-letter items older than %ss",
                len(to_remove),
                older_than_seconds,
            )
        return len(to_remove)
