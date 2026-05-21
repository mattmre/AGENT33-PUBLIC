"""Extended provenance receipt store with SHA-256 tamper-evidence hashing.

Builds on the core :class:`~agent33.provenance.collector.ProvenanceCollector`
and :class:`~agent33.provenance.models.ProvenanceReceipt`, adding:

* ``inputs_hash`` / ``outputs_hash`` — SHA-256 digests of JSON-serialised
  inputs and outputs for tamper evidence.
* ``entity_type`` / ``entity_id`` — typed entity references for richer
  querying (agent_action, tool_call, workflow_step, data_access).
* ``ReceiptStore`` — thin facade around :class:`ProvenanceCollector` that
  handles hash computation and entity-based queries.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.services.orchestration_state import OrchestrationStateStore

logger = logging.getLogger(__name__)

_NAMESPACE = "provenance_receipts"


# ---------------------------------------------------------------------------
# Entity type enum
# ---------------------------------------------------------------------------


class EntityType(StrEnum):
    """Categories of tracked entities for provenance receipts."""

    AGENT_ACTION = "agent_action"
    TOOL_CALL = "tool_call"
    WORKFLOW_STEP = "workflow_step"
    DATA_ACCESS = "data_access"


# ---------------------------------------------------------------------------
# Extended receipt model
# ---------------------------------------------------------------------------


class HashedReceipt(BaseModel):
    """Provenance receipt with SHA-256 hash fields for tamper evidence.

    Compatible with the base :class:`ProvenanceReceipt` but adds entity
    typing and cryptographic hash fields.
    """

    receipt_id: str = Field(default_factory=lambda: uuid4().hex)
    entity_type: EntityType
    entity_id: str = ""
    tenant_id: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actor: str = ""
    action: str = ""
    inputs_hash: str = ""
    outputs_hash: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    parent_receipt_id: str = ""
    session_id: str = ""


# ---------------------------------------------------------------------------
# Hash helper
# ---------------------------------------------------------------------------


def compute_hash(data: Any) -> str:
    """Compute SHA-256 hex digest of JSON-serialised *data*.

    Returns an empty string when *data* is ``None`` or empty.
    """
    if data is None:
        return ""
    if isinstance(data, dict) and not data:
        return ""
    if isinstance(data, (list, tuple)) and not data:
        return ""
    try:
        serialised = json.dumps(data, sort_keys=True, default=str)
    except (TypeError, ValueError):
        serialised = str(data)
    return hashlib.sha256(serialised.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Receipt store
# ---------------------------------------------------------------------------


class ReceiptStore:
    """Thread-safe in-memory store for :class:`HashedReceipt` instances.

    Provides entity-based and session-based queries plus chain traversal.
    """

    def __init__(
        self,
        max_receipts: int = 10_000,
        state_store: OrchestrationStateStore | None = None,
    ) -> None:
        self._max_receipts = max_receipts
        self._receipts: list[HashedReceipt] = []
        self._index: dict[str, HashedReceipt] = {}
        self._lock = threading.Lock()
        self._state_store = state_store
        if state_store is None:
            logger.warning(
                "receipt_store_no_state_store: receipts will not persist across restarts"
            )
        self._load_state()

    def _persist_state(self, snapshot: list[HashedReceipt]) -> None:
        """Write *snapshot* to the state store. Caller must hold no lock during I/O."""
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            _NAMESPACE,
            {"receipts": [r.model_dump(mode="json") for r in snapshot]},
        )

    def _load_state(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace(_NAMESPACE)
        for item in payload.get("receipts", []):
            if not isinstance(item, dict):
                continue
            # Stop loading once capacity is reached (avoids temporary OOM spike).
            if len(self._receipts) >= self._max_receipts:
                break
            try:
                receipt = HashedReceipt.model_validate(item)
                self._receipts.append(receipt)
                self._index[receipt.receipt_id] = receipt
            except Exception as exc:
                logger.warning("receipt_restore_failed: %s", exc)

    # -- Mutations -----------------------------------------------------------

    def record(self, receipt: HashedReceipt) -> None:
        """Store a receipt, evicting the oldest if capacity is reached."""
        with self._lock:
            if len(self._receipts) >= self._max_receipts:
                evicted = self._receipts.pop(0)
                self._index.pop(evicted.receipt_id, None)
            self._receipts.append(receipt)
            self._index[receipt.receipt_id] = receipt
            snapshot = list(self._receipts)
        # Persist after releasing the lock; use the snapshot taken under the lock.
        self._persist_state(snapshot)
        logger.debug(
            "hashed_receipt_recorded",
            extra={
                "receipt_id": receipt.receipt_id,
                "entity_type": receipt.entity_type,
            },
        )

    # -- Queries -------------------------------------------------------------

    def get(self, receipt_id: str) -> HashedReceipt | None:
        """Return a receipt by its ID, or ``None``."""
        with self._lock:
            return self._index.get(receipt_id)

    def list_by_entity(
        self,
        entity_type: EntityType,
        entity_id: str,
        *,
        limit: int = 100,
    ) -> list[HashedReceipt]:
        """Return receipts matching *entity_type* and *entity_id* (newest first)."""
        with self._lock:
            results: list[HashedReceipt] = []
            for receipt in reversed(self._receipts):
                if receipt.entity_type == entity_type and receipt.entity_id == entity_id:
                    results.append(receipt)
                    if len(results) >= limit:
                        break
            return results

    def list_by_session(
        self,
        session_id: str,
        *,
        limit: int = 100,
    ) -> list[HashedReceipt]:
        """Return all receipts in a session (newest first)."""
        with self._lock:
            results: list[HashedReceipt] = []
            for receipt in reversed(self._receipts):
                if receipt.session_id == session_id:
                    results.append(receipt)
                    if len(results) >= limit:
                        break
            return results

    def list_all(
        self,
        *,
        entity_type: EntityType | None = None,
        actor: str = "",
        session_id: str = "",
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[HashedReceipt]:
        """Filter receipts by optional criteria.  Newest first."""
        with self._lock:
            results: list[HashedReceipt] = []
            for receipt in reversed(self._receipts):
                if entity_type is not None and receipt.entity_type != entity_type:
                    continue
                if actor and receipt.actor != actor:
                    continue
                if session_id and receipt.session_id != session_id:
                    continue
                if since is not None and receipt.timestamp < since:
                    continue
                if until is not None and receipt.timestamp > until:
                    continue
                results.append(receipt)
                if len(results) >= limit:
                    break
            return results

    def get_chain(self, receipt_id: str) -> list[HashedReceipt]:
        """Follow ``parent_receipt_id`` links to build a provenance chain.

        Returns the chain from the given receipt back to the root (no parent).
        Stops if a cycle is detected or a parent is missing.
        """
        with self._lock:
            chain: list[HashedReceipt] = []
            seen: set[str] = set()
            current_id = receipt_id
            while current_id:
                if current_id in seen:
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
