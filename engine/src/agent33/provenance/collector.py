"""In-memory provenance receipt collector with bounded storage."""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from agent33.provenance.models import ProvenanceReceipt, ProvenanceSource

logger = logging.getLogger(__name__)


class ProvenanceCollector:
    """Thread-safe in-memory store for provenance receipts.

    Receipts are stored in insertion order.  When *max_receipts* is reached,
    the oldest receipt is evicted (FIFO).
    """

    def __init__(self, max_receipts: int = 10000) -> None:
        self._max_receipts = max_receipts
        self._receipts: deque[ProvenanceReceipt] = deque(maxlen=max_receipts)
        self._index: dict[str, ProvenanceReceipt] = {}
        self._lock = threading.Lock()

    # -- Mutations -------------------------------------------------------------

    def record(self, receipt: ProvenanceReceipt) -> None:
        """Append a receipt, evicting the oldest if capacity is reached."""
        with self._lock:
            if len(self._receipts) == self._max_receipts:
                evicted = self._receipts[0]
                self._index.pop(evicted.receipt_id, None)
            self._receipts.append(receipt)
            self._index[receipt.receipt_id] = receipt
        logger.debug(
            "provenance_receipt_recorded",
            extra={"receipt_id": receipt.receipt_id, "source": receipt.source},
        )

    # -- Queries ---------------------------------------------------------------

    def get(self, receipt_id: str) -> ProvenanceReceipt | None:
        """Return a receipt by its ID, or ``None``."""
        with self._lock:
            return self._index.get(receipt_id)

    def query(
        self,
        *,
        source: ProvenanceSource | None = None,
        session_id: str = "",
        tenant_id: str = "",
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ProvenanceReceipt]:
        """Filter receipts by optional criteria.  Newest first."""
        with self._lock:
            results: list[ProvenanceReceipt] = []
            for receipt in reversed(self._receipts):
                if source is not None and receipt.source != source:
                    continue
                if session_id and receipt.session_id != session_id:
                    continue
                if tenant_id and receipt.tenant_id != tenant_id:
                    continue
                if since is not None and receipt.timestamp < since:
                    continue
                results.append(receipt)
                if len(results) >= limit:
                    break
            return results

    def build_chain(self, receipt_id: str) -> list[ProvenanceReceipt]:
        """Follow ``parent_receipt_id`` links to build a provenance chain.

        Returns the chain from the given receipt back to the root (no parent).
        Stops if a cycle is detected or a parent is missing.
        """
        with self._lock:
            chain: list[ProvenanceReceipt] = []
            seen: set[str] = set()
            current_id = receipt_id
            while current_id:
                if current_id in seen:
                    # Cycle detected -- stop without infinite loop.
                    break
                seen.add(current_id)
                receipt = self._index.get(current_id)
                if receipt is None:
                    break
                chain.append(receipt)
                current_id = receipt.parent_receipt_id
            return chain

    @property
    def count(self) -> int:
        """Number of receipts currently stored."""
        with self._lock:
            return len(self._receipts)
