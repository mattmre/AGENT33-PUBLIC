"""Failure taxonomy alignment for the iterative tool-use loop.

Maps :class:`ToolLoopResult` termination reasons to the observability
failure taxonomy (:mod:`agent33.observability.failure`) and trace
outcome models (:mod:`agent33.observability.trace_models`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent33.agents.tool_loop import ToolLoopResult

from agent33.observability.failure import (
    FailureCategory,
    FailureClassification,
    FailureRecord,
    FailureResolution,
    FailureSeverity,
)
from agent33.observability.trace_models import TraceOutcome, TraceStatus

# ---------------------------------------------------------------------------
# Tool-loop failure subcodes
# ---------------------------------------------------------------------------

TOOL_LOOP_SUBCODES: dict[str, dict[str, str | FailureCategory | FailureSeverity]] = {
    "tool_argument_error": {
        "subcode": "F-EXE-TL01",
        "description": "LLM provided invalid arguments to a tool",
        "category": FailureCategory.EXECUTION,
        "severity": FailureSeverity.MEDIUM,
    },
    "tool_execution_error": {
        "subcode": "F-EXE-TL02",
        "description": "Tool execution raised an exception",
        "category": FailureCategory.EXECUTION,
        "severity": FailureSeverity.MEDIUM,
    },
    "tool_governance_denied": {
        "subcode": "F-SEC-TL03",
        "description": "Tool call blocked by governance/allowlist",
        "category": FailureCategory.SECURITY,
        "severity": FailureSeverity.HIGH,
    },
    "max_iterations": {
        "subcode": "F-RES-TL04",
        "description": "Tool loop hit max iterations without final answer",
        "category": FailureCategory.RESOURCE,
        "severity": FailureSeverity.MEDIUM,
    },
    "context_exhausted": {
        "subcode": "F-RES-TL05",
        "description": "Context window exhausted during tool loop",
        "category": FailureCategory.RESOURCE,
        "severity": FailureSeverity.HIGH,
    },
    "budget_exceeded": {
        "subcode": "F-RES-TL06",
        "description": "Autonomy budget exhausted",
        "category": FailureCategory.RESOURCE,
        "severity": FailureSeverity.MEDIUM,
    },
    "leakage_detected": {
        "subcode": "F-VAL-TL07",
        "description": "Answer leakage detected in tool output",
        "category": FailureCategory.VALIDATION,
        "severity": FailureSeverity.LOW,
    },
    "error": {
        "subcode": "F-EXE-TL08",
        "description": "Consecutive error threshold exceeded",
        "category": FailureCategory.EXECUTION,
        "severity": FailureSeverity.HIGH,
    },
}


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_tool_loop_failure(result: ToolLoopResult) -> FailureClassification:
    """Map a failed :class:`ToolLoopResult` to a :class:`FailureClassification`.

    Returns a classification with ``UNKNOWN`` category if the termination
    reason does not match any known subcode.
    """
    if result.termination_reason == "completed":
        return FailureClassification(
            code="",
            subcode="",
            category=FailureCategory.UNKNOWN,
            severity=FailureSeverity.LOW,
        )

    meta = TOOL_LOOP_SUBCODES.get(result.termination_reason)
    if meta is None:
        return FailureClassification(
            code=FailureCategory.UNKNOWN.value,
            subcode="F-UNK-TL00",
            category=FailureCategory.UNKNOWN,
            severity=FailureSeverity.MEDIUM,
        )

    cat = meta["category"]
    sev = meta["severity"]
    assert isinstance(cat, FailureCategory)
    assert isinstance(sev, FailureSeverity)
    return FailureClassification(
        code=cat.value,
        subcode=str(meta["subcode"]),
        category=cat,
        severity=sev,
    )


def tool_loop_to_trace_outcome(result: ToolLoopResult) -> TraceOutcome:
    """Map a :class:`ToolLoopResult` to a :class:`TraceOutcome`.

    Successful completions get ``COMPLETED`` status.  Timeouts
    (``max_iterations``) get ``TIMEOUT``.  Everything else gets ``FAILED``
    with the appropriate failure code and message.
    """
    if result.termination_reason == "completed":
        return TraceOutcome(status=TraceStatus.COMPLETED)

    classification = classify_tool_loop_failure(result)

    # Map termination reason to trace status
    if result.termination_reason == "max_iterations":
        status = TraceStatus.TIMEOUT
    elif result.termination_reason == "budget_exceeded":
        status = TraceStatus.CANCELLED
    else:
        status = TraceStatus.FAILED

    return TraceOutcome(
        status=status,
        failure_code=classification.subcode,
        failure_message=str(
            TOOL_LOOP_SUBCODES.get(result.termination_reason, {}).get(
                "description", result.termination_reason
            )
        ),
        failure_category=classification.category.value,
    )


def tool_loop_to_failure_record(
    result: ToolLoopResult,
    trace_id: str = "",
) -> FailureRecord | None:
    """Create a :class:`FailureRecord` from a failed :class:`ToolLoopResult`.

    Returns ``None`` if the result represents a successful completion.
    """
    if result.termination_reason == "completed":
        return None

    classification = classify_tool_loop_failure(result)
    meta = TOOL_LOOP_SUBCODES.get(result.termination_reason, {})

    return FailureRecord(
        trace_id=trace_id,
        classification=classification,
        message=str(meta.get("description", result.termination_reason)),
        context={
            "termination_reason": result.termination_reason,
            "iterations": str(result.iterations),
            "tool_calls_made": str(result.tool_calls_made),
            "tools_used": ",".join(result.tools_used),
            "model": result.model,
        },
        resolution=FailureResolution(
            retryable=classification.category
            in {FailureCategory.EXECUTION, FailureCategory.RESOURCE, FailureCategory.DEPENDENCY},
        ),
    )
