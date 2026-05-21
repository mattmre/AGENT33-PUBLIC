"""Context engine: protocol and builtin implementation."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from agent33.context.models import (
    CompactionEvent,
    ContextAssemblyReport,
    ContextSlot,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ContextEngine(Protocol):
    """Pluggable context engine interface.

    Implementations assemble context windows for agent sessions and
    compact them when budget limits are reached.
    """

    engine_id: str

    async def assemble(self, session_id: str) -> ContextAssemblyReport:
        """Assemble the context window for a session."""
        ...

    async def compact(self, session_id: str) -> CompactionEvent:
        """Compact the context window for a session."""
        ...

    def health(self) -> dict[str, Any]:
        """Return engine health status."""
        ...


# ---------------------------------------------------------------------------
# Builtin implementation
# ---------------------------------------------------------------------------


class BuiltinContextEngine:
    """Default context engine with basic slot assembly and pass-through compaction."""

    engine_id: str = "builtin"

    async def assemble(self, session_id: str) -> ContextAssemblyReport:
        """Assemble a context window with default slots.

        The builtin engine provides a simple three-slot layout:
        system prompt, conversation history, and tool results.
        """
        now = datetime.now(UTC)
        slots = [
            ContextSlot(
                name="system_prompt",
                priority=100,
                token_budget=500,
                source="builtin",
                content_hash=hashlib.sha256(f"{session_id}:system_prompt".encode()).hexdigest()[
                    :16
                ],
            ),
            ContextSlot(
                name="conversation_history",
                priority=80,
                token_budget=3000,
                source="builtin",
                content_hash=hashlib.sha256(
                    f"{session_id}:history:{now.isoformat()}".encode()
                ).hexdigest()[:16],
            ),
            ContextSlot(
                name="tool_results",
                priority=60,
                token_budget=1500,
                source="builtin",
                content_hash=hashlib.sha256(
                    f"{session_id}:tools:{now.isoformat()}".encode()
                ).hexdigest()[:16],
            ),
        ]
        total_tokens = sum(s.token_budget for s in slots)

        return ContextAssemblyReport(
            session_id=session_id,
            timestamp=now,
            slots_filled=slots,
            total_tokens=total_tokens,
            compaction_triggered=False,
            engine_id=self.engine_id,
        )

    async def compact(self, session_id: str) -> CompactionEvent:
        """Perform a no-op compaction (builtin does not compact).

        Returns a successful compaction event with unchanged token counts.
        """
        now = datetime.now(UTC)
        return CompactionEvent(
            session_id=session_id,
            timestamp=now,
            tokens_before=5000,
            tokens_after=5000,
            strategy="noop",
            success=True,
        )

    def health(self) -> dict[str, Any]:
        """Return builtin engine health."""
        return {
            "engine_id": self.engine_id,
            "status": "healthy",
            "type": "builtin",
        }
