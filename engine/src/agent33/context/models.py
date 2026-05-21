"""Context engine models: slots, assembly reports, compaction events."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 -- Pydantic needs runtime type

from pydantic import BaseModel, Field


class ContextSlot(BaseModel):
    """A named slot in the assembled context window."""

    name: str
    priority: int = 0
    token_budget: int = 0
    source: str = ""
    content_hash: str = ""


class ContextAssemblyReport(BaseModel):
    """Report from a context assembly pass."""

    session_id: str
    timestamp: datetime
    slots_filled: list[ContextSlot] = Field(default_factory=list)
    total_tokens: int = 0
    compaction_triggered: bool = False
    engine_id: str = ""


class CompactionEvent(BaseModel):
    """Record of a single compaction operation."""

    session_id: str
    timestamp: datetime
    tokens_before: int
    tokens_after: int
    strategy: str = ""
    success: bool = True
    failure_reason: str = ""


class CompactionHistory(BaseModel):
    """Collection of compaction events for a session."""

    session_id: str
    events: list[CompactionEvent] = Field(default_factory=list)
    total_compactions: int = 0


# Rebuild Pydantic models so they resolve 'datetime' under PEP 563
ContextAssemblyReport.model_rebuild()
CompactionEvent.model_rebuild()
