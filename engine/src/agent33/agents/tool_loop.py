"""Iterative tool-use loop for agent execution.

Implements the core loop that allows an agent to call tools repeatedly
until the task is complete, a budget is exceeded, or an error threshold
is reached.  This is the P0 capability gap identified in the SkillsBench
analysis.
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import logging
import re
from typing import TYPE_CHECKING, Any, cast

from agent33.llm.base import ChatMessage, LLMResponse, ToolCallDelta
from agent33.llm.stream_assembler import ToolCallAssembler
from agent33.tools.base import ToolResult
from agent33.tools.schema import generate_tool_description

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from agent33.agents.context_manager import ContextManager
    from agent33.agents.definition import AutonomyLevel
    from agent33.agents.events import ToolLoopEvent
    from agent33.autonomy.enforcement import RuntimeEnforcer
    from agent33.llm.router import ModelRouter
    from agent33.llm.text_tool_parser import TextToolParser
    from agent33.memory.context_compressor import ContextCompressor
    from agent33.memory.observation import ObservationCapture
    from agent33.observability.metrics import MetricsCollector
    from agent33.tools.base import ToolContext
    from agent33.tools.governance import ToolGovernance
    from agent33.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

CONFIRMATION_PROMPT = (
    "You indicated you have completed the task. Please respond with "
    "exactly one of the following formats:\n\n"
    "COMPLETED: [your final answer]\n"
    "CONTINUE: [what you still need to do]\n\n"
    "If the task is not fully complete, use CONTINUE and keep working. "
    "If it is complete, use COMPLETED and restate your final answer."
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class ToolLoopConfig:
    """Immutable configuration for a tool-use loop."""

    max_iterations: int = 20
    max_tool_calls_per_iteration: int = 5
    error_threshold: int = 3
    enable_double_confirmation: bool = True
    loop_detection_threshold: int = 0  # 0 disables loop detection by default
    text_tool_parser: TextToolParser | None = None
    evaluation_mode: bool = False
    """If True, run in evaluation mode: stricter context enforcement, no side
    effects recorded.

    In evaluation mode the loop:
    - Uses a simple word-count token estimate instead of the model's reported
      token count to ensure deterministic context-window enforcement
      independent of LLM availability.
    - Proactively evicts the oldest non-system messages when the estimated
      token count exceeds 90 % of ``model_context_window`` on the ToolLoop
      that owns this config.
    - Still respects ``max_iterations`` -- do NOT skip the termination logic.
    """


@dataclasses.dataclass(slots=True)
class ToolLoopState:
    """Mutable state tracked across loop iterations."""

    iteration: int = 0
    total_tokens: int = 0
    tool_calls_made: int = 0
    tools_used: list[str] = dataclasses.field(default_factory=list)
    consecutive_errors: int = 0
    confirmation_pending: bool = False
    call_history: list[str] = dataclasses.field(default_factory=list)
    token_usage_available: bool = True


@dataclasses.dataclass(frozen=True, slots=True)
class ToolLoopResult:
    """Immutable result returned when the loop terminates."""

    output: dict[str, Any]
    raw_response: str
    tokens_used: int
    model: str
    iterations: int
    tool_calls_made: int
    tools_used: list[str]
    termination_reason: str  # "completed", "max_iterations", "error", "budget_exceeded"
    tokens_available: bool = True


class _ToolExecError(Exception):
    """Raised inside the delegation relay to propagate tool execution errors."""


# ---------------------------------------------------------------------------
# ToolLoop
# ---------------------------------------------------------------------------


class ToolLoop:
    """Iterative tool-use loop for agent execution.

    Sends messages to an LLM via *router*, inspects the response for tool
    calls, executes them through *tool_registry* (with governance and
    autonomy checks), appends the results back to the conversation, and
    repeats until the LLM signals completion or a limit is reached.
    """

    def __init__(
        self,
        router: ModelRouter,
        tool_registry: ToolRegistry,
        tool_governance: ToolGovernance | None = None,
        tool_context: ToolContext | None = None,
        observation_capture: ObservationCapture | None = None,
        runtime_enforcer: RuntimeEnforcer | None = None,
        config: ToolLoopConfig | None = None,
        agent_name: str = "",
        session_id: str = "",
        context_manager: ContextManager | None = None,
        leakage_detector: Callable[[str], bool] | None = None,
        hook_registry: Any | None = None,
        tenant_id: str = "",
        autonomy_level: AutonomyLevel | None = None,
        context_compressor: ContextCompressor | None = None,
        model_context_window: int = 128_000,
        metrics_collector: MetricsCollector | None = None,
        *,
        redact_secrets: bool = True,
        allow_model_fallback: bool = False,
    ) -> None:
        self._router = router
        self._tool_registry = tool_registry
        self._tool_governance = tool_governance
        self._tool_context = tool_context
        self._observation_capture = observation_capture
        self._runtime_enforcer = runtime_enforcer
        self._config = config or ToolLoopConfig()
        self._agent_name = agent_name
        self._session_id = session_id
        self._context_manager = context_manager
        self._leakage_detector = leakage_detector
        self._hook_registry = hook_registry
        self._tenant_id = tenant_id
        self._autonomy_level = autonomy_level
        self._context_compressor = context_compressor
        self._model_context_window = model_context_window
        self._metrics = metrics_collector
        self._redact_secrets = redact_secrets
        self._allow_model_fallback = allow_model_fallback
        self._last_accumulated_messages: list[ChatMessage] | None = None
        self._last_relay_results: list[ToolResult] = []

    def last_messages(self) -> list[ChatMessage] | None:
        """Return the final message list from the most recent tool-loop run."""
        return self._last_accumulated_messages

    # ------------------------------------------------------------------
    # Evaluation-mode context budget enforcement
    # ------------------------------------------------------------------

    def _evict_for_context_budget(
        self,
        messages: list[ChatMessage],
        budget_tokens: int,
    ) -> None:
        """Evict oldest non-system messages until estimated token count fits in budget.

        Uses a simple word-count heuristic (words * 1.3) as a token estimate.
        System messages are never evicted.  At least 2 non-system messages are
        kept to preserve the most recent exchange.

        This is intentionally simple -- it is used only in evaluation mode where
        determinism matters more than precision.
        """

        def _estimate_tokens(msg: ChatMessage) -> int:
            content = msg.content or ""
            if isinstance(content, list):
                content = " ".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            return max(1, int(len(content.split()) * 1.3))

        while True:
            total = sum(_estimate_tokens(m) for m in messages)
            if total <= budget_tokens:
                break
            # Find oldest non-system message (keep at least 2 non-system)
            non_system = [i for i, m in enumerate(messages) if m.role != "system"]
            if len(non_system) <= 2:
                break
            messages.pop(non_system[0])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ToolLoopResult:
        """Execute the iterative tool-use loop.

        Parameters
        ----------
        messages:
            Initial conversation messages (system + user at minimum).
        model:
            Model identifier to pass to the router.
        temperature:
            Sampling temperature.
        max_tokens:
            Optional max-tokens cap per LLM call.

        Returns
        -------
        ToolLoopResult
            Contains the final output, token usage, iteration count,
            tool-call stats, and termination reason.
        """
        state = ToolLoopState()

        last_raw = ""
        last_model = model

        while state.iteration < self._config.max_iterations:
            state.iteration += 1  # 1-based iteration count
            tool_descriptions = self._collect_tool_descriptions()

            # --- Evaluation-mode: proactive context eviction ------------------
            if self._config.evaluation_mode:
                self._evict_for_context_budget(messages, int(self._model_context_window * 0.90))

            # --- Call the LLM -------------------------------------------------
            try:
                response = await self._router.complete(
                    messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tool_descriptions if tool_descriptions else None,
                    allow_fallback=self._allow_model_fallback,
                )
            except Exception:
                state.consecutive_errors += 1
                logger.warning(
                    "LLM call failed (attempt %d, consecutive_errors=%d)",
                    state.iteration,
                    state.consecutive_errors,
                    exc_info=True,
                )
                if state.consecutive_errors >= self._config.error_threshold:
                    return self._build_result(state, last_raw, last_model, "error")
                continue

            # --- Track tokens -------------------------------------------------
            self._track_token_usage(state, response)
            last_raw = response.content
            last_model = response.model

            # --- Text-based tool call parsing (Phase 36) ----------------------
            if not response.tool_calls and self._config.text_tool_parser:
                parsed = self._config.text_tool_parser.parse(response.content)
                if parsed:
                    response = dataclasses.replace(response, tool_calls=parsed)

            # --- Record observation for LLM response --------------------------
            await self._record_observation(
                event_type="llm_response",
                content=response.content[:2000],
                metadata={
                    "model": response.model,
                    "tokens": response.total_tokens if response.usage_available else None,
                    "usage_available": response.usage_available,
                    "has_tool_calls": response.has_tool_calls,
                    "iteration": state.iteration,
                },
            )

            # --- Handle tool calls --------------------------------------------
            if response.has_tool_calls:
                state.consecutive_errors = 0
                state.confirmation_pending = False

                # --- Doom-loop detection ---
                if self._config.loop_detection_threshold > 0:
                    loop_detected = self._check_doom_loop(response, state)
                    if loop_detected:
                        logger.warning(
                            "Doom-loop detected: identical tool call repeated %d times",
                            self._config.loop_detection_threshold,
                        )
                        return self._build_result(state, last_raw, last_model, "loop_detected")

                tool_results = await self._execute_tool_calls(response, state)

                # Check if budget enforcer blocked during tool execution
                if self._runtime_enforcer is not None and any(
                    tr.error == "__budget_blocked__" for tr in tool_results
                ):
                    return self._build_result(state, last_raw, last_model, "budget_exceeded")

                # Only include tool_calls that were actually processed in
                # the assistant message.  OpenAI-style APIs require every
                # tool_call id to have a matching role="tool" result; if
                # we cap at max_tool_calls_per_iteration the rest must
                # not appear in the conversation.
                assert response.tool_calls is not None  # guarded by has_tool_calls
                processed_tool_calls = response.tool_calls[: len(tool_results)]

                messages.append(
                    ChatMessage(
                        role="assistant",
                        content=response.content,
                        tool_calls=processed_tool_calls,
                    )
                )

                # Append tool result messages
                for i, tool_result in enumerate(tool_results):
                    tc = processed_tool_calls[i] if i < len(processed_tool_calls) else None
                    tc_id = tc.id if tc else ""
                    tc_name = tc.function.name if tc else ""
                    # Truncate raw tool output before adding to LLM context
                    from agent33.agents.context_manager import truncate_tool_output

                    content = (
                        truncate_tool_output(tool_result.output)
                        if tool_result.success
                        else f"Error: {truncate_tool_output(tool_result.error)}"
                    )
                    # Phase 52: redact secrets from tool output
                    from agent33.security.redaction import redact_secrets

                    content = redact_secrets(content, enabled=self._redact_secrets)
                    messages.append(
                        ChatMessage(
                            role="tool",
                            content=content,
                            tool_call_id=tc_id,
                            name=tc_name,
                        )
                    )

                # --- PHASE 34: Segmented Context Wipe (Handoff Interceptor) ---
                for tc, result in zip(processed_tool_calls, tool_results, strict=False):
                    if tc.function.name == "handoff" and result.success:
                        logger.info("PHASE 34: Intercepting Handoff -> Triggering Context Wipe.")
                        from agent33.workflows.actions.handoff import StateLedger, execute_handoff

                        try:
                            # Re-parse args, the registry already validated them
                            parsed_args = json.loads(tc.function.arguments)
                            ledger = StateLedger(**parsed_args.get("ledger_data", {}))
                            # Save system prompt before wiping, then reset conversation
                            system_content = messages[0].content if messages else ""
                            messages.clear()
                            wiped_messages = execute_handoff(
                                ledger,
                                [
                                    ChatMessage(
                                        role="system",
                                        content=system_content,
                                    )
                                ],
                            )
                            messages.extend(wiped_messages)

                            # Log to ui/observation for user visibility
                            obj = ledger.objective
                            await self._record_observation(
                                event_type="handoff_context_wipe",
                                content=f"Agent memory wiped. Fresh context + Objective: {obj}",
                                metadata={
                                    "source": ledger.source_agent,
                                    "target": ledger.target_agent,
                                },
                            )
                        except Exception as e:
                            logger.error(f"Handoff wipe failed unexpectedly: {e}")
            else:
                # --- Text-only response (no tool calls) -----------------------
                if not self._config.enable_double_confirmation:
                    output = self._parse_output(response.content)
                    return ToolLoopResult(
                        output=output,
                        raw_response=response.content,
                        tokens_used=state.total_tokens,
                        model=response.model,
                        iterations=state.iteration,
                        tool_calls_made=state.tool_calls_made,
                        tools_used=list(state.tools_used),
                        termination_reason="completed",
                        tokens_available=state.token_usage_available,
                    )

                if not state.confirmation_pending:
                    state.confirmation_pending = True
                    messages.append(ChatMessage(role="assistant", content=response.content))
                    messages.append(ChatMessage(role="user", content=CONFIRMATION_PROMPT))
                else:
                    # Parse structured confirmation response
                    final_text = response.content
                    confirmed = _parse_confirmation(final_text)

                    if confirmed is False:
                        # LLM said CONTINUE — keep going
                        state.confirmation_pending = False
                        messages.append(ChatMessage(role="assistant", content=response.content))
                        continue

                    if confirmed is None:
                        # Ambiguous response format; ask again for explicit confirmation.
                        messages.append(ChatMessage(role="assistant", content=response.content))
                        messages.append(ChatMessage(role="user", content=CONFIRMATION_PROMPT))
                        state.confirmation_pending = True
                        continue

                    # confirmed is True
                    final_text = _strip_completion_prefix(final_text)

                    output = self._parse_output(final_text)
                    return ToolLoopResult(
                        output=output,
                        raw_response=response.content,
                        tokens_used=state.total_tokens,
                        model=response.model,
                        iterations=state.iteration,
                        tool_calls_made=state.tool_calls_made,
                        tools_used=list(state.tools_used),
                        termination_reason="completed",
                        tokens_available=state.token_usage_available,
                    )

            # --- Context management after message changes ---------------------
            if self._context_manager is not None:
                messages = await self._context_manager.manage(messages)

            # --- Phase 50: Context compression --------------------------------
            if self._context_compressor is not None and self._context_compressor.needs_compression(
                messages, self._model_context_window
            ):
                try:
                    compressed, stats = await self._context_compressor.compress(
                        messages, model, self._router
                    )
                    # Atomic swap: replace the message list contents
                    messages.clear()
                    messages.extend(compressed)
                    logger.info(
                        "Context compression applied: %d -> %d tokens (ratio=%.2f)",
                        stats.original_tokens,
                        stats.compressed_tokens,
                        stats.compression_ratio,
                    )
                except Exception:
                    logger.warning(
                        "Context compression failed, continuing with uncompressed context",
                        exc_info=True,
                    )

            # --- Check termination conditions ---------------------------------
            if state.consecutive_errors >= self._config.error_threshold:
                return self._build_result(state, last_raw, last_model, "error")

            if self._runtime_enforcer is not None:
                from agent33.autonomy.models import EnforcementResult

                iter_result = self._runtime_enforcer.record_iteration()
                if iter_result == EnforcementResult.BLOCKED:
                    return self._build_result(state, last_raw, last_model, "budget_exceeded")

                dur_result = self._runtime_enforcer.check_duration()
                if dur_result == EnforcementResult.BLOCKED:
                    return self._build_result(state, last_raw, last_model, "budget_exceeded")

        # --- Max iterations exhausted -----------------------------------------
        return self._build_result(state, last_raw, last_model, "max_iterations")

    async def run_stream(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[ToolLoopEvent, None]:
        """Stream tool loop execution as events.

        Yields ToolLoopEvent objects for each significant step.
        Always terminates with a ``completed`` event.
        """
        from agent33.agents.events import ToolLoopEvent

        state = ToolLoopState()
        tools = self._collect_tool_descriptions()
        accumulated_messages = list(messages)

        yield ToolLoopEvent(
            event_type="loop_started",
            iteration=0,
            data={
                "max_iterations": self._config.max_iterations,
                "tools_count": len(tools),
            },
        )

        termination_reason = "max_iterations"
        final_response: LLMResponse | None = None
        last_response: LLMResponse | None = None

        try:
            while state.iteration < self._config.max_iterations:
                state.iteration += 1
                tools = self._collect_tool_descriptions()

                yield ToolLoopEvent(
                    event_type="iteration_started",
                    iteration=state.iteration,
                    data={"message_count": len(accumulated_messages)},
                )

                # --- Evaluation-mode: proactive context eviction ------------------
                if self._config.evaluation_mode:
                    self._evict_for_context_budget(
                        accumulated_messages, int(self._model_context_window * 0.90)
                    )

                # --- LLM call -------------------------------------------------
                yield ToolLoopEvent(
                    event_type="llm_request",
                    iteration=state.iteration,
                    data={
                        "model": model,
                        "temperature": temperature,
                        "tools_count": len(tools),
                    },
                )

                try:
                    stream_result: dict[str, LLMResponse] = {}
                    async for token_event in self._stream_response_events(
                        accumulated_messages,
                        result_holder=stream_result,
                        iteration=state.iteration,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        tools=tools or None,
                    ):
                        yield token_event
                    response = stream_result["response"]
                except Exception as exc:
                    if isinstance(exc, TypeError):
                        logger.warning(
                            "Streaming LLM call failed with non-retryable TypeError",
                            exc_info=True,
                        )
                        yield ToolLoopEvent(
                            event_type="error",
                            iteration=state.iteration,
                            data={
                                "error": str(exc),
                                "phase": "llm_call",
                                "retrying": False,
                            },
                        )
                        termination_reason = "llm_error"
                        break

                    state.consecutive_errors += 1
                    logger.warning(
                        "Streaming LLM call failed (attempt %d, consecutive_errors=%d)",
                        state.iteration,
                        state.consecutive_errors,
                        exc_info=True,
                    )
                    yield ToolLoopEvent(
                        event_type="error",
                        iteration=state.iteration,
                        data={
                            "error": str(exc),
                            "phase": "llm_call",
                            "consecutive_errors": state.consecutive_errors,
                            "retrying": state.consecutive_errors < self._config.error_threshold,
                        },
                    )
                    if state.consecutive_errors >= self._config.error_threshold:
                        termination_reason = "error"
                        break
                    continue

                self._track_token_usage(state, response)
                last_response = response

                yield ToolLoopEvent(
                    event_type="llm_response",
                    iteration=state.iteration,
                    data={
                        "has_tool_calls": bool(response.tool_calls),
                        "content_length": len(response.content or ""),
                        "prompt_tokens": (
                            response.prompt_tokens if response.usage_available else None
                        ),
                        "completion_tokens": (
                            response.completion_tokens if response.usage_available else None
                        ),
                        "usage_available": response.usage_available,
                        "finish_reason": response.finish_reason,
                    },
                )

                # --- Record observation for LLM response (parity with run()) ----
                await self._record_observation(
                    event_type="llm_response",
                    content=(response.content or "")[:2000],
                    metadata={
                        "model": response.model,
                        "tokens": (response.total_tokens if response.usage_available else None),
                        "usage_available": response.usage_available,
                        "has_tool_calls": response.has_tool_calls,
                        "iteration": state.iteration,
                    },
                )

                # --- Text-based tool call parsing (Phase 36) ------------------
                if (
                    not response.tool_calls
                    and response.content
                    and self._config.text_tool_parser is not None
                ):
                    parsed = self._config.text_tool_parser.parse(response.content)
                    if parsed:
                        response = dataclasses.replace(response, tool_calls=parsed)

                has_tool_calls = bool(response.tool_calls)

                if has_tool_calls:
                    state.consecutive_errors = 0
                    state.confirmation_pending = False
                    tool_names = [tc.function.name for tc in (response.tool_calls or [])]
                    yield ToolLoopEvent(
                        event_type="tool_call_requested",
                        iteration=state.iteration,
                        data={"tools": tool_names, "count": len(tool_names)},
                    )

                    # --- Doom-loop detection ----------------------------------
                    if self._config.loop_detection_threshold > 0 and self._check_doom_loop(
                        response, state
                    ):
                        yield ToolLoopEvent(
                            event_type="loop_detected",
                            iteration=state.iteration,
                            data={
                                "threshold": self._config.loop_detection_threshold,
                            },
                        )
                        termination_reason = "loop_detected"
                        final_response = response
                        break

                    # --- Emit tool_call_started for each call -----------------
                    for tc in response.tool_calls or []:
                        yield ToolLoopEvent(
                            event_type="tool_call_started",
                            iteration=state.iteration,
                            data={"tool": tc.function.name, "call_id": tc.id},
                        )

                    # --- Execute tool calls (with delegation relay) ------
                    _relay_result = self._execute_with_delegation_relay(response, state)
                    _relay_broke = False
                    try:
                        async for _relay_evt in _relay_result:
                            yield _relay_evt
                    except _ToolExecError as _te:
                        yield ToolLoopEvent(
                            event_type="error",
                            iteration=state.iteration,
                            data={
                                "error": str(_te),
                                "phase": "tool_execution",
                            },
                        )
                        termination_reason = "tool_error"
                        _relay_broke = True

                    if _relay_broke:
                        break

                    results = self._last_relay_results

                    # Emit tool_call_completed for each result
                    assert response.tool_calls is not None
                    processed_calls = response.tool_calls[: len(results)]
                    for tc, result in zip(processed_calls, results, strict=False):
                        yield ToolLoopEvent(
                            event_type="tool_call_completed",
                            iteration=state.iteration,
                            data={
                                "tool": tc.function.name,
                                "success": result.success,
                                "output_length": len(
                                    result.output if result.success else result.error
                                ),
                            },
                        )

                    # Check if budget enforcer blocked during tool execution
                    if self._runtime_enforcer is not None and any(
                        tr.error == "__budget_blocked__" for tr in results
                    ):
                        yield ToolLoopEvent(
                            event_type="tool_call_blocked",
                            iteration=state.iteration,
                            data={"reason": "budget_exceeded"},
                        )
                        termination_reason = "budget_exceeded"
                        final_response = response
                        break

                    # --- Append assistant + tool results -----------------------
                    processed_tool_calls = response.tool_calls[: len(results)]
                    accumulated_messages.append(
                        ChatMessage(
                            role="assistant",
                            content=response.content,
                            tool_calls=processed_tool_calls,
                        )
                    )
                    for i, tool_result in enumerate(results):
                        tc_obj = processed_tool_calls[i] if i < len(processed_tool_calls) else None
                        tc_id = tc_obj.id if tc_obj else ""
                        tc_name = tc_obj.function.name if tc_obj else ""
                        from agent33.agents.context_manager import truncate_tool_output

                        content = (
                            truncate_tool_output(tool_result.output)
                            if tool_result.success
                            else f"Error: {truncate_tool_output(tool_result.error)}"
                        )
                        # Phase 52: redact secrets from tool output
                        from agent33.security.redaction import redact_secrets

                        content = redact_secrets(content, enabled=self._redact_secrets)
                        accumulated_messages.append(
                            ChatMessage(
                                role="tool",
                                content=content,
                                tool_call_id=tc_id,
                                name=tc_name,
                            )
                        )

                    # --- PHASE 34: Segmented Context Wipe (Handoff Interceptor) ---
                    for tc, result in zip(processed_calls, results, strict=False):
                        if tc.function.name == "handoff" and result.success:
                            logger.info(
                                "PHASE 34: Intercepting Handoff -> "
                                "Triggering Context Wipe (stream)."
                            )
                            from agent33.workflows.actions.handoff import (
                                StateLedger,
                                execute_handoff,
                            )

                            try:
                                parsed_args = json.loads(tc.function.arguments)
                                ledger = StateLedger(**parsed_args.get("ledger_data", {}))
                                system_content = (
                                    accumulated_messages[0].content if accumulated_messages else ""
                                )
                                accumulated_messages.clear()
                                wiped_messages = execute_handoff(
                                    ledger,
                                    [
                                        ChatMessage(
                                            role="system",
                                            content=system_content,
                                        )
                                    ],
                                )
                                accumulated_messages.extend(wiped_messages)

                                obj = ledger.objective
                                yield ToolLoopEvent(
                                    event_type="handoff_context_wipe",
                                    iteration=state.iteration,
                                    data={
                                        "source": ledger.source_agent,
                                        "target": ledger.target_agent,
                                        "objective": obj,
                                    },
                                )
                                await self._record_observation(
                                    event_type="handoff_context_wipe",
                                    content=(
                                        f"Agent memory wiped. Fresh context + Objective: {obj}"
                                    ),
                                    metadata={
                                        "source": ledger.source_agent,
                                        "target": ledger.target_agent,
                                    },
                                )
                            except Exception as e:
                                logger.error(f"Handoff wipe failed unexpectedly: {e}")
                else:
                    # --- No tool calls — text response (double-confirmation) ---
                    if not self._config.enable_double_confirmation:
                        final_response = response
                        termination_reason = "completed"
                        break

                    if not state.confirmation_pending:
                        # First text-only response: ask for confirmation
                        state.confirmation_pending = True
                        accumulated_messages.append(
                            ChatMessage(role="assistant", content=response.content)
                        )
                        accumulated_messages.append(
                            ChatMessage(role="user", content=CONFIRMATION_PROMPT)
                        )
                        yield ToolLoopEvent(
                            event_type="confirmation_prompt",
                            iteration=state.iteration,
                            data={"content": response.content},
                        )
                        continue
                    else:
                        # Second+ text-only response: parse confirmation
                        confirmed = _parse_confirmation(response.content)

                        if confirmed is True:
                            final_text = _strip_completion_prefix(response.content)
                            final_response = dataclasses.replace(response, content=final_text)
                            yield ToolLoopEvent(
                                event_type="confirmation_result",
                                iteration=state.iteration,
                                data={"confirmed": True, "content": final_text},
                            )
                            termination_reason = "completed"
                            break
                        elif confirmed is False:
                            state.confirmation_pending = False
                            accumulated_messages.append(
                                ChatMessage(role="assistant", content=response.content)
                            )
                            yield ToolLoopEvent(
                                event_type="confirmation_result",
                                iteration=state.iteration,
                                data={"confirmed": False},
                            )
                            continue
                        else:
                            # Ambiguous — re-send confirmation prompt
                            accumulated_messages.append(
                                ChatMessage(role="assistant", content=response.content)
                            )
                            accumulated_messages.append(
                                ChatMessage(role="user", content=CONFIRMATION_PROMPT)
                            )
                            yield ToolLoopEvent(
                                event_type="confirmation_prompt",
                                iteration=state.iteration,
                                data={"content": response.content},
                            )
                            continue

                # --- Context management ---------------------------------------
                if self._context_manager is not None:
                    before_len = len(accumulated_messages)
                    accumulated_messages = await self._context_manager.manage(accumulated_messages)
                    if len(accumulated_messages) != before_len:
                        yield ToolLoopEvent(
                            event_type="context_managed",
                            iteration=state.iteration,
                            data={
                                "before": before_len,
                                "after": len(accumulated_messages),
                            },
                        )

                # --- Phase 50: Context compression --------------------------------
                if (
                    self._context_compressor is not None
                    and self._context_compressor.needs_compression(
                        accumulated_messages, self._model_context_window
                    )
                ):
                    try:
                        compressed, comp_stats = await self._context_compressor.compress(
                            accumulated_messages, model, self._router
                        )
                        before_count = len(accumulated_messages)
                        accumulated_messages = compressed
                        yield ToolLoopEvent(
                            event_type="context_compressed",
                            iteration=state.iteration,
                            data={
                                "before_tokens": comp_stats.original_tokens,
                                "after_tokens": comp_stats.compressed_tokens,
                                "messages_removed": comp_stats.messages_removed,
                                "before_messages": before_count,
                                "after_messages": len(accumulated_messages),
                                "ratio": comp_stats.compression_ratio,
                            },
                        )
                    except Exception as comp_exc:
                        yield ToolLoopEvent(
                            event_type="error",
                            iteration=state.iteration,
                            data={
                                "error": str(comp_exc),
                                "phase": "context_compression",
                            },
                        )

                if state.consecutive_errors >= self._config.error_threshold:
                    termination_reason = "error"
                    final_response = response
                    break

                if self._runtime_enforcer is not None:
                    from agent33.autonomy.models import EnforcementResult

                    iter_result = self._runtime_enforcer.record_iteration()
                    if iter_result == EnforcementResult.BLOCKED:
                        yield ToolLoopEvent(
                            event_type="tool_call_blocked",
                            iteration=state.iteration,
                            data={"reason": "budget_exceeded", "phase": "iteration"},
                        )
                        termination_reason = "budget_exceeded"
                        final_response = response
                        break

                    dur_result = self._runtime_enforcer.check_duration()
                    if dur_result == EnforcementResult.BLOCKED:
                        yield ToolLoopEvent(
                            event_type="tool_call_blocked",
                            iteration=state.iteration,
                            data={"reason": "budget_exceeded", "phase": "duration"},
                        )
                        termination_reason = "budget_exceeded"
                        final_response = response
                        break

        except Exception as exc:
            yield ToolLoopEvent(
                event_type="error",
                iteration=state.iteration,
                data={"error": str(exc), "phase": "loop"},
            )
            termination_reason = "error"

        # --- Expose accumulated messages for trajectory capture ----------------
        self._last_accumulated_messages = list(accumulated_messages)

        # --- Always emit completed event --------------------------------------
        response_for_output = final_response or last_response
        raw = (response_for_output.content if response_for_output else "") or ""
        parsed_output = self._parse_output(raw)
        yield ToolLoopEvent(
            event_type="completed",
            iteration=state.iteration,
            data={
                "termination_reason": termination_reason,
                "total_tokens": state.total_tokens if state.token_usage_available else None,
                "tokens_available": state.token_usage_available,
                "tool_calls_made": state.tool_calls_made,
                "tools_used": list(state.tools_used),
                "output": parsed_output,
            },
        )

    async def _stream_response_events(
        self,
        messages: list[ChatMessage],
        *,
        result_holder: dict[str, LLMResponse],
        iteration: int,
        model: str,
        temperature: float,
        max_tokens: int | None,
        tools: list[dict[str, Any]] | None,
    ) -> AsyncGenerator[ToolLoopEvent, None]:
        """Yield token events while constructing the effective LLM response."""
        from agent33.agents.events import ToolLoopEvent

        assembler = ToolCallAssembler()
        saw_stream_chunks = False
        saw_tool_delta = False
        content_parts: list[str] = []
        response_model = model
        prompt_tokens = 0
        completion_tokens = 0
        usage_available = False
        stream_finish_reason: str | None = None

        try:
            stream = self._router.stream_complete
        except AttributeError:
            saw_stream_chunks = False
        else:
            try:
                stream_result = stream(
                    messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                )
            except NotImplementedError:
                saw_stream_chunks = False
            else:
                try:
                    stream_iter = aiter(stream_result)
                except TypeError:
                    if inspect.iscoroutine(stream_result):
                        stream_result.close()
                    saw_stream_chunks = False
                else:
                    try:
                        async for chunk in cast("AsyncGenerator[Any, None]", stream_iter):
                            saw_stream_chunks = True
                            if chunk.delta_content:
                                content_parts.append(chunk.delta_content)
                                yield ToolLoopEvent(
                                    event_type="llm_token",
                                    iteration=iteration,
                                    data={"token": chunk.delta_content},
                                )
                            if chunk.tool_call_delta is not None:
                                assembler.add_delta(chunk.tool_call_delta)
                                saw_tool_delta = True
                            for index, tool_call in enumerate(chunk.delta_tool_calls):
                                assembler.add_delta(
                                    ToolCallDelta(
                                        index=index,
                                        id=tool_call.id,
                                        name=tool_call.function.name,
                                        arguments_fragment=tool_call.function.arguments,
                                    )
                                )
                                saw_tool_delta = True
                            if chunk.model:
                                response_model = chunk.model
                            if chunk.usage_available:
                                usage_available = True
                                prompt_tokens = max(prompt_tokens, chunk.prompt_tokens)
                                completion_tokens = max(
                                    completion_tokens,
                                    chunk.completion_tokens,
                                )
                            if chunk.finish_reason is not None:
                                stream_finish_reason = chunk.finish_reason
                    except NotImplementedError:
                        saw_stream_chunks = False
                    except TypeError as exc:
                        if not saw_stream_chunks and self._is_stream_unsupported_error(exc):
                            saw_stream_chunks = False
                        else:
                            raise
        if not saw_stream_chunks:
            result_holder["response"] = await self._router.complete(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                allow_fallback=self._allow_model_fallback,
            )
            return

        tool_calls = assembler.close()
        response = LLMResponse(
            content="".join(content_parts),
            model=response_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            tool_calls=tool_calls or None,
            finish_reason="tool_calls" if tool_calls else (stream_finish_reason or "stop"),
            usage_available=usage_available,
        )
        if not saw_tool_delta and not tool_calls and stream_finish_reason == "tool_calls":
            response = await self._router.complete(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                allow_fallback=self._allow_model_fallback,
            )
        result_holder["response"] = response

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_stream_unsupported_error(exc: TypeError) -> bool:
        """Return True when *exc* looks like a non-streaming provider fallback case."""
        message = str(exc)
        return any(
            marker in message
            for marker in (
                "__aiter__",
                "async iterable",
                "async iterator",
                "async for",
            )
        )

    def _collect_tool_descriptions(self) -> list[dict[str, Any]]:
        """Build OpenAI-style tool descriptions from the registry."""
        descriptions: list[dict[str, Any]] = []
        for tool in self._tool_registry.list_all():
            entry = self._tool_registry.get_entry(tool.name)
            descriptions.append(generate_tool_description(tool, entry))
        return descriptions

    def _check_doom_loop(
        self,
        response: LLMResponse,
        state: ToolLoopState,
    ) -> bool:
        """Check if the same tool call is being repeated consecutively.

        Returns True if the most recent tool call signature has been repeated
        threshold times in a row.
        """
        if not response.tool_calls:
            return False

        # Build canonical signature for the first tool call
        # (agent typically repeats the same call, not multiple different ones)
        tc = response.tool_calls[0]
        # Sort arguments to create a stable signature
        try:
            import json

            args_dict = json.loads(tc.function.arguments)
            sorted_args = json.dumps(args_dict, sort_keys=True)
        except (json.JSONDecodeError, TypeError) as e:
            logger.debug("Tool call JSON parse fallback: %s", e)
            sorted_args = tc.function.arguments

        signature = f"{tc.function.name}:{sorted_args}"

        # Add to history
        state.call_history.append(signature)

        # Check if the last N calls are identical
        threshold = self._config.loop_detection_threshold
        if len(state.call_history) < threshold:
            return False

        recent_calls = state.call_history[-threshold:]
        return len(set(recent_calls)) == 1

    async def _execute_with_delegation_relay(
        self,
        response: LLMResponse,
        state: ToolLoopState,
    ) -> AsyncGenerator[ToolLoopEvent, None]:
        """Run ``_execute_tool_calls`` while relaying delegation events.

        Temporarily injects an ``event_sink`` into the tool context so
        that tools (e.g. ``delegate_subtask``) can push delegation
        events into an ``asyncio.Queue``.  The queue is drained
        concurrently and each event is yielded to the caller.

        On completion, ``self._last_relay_results`` is populated with
        the tool-call results.  If tool execution raises, a
        ``_ToolExecError`` is raised after draining remaining events.
        """
        queue: asyncio.Queue[ToolLoopEvent | None] = asyncio.Queue()

        async def _sink(evt: ToolLoopEvent) -> None:
            queue.put_nowait(evt)

        original_context = self._tool_context
        if self._tool_context is not None:
            self._tool_context = dataclasses.replace(self._tool_context, event_sink=_sink)
        else:
            from agent33.tools.base import ToolContext

            self._tool_context = ToolContext(event_sink=_sink)

        exec_exception: Exception | None = None
        exec_results: list[ToolResult] = []

        async def _run() -> None:
            nonlocal exec_exception, exec_results
            try:
                exec_results = await self._execute_tool_calls(response, state)
            except Exception as exc:
                exec_exception = exc
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(_run())

        while True:
            evt = await queue.get()
            if evt is None:
                break
            yield evt

        await task
        self._tool_context = original_context
        self._last_relay_results = exec_results

        if exec_exception is not None:
            raise _ToolExecError(str(exec_exception)) from exec_exception

    async def _execute_tool_calls(
        self,
        response: LLMResponse,
        state: ToolLoopState,
    ) -> list[ToolResult]:
        """Execute tool calls from an LLM response, respecting caps."""
        results: list[ToolResult] = []
        assert response.tool_calls is not None

        calls_to_process = response.tool_calls[: self._config.max_tool_calls_per_iteration]

        for tool_call in calls_to_process:
            tool_name = tool_call.function.name
            call_id = tool_call.id

            # --- Parse arguments ---
            try:
                parsed_args = json.loads(tool_call.function.arguments)
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Malformed tool call arguments for %s (call_id=%s)",
                    tool_name,
                    call_id,
                )
                state.consecutive_errors += 1
                result = ToolResult.fail(f"Invalid JSON arguments for tool '{tool_name}'")
                results.append(result)
                await self._record_observation(
                    event_type="tool_call",
                    content=f"Error parsing arguments for {tool_name}",
                    metadata={
                        "tool": tool_name,
                        "call_id": call_id,
                        "success": False,
                        "error": "malformed_arguments",
                    },
                )
                continue

            # --- Governance check ---
            if self._tool_governance is not None:
                gov_context = self._tool_context or self._default_context()
                allowed = self._tool_governance.pre_execute_check(
                    tool_name,
                    parsed_args,
                    gov_context,
                    autonomy_level=self._autonomy_level,
                )
                if not allowed:
                    logger.info("Governance denied tool call: %s", tool_name)
                    result = ToolResult.fail(f"Tool '{tool_name}' blocked by governance policy")
                    results.append(result)
                    await self._record_observation(
                        event_type="tool_call",
                        content=f"Governance blocked {tool_name}",
                        metadata={
                            "tool": tool_name,
                            "call_id": call_id,
                            "success": False,
                            "error": "governance_blocked",
                        },
                    )
                    continue

            # --- Autonomy enforcement check ---
            if self._runtime_enforcer is not None:
                from agent33.autonomy.models import EnforcementResult

                # Dispatch enforcement by tool type so the enforcer
                # checks the actual resource (command string, file path,
                # URL) rather than the tool name.
                enforce_result = EnforcementResult.ALLOWED
                if tool_name == "shell" and "command" in parsed_args:
                    enforce_result = self._runtime_enforcer.check_command(parsed_args["command"])
                elif tool_name in ("file_read", "file_write", "file_ops"):
                    path = parsed_args.get("path", parsed_args.get("file", ""))
                    if tool_name == "file_read":
                        enforce_result = self._runtime_enforcer.check_file_read(path)
                    else:
                        enforce_result = self._runtime_enforcer.check_file_write(path)
                elif tool_name == "web_fetch":
                    url = parsed_args.get("url", "")
                    enforce_result = self._runtime_enforcer.check_network(url)
                else:
                    enforce_result = self._runtime_enforcer.check_command(tool_name)
                if enforce_result == EnforcementResult.BLOCKED:
                    logger.info("Autonomy enforcer blocked tool call: %s", tool_name)
                    result = ToolResult(
                        success=False,
                        error="__budget_blocked__",
                    )
                    results.append(result)
                    return results  # Stop processing further calls

            # --- Hook: tool.execute.pre ---
            if self._hook_registry is not None:
                from agent33.hooks.models import HookEventType, ToolHookContext

                pre_runner = self._hook_registry.get_chain_runner(
                    HookEventType.TOOL_EXECUTE_PRE, self._tenant_id
                )
                tool_hook_ctx = ToolHookContext(
                    event_type=HookEventType.TOOL_EXECUTE_PRE,
                    tenant_id=self._tenant_id,
                    metadata={},
                    tool_name=tool_name,
                    arguments=parsed_args,
                    tool_context=self._tool_context,
                )
                tool_hook_ctx = await pre_runner.run(tool_hook_ctx)
                if tool_hook_ctx.abort:
                    result = ToolResult.fail(f"Hook aborted: {tool_hook_ctx.abort_reason}")
                    results.append(result)
                    continue
                # Allow hooks to modify arguments
                parsed_args = tool_hook_ctx.arguments

            # --- Execute tool ---
            context = self._tool_context or self._default_context()
            try:
                result = await self._tool_registry.validated_execute(
                    tool_name, parsed_args, context
                )
            except Exception as exc:
                logger.warning(
                    "Tool execution failed: %s (call_id=%s): %s",
                    tool_name,
                    call_id,
                    exc,
                )
                state.consecutive_errors += 1
                result = ToolResult.fail(f"Tool '{tool_name}' raised: {exc}")

            # --- Hook: tool.execute.post ---
            if self._hook_registry is not None:
                from agent33.hooks.models import HookEventType, ToolHookContext

                post_runner = self._hook_registry.get_chain_runner(
                    HookEventType.TOOL_EXECUTE_POST, self._tenant_id
                )
                tool_hook_ctx = ToolHookContext(
                    event_type=HookEventType.TOOL_EXECUTE_POST,
                    tenant_id=self._tenant_id,
                    metadata={},
                    tool_name=tool_name,
                    arguments=parsed_args,
                    tool_context=self._tool_context,
                    result=result,
                )
                tool_hook_ctx = await post_runner.run(tool_hook_ctx)

            # --- Governance audit ---
            if self._tool_governance is not None:
                self._tool_governance.log_execution(tool_name, parsed_args, result)

            # --- Check for answer leakage in tool output ---
            if (
                self._leakage_detector is not None
                and result.success
                and result.output
                and self._leakage_detector(result.output)
            ):
                logger.info("Leakage detected in tool output for %s", tool_name)
                result = ToolResult.ok("[Tool output filtered: potential answer leakage detected]")
                await self._record_observation(
                    event_type="leakage_detected",
                    content=f"Answer leakage filtered from {tool_name} output",
                    metadata={"tool": tool_name, "call_id": call_id},
                )

            # --- Record observation ---
            await self._record_observation(
                event_type="tool_call",
                content=(
                    f"{tool_name}: {result.output[:500] if result.success else result.error[:500]}"
                ),
                metadata={
                    "tool": tool_name,
                    "call_id": call_id,
                    "success": result.success,
                    "arguments": parsed_args,
                },
            )

            # --- Track stats ---
            state.tool_calls_made += 1
            if tool_name not in state.tools_used:
                state.tools_used.append(tool_name)

            # --- Emit tool usage counter ---
            if self._metrics is not None:
                self._metrics.increment(f"tool_execution_{tool_name}_total")

            results.append(result)

        return results

    async def _record_observation(
        self,
        event_type: str,
        content: str,
        metadata: dict[str, Any],
    ) -> None:
        """Record an observation if capture is configured."""
        if self._observation_capture is None:
            return
        try:
            from agent33.memory.observation import Observation

            obs = Observation(
                session_id=self._session_id,
                agent_name=self._agent_name,
                event_type=event_type,
                content=content,
                metadata=metadata,
            )
            await self._observation_capture.record(obs)
        except Exception:
            logger.debug("Failed to record observation", exc_info=True)

    @staticmethod
    def _parse_output(raw: str) -> dict[str, Any]:
        """Try to parse the LLM's final text as JSON.

        Falls back to wrapping the raw text in a ``{"response": ...}`` dict.
        """
        stripped = raw.strip()

        # Try direct JSON parse
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError) as e:
            logger.debug("Tool call JSON parse fallback: %s", e)

        # Strip markdown code fences and retry
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            inner_lines: list[str] = []
            in_block = False
            for line in lines:
                if line.strip().startswith("```") and not in_block:
                    in_block = True
                    continue
                if line.strip() == "```" and in_block:
                    break
                if in_block:
                    inner_lines.append(line)
            inner = "\n".join(inner_lines).strip()
            try:
                parsed = json.loads(inner)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, TypeError) as e:
                logger.debug("Tool call JSON parse fallback: %s", e)

        return {"response": raw}

    @staticmethod
    def _default_context() -> ToolContext:
        """Create a minimal ToolContext when none is provided."""
        from agent33.tools.base import ToolContext

        return ToolContext(user_scopes=["tools:execute"])

    def _build_result(
        self,
        state: ToolLoopState,
        raw: str,
        model: str,
        reason: str,
    ) -> ToolLoopResult:
        """Build a ToolLoopResult from current state."""
        return ToolLoopResult(
            output=self._parse_output(raw),
            raw_response=raw,
            tokens_used=state.total_tokens,
            model=model,
            iterations=state.iteration,
            tool_calls_made=state.tool_calls_made,
            tools_used=list(state.tools_used),
            termination_reason=reason,
            tokens_available=state.token_usage_available,
        )

    @staticmethod
    def _track_token_usage(state: ToolLoopState, response: LLMResponse) -> None:
        """Track token totals only when the provider reported them."""
        if response.usage_available:
            state.total_tokens += response.prompt_tokens + response.completion_tokens
            return
        state.token_usage_available = False


# ---------------------------------------------------------------------------
# Structured confirmation parsing (Gap 4 Stage 1)
# ---------------------------------------------------------------------------


def _parse_confirmation(text: str) -> bool | None:
    """Parse a structured COMPLETED/CONTINUE response.

    Returns
    -------
    True  — LLM confirmed completion ("COMPLETED: ...")
    False — LLM wants to continue ("CONTINUE: ...")
    None  — Ambiguous (no structured prefix found)
    """
    stripped = text.strip()
    upper = stripped.upper()

    if re.match(r"^CONTINUE(?:\b|[:\-\s])", upper):
        return False
    if re.match(r"^COMPLETED(?:\b|[:\-\s])", upper):
        return True
    return None


def _strip_completion_prefix(text: str) -> str:
    """Remove the ``COMPLETED:`` prefix from a confirmation response."""
    stripped = text.strip()
    return re.sub(r"^COMPLETED(?:[:\-\s]+)?", "", stripped, flags=re.IGNORECASE).strip()
