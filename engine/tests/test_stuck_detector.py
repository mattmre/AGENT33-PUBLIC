"""Focused tests for OpenHands-style stuck detector heuristics."""

from __future__ import annotations

from agent33.agents.reasoning import ReasoningStep
from agent33.agents.stuck_detector import OpenHandsStyleStuckDetector


def _step(action: str, result: str, reasoning: str = "") -> ReasoningStep:
    return ReasoningStep(
        action=action,
        result=result,
        reasoning=reasoning,
        phase=action,
    )


class TestOpenHandsStyleStuckDetector:
    def test_repeated_action_observation_pattern(self) -> None:
        detector = OpenHandsStyleStuckDetector()
        steps = [
            _step("observe", "same observation"),
            _step("observe", "same observation"),
            _step("observe", "same observation"),
            _step("observe", "same observation"),
        ]
        detection = detector.detect(steps, {}, "observe", "continue")
        assert detection is not None
        assert detection.pattern == "repeated_action_observation"

    def test_repeated_action_error_pattern(self) -> None:
        detector = OpenHandsStyleStuckDetector()
        steps = [
            _step("execute", "runtime error: file not found"),
            _step("execute", "runtime error: file not found"),
            _step("execute", "runtime error: file not found"),
            _step("execute", "runtime error: file not found"),
        ]
        detection = detector.detect(steps, {}, "execute", "validate")
        assert detection is not None
        assert detection.pattern == "repeated_action_error"

    def test_monologue_no_progress_pattern(self) -> None:
        detector = OpenHandsStyleStuckDetector()
        steps = [
            _step("observe", "thinking about approach"),
            _step("plan", "thinking about approach"),
            _step("learn", "thinking about approach"),
            _step("observe", "thinking about approach"),
            _step("plan", "thinking about approach"),
        ]
        detection = detector.detect(steps, {}, "plan", "continue")
        assert detection is not None
        assert detection.pattern == "monologue_no_progress"

    def test_abab_oscillation_pattern(self) -> None:
        detector = OpenHandsStyleStuckDetector()
        steps = [
            _step("observe", "obs 1"),
            _step("plan", "plan 1"),
            _step("observe", "obs 2"),
            _step("plan", "plan 2"),
        ]
        detection = detector.detect(steps, {}, "plan", "continue")
        assert detection is not None
        assert detection.pattern == "abab_oscillation"

    def test_context_condensation_loop_pattern(self) -> None:
        detector = OpenHandsStyleStuckDetector()
        steps = [
            _step("observe", "Need to summarize context due token limit."),
            _step("plan", "Compress context window again."),
            _step("learn", "Summarize context due token limit."),
            _step("plan", "Compress context window again."),
        ]
        detection = detector.detect(steps, {}, "plan", "continue")
        assert detection is not None
        assert detection.pattern == "context_condensation_loop"

    def test_no_detection_for_normal_progression(self) -> None:
        detector = OpenHandsStyleStuckDetector()
        steps = [
            _step("observe", "understood task"),
            _step("plan", "created plan"),
            _step("execute", "execution complete"),
            _step("verify", "checks passed"),
            _step("learn", "captured lessons"),
        ]
        detection = detector.detect(steps, {}, "learn", "final_answer")
        assert detection is None
