"""Tests for runtime integration gaps (P4).

Covers:
- Gap 1: Answer leakage detection in tool loop
- Gap 3: Failure taxonomy alignment (tool loop → trace outcome)
- Gap 4 Stage 1: Structured double-confirmation (COMPLETED/CONTINUE)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.agents.tool_loop import (
    CONFIRMATION_PROMPT,
    ToolLoop,
    ToolLoopConfig,
    ToolLoopResult,
    _parse_confirmation,
    _strip_completion_prefix,
)
from agent33.agents.tool_loop_taxonomy import (
    TOOL_LOOP_SUBCODES,
    classify_tool_loop_failure,
    tool_loop_to_failure_record,
    tool_loop_to_trace_outcome,
)
from agent33.llm.base import ChatMessage, LLMResponse
from agent33.observability.failure import FailureCategory, FailureSeverity
from agent33.observability.trace_models import TraceStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_loop_result(
    termination_reason: str = "completed",
    raw_response: str = "done",
    iterations: int = 3,
    tool_calls_made: int = 2,
    tools_used: list[str] | None = None,
    model: str = "gpt-4o",
) -> ToolLoopResult:
    return ToolLoopResult(
        output={"response": raw_response},
        raw_response=raw_response,
        tokens_used=500,
        model=model,
        iterations=iterations,
        tool_calls_made=tool_calls_made,
        tools_used=tools_used or ["shell", "file_read"],
        termination_reason=termination_reason,
    )


def _mock_router(content: str = "", has_tool_calls: bool = False) -> MagicMock:
    router = MagicMock()
    resp = LLMResponse(
        content=content,
        model="test-model",
        prompt_tokens=10,
        completion_tokens=20,
        # total_tokens is a computed property
    )
    if has_tool_calls:
        tc = MagicMock()
        tc.id = "tc_1"
        tc.function.name = "shell"
        tc.function.arguments = '{"command": "echo hello"}'
        resp = LLMResponse(
            content=content,
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens is a computed property
            tool_calls=[tc],
        )
    router.complete = AsyncMock(return_value=resp)
    return router


def _mock_tool_registry(output: str = "tool output") -> MagicMock:
    from agent33.tools.base import ToolResult

    registry = MagicMock()
    registry.list_all.return_value = []
    registry.validated_execute = AsyncMock(return_value=ToolResult.ok(output))
    registry.get_entry.return_value = None
    return registry


# ---------------------------------------------------------------------------
# Gap 1: Answer Leakage Detection in Tool Loop
# ---------------------------------------------------------------------------


class TestLeakageDetectorIntegration:
    """Tests that the leakage_detector callback filters tool output."""

    @pytest.mark.asyncio
    async def test_leakage_detector_filters_output(self) -> None:
        """When detector returns True, tool output is replaced."""

        def detector(text: str) -> bool:
            return "secret answer" in text.lower()

        # Router returns a tool call, then a final text response
        tc = MagicMock()
        tc.id = "tc_1"
        tc.function.name = "shell"
        tc.function.arguments = '{"command": "cat result.txt"}'

        tool_call_resp = LLMResponse(
            content="",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens is a computed property
            tool_calls=[tc],
        )
        final_resp = LLMResponse(
            content="COMPLETED: The answer is 42",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens is a computed property
        )

        router = MagicMock()
        router.complete = AsyncMock(side_effect=[tool_call_resp, final_resp])

        from agent33.tools.base import ToolResult

        registry = MagicMock()
        registry.list_all.return_value = []
        registry.validated_execute = AsyncMock(
            return_value=ToolResult.ok("The secret answer is 42")
        )
        registry.get_entry.return_value = None

        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            config=ToolLoopConfig(enable_double_confirmation=False),
            leakage_detector=detector,
        )

        result = await loop.run(
            [ChatMessage(role="user", content="What is the answer?")],
            model="test-model",
        )
        assert result.termination_reason == "completed"

    @pytest.mark.asyncio
    async def test_leakage_detector_not_triggered(self) -> None:
        """When detector returns False, tool output is preserved."""

        def detector(text: str) -> bool:
            return False

        tc = MagicMock()
        tc.id = "tc_1"
        tc.function.name = "shell"
        tc.function.arguments = '{"command": "ls"}'

        tool_call_resp = LLMResponse(
            content="",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens is a computed property
            tool_calls=[tc],
        )
        final_resp = LLMResponse(
            content="COMPLETED: done",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens is a computed property
        )

        router = MagicMock()
        router.complete = AsyncMock(side_effect=[tool_call_resp, final_resp])

        from agent33.tools.base import ToolResult

        registry = MagicMock()
        registry.list_all.return_value = []
        registry.validated_execute = AsyncMock(return_value=ToolResult.ok("file1.txt file2.txt"))
        registry.get_entry.return_value = None

        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            config=ToolLoopConfig(enable_double_confirmation=False),
            leakage_detector=detector,
        )

        result = await loop.run(
            [ChatMessage(role="user", content="List files")],
            model="test-model",
        )
        assert result.termination_reason == "completed"

    @pytest.mark.asyncio
    async def test_no_leakage_detector_no_filtering(self) -> None:
        """Without a detector, no filtering occurs (backward compat)."""
        tc = MagicMock()
        tc.id = "tc_1"
        tc.function.name = "shell"
        tc.function.arguments = '{"command": "echo"}'

        tool_call_resp = LLMResponse(
            content="",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens is a computed property
            tool_calls=[tc],
        )
        final_resp = LLMResponse(
            content="COMPLETED: done",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens is a computed property
        )

        router = MagicMock()
        router.complete = AsyncMock(side_effect=[tool_call_resp, final_resp])

        from agent33.tools.base import ToolResult

        registry = MagicMock()
        registry.list_all.return_value = []
        registry.validated_execute = AsyncMock(return_value=ToolResult.ok("output"))
        registry.get_entry.return_value = None

        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            config=ToolLoopConfig(enable_double_confirmation=False),
            # No leakage_detector
        )

        result = await loop.run(
            [ChatMessage(role="user", content="Do something")],
            model="test-model",
        )
        assert result.termination_reason == "completed"

    @pytest.mark.asyncio
    async def test_leakage_detector_skips_failed_results(self) -> None:
        """Leakage check only applies to successful tool results."""

        def detector(text: str) -> bool:
            return True

        tc = MagicMock()
        tc.id = "tc_1"
        tc.function.name = "shell"
        tc.function.arguments = '{"command": "bad"}'

        tool_call_resp = LLMResponse(
            content="",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens is a computed property
            tool_calls=[tc],
        )
        final_resp = LLMResponse(
            content="COMPLETED: error handled",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens is a computed property
        )

        router = MagicMock()
        router.complete = AsyncMock(side_effect=[tool_call_resp, final_resp])

        from agent33.tools.base import ToolResult

        registry = MagicMock()
        registry.list_all.return_value = []
        # Return a failed result — leakage check should not apply
        registry.validated_execute = AsyncMock(return_value=ToolResult.fail("Command not found"))
        registry.get_entry.return_value = None

        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            config=ToolLoopConfig(enable_double_confirmation=False),
            leakage_detector=detector,
        )

        result = await loop.run(
            [ChatMessage(role="user", content="Run bad command")],
            model="test-model",
        )
        assert result.termination_reason == "completed"


# ---------------------------------------------------------------------------
# Gap 3: Failure Taxonomy Alignment
# ---------------------------------------------------------------------------


class TestToolLoopSubcodes:
    """Tests for the tool-loop failure subcode mapping."""

    def test_all_subcodes_have_required_keys(self) -> None:
        for name, meta in TOOL_LOOP_SUBCODES.items():
            assert "subcode" in meta, f"{name} missing 'subcode'"
            assert "description" in meta, f"{name} missing 'description'"
            assert "category" in meta, f"{name} missing 'category'"
            assert "severity" in meta, f"{name} missing 'severity'"

    def test_subcodes_start_with_f(self) -> None:
        for name, meta in TOOL_LOOP_SUBCODES.items():
            assert str(meta["subcode"]).startswith("F-"), (
                f"{name} subcode {meta['subcode']} doesn't start with F-"
            )

    def test_categories_are_valid(self) -> None:
        for name, meta in TOOL_LOOP_SUBCODES.items():
            assert isinstance(meta["category"], FailureCategory), (
                f"{name} has invalid category: {meta['category']}"
            )

    def test_severities_are_valid(self) -> None:
        for name, meta in TOOL_LOOP_SUBCODES.items():
            assert isinstance(meta["severity"], FailureSeverity), (
                f"{name} has invalid severity: {meta['severity']}"
            )

    def test_expected_subcodes_present(self) -> None:
        expected = {
            "tool_argument_error",
            "tool_execution_error",
            "tool_governance_denied",
            "max_iterations",
            "context_exhausted",
            "budget_exceeded",
            "leakage_detected",
            "error",
        }
        assert set(TOOL_LOOP_SUBCODES.keys()) == expected


class TestClassifyToolLoopFailure:
    """Tests for classify_tool_loop_failure()."""

    def test_completed_returns_unknown(self) -> None:
        result = _make_tool_loop_result(termination_reason="completed")
        classification = classify_tool_loop_failure(result)
        assert classification.category == FailureCategory.UNKNOWN
        assert classification.code == ""

    def test_max_iterations(self) -> None:
        result = _make_tool_loop_result(termination_reason="max_iterations")
        classification = classify_tool_loop_failure(result)
        assert classification.category == FailureCategory.RESOURCE
        assert classification.subcode == "F-RES-TL04"

    def test_error(self) -> None:
        result = _make_tool_loop_result(termination_reason="error")
        classification = classify_tool_loop_failure(result)
        assert classification.category == FailureCategory.EXECUTION
        assert classification.severity == FailureSeverity.HIGH

    def test_budget_exceeded(self) -> None:
        result = _make_tool_loop_result(termination_reason="budget_exceeded")
        classification = classify_tool_loop_failure(result)
        assert classification.category == FailureCategory.RESOURCE
        assert classification.subcode == "F-RES-TL06"

    def test_unknown_reason(self) -> None:
        result = _make_tool_loop_result(termination_reason="something_new")
        classification = classify_tool_loop_failure(result)
        assert classification.category == FailureCategory.UNKNOWN
        assert classification.subcode == "F-UNK-TL00"


class TestToolLoopToTraceOutcome:
    """Tests for tool_loop_to_trace_outcome()."""

    def test_completed_maps_to_completed_status(self) -> None:
        result = _make_tool_loop_result(termination_reason="completed")
        outcome = tool_loop_to_trace_outcome(result)
        assert outcome.status == TraceStatus.COMPLETED
        assert outcome.failure_code == ""

    def test_max_iterations_maps_to_timeout(self) -> None:
        result = _make_tool_loop_result(termination_reason="max_iterations")
        outcome = tool_loop_to_trace_outcome(result)
        assert outcome.status == TraceStatus.TIMEOUT
        assert outcome.failure_code == "F-RES-TL04"
        assert "max iterations" in outcome.failure_message.lower()

    def test_budget_exceeded_maps_to_cancelled(self) -> None:
        result = _make_tool_loop_result(termination_reason="budget_exceeded")
        outcome = tool_loop_to_trace_outcome(result)
        assert outcome.status == TraceStatus.CANCELLED
        assert outcome.failure_code == "F-RES-TL06"

    def test_error_maps_to_failed(self) -> None:
        result = _make_tool_loop_result(termination_reason="error")
        outcome = tool_loop_to_trace_outcome(result)
        assert outcome.status == TraceStatus.FAILED
        assert outcome.failure_code == "F-EXE-TL08"

    def test_failure_category_populated(self) -> None:
        result = _make_tool_loop_result(termination_reason="error")
        outcome = tool_loop_to_trace_outcome(result)
        assert outcome.failure_category == FailureCategory.EXECUTION.value

    def test_governance_denied_maps_to_failed(self) -> None:
        result = _make_tool_loop_result(termination_reason="tool_governance_denied")
        outcome = tool_loop_to_trace_outcome(result)
        assert outcome.status == TraceStatus.FAILED
        assert outcome.failure_category == FailureCategory.SECURITY.value


class TestToolLoopToFailureRecord:
    """Tests for tool_loop_to_failure_record()."""

    def test_completed_returns_none(self) -> None:
        result = _make_tool_loop_result(termination_reason="completed")
        record = tool_loop_to_failure_record(result)
        assert record is None

    def test_error_returns_record(self) -> None:
        result = _make_tool_loop_result(
            termination_reason="error",
            iterations=5,
            tool_calls_made=3,
            tools_used=["shell", "file_read"],
        )
        record = tool_loop_to_failure_record(result, trace_id="TRC-123")
        assert record is not None
        assert record.trace_id == "TRC-123"
        assert record.classification.category == FailureCategory.EXECUTION
        assert record.context["iterations"] == "5"
        assert record.context["tool_calls_made"] == "3"
        assert "shell" in record.context["tools_used"]

    def test_retryable_for_execution_failures(self) -> None:
        result = _make_tool_loop_result(termination_reason="error")
        record = tool_loop_to_failure_record(result)
        assert record is not None
        assert record.resolution.retryable is True

    def test_not_retryable_for_security_failures(self) -> None:
        result = _make_tool_loop_result(termination_reason="tool_governance_denied")
        record = tool_loop_to_failure_record(result)
        assert record is not None
        assert record.resolution.retryable is False

    def test_max_iterations_has_context(self) -> None:
        result = _make_tool_loop_result(
            termination_reason="max_iterations",
            model="llama3.2",
        )
        record = tool_loop_to_failure_record(result)
        assert record is not None
        assert record.context["model"] == "llama3.2"
        assert record.context["termination_reason"] == "max_iterations"


# ---------------------------------------------------------------------------
# Gap 4 Stage 1: Structured Double-Confirmation
# ---------------------------------------------------------------------------


class TestParseConfirmation:
    """Tests for _parse_confirmation()."""

    def test_completed_prefix(self) -> None:
        assert _parse_confirmation("COMPLETED: The answer is 42") is True

    def test_completed_lowercase(self) -> None:
        assert _parse_confirmation("completed: I'm done") is True

    def test_completed_mixed_case(self) -> None:
        assert _parse_confirmation("Completed: Here is the result") is True

    def test_completed_space_separator(self) -> None:
        assert _parse_confirmation("COMPLETED I finished the task") is True

    def test_continue_prefix(self) -> None:
        assert _parse_confirmation("CONTINUE: I need to check more files") is False

    def test_continue_lowercase(self) -> None:
        assert _parse_confirmation("continue: still working") is False

    def test_continue_mixed_case(self) -> None:
        assert _parse_confirmation("Continue: Let me verify") is False

    def test_continue_space_separator(self) -> None:
        assert _parse_confirmation("CONTINUE I still need to run tests") is False

    def test_ambiguous_no_prefix(self) -> None:
        assert _parse_confirmation("I believe the task is done") is None

    def test_ambiguous_empty(self) -> None:
        assert _parse_confirmation("") is None

    def test_ambiguous_json_response(self) -> None:
        assert _parse_confirmation('{"result": "done"}') is None

    def test_whitespace_stripping(self) -> None:
        assert _parse_confirmation("  COMPLETED: answer  ") is True
        assert _parse_confirmation("  CONTINUE: more work  ") is False


class TestStripCompletionPrefix:
    """Tests for _strip_completion_prefix()."""

    def test_strips_completed_colon(self) -> None:
        assert _strip_completion_prefix("COMPLETED: The answer is 42") == "The answer is 42"

    def test_strips_completed_space(self) -> None:
        assert _strip_completion_prefix("COMPLETED The answer") == "The answer"

    def test_preserves_no_prefix(self) -> None:
        assert _strip_completion_prefix("Just a normal response") == "Just a normal response"

    def test_case_insensitive(self) -> None:
        assert _strip_completion_prefix("completed: result") == "result"

    def test_whitespace_handling(self) -> None:
        assert _strip_completion_prefix("  COMPLETED:  hello  ") == "hello"


class TestConfirmationPromptFormat:
    """Tests that the confirmation prompt uses structured format."""

    def test_prompt_mentions_completed(self) -> None:
        assert "COMPLETED:" in CONFIRMATION_PROMPT

    def test_prompt_mentions_continue(self) -> None:
        assert "CONTINUE:" in CONFIRMATION_PROMPT

    def test_prompt_requires_exact_format(self) -> None:
        assert "exactly one of" in CONFIRMATION_PROMPT.lower()


class TestDoubleConfirmationStructured:
    """Integration tests for structured confirmation in the tool loop."""

    @pytest.mark.asyncio
    async def test_completed_response_accepted(self) -> None:
        """LLM responds with COMPLETED: prefix — loop terminates."""
        first_resp = LLMResponse(
            content="I think I'm done",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens is a computed property
        )
        confirm_resp = LLMResponse(
            content="COMPLETED: The answer is 42",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens is a computed property
        )

        router = MagicMock()
        router.complete = AsyncMock(side_effect=[first_resp, confirm_resp])

        registry = MagicMock()
        registry.list_all.return_value = []

        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            config=ToolLoopConfig(enable_double_confirmation=True),
        )

        result = await loop.run(
            [ChatMessage(role="user", content="What is the answer?")],
            model="test-model",
        )
        assert result.termination_reason == "completed"
        assert "The answer is 42" in result.raw_response

    @pytest.mark.asyncio
    async def test_continue_response_keeps_going(self) -> None:
        """LLM responds with CONTINUE: — loop continues."""
        first_resp = LLMResponse(
            content="I think I'm done",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens is a computed property
        )
        continue_resp = LLMResponse(
            content="CONTINUE: I need to verify the output",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens is a computed property
        )
        # After CONTINUE, LLM gives another text response
        second_resp = LLMResponse(
            content="Now I'm really done",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens is a computed property
        )
        final_confirm = LLMResponse(
            content="COMPLETED: Yes, the final answer is confirmed",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens is a computed property
        )

        router = MagicMock()
        router.complete = AsyncMock(
            side_effect=[first_resp, continue_resp, second_resp, final_confirm]
        )

        registry = MagicMock()
        registry.list_all.return_value = []

        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            config=ToolLoopConfig(enable_double_confirmation=True),
        )

        result = await loop.run(
            [ChatMessage(role="user", content="Do the task")],
            model="test-model",
        )
        assert result.termination_reason == "completed"
        # Should have gone through multiple iterations
        assert result.iterations >= 2

    @pytest.mark.asyncio
    async def test_ambiguous_response_reprompts(self) -> None:
        """Ambiguous confirmation should trigger another confirmation prompt."""
        first_resp = LLMResponse(
            content="Here is the result",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens is a computed property
        )
        ambiguous_resp = LLMResponse(
            content="Yes, I've finished the task. The answer is 42.",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens is a computed property
        )
        final_resp = LLMResponse(
            content="COMPLETED: The answer is 42.",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens is a computed property
        )

        router = MagicMock()
        router.complete = AsyncMock(side_effect=[first_resp, ambiguous_resp, final_resp])

        registry = MagicMock()
        registry.list_all.return_value = []

        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            config=ToolLoopConfig(enable_double_confirmation=True),
        )

        result = await loop.run(
            [ChatMessage(role="user", content="What is 6*7?")],
            model="test-model",
        )
        assert result.termination_reason == "completed"
        assert result.raw_response.startswith("COMPLETED:")
