"""Token counting protocol with heuristic and tiktoken implementations.

Provides a pluggable :class:`TokenCounter` protocol so that any subsystem
needing token estimates (context management, chunking, short-term memory)
can be configured with either the fast heuristic or an accurate tiktoken
encoder at runtime.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class TokenCounter(Protocol):
    """Protocol for token counting implementations."""

    def count(self, text: str) -> int:
        """Return the estimated token count for *text*."""
        ...

    def count_messages(self, messages: list[dict]) -> int:  # type: ignore[type-arg]
        """Return the estimated token count for a list of chat messages."""
        ...

    @property
    def name(self) -> str:
        """Human-readable identifier for this counter implementation."""
        ...


class EstimateTokenCounter:
    """Heuristic-based counter using chars/3.5.  No external deps."""

    def __init__(self, chars_per_token: float = 3.5, message_overhead: int = 4) -> None:
        self._cpt = chars_per_token
        self._overhead = message_overhead

    def count(self, text: str) -> int:
        if not text:
            return 0
        return max(1, int(len(text) / self._cpt))

    def count_messages(self, messages: list[dict]) -> int:  # type: ignore[type-arg]
        total = 0
        for msg in messages:
            total += self._overhead
            for v in msg.values():
                if isinstance(v, str):
                    total += self.count(v)
        return total + 3  # reply priming

    @property
    def name(self) -> str:
        return "estimate"


class TiktokenCounter:
    """Tiktoken-based counter.  Falls back to EstimateTokenCounter if not installed."""

    def __init__(
        self,
        model: str = "gpt-4o",
        fallback: TokenCounter | None = None,
    ) -> None:
        self._fallback: TokenCounter = fallback or EstimateTokenCounter()
        self._available: bool = False
        self._encoding: Any = None
        try:
            import tiktoken

            self._encoding = tiktoken.encoding_for_model(model)
            self._available = True
        except (ImportError, KeyError):
            logger.debug(
                "tiktoken not available for model %r; using fallback counter",
                model,
            )
            self._encoding = None

    def count(self, text: str) -> int:
        if self._available and self._encoding is not None:
            return len(self._encoding.encode(text))
        return self._fallback.count(text)

    def count_messages(self, messages: list[dict]) -> int:  # type: ignore[type-arg]
        if not self._available or self._encoding is None:
            return self._fallback.count_messages(messages)
        total = 0
        for msg in messages:
            total += 4
            for key, value in msg.items():
                if isinstance(value, str):
                    total += len(self._encoding.encode(value))
                if key == "name":
                    total += -1
            # Each message carries a separator (empty assistant prompt).
        return total + 3  # reply priming

    @property
    def name(self) -> str:
        if self._available:
            return "tiktoken"
        return f"tiktoken-fallback({self._fallback.name})"


def create_token_counter(
    prefer_tiktoken: bool = True,
    model: str = "gpt-4o",
) -> TokenCounter:
    """Create the best available token counter.

    When *prefer_tiktoken* is ``True`` (default), attempts to use tiktoken
    and falls back to the heuristic estimator.
    """
    if prefer_tiktoken:
        counter = TiktokenCounter(model=model)
        if counter._available:  # noqa: SLF001
            return counter
    return EstimateTokenCounter()
