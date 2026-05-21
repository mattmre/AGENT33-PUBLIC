"""Training algorithms for autonomous prompt improvement."""

from __future__ import annotations

import abc
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent33.llm.router import ModelRouter

logger = logging.getLogger(__name__)

_APO_PROMPT = """\
You are optimizing an AI agent's system prompt. Analyze the high-reward and \
low-reward examples below, then generate an improved system prompt.

Current system prompt:
{current_prompt}

HIGH-REWARD examples (these worked well):
{good_examples}

LOW-REWARD examples (these performed poorly):
{bad_examples}

Analyze the differences. What patterns lead to success vs failure?
Generate an improved system prompt that addresses the weaknesses.

Return ONLY the new system prompt text, nothing else.
"""


class Algorithm(abc.ABC):
    """Base class for training algorithms."""

    @abc.abstractmethod
    async def run(self, rollouts: list[dict[str, Any]], current_prompt: str) -> str:
        """Given rollout data and current prompt, return an improved prompt."""
        ...


class APO(Algorithm):
    """Automatic Prompt Optimization via LLM reflection.

    Analyzes high-reward vs low-reward rollouts, identifies prompt weaknesses,
    and generates an improved system prompt.
    """

    def __init__(self, router: ModelRouter, model: str = "") -> None:
        self._router = router
        self._model = model or "llama3.2"

    async def run(self, rollouts: list[dict[str, Any]], current_prompt: str) -> str:
        from agent33.llm.base import ChatMessage

        if not rollouts:
            return current_prompt

        sorted_rollouts = sorted(rollouts, key=lambda r: r.get("total_reward", 0))
        mid = len(sorted_rollouts) // 2
        bad = sorted_rollouts[: max(1, mid)]
        good = sorted_rollouts[max(1, mid) :]

        good_text = "\n---\n".join(
            f"Reward: {r.get('total_reward', 0):.2f}\n"
            f"Spans: {json.dumps(r.get('spans', []), default=str)[:500]}"
            for r in good[:5]
        )
        bad_text = "\n---\n".join(
            f"Reward: {r.get('total_reward', 0):.2f}\n"
            f"Spans: {json.dumps(r.get('spans', []), default=str)[:500]}"
            for r in bad[:5]
        )

        prompt = _APO_PROMPT.format(
            current_prompt=current_prompt,
            good_examples=good_text,
            bad_examples=bad_text,
        )
        response = await self._router.complete(
            [ChatMessage(role="user", content=prompt)],
            model=self._model,
            temperature=0.7,
        )
        return response.content.strip()


class SFT(Algorithm):
    """Supervised Fine-Tuning data extraction.

    Extracts (input, ideal_output) pairs from top rollouts
    and formats them for future fine-tuning.
    """

    def __init__(self, router: ModelRouter | None = None) -> None:
        self._router = router

    async def run(self, rollouts: list[dict[str, Any]], current_prompt: str) -> str:
        """Extract training pairs from top rollouts.

        Returns JSON string of training data, not a new prompt.
        """
        sorted_rollouts = sorted(rollouts, key=lambda r: r.get("total_reward", 0), reverse=True)

        training_pairs: list[dict[str, str]] = []
        for r in sorted_rollouts[:10]:
            spans = r.get("spans", [])
            prompt_spans = [s for s in spans if s.get("span_type") == "prompt"]
            result_spans = [s for s in spans if s.get("span_type") == "result"]
            if prompt_spans and result_spans:
                training_pairs.append(
                    {
                        "input": prompt_spans[0].get("content", ""),
                        "output": result_spans[-1].get("content", ""),
                        "reward": str(r.get("total_reward", 0)),
                    }
                )

        return json.dumps(training_pairs, indent=2)
