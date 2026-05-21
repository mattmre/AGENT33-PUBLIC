"""Workflow event types for real-time run-scoped status streaming."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from agent33.config import settings

# ---------------------------------------------------------------------------
# Schema versioning
# ---------------------------------------------------------------------------

SCHEMA_VERSION_V1: int = 1
SCHEMA_VERSION_V2: int = 2
CURRENT_SCHEMA_VERSION: int = SCHEMA_VERSION_V1
"""The default schema version expected by existing clients.

Clients that receive an event with a different ``schema_version`` must
immediately close the connection and raise :exc:`SchemaVersionMismatchError`.
There is no graceful downgrade path.
"""

SSE_SCHEMA_V2_KILL_SWITCH = Path("/tmp/agent33_disable_sse_v2")


def sse_schema_v2_kill_switch_active() -> bool:
    """Return ``True`` when the file-based SSE v2 kill switch is active."""
    return SSE_SCHEMA_V2_KILL_SWITCH.exists()


def resolve_active_schema_version() -> int:
    """Resolve the schema version the backend should emit for new workflow runs."""
    if sse_schema_v2_kill_switch_active():
        return SCHEMA_VERSION_V1
    if settings.sse_schema_v2_enabled:
        return SCHEMA_VERSION_V2
    return SCHEMA_VERSION_V1


class SchemaVersionMismatchError(Exception):
    """Raised when an SSE client receives an event with an unexpected schema version."""

    def __init__(self, received: int, expected: int) -> None:
        self.received = received
        self.expected = expected
        super().__init__(f"SSE schema version mismatch: expected {expected}, got {received}")


def check_schema_version(
    event_dict: dict[str, Any],
    *,
    expected_version: int = CURRENT_SCHEMA_VERSION,
) -> None:
    """Strict schema-version guard for SSE client consumers.

    Reads ``schema_version`` from *event_dict*.  A missing key is treated as
    version ``0`` (i.e. a pre-versioning payload), which is always a mismatch
    against any positive *expected_version*.

    Raises:
        SchemaVersionMismatchError: When ``event_dict["schema_version"]`` does
            not equal *expected_version*.
    """
    received: int = int(event_dict.get("schema_version", 0))
    if received != expected_version:
        raise SchemaVersionMismatchError(received=received, expected=expected_version)


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


class WorkflowEventType(StrEnum):
    """Types of events emitted during workflow execution."""

    SYNC = "sync"
    HEARTBEAT = "heartbeat"
    WORKFLOW_STARTED = "workflow_started"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    STEP_SKIPPED = "step_skipped"
    STEP_RETRYING = "step_retrying"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"


@dataclass(frozen=True)
class WorkflowEvent:
    """Immutable event emitted during a single workflow execution run.

    ``run_id`` is the unique execution identifier. ``workflow_name`` identifies the
    workflow definition shared across multiple runs.
    """

    event_type: WorkflowEventType
    run_id: str
    workflow_name: str
    timestamp: float = field(default_factory=time.time)
    step_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    event_id: str | None = None
    schema_version: int = field(default_factory=resolve_active_schema_version)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for JSON serialization."""
        result: dict[str, Any] = {
            "type": self.event_type.value,
            "run_id": self.run_id,
            "workflow_name": self.workflow_name,
            "timestamp": self.timestamp,
            "schema_version": self.schema_version,
        }
        if self.step_id is not None:
            result["step_id"] = self.step_id
        if self.data:
            result["data"] = self.data
        return result

    def to_json(self) -> str:
        """Serialize the event to a JSON string for transport."""
        return json.dumps(self.to_dict())
