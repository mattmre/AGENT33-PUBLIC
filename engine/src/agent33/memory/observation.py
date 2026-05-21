"""Observation capture for recording all agent activity."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agent33.security.redaction import redact_secrets


@dataclass(frozen=True, slots=True)
class Observation:
    """A single recorded event from agent execution."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str = ""
    agent_name: str = ""
    event_type: str = ""  # tool_call, llm_response, decision, error
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


# Tags that cause observations to be filtered from recall
_PRIVATE_TAGS = frozenset({"sensitive", "pii", "secret"})


class ObservationCapture:
    """Records observations from agent execution into memory.

    Buffers observations and stores them with embeddings for later
    semantic retrieval via ProgressiveRecall.
    """

    def __init__(
        self,
        long_term_memory: Any | None = None,
        embedding_provider: Any | None = None,
        nats_bus: Any | None = None,
        *,
        redact_enabled: bool = True,
    ) -> None:
        self._memory = long_term_memory
        self._embeddings = embedding_provider
        self._nats_bus = nats_bus
        self._redact_enabled = redact_enabled
        self._buffer: list[Observation] = []

    async def record(self, obs: Observation) -> str:
        """Record an observation, storing it with embedding if available.

        Returns the observation ID. Observations tagged with private tags
        (sensitive, pii, secret) are buffered but not stored in long-term memory.
        """
        self._buffer.append(obs)

        # Redact secrets from content before any persistence / publishing.
        safe_content = redact_secrets(obs.content, enabled=self._redact_enabled)

        is_private = bool(set(obs.tags) & _PRIVATE_TAGS)

        if self._memory is not None and self._embeddings is not None and not is_private:
            try:
                embedding = await self._embeddings.embed(safe_content)
                await self._memory.store(
                    content=safe_content,
                    embedding=embedding,
                    metadata={
                        "observation_id": obs.id,
                        "session_id": obs.session_id,
                        "agent_name": obs.agent_name,
                        "event_type": obs.event_type,
                        "tags": obs.tags,
                        "timestamp": obs.timestamp.isoformat(),
                        **(obs.metadata),
                    },
                )
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "failed to store observation %s", obs.id, exc_info=True
                )

        if self._nats_bus is not None:
            try:
                await self._nats_bus.publish(
                    "agent.observation",
                    {
                        "id": obs.id,
                        "session_id": obs.session_id,
                        "agent_name": obs.agent_name,
                        "event_type": obs.event_type,
                        "content": safe_content,
                        "metadata": obs.metadata,
                        "tags": obs.tags,
                        "timestamp": obs.timestamp.isoformat(),
                    },
                )
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "failed to publish observation to NATS", exc_info=True
                )

        return obs.id

    async def flush(self) -> list[Observation]:
        """Return and clear the observation buffer."""
        observations = list(self._buffer)
        self._buffer.clear()
        return observations

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)
