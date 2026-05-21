"""Database-backed verification for evaluation tasks.

Provides a :class:`DatabaseVerifier` that executes SQL queries and
compares results against expected values using pluggable comparison
modes.  Designed for use in golden-task evaluation where task success
is determined by database state after agent execution.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Coroutine
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

QueryExecutor = Callable[[str, float], Coroutine[Any, Any, list[dict[str, Any]]]]
"""Async callback: (query, timeout_seconds) -> list of row dicts."""


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ComparisonMode(StrEnum):
    """How to compare actual query results against expected values."""

    EXACT = "exact"
    CONTAINS = "contains"
    ROW_COUNT = "row_count"
    NOT_EMPTY = "not_empty"
    REGEX = "regex"
    JSON_SUBSET = "json_subset"


class VerificationSpec(BaseModel):
    """Specification for a single database verification check."""

    name: str
    query: str
    expected: Any = None
    comparison_mode: ComparisonMode = ComparisonMode.EXACT
    database: str = "default"
    timeout_seconds: float = Field(default=10.0, gt=0)


class VerificationResult(BaseModel):
    """Result of a single verification check."""

    spec_name: str
    passed: bool
    actual_value: Any = None
    expected_value: Any = None
    error_message: str | None = None
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------


class DatabaseVerifier:
    """Verifies database state by executing queries and comparing results.

    Parameters
    ----------
    execute_query:
        Async callback that runs a SQL query and returns a list of row
        dicts.  This allows the verifier to work without a real database
        connection -- callers (and tests) can provide any implementation.
    db_url:
        Optional database URL.  Stored for reference but not used
        directly; the ``execute_query`` callback handles actual execution.
    """

    def __init__(
        self,
        execute_query: QueryExecutor | None = None,
        db_url: str | None = None,
    ) -> None:
        self._execute_query = execute_query
        self._db_url = db_url

    async def verify(self, spec: VerificationSpec) -> VerificationResult:
        """Run a single verification and return the result."""
        start = time.monotonic()
        try:
            if self._execute_query is None:
                return VerificationResult(
                    spec_name=spec.name,
                    passed=False,
                    expected_value=spec.expected,
                    error_message="No query executor configured",
                    duration_ms=_elapsed_ms(start),
                )

            rows = await self._execute_query(spec.query, spec.timeout_seconds)
            passed, actual, error = self._compare(spec, rows)
            return VerificationResult(
                spec_name=spec.name,
                passed=passed,
                actual_value=actual,
                expected_value=spec.expected,
                error_message=error,
                duration_ms=_elapsed_ms(start),
            )
        except Exception as exc:
            return VerificationResult(
                spec_name=spec.name,
                passed=False,
                expected_value=spec.expected,
                error_message=f"Query execution failed: {exc}",
                duration_ms=_elapsed_ms(start),
            )

    async def verify_all(self, specs: list[VerificationSpec]) -> list[VerificationResult]:
        """Run multiple verifications and return all results."""
        return [await self.verify(spec) for spec in specs]

    # ------------------------------------------------------------------
    # Comparison dispatch
    # ------------------------------------------------------------------

    def _compare(
        self,
        spec: VerificationSpec,
        rows: list[dict[str, Any]],
    ) -> tuple[bool, Any, str | None]:
        """Dispatch to the appropriate comparison method.

        Returns (passed, actual_value, error_message_or_none).
        """
        handlers = {
            ComparisonMode.EXACT: self._compare_exact,
            ComparisonMode.CONTAINS: self._compare_contains,
            ComparisonMode.ROW_COUNT: self._compare_row_count,
            ComparisonMode.NOT_EMPTY: self._compare_not_empty,
            ComparisonMode.REGEX: self._compare_regex,
            ComparisonMode.JSON_SUBSET: self._compare_json_subset,
        }
        handler = handlers.get(spec.comparison_mode)
        if handler is None:
            return False, rows, f"Unknown comparison mode: {spec.comparison_mode}"
        return handler(spec, rows)

    # ------------------------------------------------------------------
    # Comparison methods
    # ------------------------------------------------------------------

    @staticmethod
    def _compare_exact(
        spec: VerificationSpec, rows: list[dict[str, Any]]
    ) -> tuple[bool, Any, str | None]:
        """Exact equality between rows and expected."""
        if rows == spec.expected:
            return True, rows, None
        return False, rows, f"Expected {spec.expected!r}, got {rows!r}"

    @staticmethod
    def _compare_contains(
        spec: VerificationSpec, rows: list[dict[str, Any]]
    ) -> tuple[bool, Any, str | None]:
        """Check that expected value appears somewhere in the result.

        Supports:
        - String expected: checks if it appears in any cell value
        - Dict expected: checks if any row contains all expected key-value pairs
        - List expected: checks if all expected items are present in rows
        """
        expected = spec.expected
        if isinstance(expected, str):
            for row in rows:
                for val in row.values():
                    if expected in str(val):
                        return True, rows, None
            return False, rows, f"Expected to contain {expected!r}"

        if isinstance(expected, dict):
            for row in rows:
                if all(row.get(k) == v for k, v in expected.items()):
                    return True, rows, None
            return False, rows, f"No row contains {expected!r}"

        if isinstance(expected, list):
            for exp_item in expected:
                found = False
                for row in rows:
                    if isinstance(exp_item, dict):
                        if all(row.get(k) == v for k, v in exp_item.items()):
                            found = True
                            break
                    elif exp_item in row.values():
                        found = True
                        break
                if not found:
                    return False, rows, f"Missing expected item: {exp_item!r}"
            return True, rows, None

        return False, rows, f"Unsupported expected type for contains: {type(expected)}"

    @staticmethod
    def _compare_row_count(
        spec: VerificationSpec, rows: list[dict[str, Any]]
    ) -> tuple[bool, Any, str | None]:
        """Check that the number of rows matches expected."""
        actual_count = len(rows)
        expected_count = spec.expected
        if not isinstance(expected_count, int):
            msg = f"Expected integer for row_count, got {type(expected_count)}"
            return False, actual_count, msg
        if actual_count == expected_count:
            return True, actual_count, None
        return False, actual_count, f"Expected {expected_count} rows, got {actual_count}"

    @staticmethod
    def _compare_not_empty(
        _spec: VerificationSpec,
        rows: list[dict[str, Any]],
    ) -> tuple[bool, Any, str | None]:
        """Check that the query returned at least one row."""
        count = len(rows)
        if count > 0:
            return True, count, None
        return False, count, "Expected non-empty result, got 0 rows"

    @staticmethod
    def _compare_regex(
        spec: VerificationSpec, rows: list[dict[str, Any]]
    ) -> tuple[bool, Any, str | None]:
        """Check that expected regex matches some cell value in the result."""
        pattern = spec.expected
        if not isinstance(pattern, str):
            return False, rows, f"Expected string regex pattern, got {type(pattern)}"
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            return False, rows, f"Invalid regex pattern: {exc}"

        for row in rows:
            for val in row.values():
                if compiled.search(str(val)):
                    return True, rows, None
        return False, rows, f"No value matched regex {pattern!r}"

    @staticmethod
    def _compare_json_subset(
        spec: VerificationSpec, rows: list[dict[str, Any]]
    ) -> tuple[bool, Any, str | None]:
        """Check that expected is a JSON subset of the actual result.

        The expected value (dict) must be a subset of at least one row,
        meaning every key-value pair in expected must be present in a row.
        For nested structures, both sides are serialized to JSON and
        compared as dicts.
        """
        expected = spec.expected
        if not isinstance(expected, dict):
            return False, rows, f"Expected dict for json_subset, got {type(expected)}"

        for row in rows:
            if _is_json_subset(expected, row):
                return True, rows, None
        return False, rows, f"No row is a JSON superset of {expected!r}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _elapsed_ms(start: float) -> float:
    return (time.monotonic() - start) * 1000.0


def _is_json_subset(subset: dict[str, Any], superset: dict[str, Any]) -> bool:
    """Check if *subset* is contained within *superset* recursively."""
    for key, expected_val in subset.items():
        if key not in superset:
            return False
        actual_val = superset[key]

        # If both are dicts, recurse
        if isinstance(expected_val, dict) and isinstance(actual_val, dict):
            if not _is_json_subset(expected_val, actual_val):
                return False
        # If actual is a JSON string, parse and compare
        elif isinstance(actual_val, str) and isinstance(expected_val, dict):
            try:
                parsed = json.loads(actual_val)
                if not isinstance(parsed, dict) or not _is_json_subset(expected_val, parsed):
                    return False
            except (json.JSONDecodeError, TypeError):
                return False
        elif expected_val != actual_val:
            return False
    return True
