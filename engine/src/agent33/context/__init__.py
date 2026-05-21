"""Context engine abstraction (Track 8).

Public API:
    ContextSlot, ContextAssemblyReport, CompactionEvent, CompactionHistory,
    ContextEngine, BuiltinContextEngine, ContextEngineRegistry.
"""

from agent33.context.engine import BuiltinContextEngine, ContextEngine
from agent33.context.models import (
    CompactionEvent,
    CompactionHistory,
    ContextAssemblyReport,
    ContextSlot,
)
from agent33.context.registry import ContextEngineRegistry

__all__ = [
    "BuiltinContextEngine",
    "CompactionEvent",
    "CompactionHistory",
    "ContextAssemblyReport",
    "ContextEngine",
    "ContextEngineRegistry",
    "ContextSlot",
]
