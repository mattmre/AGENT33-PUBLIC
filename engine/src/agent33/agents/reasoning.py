"""5-phase reasoning protocol with NextAction FSM.

Wraps the tool-use loop in a structured OBSERVE → PLAN → EXECUTE → VERIFY →
LEARN cycle with composable ISC guardrails.  Inspired by Agno's NextAction
FSM pattern, adapted for AGENT-33's multi-agent architecture.
"""

from __future__ import annotations

import dataclasses
import logging
import os
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from agent33.llm.base import ChatMessage

if TYPE_CHECKING:
    from agent33.agents.isc import GuardrailResult, ISCManager
    from agent33.agents.stuck_detector import StuckDetection, StuckDetector
    from agent33.agents.tool_loop import ToolLoop
    from agent33.llm.router import ModelRouter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class NextAction(StrEnum):
    """FSM actions that determine phase transitions."""

    CONTINUE = "continue"
    VALIDATE = "validate"
    FINAL_ANSWER = "final_answer"
    RESET = "reset"


class ReasoningPhase(StrEnum):
    """The five phases of the reasoning protocol."""

    OBSERVE = "observe"
    PLAN = "plan"
    EXECUTE = "execute"
    VERIFY = "verify"
    LEARN = "learn"


# ---------------------------------------------------------------------------
# Phase artifacts (all frozen)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class ObserveArtifact:
    observations: list[str]
    constraints: list[str]
    anti_criteria: list[str]


@dataclasses.dataclass(frozen=True, slots=True)
class PlanArtifact:
    plan_steps: list[str]
    approach: str
    estimated_steps: int


@dataclasses.dataclass(frozen=True, slots=True)
class ExecuteArtifact:
    tool_loop_result: Any
    raw_output: str


@dataclasses.dataclass(frozen=True, slots=True)
class VerifyArtifact:
    isc_results: list[GuardrailResult]
    all_passed: bool
    failed_criteria: list[str]


@dataclasses.dataclass(frozen=True, slots=True)
class LearnArtifact:
    lessons: list[str]
    recommendations: list[str]
    confidence_delta: float


# ---------------------------------------------------------------------------
# Pydantic model (for API serialization)
# ---------------------------------------------------------------------------


class ReasoningStep(BaseModel):
    """A single step in the reasoning trace."""

    step_id: str = Field(default_factory=lambda: f"rs-{os.urandom(6).hex()}")
    title: str = ""
    action: str = ""
    result: str = ""
    reasoning: str = ""
    next_action: str = NextAction.CONTINUE.value
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    phase: str = ReasoningPhase.OBSERVE.value


# ---------------------------------------------------------------------------
# Config / State / Result
# ---------------------------------------------------------------------------

_ALL_PHASES = (
    ReasoningPhase.OBSERVE,
    ReasoningPhase.PLAN,
    ReasoningPhase.EXECUTE,
    ReasoningPhase.VERIFY,
    ReasoningPhase.LEARN,
)


@dataclasses.dataclass(frozen=True, slots=True)
class ReasoningConfig:
    max_steps: int = 25
    quality_gate_threshold: float = 0.7
    enable_anti_criteria: bool = True
    phases_enabled: tuple[ReasoningPhase, ...] = _ALL_PHASES
    phase_dispatch_max_retries: int = 1
    enable_graceful_degradation: bool = True
    degraded_step_confidence: float = 0.8


@dataclasses.dataclass(slots=True)
class ReasoningState:
    current_phase: ReasoningPhase = ReasoningPhase.OBSERVE
    steps: list[ReasoningStep] = dataclasses.field(default_factory=list)
    current_step_index: int = 0
    phase_artifacts: dict[str, Any] = dataclasses.field(default_factory=dict)
    validated: bool = False
    reset_count: int = 0


@dataclasses.dataclass(frozen=True, slots=True)
class ReasoningResult:
    steps: list[ReasoningStep]
    final_output: str
    phase_artifacts: dict[str, Any]
    termination_reason: str
    total_steps: int


# ---------------------------------------------------------------------------
# FSM transition rules
# ---------------------------------------------------------------------------

_PHASE_ORDER: list[ReasoningPhase] = [
    ReasoningPhase.OBSERVE,
    ReasoningPhase.PLAN,
    ReasoningPhase.EXECUTE,
    ReasoningPhase.VERIFY,
    ReasoningPhase.LEARN,
]

_VALID_ACTIONS: dict[ReasoningPhase, set[NextAction]] = {
    ReasoningPhase.OBSERVE: {NextAction.CONTINUE, NextAction.RESET},
    ReasoningPhase.PLAN: {NextAction.CONTINUE, NextAction.RESET},
    ReasoningPhase.EXECUTE: {NextAction.CONTINUE, NextAction.VALIDATE, NextAction.RESET},
    ReasoningPhase.VERIFY: {NextAction.VALIDATE, NextAction.RESET, NextAction.CONTINUE},
    ReasoningPhase.LEARN: {NextAction.FINAL_ANSWER, NextAction.RESET},
}


def _next_phase(current: ReasoningPhase) -> ReasoningPhase | None:
    """Return the next phase in order, or ``None`` if at the end."""
    idx = _PHASE_ORDER.index(current)
    if idx + 1 < len(_PHASE_ORDER):
        return _PHASE_ORDER[idx + 1]
    return None


# ---------------------------------------------------------------------------
# Reasoning Protocol
# ---------------------------------------------------------------------------


class ReasoningProtocol:
    """5-phase reasoning loop wrapping the tool-use loop.

    Parameters
    ----------
    config:
        Reasoning configuration (max steps, quality gate, etc.)
    isc_manager:
        Optional ISC manager for the VERIFY phase.
    stuck_detector:
        Reserved for Phase 29.4 (OpenHands StuckDetector integration).
    """

    _MAX_RESETS = 3

    def __init__(
        self,
        config: ReasoningConfig | None = None,
        isc_manager: ISCManager | None = None,
        stuck_detector: StuckDetector | None = None,
    ) -> None:
        self._config = config or ReasoningConfig()
        self._isc_manager = isc_manager
        self._stuck_detector = stuck_detector

    async def run(
        self,
        task_input: str,
        tool_loop: ToolLoop,
        model: str,
        router: ModelRouter,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system_prompt: str = "",
    ) -> ReasoningResult:
        """Execute the full reasoning protocol.

        Loops through phases (OBSERVE → PLAN → EXECUTE → VERIFY → LEARN),
        calling phase handlers, recording steps, and processing FSM actions.
        """
        state = ReasoningState()

        while state.current_step_index < self._config.max_steps:
            # Skip disabled phases
            if state.current_phase not in self._config.phases_enabled:
                nxt = _next_phase(state.current_phase)
                if nxt is None:
                    break
                state.current_phase = nxt
                continue

            # Call phase handler
            step, next_action, terminal_reason = await self._dispatch_phase_with_recovery(
                state=state,
                task_input=task_input,
                tool_loop=tool_loop,
                model=model,
                router=router,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )

            if terminal_reason is not None:
                if step is not None:
                    state.steps.append(step)
                    state.current_step_index += 1
                return self._build_result(state, terminal_reason)

            if step is None or next_action is None:  # defensive: unreachable
                return self._build_result(state, "phase_dispatch_failed")

            state.steps.append(step)
            state.current_step_index += 1

            # Validate the action against FSM rules
            valid = _VALID_ACTIONS.get(state.current_phase, set())
            if next_action not in valid:
                logger.warning(
                    "Invalid action %s for phase %s, defaulting to CONTINUE",
                    next_action,
                    state.current_phase,
                )
                next_action = NextAction.CONTINUE

            if self._stuck_detector is not None:
                try:
                    detection = self._stuck_detector.detect(
                        steps=state.steps,
                        phase_artifacts=state.phase_artifacts,
                        current_phase=state.current_phase.value,
                        normalized_action=next_action.value,
                    )
                    if detection is not None:
                        state.phase_artifacts["stuck_detector"] = self._stuck_metadata(
                            detection=detection,
                            state=state,
                            normalized_action=next_action,
                        )
                        return self._build_result(state, "stuck_detected")
                except Exception as exc:  # pragma: no cover - covered by integration test
                    logger.warning("Stuck detector failed: %s", exc)
                    logger.debug("Stuck detector exception details", exc_info=True)

            # Quality gate: if confidence drops below threshold, reset
            if step.confidence < self._config.quality_gate_threshold:
                logger.info(
                    "Quality gate triggered (%.2f < %.2f), resetting",
                    step.confidence,
                    self._config.quality_gate_threshold,
                )
                next_action = NextAction.RESET

            # Process action
            if next_action == NextAction.RESET:
                state.reset_count += 1
                if state.reset_count > self._MAX_RESETS:
                    return self._build_result(state, "max_resets_exceeded")
                state.current_phase = ReasoningPhase.OBSERVE
                state.validated = False
                continue

            if next_action == NextAction.VALIDATE:
                state.current_phase = ReasoningPhase.VERIFY
                continue

            if next_action == NextAction.FINAL_ANSWER:
                # Hard gate: only reachable from LEARN and only if validated
                if state.current_phase != ReasoningPhase.LEARN or not state.validated:
                    logger.warning(
                        "FINAL_ANSWER rejected: phase=%s validated=%s",
                        state.current_phase,
                        state.validated,
                    )
                    next_action = NextAction.CONTINUE
                else:
                    # Extract output from ExecuteArtifact
                    output = self._extract_output(state)
                    return ReasoningResult(
                        steps=list(state.steps),
                        final_output=output,
                        phase_artifacts=dict(state.phase_artifacts),
                        termination_reason="completed",
                        total_steps=state.current_step_index,
                    )

            # CONTINUE: advance to next phase
            if next_action == NextAction.CONTINUE:
                nxt = _next_phase(state.current_phase)
                if nxt is None:
                    # Cycle back to OBSERVE (normal multi-cycle)
                    state.current_phase = ReasoningPhase.OBSERVE
                else:
                    state.current_phase = nxt

        return self._build_result(state, "max_steps_exceeded")

    # ------------------------------------------------------------------
    # Phase dispatch
    # ------------------------------------------------------------------

    async def _dispatch_phase(
        self,
        state: ReasoningState,
        task_input: str,
        tool_loop: ToolLoop,
        model: str,
        router: ModelRouter,
        temperature: float,
        max_tokens: int | None,
        system_prompt: str,
    ) -> tuple[ReasoningStep, NextAction]:
        """Route to the correct phase handler."""
        phase = state.current_phase
        if phase == ReasoningPhase.OBSERVE:
            return await self._phase_observe(
                state, task_input, model, router, temperature, max_tokens, system_prompt
            )
        if phase == ReasoningPhase.PLAN:
            return await self._phase_plan(
                state, task_input, model, router, temperature, max_tokens, system_prompt
            )
        if phase == ReasoningPhase.EXECUTE:
            return await self._phase_execute(
                state, task_input, tool_loop, model, max_tokens, system_prompt
            )
        if phase == ReasoningPhase.VERIFY:
            return await self._phase_verify(state, task_input)
        if phase == ReasoningPhase.LEARN:
            return await self._phase_learn(
                state, task_input, model, router, temperature, max_tokens, system_prompt
            )
        # Unreachable, but satisfy type checker
        raise ValueError(f"Unknown phase: {phase}")  # pragma: no cover

    async def _dispatch_phase_with_recovery(
        self,
        state: ReasoningState,
        task_input: str,
        tool_loop: ToolLoop,
        model: str,
        router: ModelRouter,
        temperature: float,
        max_tokens: int | None,
        system_prompt: str,
    ) -> tuple[ReasoningStep | None, NextAction | None, str | None]:
        """Dispatch phase with bounded retries and optional graceful degradation."""
        retries = max(0, self._config.phase_dispatch_max_retries)
        total_attempts = retries + 1
        last_error: Exception | None = None

        for attempt in range(1, total_attempts + 1):
            try:
                step, action = await self._dispatch_phase(
                    state=state,
                    task_input=task_input,
                    tool_loop=tool_loop,
                    model=model,
                    router=router,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system_prompt=system_prompt,
                )
                if attempt > 1:
                    recovery_events = state.phase_artifacts.setdefault("recovery_events", [])
                    if isinstance(recovery_events, list):
                        recovery_events.append(
                            {
                                "phase": state.current_phase.value,
                                "status": "recovered",
                                "attempts": attempt,
                            }
                        )
                return step, action, None
            except Exception as exc:  # pragma: no cover - exercised via tests
                last_error = exc
                if attempt < total_attempts:
                    logger.warning(
                        "Phase dispatch failed (phase=%s, attempt=%d/%d): %s",
                        state.current_phase.value,
                        attempt,
                        total_attempts,
                        exc,
                    )
                    continue

        if not self._config.enable_graceful_degradation:
            if last_error is None:
                raise RuntimeError("Phase dispatch failed without exception context")
            raise last_error

        failure_phase = state.current_phase
        fail_closed = failure_phase == ReasoningPhase.VERIFY
        if fail_closed:
            state.validated = False
            degraded_action = NextAction.RESET
        else:
            degraded_action = NextAction.CONTINUE

        degraded_confidence = max(
            self._config.degraded_step_confidence,
            min(1.0, self._config.quality_gate_threshold + 0.01),
        )

        state.phase_artifacts["degradation"] = {
            "phase": failure_phase.value,
            "attempts": total_attempts,
            "error": str(last_error) if last_error is not None else "unknown_error",
            "graceful": True,
            "fail_closed": fail_closed,
        }

        degraded_step = ReasoningStep(
            title=f"Degraded {failure_phase.value} after dispatch failure",
            action=failure_phase.value,
            result=(
                f"Phase dispatch failed after {total_attempts} attempts; "
                "terminating with graceful degradation"
            ),
            reasoning=(f"Retries exhausted during phase dispatch. Fail-closed={fail_closed}."),
            next_action=degraded_action.value,
            confidence=degraded_confidence,
            phase=failure_phase.value,
        )

        return degraded_step, degraded_action, "degraded_phase_dispatch_failure"

    # ------------------------------------------------------------------
    # Phase handlers
    # ------------------------------------------------------------------

    async def _phase_observe(
        self,
        state: ReasoningState,
        task_input: str,
        model: str,
        router: ModelRouter,
        temperature: float,
        max_tokens: int | None,
        system_prompt: str,
    ) -> tuple[ReasoningStep, NextAction]:
        prompt = (
            f"{system_prompt}\n\n"
            "You are in the OBSERVE phase. Analyze the task and identify:\n"
            "1. Key observations about the task\n"
            "2. Constraints that must be satisfied\n"
            "3. Anti-criteria (things that should NOT happen)\n\n"
            f"Task: {task_input}\n\n"
            "Respond with your observations, constraints, and anti-criteria."
        )
        messages = [
            ChatMessage(role="system", content=prompt),
            ChatMessage(role="user", content=task_input),
        ]

        response = await router.complete(
            messages, model=model, temperature=temperature, max_tokens=max_tokens
        )

        artifact = ObserveArtifact(
            observations=[response.content[:500]],
            constraints=[],
            anti_criteria=[],
        )
        state.phase_artifacts["observe"] = artifact

        step = ReasoningStep(
            title="Observation",
            action="observe",
            result=response.content[:500],
            reasoning="Analyzed task requirements and constraints",
            next_action=NextAction.CONTINUE.value,
            confidence=0.8,
            phase=ReasoningPhase.OBSERVE.value,
        )
        return step, NextAction.CONTINUE

    async def _phase_plan(
        self,
        state: ReasoningState,
        task_input: str,
        model: str,
        router: ModelRouter,
        temperature: float,
        max_tokens: int | None,
        system_prompt: str,
    ) -> tuple[ReasoningStep, NextAction]:
        observe_artifact = state.phase_artifacts.get("observe")
        obs_context = ""
        if isinstance(observe_artifact, ObserveArtifact):
            obs_context = "\n".join(observe_artifact.observations)

        prompt = (
            f"{system_prompt}\n\n"
            "You are in the PLAN phase. Based on observations, create an execution plan.\n\n"
            f"Observations: {obs_context}\n"
            f"Task: {task_input}\n\n"
            "Respond with your plan steps and approach."
        )
        messages = [
            ChatMessage(role="system", content=prompt),
            ChatMessage(role="user", content=task_input),
        ]

        response = await router.complete(
            messages, model=model, temperature=temperature, max_tokens=max_tokens
        )

        artifact = PlanArtifact(
            plan_steps=[response.content[:500]],
            approach="structured",
            estimated_steps=3,
        )
        state.phase_artifacts["plan"] = artifact

        step = ReasoningStep(
            title="Planning",
            action="plan",
            result=response.content[:500],
            reasoning="Created execution plan based on observations",
            next_action=NextAction.CONTINUE.value,
            confidence=0.8,
            phase=ReasoningPhase.PLAN.value,
        )
        return step, NextAction.CONTINUE

    async def _phase_execute(
        self,
        state: ReasoningState,
        task_input: str,
        tool_loop: ToolLoop,
        model: str,
        max_tokens: int | None,
        system_prompt: str,
    ) -> tuple[ReasoningStep, NextAction]:
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=task_input),
        ]

        loop_result = await tool_loop.run(messages=messages, model=model, max_tokens=max_tokens)

        artifact = ExecuteArtifact(
            tool_loop_result=loop_result,
            raw_output=loop_result.raw_response,
        )
        state.phase_artifacts["execute"] = artifact

        step = ReasoningStep(
            title="Execution",
            action="execute",
            result=loop_result.raw_response[:500],
            reasoning=f"Executed via tool loop ({loop_result.iterations} iterations)",
            next_action=NextAction.VALIDATE.value,
            confidence=0.8,
            phase=ReasoningPhase.EXECUTE.value,
        )
        return step, NextAction.VALIDATE

    async def _phase_verify(
        self,
        state: ReasoningState,
        task_input: str,
    ) -> tuple[ReasoningStep, NextAction]:
        if self._isc_manager is None:
            # No ISC manager — auto-pass verification
            state.validated = True
            step = ReasoningStep(
                title="Verification (no ISC)",
                action="verify",
                result="No criteria configured — auto-passed",
                reasoning="ISC manager not configured, skipping verification",
                next_action=NextAction.CONTINUE.value,
                confidence=0.9,
                phase=ReasoningPhase.VERIFY.value,
            )
            return step, NextAction.CONTINUE

        context: dict[str, Any] = {
            "task_input": task_input,
            "phase_artifacts": state.phase_artifacts,
        }

        results = self._isc_manager.evaluate_all(
            context,
            enable_anti_criteria=self._config.enable_anti_criteria,
        )

        all_passed = all(r.success for r in results)
        failed = [r.criterion_name for r in results if not r.success]

        artifact = VerifyArtifact(
            isc_results=results,
            all_passed=all_passed,
            failed_criteria=failed,
        )
        state.phase_artifacts["verify"] = artifact
        state.validated = all_passed

        if all_passed:
            step = ReasoningStep(
                title="Verification passed",
                action="verify",
                result=f"All {len(results)} criteria passed",
                reasoning="All ISC criteria satisfied",
                next_action=NextAction.CONTINUE.value,
                confidence=0.95,
                phase=ReasoningPhase.VERIFY.value,
            )
            return step, NextAction.CONTINUE
        else:
            step = ReasoningStep(
                title="Verification failed",
                action="verify",
                result=f"Failed: {', '.join(failed)}",
                reasoning=f"{len(failed)} criteria failed verification",
                next_action=NextAction.RESET.value,
                confidence=0.3,
                phase=ReasoningPhase.VERIFY.value,
            )
            return step, NextAction.RESET

    async def _phase_learn(
        self,
        state: ReasoningState,
        task_input: str,
        model: str,
        router: ModelRouter,
        temperature: float,
        max_tokens: int | None,
        system_prompt: str,
    ) -> tuple[ReasoningStep, NextAction]:
        execute_result = ""
        execute_artifact = state.phase_artifacts.get("execute")
        if isinstance(execute_artifact, ExecuteArtifact):
            execute_result = execute_artifact.raw_output[:500]

        prompt = (
            f"{system_prompt}\n\n"
            "You are in the LEARN phase. Reflect on the execution result:\n\n"
            f"Task: {task_input}\n"
            f"Execution result: {execute_result}\n\n"
            "Provide lessons learned and recommendations."
        )
        messages = [
            ChatMessage(role="system", content=prompt),
            ChatMessage(role="user", content="Summarize lessons learned."),
        ]

        response = await router.complete(
            messages, model=model, temperature=temperature, max_tokens=max_tokens
        )

        artifact = LearnArtifact(
            lessons=[response.content[:300]],
            recommendations=[],
            confidence_delta=0.0,
        )
        state.phase_artifacts["learn"] = artifact

        # If validated, signal FINAL_ANSWER; otherwise RESET
        next_action = NextAction.FINAL_ANSWER if state.validated else NextAction.RESET

        step = ReasoningStep(
            title="Learning",
            action="learn",
            result=response.content[:500],
            reasoning="Reflected on execution and extracted lessons",
            next_action=next_action.value,
            confidence=0.85,
            phase=ReasoningPhase.LEARN.value,
        )
        return step, next_action

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_output(self, state: ReasoningState) -> str:
        """Extract the final output from the execute artifact."""
        execute_artifact = state.phase_artifacts.get("execute")
        if isinstance(execute_artifact, ExecuteArtifact):
            return execute_artifact.raw_output
        return ""

    def _build_result(
        self,
        state: ReasoningState,
        reason: str,
    ) -> ReasoningResult:
        return ReasoningResult(
            steps=list(state.steps),
            final_output=self._extract_output(state),
            phase_artifacts=dict(state.phase_artifacts),
            termination_reason=reason,
            total_steps=state.current_step_index,
        )

    def _stuck_metadata(
        self,
        detection: StuckDetection,
        state: ReasoningState,
        normalized_action: NextAction,
    ) -> dict[str, Any]:
        return {
            "triggered": True,
            "pattern": detection.pattern,
            "reason": detection.reason,
            "window_size": detection.window_size,
            "evidence": dict(detection.evidence),
            "phase": state.current_phase.value,
            "next_action": normalized_action.value,
            "step_index": state.current_step_index,
            "total_steps_seen": len(state.steps),
        }
