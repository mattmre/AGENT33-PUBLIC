"""Session summarization via LLM compression."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from agent33.security.redaction import redact_secrets

if TYPE_CHECKING:
    from agent33.llm.router import ModelRouter
    from agent33.memory.long_term import LongTermMemory
    from agent33.memory.observation import Observation

logger = logging.getLogger(__name__)

_SUMMARIZE_PROMPT = """\
Summarize the following agent observations into a structured JSON object.
Return ONLY valid JSON with these fields:
- "summary": A 2-3 sentence summary of what happened
- "key_facts": A list of important facts/decisions (max 10 items)
- "tags": A list of relevant topic tags

Observations:
{observations}
"""


class SessionSummarizer:
    """Compresses session observations into structured summaries via LLM."""

    def __init__(
        self,
        router: ModelRouter,
        long_term_memory: LongTermMemory | None = None,
        embedding_provider: Any | None = None,
        model: str = "llama3.2",
        *,
        redact_enabled: bool = True,
    ) -> None:
        self._router = router
        self._memory = long_term_memory
        self._embeddings = embedding_provider
        self._model = model
        self._redact_enabled = redact_enabled

    async def summarize(self, observations: list[Observation]) -> dict[str, Any]:
        """Compress a list of observations into a structured summary."""
        from agent33.llm.base import ChatMessage

        obs_text = "\n".join(
            f"[{o.event_type}] {o.agent_name}: "
            f"{redact_secrets(o.content[:500], enabled=self._redact_enabled)}"
            for o in observations
        )
        prompt = _SUMMARIZE_PROMPT.format(observations=obs_text)

        response = await self._router.complete(
            [ChatMessage(role="user", content=prompt)],
            model=self._model,
            temperature=0.3,
        )

        try:
            raw = response.content.strip()
            if raw.startswith("```"):
                lines = raw.splitlines()
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
                raw = "\n".join(inner)
            result: dict[str, Any] = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            result = {
                "summary": response.content[:500],
                "key_facts": [],
                "tags": [],
            }

        # Redact any secrets that leaked through the LLM summary output.
        if "summary" in result and isinstance(result["summary"], str):
            result["summary"] = redact_secrets(result["summary"], enabled=self._redact_enabled)
        if "key_facts" in result and isinstance(result["key_facts"], list):
            result["key_facts"] = [
                redact_secrets(f, enabled=self._redact_enabled) if isinstance(f, str) else f
                for f in result["key_facts"]
            ]

        return result

    async def auto_summarize(
        self, session_id: str, observations: list[Observation]
    ) -> dict[str, Any]:
        """Summarize and store the result in long-term memory."""
        result = await self.summarize(observations)

        if self._memory is not None and self._embeddings is not None:
            try:
                summary_text = json.dumps(result)
                embedding = await self._embeddings.embed(result.get("summary", ""))
                await self._memory.store(
                    content=summary_text,
                    embedding=embedding,
                    metadata={
                        "type": "session_summary",
                        "session_id": session_id,
                        "tags": result.get("tags", []),
                    },
                )
            except Exception:
                logger.warning("failed to store summary for session %s", session_id, exc_info=True)

        return result
