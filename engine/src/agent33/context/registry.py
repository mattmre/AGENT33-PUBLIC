"""Context engine registry: discover, select, and manage context engines."""

from __future__ import annotations

import logging
from typing import Any

from agent33.context.engine import BuiltinContextEngine, ContextEngine

logger = logging.getLogger(__name__)


class ContextEngineRegistry:
    """Manages available context engines and selects the active one."""

    def __init__(self, default_engine: str = "builtin") -> None:
        self._engines: dict[str, ContextEngine] = {}
        self._active_id: str = default_engine

        # Always register the builtin engine
        builtin = BuiltinContextEngine()
        self._engines[builtin.engine_id] = builtin

    def register(self, engine: ContextEngine) -> None:
        """Register a context engine.

        Raises:
            ValueError: If an engine with the same id is already registered.
        """
        if engine.engine_id in self._engines:
            raise ValueError(f"Context engine '{engine.engine_id}' is already registered")
        self._engines[engine.engine_id] = engine
        logger.info("context_engine_registered engine_id=%s", engine.engine_id)

    def get_active(self) -> ContextEngine:
        """Return the currently active context engine.

        Raises:
            KeyError: If the active engine id is not registered.
        """
        engine = self._engines.get(self._active_id)
        if engine is None:
            raise KeyError(f"Active context engine '{self._active_id}' is not registered")
        return engine

    def list_available(self) -> list[str]:
        """Return the ids of all registered engines."""
        return sorted(self._engines.keys())

    def set_active(self, engine_id: str) -> None:
        """Switch the active context engine.

        Raises:
            KeyError: If the engine id is not registered.
        """
        if engine_id not in self._engines:
            raise KeyError(f"Context engine '{engine_id}' is not registered")
        self._active_id = engine_id
        logger.info("context_engine_active engine_id=%s", engine_id)

    def health_check(self) -> dict[str, Any]:
        """Return health status for all registered engines."""
        results: dict[str, Any] = {
            "active_engine": self._active_id,
            "engines": {},
        }
        for engine_id, engine in self._engines.items():
            try:
                results["engines"][engine_id] = engine.health()
            except Exception as exc:
                results["engines"][engine_id] = {
                    "engine_id": engine_id,
                    "status": "error",
                    "error": str(exc),
                }
        return results
