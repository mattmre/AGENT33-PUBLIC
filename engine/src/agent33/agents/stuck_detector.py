"""Lightweight stuck-detector contract and default heuristics.

This module provides a small integration surface for reasoning-loop stuck
detection plus a conservative default implementation inspired by OpenHands-
style loop patterns.
"""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclasses.dataclass(frozen=True, slots=True)
class StuckDetection:
    """Structured result when a stuck pattern is detected."""

    pattern: str
    reason: str
    window_size: int
    evidence: dict[str, Any] = dataclasses.field(default_factory=dict)


class StuckDetector(Protocol):
    """Contract for reasoning-loop stuck detection."""

    def detect(
        self,
        steps: Sequence[Any],
        phase_artifacts: Mapping[str, Any],
        current_phase: str,
        normalized_action: str,
    ) -> StuckDetection | None:
        """Return a detection result when stuck behavior is observed."""


_ERROR_TERMS = (
    "error",
    "failed",
    "failure",
    "exception",
    "traceback",
    "invalid",
    "timeout",
)
_CONDENSATION_TERMS = (
    "condense",
    "condensed",
    "condensation",
    "compress",
    "compressed",
    "compression",
    "summarize",
    "summary",
    "shorten",
    "truncate",
    "token limit",
    "context window",
)
_MONOLOGUE_ACTIONS = {"observe", "plan", "learn"}


def _text_fingerprint(value: str) -> str:
    normalized = re.sub(r"\s+", " ", (value or "").strip().lower())
    return normalized[:160]


class OpenHandsStyleStuckDetector:
    """Default heuristic stuck detector for common loop patterns."""

    def __init__(self, history_window: int = 6) -> None:
        self._history_window = max(4, history_window)

    def detect(
        self,
        steps: Sequence[Any],
        phase_artifacts: Mapping[str, Any],
        current_phase: str,
        normalized_action: str,
    ) -> StuckDetection | None:
        del phase_artifacts, current_phase, normalized_action  # Reserved for future heuristics.

        if len(steps) < 4:
            return None

        recent = list(steps[-self._history_window :])
        actions = [str(getattr(step, "action", "")).strip().lower() for step in recent]
        results = [str(getattr(step, "result", "")) for step in recent]
        reasonings = [str(getattr(step, "reasoning", "")) for step in recent]
        combined = [f"{r} {g}".strip() for r, g in zip(results, reasonings, strict=False)]
        fingerprints = [_text_fingerprint(text) for text in combined]

        # 1) Repeated action-error pattern
        if len(recent) >= 2:
            last_actions = actions[-2:]
            last_text = combined[-2:]
            last_fp = fingerprints[-2:]
            error_hits = [any(term in text.lower() for term in _ERROR_TERMS) for text in last_text]
            if len(set(last_actions)) == 1 and all(error_hits) and len(set(last_fp)) == 1:
                return StuckDetection(
                    pattern="repeated_action_error",
                    reason="Same action repeats with the same error signature.",
                    window_size=2,
                    evidence={"action": last_actions[0], "error_text": last_text[-1][:200]},
                )

        # 2) Repeated action-observation pattern
        if len(recent) >= 3:
            last_actions = actions[-3:]
            last_fp = fingerprints[-3:]
            if len(set(last_actions)) == 1 and len(set(last_fp)) == 1 and last_fp[0]:
                return StuckDetection(
                    pattern="repeated_action_observation",
                    reason="Repeated same action with near-identical observation text.",
                    window_size=3,
                    evidence={"action": last_actions[0], "fingerprint": last_fp[0]},
                )

        # 3) Monologue / no-progress loop
        if len(recent) >= 5:
            last_actions = actions[-5:]
            if all(action in _MONOLOGUE_ACTIONS for action in last_actions):
                diversity = len({fp for fp in fingerprints[-5:] if fp})
                if diversity <= 2:
                    return StuckDetection(
                        pattern="monologue_no_progress",
                        reason="Extended non-executing monologue with little textual progress.",
                        window_size=5,
                        evidence={"actions": last_actions, "unique_fingerprints": diversity},
                    )

        # 4) ABAB oscillation
        if len(recent) >= 4:
            a1, b1, a2, b2 = actions[-4:]
            if a1 and b1 and a1 == a2 and b1 == b2 and a1 != b1:
                return StuckDetection(
                    pattern="abab_oscillation",
                    reason="Detected ABAB action oscillation without convergence.",
                    window_size=4,
                    evidence={"sequence": actions[-4:]},
                )

        # 5) Context-condensation loop (text-based heuristic)
        if len(recent) >= 4:
            last_texts = combined[-4:]
            condensation_mentions = [
                any(term in text.lower() for term in _CONDENSATION_TERMS) for text in last_texts
            ]
            if sum(condensation_mentions) >= 3 and len(set(fingerprints[-4:])) <= 3:
                return StuckDetection(
                    pattern="context_condensation_loop",
                    reason="Repeated context-condensation attempts without meaningful change.",
                    window_size=4,
                    evidence={"mentions": sum(condensation_mentions)},
                )

        return None
