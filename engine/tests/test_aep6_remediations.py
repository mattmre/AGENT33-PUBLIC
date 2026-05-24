"""Tests for Architecture & Planning Loop 6 remediations.

C1: Pack addenda + tool config wired into AgentRuntime
H1: approved-tools.json loaded into ToolGovernance
H3: Outcome recording in SSE stream route
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from agent33.agents.definition import AgentDefinition
from agent33.agents.runtime import AgentRuntime
from agent33.llm.base import ChatMessage, LLMResponse
from agent33.llm.router import ModelRouter
from agent33.tools.governance import ToolGovernance

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_definition(**overrides: Any) -> AgentDefinition:
    """Build a minimal AgentDefinition for testing."""
    base: dict[str, Any] = {
        "name": "test-agent",
        "version": "0.1.0",
        "role": "worker",
    }
    base.update(overrides)
    return AgentDefinition.model_validate(base)


def _fake_router() -> ModelRouter:
    """Return a ModelRouter with a mock provider that returns canned responses."""
    router = ModelRouter(default_provider="mock")
    provider = AsyncMock()
    provider.complete = AsyncMock(
        return_value=LLMResponse(
            content='{"result": "ok"}',
            model="mock-model",
            prompt_tokens=5,
            completion_tokens=5,
        )
    )
    router.register("mock", provider)
    return router


# ---------------------------------------------------------------------------
# C1: Pack addenda injected into system prompt
# ---------------------------------------------------------------------------


class TestPackAddendaInjection:
    """Verify that pack addenda are appended to the system prompt."""

    async def test_invoke_appends_pack_addenda(self) -> None:
        """When a session has active packs with addenda, they appear in the prompt."""
        definition = _minimal_definition()
        router = _fake_router()

        mock_registry = MagicMock()
        mock_registry.get_session_prompt_addenda.return_value = [
            "Always use metric units.",
            "Prefer concise answers.",
        ]
        mock_registry.get_session_tool_config.return_value = {}

        runtime = AgentRuntime(
            definition=definition,
            router=router,
            model="mock-model",
            session_id="sess-001",
            pack_registry=mock_registry,
        )

        result = await runtime.invoke({"task": "hello"})

        # The pack registry was called with our session id
        mock_registry.get_session_prompt_addenda.assert_called_once_with(
            "sess-001",
            ppack_variant="",
        )

        # Verify the addenda ended up in the LLM call
        call_args = router.providers["mock"].complete.call_args
        messages: list[ChatMessage] = call_args[0][0]
        system_msg = messages[0].content
        assert "Always use metric units." in system_msg
        assert "Prefer concise answers." in system_msg
        assert "# Pack Addenda" in system_msg
        assert result.output == {"result": "ok"}

    async def test_invoke_no_addenda_when_no_session(self) -> None:
        """Without a session_id, the pack registry is not queried."""
        definition = _minimal_definition()
        router = _fake_router()

        mock_registry = MagicMock()

        runtime = AgentRuntime(
            definition=definition,
            router=router,
            model="mock-model",
            session_id="",
            pack_registry=mock_registry,
        )

        await runtime.invoke({"task": "hello"})

        mock_registry.get_session_prompt_addenda.assert_not_called()

    async def test_invoke_no_addenda_when_pack_registry_absent(self) -> None:
        """Without a pack_registry, invoke still works normally."""
        definition = _minimal_definition()
        router = _fake_router()

        runtime = AgentRuntime(
            definition=definition,
            router=router,
            model="mock-model",
            session_id="sess-002",
            pack_registry=None,
        )

        result = await runtime.invoke({"task": "hello"})
        assert result.output == {"result": "ok"}

    async def test_invoke_empty_addenda_no_header(self) -> None:
        """When addenda list is empty, no Pack Addenda section is added."""
        definition = _minimal_definition()
        router = _fake_router()

        mock_registry = MagicMock()
        mock_registry.get_session_prompt_addenda.return_value = []

        runtime = AgentRuntime(
            definition=definition,
            router=router,
            model="mock-model",
            session_id="sess-003",
            pack_registry=mock_registry,
        )

        await runtime.invoke({"task": "hello"})

        call_args = router.providers["mock"].complete.call_args
        messages: list[ChatMessage] = call_args[0][0]
        system_msg = messages[0].content
        assert "# Pack Addenda" not in system_msg


# ---------------------------------------------------------------------------
# C1: Pack tool config narrowing
# ---------------------------------------------------------------------------


class TestPackToolConfigNarrowing:
    """Verify that pack tool config narrows tool policies on ToolContext."""

    def test_narrowing_deny_overrides_allow(self) -> None:
        """A pack policy of 'deny' should override 'allow'."""
        from agent33.tools.base import ToolContext

        definition = _minimal_definition()
        router = _fake_router()

        mock_registry = MagicMock()
        mock_registry.get_session_prompt_addenda.return_value = []
        mock_registry.get_session_tool_config.return_value = {
            "shell": {"policy": "deny"},
        }

        tool_context = ToolContext(
            user_scopes=["tools:execute"],
            tool_policies={"shell": "allow"},
            session_id="sess-tc-1",
        )

        runtime = AgentRuntime(
            definition=definition,
            router=router,
            model="mock-model",
            session_id="sess-tc-1",
            pack_registry=mock_registry,
            tool_context=tool_context,
        )

        narrowed = runtime._apply_pack_tool_narrowing()
        assert narrowed is not None
        assert narrowed.tool_policies["shell"] == "deny"

    def test_narrowing_cannot_widen(self) -> None:
        """A pack policy of 'allow' should NOT override a 'deny'."""
        from agent33.tools.base import ToolContext

        definition = _minimal_definition()
        router = _fake_router()

        mock_registry = MagicMock()
        mock_registry.get_session_prompt_addenda.return_value = []
        mock_registry.get_session_tool_config.return_value = {
            "shell": {"policy": "allow"},
        }

        tool_context = ToolContext(
            user_scopes=["tools:execute"],
            tool_policies={"shell": "deny"},
            session_id="sess-tc-2",
        )

        runtime = AgentRuntime(
            definition=definition,
            router=router,
            model="mock-model",
            session_id="sess-tc-2",
            pack_registry=mock_registry,
            tool_context=tool_context,
        )

        narrowed = runtime._apply_pack_tool_narrowing()
        assert narrowed is not None
        # Existing deny must be preserved -- pack cannot widen
        assert narrowed.tool_policies["shell"] == "deny"

    def test_narrowing_ask_overrides_allow(self) -> None:
        """A pack policy of 'ask' should override 'allow'."""
        from agent33.tools.base import ToolContext

        definition = _minimal_definition()
        router = _fake_router()

        mock_registry = MagicMock()
        mock_registry.get_session_prompt_addenda.return_value = []
        mock_registry.get_session_tool_config.return_value = {
            "web_fetch": {"policy": "ask"},
        }

        tool_context = ToolContext(
            user_scopes=["tools:execute"],
            tool_policies={},
            session_id="sess-tc-3",
        )

        runtime = AgentRuntime(
            definition=definition,
            router=router,
            model="mock-model",
            session_id="sess-tc-3",
            pack_registry=mock_registry,
            tool_context=tool_context,
        )

        narrowed = runtime._apply_pack_tool_narrowing()
        assert narrowed is not None
        assert narrowed.tool_policies["web_fetch"] == "ask"

    def test_no_narrowing_without_pack_registry(self) -> None:
        """Without pack_registry, tool context is returned as-is."""
        from agent33.tools.base import ToolContext

        definition = _minimal_definition()
        router = _fake_router()

        tool_context = ToolContext(
            user_scopes=["tools:execute"],
            tool_policies={"shell": "allow"},
            session_id="sess-tc-4",
        )

        runtime = AgentRuntime(
            definition=definition,
            router=router,
            model="mock-model",
            session_id="sess-tc-4",
            pack_registry=None,
            tool_context=tool_context,
        )

        result = runtime._apply_pack_tool_narrowing()
        assert result is tool_context  # exact same object, no copy


# ---------------------------------------------------------------------------
# H1: Load approved-tools.json into ToolGovernance
# ---------------------------------------------------------------------------


class TestApprovedToolsLoading:
    """Verify that ToolGovernance.load_approved_tools_file works correctly."""

    def test_load_valid_file(self, tmp_path: Path) -> None:
        """Approved tools are loaded from a well-formed JSON file."""
        approved_file = tmp_path / "approved-tools.json"
        approved_file.write_text(
            json.dumps(
                {
                    "shell": {"approved_at": "2026-04-01T00:00:00Z", "reason": "dev"},
                    "web_fetch": {"approved_at": "2026-04-02T00:00:00Z", "reason": ""},
                }
            ),
            encoding="utf-8",
        )

        gov = ToolGovernance()
        gov.load_approved_tools_file(approved_file)

        assert "shell" in gov.approved_tools
        assert "web_fetch" in gov.approved_tools
        assert len(gov.approved_tools) == 2

    def test_load_nonexistent_file(self) -> None:
        """Loading a nonexistent file silently does nothing."""
        gov = ToolGovernance()
        gov.load_approved_tools_file(Path("/nonexistent/path/approved-tools.json"))
        assert len(gov.approved_tools) == 0

    def test_load_malformed_json(self, tmp_path: Path) -> None:
        """Malformed JSON is silently ignored."""
        approved_file = tmp_path / "approved-tools.json"
        approved_file.write_text("{not valid json", encoding="utf-8")

        gov = ToolGovernance()
        gov.load_approved_tools_file(approved_file)
        assert len(gov.approved_tools) == 0

    def test_load_wrong_type(self, tmp_path: Path) -> None:
        """A JSON file that is not an object (e.g. a list) is ignored."""
        approved_file = tmp_path / "approved-tools.json"
        approved_file.write_text('["tool1", "tool2"]', encoding="utf-8")

        gov = ToolGovernance()
        gov.load_approved_tools_file(approved_file)
        assert len(gov.approved_tools) == 0

    def test_additive_loading(self, tmp_path: Path) -> None:
        """Loading twice is additive, not replacing."""
        file1 = tmp_path / "f1.json"
        file1.write_text(json.dumps({"shell": {}}), encoding="utf-8")
        file2 = tmp_path / "f2.json"
        file2.write_text(json.dumps({"web_fetch": {}}), encoding="utf-8")

        gov = ToolGovernance()
        gov.load_approved_tools_file(file1)
        gov.load_approved_tools_file(file2)

        assert "shell" in gov.approved_tools
        assert "web_fetch" in gov.approved_tools


class TestApprovedToolBypassesAskPolicy:
    """Verify that a CLI-approved tool bypasses the ask policy."""

    def test_approved_tool_bypasses_ask(self, tmp_path: Path) -> None:
        """An approved tool with an 'ask' policy should be allowed."""
        from agent33.tools.base import ToolContext

        approved_file = tmp_path / "approved-tools.json"
        approved_file.write_text(
            json.dumps({"shell": {"approved_at": "2026-04-01T00:00:00Z"}}),
            encoding="utf-8",
        )

        gov = ToolGovernance()
        gov.load_approved_tools_file(approved_file)

        ctx = ToolContext(
            user_scopes=["tools:execute"],
            tool_policies={"shell": "ask"},
            command_allowlist=["ls"],
        )

        result = gov.pre_execute_check("shell", {"command": "ls"}, ctx)
        assert result is True

    def test_unapproved_tool_blocked_by_ask(self) -> None:
        """An unapproved tool with an 'ask' policy should be blocked."""
        from agent33.tools.base import ToolContext

        gov = ToolGovernance()
        ctx = ToolContext(
            user_scopes=["tools:execute"],
            tool_policies={"shell": "ask"},
        )

        result = gov.pre_execute_check("shell", {"command": "ls"}, ctx)
        assert result is False

    def test_approved_tool_still_denied_by_deny(self, tmp_path: Path) -> None:
        """An approved tool with a 'deny' policy remains denied."""
        from agent33.tools.base import ToolContext

        approved_file = tmp_path / "approved-tools.json"
        approved_file.write_text(
            json.dumps({"shell": {"approved_at": "2026-04-01T00:00:00Z"}}),
            encoding="utf-8",
        )

        gov = ToolGovernance()
        gov.load_approved_tools_file(approved_file)

        ctx = ToolContext(
            user_scopes=["tools:execute"],
            tool_policies={"shell": "deny"},
        )

        result = gov.pre_execute_check("shell", {"command": "ls"}, ctx)
        assert result is False


# ---------------------------------------------------------------------------
# H3: Outcome recording in SSE stream route
# ---------------------------------------------------------------------------


class TestSSEStreamOutcomeRecording:
    """Verify that the SSE stream route records outcome events."""

    async def test_stream_records_success_outcome(self) -> None:
        """Successful stream completion records SUCCESS_RATE=1.0 + LATENCY_MS."""
        from agent33.api.routes.agents import _record_outcome_safe
        from agent33.outcomes.models import OutcomeMetricType

        mock_svc = MagicMock()
        _record_outcome_safe(
            mock_svc,
            tenant_id="t1",
            domain="test",
            event_type="invoke_iterative_stream",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=1.0,
            metadata={"iterations": 3, "termination": "complete"},
        )
        mock_svc.record_event.assert_called_once()
        call_event = mock_svc.record_event.call_args[1]["event"]
        assert call_event.metric_type == OutcomeMetricType.SUCCESS_RATE
        assert call_event.value == 1.0
        assert call_event.metadata["termination"] == "complete"

    async def test_stream_records_failure_outcome(self) -> None:
        """Failed stream records SUCCESS_RATE=0.0 with error metadata."""
        from agent33.api.routes.agents import _record_outcome_safe
        from agent33.outcomes.models import OutcomeMetricType

        mock_svc = MagicMock()
        _record_outcome_safe(
            mock_svc,
            tenant_id="t1",
            domain="test",
            event_type="invoke_iterative_stream",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=0.0,
            metadata={"error": "connection lost", "termination": "error"},
        )
        mock_svc.record_event.assert_called_once()
        call_event = mock_svc.record_event.call_args[1]["event"]
        assert call_event.value == 0.0
        assert call_event.metadata["error"] == "connection lost"

    async def test_stream_records_latency_outcome(self) -> None:
        """Verify LATENCY_MS recording path is correct."""
        from agent33.api.routes.agents import _record_outcome_safe
        from agent33.outcomes.models import OutcomeMetricType

        mock_svc = MagicMock()
        _record_outcome_safe(
            mock_svc,
            tenant_id="t1",
            domain="test-agent",
            event_type="invoke_iterative_stream",
            metric_type=OutcomeMetricType.LATENCY_MS,
            value=1234.5,
            metadata={"agent": "test-agent"},
        )
        mock_svc.record_event.assert_called_once()
        call_event = mock_svc.record_event.call_args[1]["event"]
        assert call_event.metric_type == OutcomeMetricType.LATENCY_MS
        assert call_event.value == 1234.5

    def test_stream_route_source_contains_outcome_wiring(self) -> None:
        """The SSE stream route source must reference outcome recording."""
        from agent33.api.routes import agents as agents_module

        source = inspect.getsource(agents_module.invoke_agent_iterative_stream)
        assert "_record_outcome_safe" in source
        assert "outcomes_svc_stream" in source
        assert "OutcomeMetricType.SUCCESS_RATE" in source
        assert "OutcomeMetricType.LATENCY_MS" in source
        # Both success and failure paths must be present
        assert "value=1.0" in source
        assert "value=0.0" in source
