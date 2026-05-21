"""Tests for the sub-agent handoff ledger mechanism."""

from __future__ import annotations

from agent33.llm.base import ChatMessage
from agent33.workflows.actions.handoff import (
    StateLedger,
    execute_handoff,
)

# ---------------------------------------------------------------------------
# StateLedger construction and serialization
# ---------------------------------------------------------------------------


class TestStateLedgerSerialization:
    """Verify that StateLedger.serialize() produces the expected prompt text."""

    def test_serialize_without_data_references(self) -> None:
        """Core path: ledger with no data_references omits the Data Pointers section."""
        ledger = StateLedger(
            source_agent="researcher",
            target_agent="code-worker",
            objective="Refactor auth module",
            synthesized_context="Auth is using deprecated bcrypt rounds.",
        )

        result = ledger.serialize()

        assert result.startswith("# Handoff Ledger (from researcher)")
        assert "**Objective**: Refactor auth module" in result
        assert "## Synthesized Context" in result
        assert "Auth is using deprecated bcrypt rounds." in result
        # The Data Pointers section must be absent when there are no references.
        assert "Data Pointers" not in result

    def test_serialize_with_data_references(self) -> None:
        """When data_references are provided, each key-value pair appears as a bullet."""
        ledger = StateLedger(
            source_agent="orchestrator",
            target_agent="qa",
            objective="Validate migration",
            synthesized_context="Migration script v3 ready.",
            data_references={"migration_id": "mig-42", "row_count": 1500},
        )

        result = ledger.serialize()

        assert "## Data Pointers" in result
        assert "- migration_id: mig-42" in result
        assert "- row_count: 1500" in result

    def test_default_data_references_is_empty_dict(self) -> None:
        """Ensure the mutable default factory produces an isolated empty dict."""
        a = StateLedger(
            source_agent="a",
            target_agent="b",
            objective="x",
            synthesized_context="y",
        )
        b = StateLedger(
            source_agent="c",
            target_agent="d",
            objective="x",
            synthesized_context="y",
        )

        assert a.data_references == {}
        assert b.data_references == {}
        # Mutating one must not affect the other (no shared mutable default).
        a.data_references["key"] = "val"
        assert "key" not in b.data_references


# ---------------------------------------------------------------------------
# execute_handoff() context truncation
# ---------------------------------------------------------------------------


class TestExecuteHandoff:
    """Verify that execute_handoff() correctly truncates and replaces context."""

    @staticmethod
    def _make_ledger() -> StateLedger:
        return StateLedger(
            source_agent="director",
            target_agent="implementer",
            objective="Build feature X",
            synthesized_context="Prior analysis concluded X is feasible.",
            data_references={"spec_url": "https://example.com/spec"},
        )

    def test_empty_messages_returns_empty(self) -> None:
        """Edge case: an empty message list yields an empty result, no crash."""
        result = execute_handoff(self._make_ledger(), [])
        assert result == []

    def test_truncation_preserves_system_and_injects_ledger(self) -> None:
        """Only the system prompt survives; the ledger becomes the sole user msg.

        This is the critical behaviour: a 50-message conversation must be
        reduced to exactly 2 messages (system + ledger), breaking linear
        token scaling.
        """
        system = ChatMessage(role="system", content="You are a helpful agent.")
        history = [
            system,
            ChatMessage(role="user", content="Step 1 analysis..."),
            ChatMessage(role="assistant", content="Step 1 done."),
            ChatMessage(role="user", content="Step 2 analysis..."),
            ChatMessage(role="assistant", content="Step 2 done."),
        ]

        result = execute_handoff(self._make_ledger(), history)

        # Exactly 2 messages: system prompt + new ledger context.
        assert len(result) == 2
        assert result[0].role == "system"
        assert result[0].content == "You are a helpful agent."
        assert result[1].role == "user"
        # The user message content must be the serialized ledger, not old history.
        assert "# Handoff Ledger (from director)" in result[1].content
        assert "Build feature X" in result[1].content
        assert "spec_url" in result[1].content

    def test_non_system_first_message_gets_empty_system_prompt(self) -> None:
        """When messages[0] is not role=system, a blank system prompt is synthesized.

        This guards against conversations that lack an explicit system prompt.
        """
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there"),
        ]

        result = execute_handoff(self._make_ledger(), messages)

        assert len(result) == 2
        # An empty system prompt must be injected.
        assert result[0].role == "system"
        assert result[0].content == ""
        # Ledger is still the second message.
        assert result[1].role == "user"
        assert "Handoff Ledger" in result[1].content
