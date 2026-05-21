"""Sub-agent handoff ledger mechanism for swarm orchestration.

Inspired by openai/swarm and Continuous-Claude-v3, this module manages
the explicit transition of state (Context Ledger) between isolated agents
to prevent token window bloat and context pollution during complex
multi-step workflows.
"""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass
class StateLedger:
    """The immutable state payload passed between handoffs.

    Instead of passing the entire raw conversation history, agents
    pass a highly condensed ledger containing only actionable
    objectives, synthesized conclusions, and data pointers.
    """

    source_agent: str
    target_agent: str
    objective: str
    synthesized_context: str
    data_references: dict[str, Any] = dataclasses.field(default_factory=dict)

    def serialize(self) -> str:
        """Render the ledger for the target agent's system prompt."""
        parts = [
            f"# Handoff Ledger (from {self.source_agent})",
            f"**Objective**: {self.objective}",
            "\n## Synthesized Context",
            self.synthesized_context,
        ]

        if self.data_references:
            parts.append("\n## Data Pointers")
            for k, v in self.data_references.items():
                parts.append(f"- {k}: {v}")

        return "\n".join(parts)


def execute_handoff(ledger: StateLedger, messages: list[Any]) -> list[Any]:
    """
    Execute a structured handoff to a new agent phase, violently wiping previous context.

    This interceptor takes the active `messages` array from the orchestrator and slices it
    down to exclusively the System Prompt and the new Target Objective (the ledger context).
    This fundamentally breaks the linear token scaling problem for 3090 constrained environments.

    Returns:
        The truncated messages array ready for the Implementor phase.
    """
    from agent33.llm.base import ChatMessage

    if not messages:
        return []

    # Preserve ONLY the system prompt (Index 0)
    system_prompt = (
        messages[0] if messages[0].role == "system" else ChatMessage(role="system", content="")
    )

    # Create the fresh Implementor context seed
    new_context = ChatMessage(role="user", content=ledger.serialize())

    return [system_prompt, new_context]
