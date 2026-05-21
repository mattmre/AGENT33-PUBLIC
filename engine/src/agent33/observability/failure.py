"""Failure taxonomy from ``core/orchestrator/TRACE_SCHEMA.md``.

Provides structured failure classification, severity levels, and
resolution metadata.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FailureCategory(StrEnum):
    """Top-level failure categories."""

    ENVIRONMENT = "F-ENV"
    INPUT = "F-INP"
    EXECUTION = "F-EXE"
    TIMEOUT = "F-TMO"
    RESOURCE = "F-RES"
    SECURITY = "F-SEC"
    DEPENDENCY = "F-DEP"
    VALIDATION = "F-VAL"
    REVIEW = "F-REV"
    UNKNOWN = "F-UNK"


class FailureSeverity(StrEnum):
    """Severity levels for failures."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Category metadata
# ---------------------------------------------------------------------------


_CATEGORY_META: dict[FailureCategory, dict[str, object]] = {
    FailureCategory.ENVIRONMENT: {
        "retryable": True,
        "escalate_after": 2,
        "description": "Setup, dependencies, permissions",
    },
    FailureCategory.INPUT: {
        "retryable": False,
        "escalate_after": 0,
        "description": "Invalid input, missing files",
    },
    FailureCategory.EXECUTION: {
        "retryable": True,
        "escalate_after": 1,
        "description": "Runtime errors, crashes",
    },
    FailureCategory.TIMEOUT: {
        "retryable": True,
        "escalate_after": 1,
        "description": "Exceeded time limit",
    },
    FailureCategory.RESOURCE: {
        "retryable": True,
        "escalate_after": 1,
        "description": "Memory, disk, network",
    },
    FailureCategory.SECURITY: {
        "retryable": False,
        "escalate_after": 0,
        "description": "Blocked by policy",
    },
    FailureCategory.DEPENDENCY: {
        "retryable": True,
        "escalate_after": 3,
        "description": "External service failure",
    },
    FailureCategory.VALIDATION: {
        "retryable": False,
        "escalate_after": 0,
        "description": "Output validation failed",
    },
    FailureCategory.REVIEW: {
        "retryable": False,
        "escalate_after": 0,
        "description": "Reviewer rejected",
    },
    FailureCategory.UNKNOWN: {
        "retryable": False,
        "escalate_after": 0,
        "description": "Unclassified failure",
    },
}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class FailureClassification(BaseModel):
    """Classification details for a failure."""

    code: str = ""  # e.g. "F-EXE"
    subcode: str = ""  # e.g. "F-EXE-001"
    category: FailureCategory = FailureCategory.UNKNOWN
    severity: FailureSeverity = FailureSeverity.MEDIUM


class FailureResolution(BaseModel):
    """Resolution metadata for a failure."""

    retryable: bool = False
    retry_count: int = 0
    escalation_required: bool = False
    escalation_target: str = ""
    resolution_status: str = "pending"  # pending | resolved | wontfix
    resolution_notes: str = ""


def _failure_id() -> str:
    now = datetime.now(UTC)
    rand = uuid.uuid4().hex[:4].upper()
    return f"FLR-{now:%Y%m%d}-{rand}"


class FailureRecord(BaseModel):
    """Complete failure record matching TRACE_SCHEMA.md failure schema."""

    failure_id: str = Field(default_factory=_failure_id)
    trace_id: str = ""
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    classification: FailureClassification = Field(default_factory=FailureClassification)
    message: str = ""
    stack_trace: str = ""
    context: dict[str, str] = Field(default_factory=dict)

    resolution: FailureResolution = Field(default_factory=FailureResolution)
    artifact_refs: list[str] = Field(default_factory=list)

    @classmethod
    def from_exception(
        cls,
        exc: Exception,
        trace_id: str = "",
        category: FailureCategory = FailureCategory.EXECUTION,
        severity: FailureSeverity = FailureSeverity.MEDIUM,
    ) -> FailureRecord:
        """Create a FailureRecord from a Python exception."""
        import traceback

        meta = _CATEGORY_META.get(category, {})
        return cls(
            trace_id=trace_id,
            classification=FailureClassification(
                code=category.value,
                category=category,
                severity=severity,
            ),
            message=str(exc),
            stack_trace=traceback.format_exc(),
            resolution=FailureResolution(
                retryable=bool(meta.get("retryable", False)),
                escalation_required=not meta.get("retryable", False),
            ),
        )


def is_retryable(category: FailureCategory) -> bool:
    """Return ``True`` if failures in *category* are retryable."""
    meta = _CATEGORY_META.get(category, {})
    return bool(meta.get("retryable", False))


def escalate_after(category: FailureCategory) -> int:
    """Return the retry count after which to escalate for *category*."""
    meta = _CATEGORY_META.get(category, {})
    value = meta.get("escalate_after", 0)
    if isinstance(value, (int, str)):
        return int(value)
    return 0
