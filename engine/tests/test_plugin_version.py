"""Tests for SemVer constraint checking."""

from __future__ import annotations

import pytest

from agent33.plugins.version import parse_version, satisfies_constraint


class TestParseVersion:
    """Tests for parse_version()."""

    def test_valid_semver(self) -> None:
        assert parse_version("1.2.3") == (1, 2, 3)

    def test_zero_version(self) -> None:
        assert parse_version("0.0.0") == (0, 0, 0)

    def test_large_version(self) -> None:
        assert parse_version("100.200.300") == (100, 200, 300)

    def test_invalid_format_two_parts(self) -> None:
        with pytest.raises(ValueError, match="Invalid SemVer format"):
            parse_version("1.0")

    def test_invalid_format_one_part(self) -> None:
        with pytest.raises(ValueError, match="Invalid SemVer format"):
            parse_version("1")

    def test_non_integer_component(self) -> None:
        with pytest.raises(ValueError, match="non-integer"):
            parse_version("1.a.3")

    def test_whitespace_is_stripped(self) -> None:
        assert parse_version("  1.2.3  ") == (1, 2, 3)


class TestSatisfiesConstraint:
    """Tests for satisfies_constraint()."""

    # Wildcard
    def test_wildcard_matches_any(self) -> None:
        assert satisfies_constraint("0.0.1", "*") is True
        assert satisfies_constraint("99.99.99", "*") is True

    # Exact match
    def test_exact_match(self) -> None:
        assert satisfies_constraint("1.2.3", "1.2.3") is True

    def test_exact_no_match(self) -> None:
        assert satisfies_constraint("1.2.4", "1.2.3") is False

    # Greater or equal
    def test_gte_equal(self) -> None:
        assert satisfies_constraint("1.0.0", ">=1.0.0") is True

    def test_gte_greater(self) -> None:
        assert satisfies_constraint("2.0.0", ">=1.0.0") is True

    def test_gte_less(self) -> None:
        assert satisfies_constraint("0.9.0", ">=1.0.0") is False

    # Less or equal
    def test_lte_equal(self) -> None:
        assert satisfies_constraint("1.0.0", "<=1.0.0") is True

    def test_lte_less(self) -> None:
        assert satisfies_constraint("0.9.0", "<=1.0.0") is True

    def test_lte_greater(self) -> None:
        assert satisfies_constraint("1.0.1", "<=1.0.0") is False

    # Strictly greater
    def test_gt_greater(self) -> None:
        assert satisfies_constraint("1.0.1", ">1.0.0") is True

    def test_gt_equal_fails(self) -> None:
        assert satisfies_constraint("1.0.0", ">1.0.0") is False

    # Strictly less
    def test_lt_less(self) -> None:
        assert satisfies_constraint("0.9.9", "<1.0.0") is True

    def test_lt_equal_fails(self) -> None:
        assert satisfies_constraint("1.0.0", "<1.0.0") is False

    # Caret (^) — compatible: same major, >= minor.patch
    def test_caret_same_major_higher_minor(self) -> None:
        assert satisfies_constraint("1.5.0", "^1.0.0") is True

    def test_caret_exact_match(self) -> None:
        assert satisfies_constraint("1.0.0", "^1.0.0") is True

    def test_caret_different_major(self) -> None:
        assert satisfies_constraint("2.0.0", "^1.0.0") is False

    def test_caret_lower_version(self) -> None:
        assert satisfies_constraint("0.9.0", "^1.0.0") is False

    # Tilde (~) — approximately: same major.minor, >= patch
    def test_tilde_same_minor_higher_patch(self) -> None:
        assert satisfies_constraint("1.2.5", "~1.2.3") is True

    def test_tilde_exact_match(self) -> None:
        assert satisfies_constraint("1.2.3", "~1.2.3") is True

    def test_tilde_different_minor(self) -> None:
        assert satisfies_constraint("1.3.0", "~1.2.3") is False

    def test_tilde_lower_patch(self) -> None:
        assert satisfies_constraint("1.2.2", "~1.2.3") is False

    # Edge cases
    def test_unparseable_constraint_fails_open(self) -> None:
        """Unparseable constraints fail open (return True) with a warning."""
        assert satisfies_constraint("1.0.0", "not-a-version") is True

    def test_unparseable_version_fails_open(self) -> None:
        """Unparseable version fails open."""
        assert satisfies_constraint("invalid", ">=1.0.0") is True

    def test_whitespace_in_constraint(self) -> None:
        """Whitespace in constraint is stripped."""
        assert satisfies_constraint("1.0.0", "  >=1.0.0  ") is True
