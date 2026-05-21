"""Context slot abstraction with priority-based budget assembly (Track 8).

Manages named slots that contribute content to the context window.  Each
slot carries a priority level and a token cost.  The ``ContextSlotManager``
assembles slots within a given token budget, filling highest-priority slots
first.
"""

from __future__ import annotations

import logging
import math
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SlotPriority(StrEnum):
    """Priority classification for context slots."""

    REQUIRED = "required"
    PREFERRED = "preferred"
    OPTIONAL = "optional"


# Numeric weights for sorting (higher = filled first)
_PRIORITY_WEIGHT: dict[SlotPriority, int] = {
    SlotPriority.REQUIRED: 300,
    SlotPriority.PREFERRED: 200,
    SlotPriority.OPTIONAL: 100,
}


class ContextSlot(BaseModel):
    """A named slot in the assembled context window."""

    name: str
    content: str = ""
    token_count: int = 0
    priority: SlotPriority = SlotPriority.OPTIONAL
    max_tokens: int = 0
    source: str = ""  # system | user | tool | memory

    def effective_tokens(self) -> int:
        """Return the token cost for this slot.

        If ``token_count`` is explicitly set, use that.  Otherwise estimate
        from ``content`` length using a word-based heuristic.
        """
        if self.token_count > 0:
            return self.token_count
        if self.content:
            return max(1, math.ceil(len(self.content.split()) * 1.3))
        return 0


class AssembledContext(BaseModel):
    """Result of a budget-aware assembly pass."""

    included: list[ContextSlot] = Field(default_factory=list)
    excluded: list[ContextSlot] = Field(default_factory=list)
    total_tokens: int = 0
    budget: int = 0
    budget_remaining: int = 0


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class ContextSlotManager:
    """Manages named context slots per session.

    Slots are stored per ``session_id``.  The manager supports register,
    update, evict, list, and budget-aware assembly.
    """

    def __init__(self) -> None:
        # session_id -> {slot_name -> ContextSlot}
        self._slots: dict[str, dict[str, ContextSlot]] = {}

    # -- Lifecycle ----------------------------------------------------------

    def register(self, session_id: str, slot: ContextSlot) -> None:
        """Register a new slot for a session.

        If a slot with the same name already exists for the session, it is
        overwritten (i.e., an upsert).
        """
        session_slots = self._slots.setdefault(session_id, {})
        session_slots[slot.name] = slot
        logger.debug(
            "context_slot_registered session=%s slot=%s priority=%s",
            session_id,
            slot.name,
            slot.priority,
        )

    def update(
        self,
        session_id: str,
        name: str,
        *,
        content: str | None = None,
        token_count: int | None = None,
        priority: SlotPriority | None = None,
        max_tokens: int | None = None,
        source: str | None = None,
    ) -> ContextSlot:
        """Update fields on an existing slot.

        Only provided (non-None) fields are changed.

        Raises:
            KeyError: If the session or slot does not exist.
        """
        slot = self._get_slot(session_id, name)
        if content is not None:
            slot.content = content
        if token_count is not None:
            slot.token_count = token_count
        if priority is not None:
            slot.priority = priority
        if max_tokens is not None:
            slot.max_tokens = max_tokens
        if source is not None:
            slot.source = source
        return slot

    def evict(self, session_id: str, name: str) -> ContextSlot:
        """Remove a slot from a session and return it.

        Raises:
            KeyError: If the session or slot does not exist.
        """
        session_slots = self._slots.get(session_id)
        if session_slots is None or name not in session_slots:
            raise KeyError(f"Slot '{name}' not found for session '{session_id}'")
        slot = session_slots.pop(name)
        logger.debug("context_slot_evicted session=%s slot=%s", session_id, name)
        return slot

    def list_slots(self, session_id: str) -> list[ContextSlot]:
        """Return all registered slots for a session, sorted by priority weight descending."""
        session_slots = self._slots.get(session_id, {})
        slots = list(session_slots.values())
        slots.sort(key=lambda s: _PRIORITY_WEIGHT.get(s.priority, 0), reverse=True)
        return slots

    def get_slot(self, session_id: str, name: str) -> ContextSlot:
        """Retrieve a single slot by session and name.

        Raises:
            KeyError: If the session or slot does not exist.
        """
        return self._get_slot(session_id, name)

    # -- Budget-aware assembly ----------------------------------------------

    def assemble(self, session_id: str, budget: int) -> AssembledContext:
        """Assemble slots for a session within *budget* tokens.

        Slots are filled in priority order (required first, then preferred,
        then optional).  Within the same priority tier, slots are filled in
        registration order.  A slot is only included if its effective token
        cost fits within the remaining budget.  If a slot has ``max_tokens``
        set and its content exceeds that limit, only ``max_tokens`` is
        charged.

        Returns an ``AssembledContext`` with included/excluded lists and
        budget accounting.
        """
        slots = self.list_slots(session_id)  # already sorted by priority
        included: list[ContextSlot] = []
        excluded: list[ContextSlot] = []
        remaining = budget

        for slot in slots:
            cost = slot.effective_tokens()
            # Enforce per-slot cap if set
            if slot.max_tokens > 0:
                cost = min(cost, slot.max_tokens)

            if cost <= remaining:
                included.append(slot)
                remaining -= cost
            else:
                excluded.append(slot)

        total_tokens = budget - remaining
        return AssembledContext(
            included=included,
            excluded=excluded,
            total_tokens=total_tokens,
            budget=budget,
            budget_remaining=remaining,
        )

    # -- Helpers ------------------------------------------------------------

    def clear_session(self, session_id: str) -> None:
        """Remove all slots for a session."""
        self._slots.pop(session_id, None)

    def session_token_total(self, session_id: str) -> int:
        """Return the sum of effective tokens across all slots for a session."""
        return sum(s.effective_tokens() for s in self.list_slots(session_id))

    def to_summary(self, session_id: str) -> dict[str, Any]:
        """Return a JSON-serialisable summary of slots for a session."""
        slots = self.list_slots(session_id)
        return {
            "session_id": session_id,
            "slot_count": len(slots),
            "total_tokens": sum(s.effective_tokens() for s in slots),
            "slots": [s.model_dump() for s in slots],
        }

    def _get_slot(self, session_id: str, name: str) -> ContextSlot:
        session_slots = self._slots.get(session_id)
        if session_slots is None or name not in session_slots:
            raise KeyError(f"Slot '{name}' not found for session '{session_id}'")
        return session_slots[name]
