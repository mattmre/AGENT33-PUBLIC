"""Speaker selection strategies for group chat."""

from __future__ import annotations

import abc
import random


class SpeakerSelector(abc.ABC):
    """Base class for speaker selection strategies."""

    def __init__(self, agent_names: list[str]) -> None:
        self._agent_names = agent_names
        self._index = 0

    @abc.abstractmethod
    def select(self, history: list[dict[str, str]]) -> str:
        """Select the next speaker based on conversation history."""


class RoundRobinSelector(SpeakerSelector):
    """Cycle through agents in order."""

    def select(self, history: list[dict[str, str]]) -> str:
        name = self._agent_names[self._index % len(self._agent_names)]
        self._index += 1
        return name


class RandomSelector(SpeakerSelector):
    """Pick a random agent each round."""

    def select(self, history: list[dict[str, str]]) -> str:
        return random.choice(self._agent_names)


class MentionSelector(SpeakerSelector):
    """Select agent mentioned by @name in the last message."""

    def select(self, history: list[dict[str, str]]) -> str:
        if not history:
            return self._agent_names[0]

        last = history[-1].get("content", "")
        for name in self._agent_names:
            if f"@{name}" in last:
                return name

        # Fallback to round-robin
        name = self._agent_names[self._index % len(self._agent_names)]
        self._index += 1
        return name


class AutoSelector(SpeakerSelector):
    """Auto-select based on simple heuristics.

    Uses mention detection first, then round-robin as fallback. The selector is
    deterministic and does not call an LLM.
    """

    def __init__(self, agent_names: list[str]) -> None:
        super().__init__(agent_names)
        self._robin = RoundRobinSelector(agent_names)

    def select(self, history: list[dict[str, str]]) -> str:
        if history:
            last = history[-1].get("content", "")
            for name in self._agent_names:
                if f"@{name}" in last:
                    return name
        return self._robin.select(history)


def get_selector(strategy: str, agent_names: list[str]) -> SpeakerSelector:
    """Factory function for speaker selectors."""
    selectors: dict[str, type[SpeakerSelector]] = {
        "round_robin": RoundRobinSelector,
        "random": RandomSelector,
        "mention": MentionSelector,
        "auto": AutoSelector,
    }
    cls = selectors.get(strategy, RoundRobinSelector)
    return cls(agent_names)
