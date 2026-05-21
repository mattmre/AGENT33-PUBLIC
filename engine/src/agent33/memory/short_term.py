"""Short-term conversation memory with token counting."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent33.agents.tokenizer import TokenCounter
    from agent33.memory.context_compressor import ContextCompressor


@dataclass
class Message:
    """A single conversation message."""

    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


def _estimate_tokens(text: str) -> int:
    """Estimate token count using word-based heuristic (words * 1.3)."""
    words = len(text.split())
    return math.ceil(words * 1.3)


@dataclass
class ShortTermMemory:
    """Maintains conversation history with token-aware trimming."""

    messages: list[Message] = field(default_factory=list)
    token_counter: TokenCounter | None = field(default=None, repr=False)
    compressor: ContextCompressor | None = field(default=None, repr=False)
    compression_count: int = 0

    def _count_tokens(self, text: str) -> int:
        """Count tokens using the configured counter, or the legacy heuristic."""
        if self.token_counter is not None:
            return self.token_counter.count(text)
        return _estimate_tokens(text)

    def add(self, role: str, content: str) -> None:
        """Append a message to the conversation history."""
        self.messages.append(Message(role=role, content=content))

    def token_count(self) -> int:
        """Return estimated total token count across all messages."""
        return sum(self._count_tokens(m.content) for m in self.messages)

    def get_context(self, max_tokens: int) -> list[dict[str, str]]:
        """Return messages fitting within *max_tokens*, trimming oldest first."""
        result: list[Message] = []
        running = 0
        # Walk from newest to oldest so we keep recent context.
        for msg in reversed(self.messages):
            cost = self._count_tokens(msg.content)
            if running + cost > max_tokens:
                break
            result.append(msg)
            running += cost
        # Restore chronological order.
        result.reverse()
        return [m.to_dict() for m in result]

    def clear(self) -> None:
        """Remove all messages."""
        self.messages.clear()
