"""Models for managed background processes."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ManagedProcessStatus(StrEnum):
    """Lifecycle states for a managed process."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"
    INTERRUPTED = "interrupted"


class ManagedProcessRecord(BaseModel):
    """Persisted metadata for a managed process."""

    process_id: str
    command: str
    status: ManagedProcessStatus = ManagedProcessStatus.RUNNING
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    exit_code: int | None = None
    pid: int | None = None
    agent_id: str = ""
    session_id: str = ""
    tenant_id: str = ""
    requested_by: str = ""
    working_dir: str = ""
    log_path: str = ""
    last_error: str = ""


class ManagedProcessListResponse(BaseModel):
    """Response model for process listing."""

    processes: list[ManagedProcessRecord] = Field(default_factory=list)
    count: int = 0
    total: int = 0


class ManagedProcessLogResponse(BaseModel):
    """Tail of a managed process log."""

    process_id: str
    content: str = ""
    line_count: int = 0


class ManagedProcessCleanupResponse(BaseModel):
    """Summary for completed-process cleanup."""

    removed: int = 0
