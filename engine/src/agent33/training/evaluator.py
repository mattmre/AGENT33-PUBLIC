"""Self-evaluation - the system scores its own outputs."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent33.llm.router import ModelRouter

logger = logging.getLogger(__name__)

_EVAL_PROMPT = """\
You are evaluating an AI agent's output. Score the quality from 0.0 to 1.0.

Task context:
{context}

Agent output:
{output}

Respond with ONLY a JSON object: {{"score": <float>, "reason": "<brief explanation>"}}
"""

_CODE_EVAL_PROMPT = """\
Review this {language} code for correctness, style, and completeness.
Score from 0.0 to 1.0.

```{language}
{code}
```

Respond with ONLY a JSON object: {{"score": <float>, "reason": "<brief explanation>"}}
"""


class SelfEvaluator:
    """Autonomous evaluation of agent outputs using LLM-as-judge."""

    def __init__(
        self,
        router: ModelRouter,
        model: str = "",
    ) -> None:
        self._router = router
        self._model = model or "llama3.2"

    async def evaluate(self, agent_result: str, task_context: str) -> float:
        """Score an agent result using LLM-as-judge (0.0 to 1.0)."""
        from agent33.llm.base import ChatMessage

        prompt = _EVAL_PROMPT.format(context=task_context, output=agent_result)
        response = await self._router.complete(
            [ChatMessage(role="user", content=prompt)],
            model=self._model,
            temperature=0.1,
        )
        return self._parse_score(response.content)

    async def evaluate_code(self, code: str, language: str = "python") -> float:
        """Score code quality using LLM review."""
        from agent33.llm.base import ChatMessage

        prompt = _CODE_EVAL_PROMPT.format(language=language, code=code)
        response = await self._router.complete(
            [ChatMessage(role="user", content=prompt)],
            model=self._model,
            temperature=0.1,
        )
        return self._parse_score(response.content)

    async def evaluate_workflow(self, result: str, expected: str) -> float:
        """Score by comparing output to expected result."""
        from agent33.llm.base import ChatMessage

        prompt = (
            "Compare these two outputs and score similarity from 0.0 to 1.0.\n\n"
            f"Expected:\n{expected}\n\nActual:\n{result}\n\n"
            'Respond with ONLY: {{"score": <float>, "reason": "<brief>"}}'
        )
        response = await self._router.complete(
            [ChatMessage(role="user", content=prompt)],
            model=self._model,
            temperature=0.1,
        )
        return self._parse_score(response.content)

    @staticmethod
    def _parse_score(raw: str) -> float:
        """Extract a score from LLM response."""
        try:
            stripped = raw.strip()
            if stripped.startswith("```"):
                lines = stripped.splitlines()
                inner = []
                started = False
                for line in lines:
                    if line.strip().startswith("```") and not started:
                        started = True
                        continue
                    if line.strip() == "```" and started:
                        break
                    if started:
                        inner.append(line)
                stripped = "\n".join(inner)
            data = json.loads(stripped)
            score = float(data.get("score", 0.0))
            return max(0.0, min(1.0, score))
        except (json.JSONDecodeError, ValueError, TypeError):
            logger.warning("failed to parse evaluation score from: %s", raw[:200])
            return 0.0
