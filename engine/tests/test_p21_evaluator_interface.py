"""P2.1 — Evaluator Interface Abstraction.

Tests cover:
- EvaluationVerdict enum values
- EvaluationInput data class fields and defaults
- EvaluationResult data class fields
- Evaluator Protocol runtime checkability
- RuleBasedEvaluator evaluate() logic (pass/fail/skip/partial)
- RuleBasedEvaluator evaluate_batch() concurrency and ordering
- EvaluatorRegistry register/get/list/default lifecycle
- Module-level default_evaluator_registry bootstrap
"""

from __future__ import annotations

import pytest

from agent33.evaluation.evaluator_interface import (
    EvaluationInput,
    EvaluationResult,
    EvaluationVerdict,
    Evaluator,
)
from agent33.evaluation.evaluator_registry import (
    EvaluatorRegistry,
    default_evaluator_registry,
)
from agent33.evaluation.rule_based_evaluator import RuleBasedEvaluator

# ===================================================================
# EvaluationVerdict
# ===================================================================


class TestEvaluationVerdict:
    """Verify the verdict enum has the correct members."""

    def test_pass_value(self) -> None:
        assert EvaluationVerdict.PASS == "pass"

    def test_fail_value(self) -> None:
        assert EvaluationVerdict.FAIL == "fail"

    def test_skip_value(self) -> None:
        assert EvaluationVerdict.SKIP == "skip"

    def test_error_value(self) -> None:
        assert EvaluationVerdict.ERROR == "error"

    def test_exactly_four_members(self) -> None:
        assert len(EvaluationVerdict) == 4


# ===================================================================
# EvaluationInput
# ===================================================================


class TestEvaluationInput:
    """Verify dataclass fields and defaults."""

    def test_required_fields_stored(self) -> None:
        inp = EvaluationInput(
            task_id="T-1",
            prompt="Do something",
            actual_output="I did it",
        )
        assert inp.task_id == "T-1"
        assert inp.prompt == "Do something"
        assert inp.actual_output == "I did it"

    def test_optional_expected_output_defaults_to_none(self) -> None:
        inp = EvaluationInput(task_id="T-2", prompt="p", actual_output="a")
        assert inp.expected_output is None

    def test_expected_output_stored_when_provided(self) -> None:
        inp = EvaluationInput(
            task_id="T-3",
            prompt="p",
            actual_output="a",
            expected_output="expected text",
        )
        assert inp.expected_output == "expected text"

    def test_metadata_defaults_to_empty_dict(self) -> None:
        inp = EvaluationInput(task_id="T-4", prompt="p", actual_output="a")
        assert inp.metadata == {}

    def test_metadata_stored_when_provided(self) -> None:
        inp = EvaluationInput(
            task_id="T-5",
            prompt="p",
            actual_output="a",
            metadata={"key": "value"},
        )
        assert inp.metadata == {"key": "value"}


# ===================================================================
# EvaluationResult
# ===================================================================


class TestEvaluationResult:
    """Verify result dataclass stores all fields."""

    def test_stores_all_fields(self) -> None:
        result = EvaluationResult(
            task_id="T-1",
            verdict=EvaluationVerdict.PASS,
            score=0.95,
            reason="Looks good",
            evaluator_id="test_eval",
        )
        assert result.task_id == "T-1"
        assert result.verdict == EvaluationVerdict.PASS
        assert result.score == 0.95
        assert result.reason == "Looks good"
        assert result.evaluator_id == "test_eval"

    def test_metadata_defaults_to_empty_dict(self) -> None:
        result = EvaluationResult(
            task_id="T-2",
            verdict=EvaluationVerdict.FAIL,
            score=0.0,
            reason="Bad",
            evaluator_id="ev",
        )
        assert result.metadata == {}

    def test_metadata_stored_when_provided(self) -> None:
        result = EvaluationResult(
            task_id="T-3",
            verdict=EvaluationVerdict.PASS,
            score=1.0,
            reason="OK",
            evaluator_id="ev",
            metadata={"detail": 42},
        )
        assert result.metadata == {"detail": 42}


# ===================================================================
# Evaluator Protocol
# ===================================================================


class TestEvaluatorProtocol:
    """Verify Protocol runtime checkability."""

    def test_protocol_is_runtime_checkable(self) -> None:
        assert isinstance(RuleBasedEvaluator(), Evaluator)

    def test_plain_object_is_not_evaluator(self) -> None:
        assert not isinstance(object(), Evaluator)

    def test_class_with_matching_methods_satisfies_protocol(self) -> None:
        """A duck-typed class with the right shape passes isinstance."""

        class FakeEvaluator:
            @property
            def evaluator_id(self) -> str:
                return "fake"

            async def evaluate(self, eval_input: EvaluationInput) -> EvaluationResult:
                raise NotImplementedError  # pragma: no cover

            async def evaluate_batch(
                self, inputs: list[EvaluationInput]
            ) -> list[EvaluationResult]:
                raise NotImplementedError  # pragma: no cover

        assert isinstance(FakeEvaluator(), Evaluator)


# ===================================================================
# RuleBasedEvaluator
# ===================================================================


class TestRuleBasedEvaluator:
    """Exercise the rule-based evaluator's core logic."""

    @pytest.fixture()
    def evaluator(self) -> RuleBasedEvaluator:
        return RuleBasedEvaluator()

    def test_evaluator_id(self, evaluator: RuleBasedEvaluator) -> None:
        assert evaluator.evaluator_id == "rule_based_v1"

    async def test_pass_when_actual_contains_expected(self, evaluator: RuleBasedEvaluator) -> None:
        result = await evaluator.evaluate(
            EvaluationInput(
                task_id="T-10",
                prompt="Describe Python",
                actual_output="Python is a versatile programming language",
                expected_output="Python",
            )
        )
        assert result.verdict == EvaluationVerdict.PASS
        assert result.score == 1.0

    async def test_fail_when_actual_missing_expected(self, evaluator: RuleBasedEvaluator) -> None:
        result = await evaluator.evaluate(
            EvaluationInput(
                task_id="T-11",
                prompt="Describe Python",
                actual_output="Java is great",
                expected_output="Python",
            )
        )
        assert result.verdict == EvaluationVerdict.FAIL
        assert result.score == 0.0

    async def test_skip_when_expected_output_is_none(self, evaluator: RuleBasedEvaluator) -> None:
        result = await evaluator.evaluate(
            EvaluationInput(
                task_id="T-12",
                prompt="Any prompt",
                actual_output="Any output",
                expected_output=None,
            )
        )
        assert result.verdict == EvaluationVerdict.SKIP
        assert result.score == 0.5

    async def test_score_1_0_for_full_match(self, evaluator: RuleBasedEvaluator) -> None:
        result = await evaluator.evaluate(
            EvaluationInput(
                task_id="T-13",
                prompt="p",
                actual_output="alpha beta gamma",
                expected_output="alpha\nbeta\ngamma",
            )
        )
        assert result.score == 1.0
        assert result.verdict == EvaluationVerdict.PASS

    async def test_score_0_0_for_no_match(self, evaluator: RuleBasedEvaluator) -> None:
        result = await evaluator.evaluate(
            EvaluationInput(
                task_id="T-14",
                prompt="p",
                actual_output="nothing here",
                expected_output="alpha\nbeta\ngamma",
            )
        )
        assert result.score == 0.0
        assert result.verdict == EvaluationVerdict.FAIL

    async def test_proportional_score_for_partial_match(
        self, evaluator: RuleBasedEvaluator
    ) -> None:
        """2 of 3 expected strings found -> score ~0.667."""
        result = await evaluator.evaluate(
            EvaluationInput(
                task_id="T-15",
                prompt="p",
                actual_output="alpha gamma",
                expected_output="alpha\nbeta\ngamma",
            )
        )
        assert result.verdict == EvaluationVerdict.FAIL
        assert abs(result.score - 2.0 / 3.0) < 0.01

    async def test_result_task_id_matches_input(self, evaluator: RuleBasedEvaluator) -> None:
        result = await evaluator.evaluate(
            EvaluationInput(
                task_id="MY-TASK-42",
                prompt="p",
                actual_output="hello",
                expected_output="hello",
            )
        )
        assert result.task_id == "MY-TASK-42"

    async def test_result_evaluator_id_is_rule_based_v1(
        self, evaluator: RuleBasedEvaluator
    ) -> None:
        result = await evaluator.evaluate(
            EvaluationInput(
                task_id="T-16",
                prompt="p",
                actual_output="x",
                expected_output="x",
            )
        )
        assert result.evaluator_id == "rule_based_v1"

    async def test_empty_expected_output_is_trivial_pass(
        self, evaluator: RuleBasedEvaluator
    ) -> None:
        """An empty string (no non-empty lines) is a trivial pass."""
        result = await evaluator.evaluate(
            EvaluationInput(
                task_id="T-17",
                prompt="p",
                actual_output="anything",
                expected_output="",
            )
        )
        assert result.verdict == EvaluationVerdict.PASS
        assert result.score == 1.0

    async def test_multiline_expected_ignores_blank_lines(
        self, evaluator: RuleBasedEvaluator
    ) -> None:
        """Blank lines in expected_output are ignored."""
        result = await evaluator.evaluate(
            EvaluationInput(
                task_id="T-18",
                prompt="p",
                actual_output="foo bar",
                expected_output="foo\n\n\nbar",
            )
        )
        assert result.verdict == EvaluationVerdict.PASS
        assert result.score == 1.0

    async def test_reason_contains_missing_substrings_on_fail(
        self, evaluator: RuleBasedEvaluator
    ) -> None:
        result = await evaluator.evaluate(
            EvaluationInput(
                task_id="T-19",
                prompt="p",
                actual_output="alpha",
                expected_output="alpha\nbeta",
            )
        )
        assert "beta" in result.reason


# ===================================================================
# RuleBasedEvaluator — evaluate_batch
# ===================================================================


class TestRuleBasedEvaluatorBatch:
    """Verify batch evaluation concurrency and ordering."""

    @pytest.fixture()
    def evaluator(self) -> RuleBasedEvaluator:
        return RuleBasedEvaluator()

    async def test_batch_returns_results_for_all_inputs(
        self, evaluator: RuleBasedEvaluator
    ) -> None:
        inputs = [
            EvaluationInput(task_id=f"B-{i}", prompt="p", actual_output="x", expected_output="x")
            for i in range(5)
        ]
        results = await evaluator.evaluate_batch(inputs)
        assert len(results) == 5

    async def test_batch_results_in_same_order_as_inputs(
        self, evaluator: RuleBasedEvaluator
    ) -> None:
        inputs = [
            EvaluationInput(
                task_id=f"ORDER-{i}",
                prompt="p",
                actual_output="match" if i % 2 == 0 else "no",
                expected_output="match",
            )
            for i in range(4)
        ]
        results = await evaluator.evaluate_batch(inputs)
        for i, result in enumerate(results):
            assert result.task_id == f"ORDER-{i}"

    async def test_batch_empty_input_returns_empty(self, evaluator: RuleBasedEvaluator) -> None:
        results = await evaluator.evaluate_batch([])
        assert results == []


# ===================================================================
# EvaluatorRegistry
# ===================================================================


class TestEvaluatorRegistry:
    """Exercise registry CRUD and default management."""

    @pytest.fixture()
    def registry(self) -> EvaluatorRegistry:
        return EvaluatorRegistry()

    def test_register_adds_evaluator(self, registry: EvaluatorRegistry) -> None:
        ev = RuleBasedEvaluator()
        registry.register(ev)
        assert registry.get("rule_based_v1") is ev

    def test_get_returns_none_for_unknown_id(self, registry: EvaluatorRegistry) -> None:
        assert registry.get("nonexistent") is None

    def test_list_ids_includes_registered(self, registry: EvaluatorRegistry) -> None:
        ev = RuleBasedEvaluator()
        registry.register(ev)
        assert "rule_based_v1" in registry.list_ids()

    def test_list_ids_empty_by_default(self, registry: EvaluatorRegistry) -> None:
        assert registry.list_ids() == []

    def test_set_default_and_get_default_roundtrip(self, registry: EvaluatorRegistry) -> None:
        ev = RuleBasedEvaluator()
        registry.register(ev)
        registry.set_default("rule_based_v1")
        assert registry.get_default() is ev

    def test_get_default_returns_none_when_unset(self, registry: EvaluatorRegistry) -> None:
        assert registry.get_default() is None

    def test_set_default_raises_for_unknown_id(self, registry: EvaluatorRegistry) -> None:
        with pytest.raises(KeyError, match="not registered"):
            registry.set_default("ghost_evaluator")

    def test_register_overwrites_existing(self, registry: EvaluatorRegistry) -> None:
        """Registering the same evaluator_id twice overwrites the first."""
        ev1 = RuleBasedEvaluator()
        ev2 = RuleBasedEvaluator()
        registry.register(ev1)
        registry.register(ev2)
        assert registry.get("rule_based_v1") is ev2

    def test_list_ids_returns_sorted(self, registry: EvaluatorRegistry) -> None:
        """Verify IDs are returned in sorted order."""

        class EvalA:
            @property
            def evaluator_id(self) -> str:
                return "z_evaluator"

            async def evaluate(self, eval_input: EvaluationInput) -> EvaluationResult:
                raise NotImplementedError  # pragma: no cover

            async def evaluate_batch(
                self, inputs: list[EvaluationInput]
            ) -> list[EvaluationResult]:
                raise NotImplementedError  # pragma: no cover

        class EvalB:
            @property
            def evaluator_id(self) -> str:
                return "a_evaluator"

            async def evaluate(self, eval_input: EvaluationInput) -> EvaluationResult:
                raise NotImplementedError  # pragma: no cover

            async def evaluate_batch(
                self, inputs: list[EvaluationInput]
            ) -> list[EvaluationResult]:
                raise NotImplementedError  # pragma: no cover

        registry.register(EvalA())  # type: ignore[arg-type]
        registry.register(EvalB())  # type: ignore[arg-type]
        ids = registry.list_ids()
        assert ids == ["a_evaluator", "z_evaluator"]


# ===================================================================
# default_evaluator_registry
# ===================================================================


class TestDefaultEvaluatorRegistry:
    """Verify the module-level registry is bootstrapped correctly."""

    def test_has_rule_based_v1_registered(self) -> None:
        assert default_evaluator_registry.get("rule_based_v1") is not None

    def test_default_is_rule_based_v1(self) -> None:
        default = default_evaluator_registry.get_default()
        assert default is not None
        assert default.evaluator_id == "rule_based_v1"

    def test_list_ids_contains_rule_based_v1(self) -> None:
        assert "rule_based_v1" in default_evaluator_registry.list_ids()
