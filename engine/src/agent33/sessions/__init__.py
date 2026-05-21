"""Operator session safety and continuity (Phase 44 + Track 8).

Public API:
    OperatorSession, OperatorSessionStatus, TaskEntry,
    SessionEvent, SessionEventType,
    OperatorSessionService, FileSessionStorage,
    SessionCatalog, SessionLineageBuilder,
    SessionSpawnService, SessionArchiveService.
"""

from agent33.sessions.archive import SessionArchiveService
from agent33.sessions.catalog import SessionCatalog
from agent33.sessions.lineage import SessionLineageBuilder
from agent33.sessions.models import (
    OperatorSession,
    OperatorSessionStatus,
    SessionEvent,
    SessionEventType,
    TaskEntry,
)
from agent33.sessions.service import OperatorSessionService
from agent33.sessions.spawn import SessionSpawnService
from agent33.sessions.storage import FileSessionStorage

__all__ = [
    "FileSessionStorage",
    "OperatorSession",
    "OperatorSessionService",
    "OperatorSessionStatus",
    "SessionArchiveService",
    "SessionCatalog",
    "SessionEvent",
    "SessionEventType",
    "SessionLineageBuilder",
    "SessionSpawnService",
    "TaskEntry",
]
