"""Tests for the ISC (Inline Success Criteria) system."""

from __future__ import annotations

import pytest

from agent33.agents.isc import (
    CompositeCriterion,
    CompositeOperator,
    GuardrailResult,
    ISCCriterion,
    ISCManager,
    _evaluate_single,
    enforce_constraint_length,
)

# ---------------------------------------------------------------------------
# GuardrailResult
# ---------------------------------------------------------------------------


class TestGuardrailResult:
    def test_success_result(self) -> None:
        r = GuardrailResult(success=True, result="ok", criterion_name="c1")
        assert r.success is True
        assert r.result == "ok"
        assert r.error is None
        assert r.criterion_name == "c1"

    def test_failure_result(self) -> None:
        r = GuardrailResult(success=False, error="bad", criterion_name="c2")
        assert r.success is False
        assert r.error == "bad"

    def test_frozen(self) -> None:
        r = GuardrailResult(success=True)
        with pytest.raises(AttributeError):
            r.success = False  # type: ignore[misc]

    def test_defaults(self) -> None:
        r = GuardrailResult(success=True)
        assert r.result is None
        assert r.error is None
        assert r.criterion_name == ""


# ---------------------------------------------------------------------------
# ISCCriterion
# ---------------------------------------------------------------------------


class TestISCCriterion:
    def test_creation(self) -> None:
        c = ISCCriterion(name="c1", description="desc", check_fn=lambda ctx: True)
        assert c.name == "c1"
        assert c.description == "desc"
        assert c.is_anti is False
        assert c.criterion_id.startswith("isc-")

    def test_auto_id_unique(self) -> None:
        c1 = ISCCriterion(name="a", description="d", check_fn=lambda ctx: True)
        c2 = ISCCriterion(name="a", description="d", check_fn=lambda ctx: True)
        assert c1.criterion_id != c2.criterion_id

    def test_and_operator(self) -> None:
        c1 = ISCCriterion(name="a", description="d", check_fn=lambda ctx: True)
        c2 = ISCCriterion(name="b", description="d", check_fn=lambda ctx: True)
        composite = c1 & c2
        assert isinstance(composite, CompositeCriterion)
        assert composite.operator == CompositeOperator.AND
        assert len(composite.criteria) == 2

    def test_or_operator(self) -> None:
        c1 = ISCCriterion(name="a", description="d", check_fn=lambda ctx: True)
        c2 = ISCCriterion(name="b", description="d", check_fn=lambda ctx: False)
        composite = c1 | c2
        assert isinstance(composite, CompositeCriterion)
        assert composite.operator == CompositeOperator.OR

    def test_chaining(self) -> None:
        c1 = ISCCriterion(name="a", description="d", check_fn=lambda ctx: True)
        c2 = ISCCriterion(name="b", description="d", check_fn=lambda ctx: True)
        c3 = ISCCriterion(name="c", description="d", check_fn=lambda ctx: True)
        composite = (c1 & c2) | c3
        assert isinstance(composite, CompositeCriterion)
        assert composite.operator == CompositeOperator.OR

    def test_anti_criteria_inversion(self) -> None:
        c = ISCCriterion(
            name="no-pii", description="no PII", check_fn=lambda ctx: True, is_anti=True
        )
        r = _evaluate_single(c, {})
        # check_fn returns True, but is_anti inverts → success=False
        assert r.success is False
        assert r.result is True

    def test_exception_handling(self) -> None:
        def bad_fn(ctx: dict) -> bool:
            raise ValueError("boom")

        c = ISCCriterion(name="bad", description="d", check_fn=bad_fn)
        r = _evaluate_single(c, {})
        assert r.success is False
        assert r.error is not None
        assert "boom" in r.error


# ---------------------------------------------------------------------------
# CompositeCriterion
# ---------------------------------------------------------------------------


class TestCompositeCriterion:
    def test_and_all_pass(self) -> None:
        c1 = ISCCriterion(name="a", description="d", check_fn=lambda ctx: True)
        c2 = ISCCriterion(name="b", description="d", check_fn=lambda ctx: True)
        composite = c1 & c2
        r = composite.evaluate({})
        assert r.success is True

    def test_and_one_fail(self) -> None:
        c1 = ISCCriterion(name="a", description="d", check_fn=lambda ctx: True)
        c2 = ISCCriterion(name="b", description="d", check_fn=lambda ctx: False)
        composite = c1 & c2
        r = composite.evaluate({})
        assert r.success is False
        assert r.error is not None

    def test_or_one_pass(self) -> None:
        c1 = ISCCriterion(name="a", description="d", check_fn=lambda ctx: False)
        c2 = ISCCriterion(name="b", description="d", check_fn=lambda ctx: True)
        composite = c1 | c2
        r = composite.evaluate({})
        assert r.success is True

    def test_or_all_fail(self) -> None:
        c1 = ISCCriterion(name="a", description="d", check_fn=lambda ctx: False)
        c2 = ISCCriterion(name="b", description="d", check_fn=lambda ctx: False)
        composite = c1 | c2
        r = composite.evaluate({})
        assert r.success is False

    def test_deep_nesting(self) -> None:
        c1 = ISCCriterion(name="a", description="d", check_fn=lambda ctx: True)
        c2 = ISCCriterion(name="b", description="d", check_fn=lambda ctx: True)
        c3 = ISCCriterion(name="c", description="d", check_fn=lambda ctx: False)
        c4 = ISCCriterion(name="d", description="d", check_fn=lambda ctx: True)
        # (a AND b) OR (c AND d) → (True AND True) OR (False AND True) → True
        composite = (c1 & c2) | (c3 & c4)
        r = composite.evaluate({})
        assert r.success is True

    def test_and_chaining(self) -> None:
        c1 = ISCCriterion(name="a", description="d", check_fn=lambda ctx: True)
        c2 = ISCCriterion(name="b", description="d", check_fn=lambda ctx: True)
        c3 = ISCCriterion(name="c", description="d", check_fn=lambda ctx: True)
        composite = CompositeCriterion(operator=CompositeOperator.AND, criteria=[c1, c2])
        chained = composite & c3
        assert isinstance(chained, CompositeCriterion)
        r = chained.evaluate({})
        assert r.success is True

    def test_or_chaining(self) -> None:
        c1 = ISCCriterion(name="a", description="d", check_fn=lambda ctx: False)
        c2 = ISCCriterion(name="b", description="d", check_fn=lambda ctx: False)
        c3 = ISCCriterion(name="c", description="d", check_fn=lambda ctx: True)
        composite = CompositeCriterion(operator=CompositeOperator.OR, criteria=[c1, c2])
        chained = composite | c3
        r = chained.evaluate({})
        assert r.success is True


# ---------------------------------------------------------------------------
# ISCManager
# ---------------------------------------------------------------------------


class TestISCManager:
    def test_add_and_get(self) -> None:
        mgr = ISCManager()
        c = ISCCriterion(name="c1", description="d", check_fn=lambda ctx: True)
        mgr.add(c)
        assert mgr.get(c.criterion_id) is c

    def test_remove(self) -> None:
        mgr = ISCManager()
        c = ISCCriterion(name="c1", description="d", check_fn=lambda ctx: True)
        mgr.add(c)
        assert mgr.remove(c.criterion_id) is True
        assert mgr.get(c.criterion_id) is None

    def test_remove_nonexistent(self) -> None:
        mgr = ISCManager()
        assert mgr.remove("isc-doesnotexist") is False

    def test_list_all(self) -> None:
        mgr = ISCManager()
        c1 = ISCCriterion(name="a", description="d", check_fn=lambda ctx: True)
        c2 = ISCCriterion(name="b", description="d", check_fn=lambda ctx: True)
        mgr.add(c1)
        mgr.add(c2)
        assert len(mgr.list_all()) == 2

    def test_evaluate_all_pass(self) -> None:
        mgr = ISCManager()
        mgr.add(ISCCriterion(name="a", description="d", check_fn=lambda ctx: True))
        mgr.add(ISCCriterion(name="b", description="d", check_fn=lambda ctx: True))
        results = mgr.evaluate_all({})
        assert all(r.success for r in results)
        assert len(results) == 2

    def test_evaluate_all_mixed(self) -> None:
        mgr = ISCManager()
        mgr.add(ISCCriterion(name="a", description="d", check_fn=lambda ctx: True))
        mgr.add(ISCCriterion(name="b", description="d", check_fn=lambda ctx: False))
        results = mgr.evaluate_all({})
        assert sum(r.success for r in results) == 1

    def test_evaluate_all_anti_criteria_disabled(self) -> None:
        mgr = ISCManager()
        mgr.add(
            ISCCriterion(name="anti", description="d", check_fn=lambda ctx: True, is_anti=True)
        )
        mgr.add(ISCCriterion(name="normal", description="d", check_fn=lambda ctx: True))
        results = mgr.evaluate_all({}, enable_anti_criteria=False)
        # Only the normal criterion should be evaluated
        assert len(results) == 1
        assert results[0].criterion_name == "normal"

    def test_evaluate_all_anti_criteria_enabled(self) -> None:
        mgr = ISCManager()
        mgr.add(
            ISCCriterion(name="anti", description="d", check_fn=lambda ctx: True, is_anti=True)
        )
        results = mgr.evaluate_all({}, enable_anti_criteria=True)
        assert len(results) == 1
        # check_fn returns True, anti inverts → success=False
        assert results[0].success is False

    def test_evaluate_all_with_exception(self) -> None:
        mgr = ISCManager()

        def raises(ctx: dict) -> bool:
            raise RuntimeError("oops")

        mgr.add(ISCCriterion(name="bad", description="d", check_fn=raises))
        results = mgr.evaluate_all({})
        assert len(results) == 1
        assert results[0].success is False
        assert "oops" in (results[0].error or "")

    def test_evaluate_composite(self) -> None:
        mgr = ISCManager()
        c1 = ISCCriterion(name="a", description="d", check_fn=lambda ctx: True)
        c2 = ISCCriterion(name="b", description="d", check_fn=lambda ctx: True)
        composite = c1 & c2
        r = mgr.evaluate_composite(composite, {})
        assert r.success is True

    def test_coverage_check_mapped(self) -> None:
        mgr = ISCManager()
        mgr.add(ISCCriterion(name="output format", description="d", check_fn=lambda ctx: True))
        result = mgr.coverage_check(["output format"])
        assert result["output format"] == "output format"

    def test_coverage_check_unmapped(self) -> None:
        mgr = ISCManager()
        result = mgr.coverage_check(["something new"])
        assert result["something new"] == "unmapped"

    def test_coverage_check_empty(self) -> None:
        mgr = ISCManager()
        result = mgr.coverage_check([])
        assert result == {}

    def test_coverage_check_description_match(self) -> None:
        mgr = ISCManager()
        mgr.add(
            ISCCriterion(
                name="format-check",
                description="validates output format",
                check_fn=lambda ctx: True,
            )
        )
        result = mgr.coverage_check(["output format"])
        assert result["output format"] == "format-check"


# ---------------------------------------------------------------------------
# enforce_constraint_length
# ---------------------------------------------------------------------------


class TestEnforceConstraintLength:
    def test_valid_8_words(self) -> None:
        assert enforce_constraint_length("output must contain valid JSON format always") is False
        assert (
            enforce_constraint_length("the system must validate all input fields correctly")
            is True
        )

    def test_valid_12_words(self) -> None:
        text = "the system must always ensure that all outputs are validated and correct"
        assert len(text.split()) == 12
        assert enforce_constraint_length(text) is True

    def test_too_short(self) -> None:
        assert enforce_constraint_length("must be valid") is False

    def test_too_long(self) -> None:
        text = (
            "the system must always ensure that all outputs"
            " are validated and correct and complete today"
        )
        assert len(text.split()) > 12
        assert enforce_constraint_length(text) is False

    def test_no_keywords(self) -> None:
        assert enforce_constraint_length("the quick brown fox jumped over the lazy dog") is False

    def test_keyword_variations(self) -> None:
        assert enforce_constraint_length("we shall deliver the product on time every week") is True
        assert (
            enforce_constraint_length("agents should never expose credentials in the output text")
            is True
        )
        assert (
            enforce_constraint_length("the pipeline ensure verify all assertions pass in tests")
            is True
        )


# ---------------------------------------------------------------------------
# CompositeOperator enum
# ---------------------------------------------------------------------------


class TestCompositeOperator:
    def test_values(self) -> None:
        assert CompositeOperator.AND == "and"
        assert CompositeOperator.OR == "or"

    def test_str_inheritance(self) -> None:
        assert isinstance(CompositeOperator.AND, str)
