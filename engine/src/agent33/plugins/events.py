"""Plugin lifecycle event recording."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.services.orchestration_state import OrchestrationStateStore


class PluginLifecycleEvent(BaseModel):
    """Recorded lifecycle event for one plugin action."""

    event_type: str
    plugin_name: str
    version: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = Field(default_factory=dict)


class PluginEventStore:
    """Persist plugin lifecycle events in the orchestration state store."""

    def __init__(
        self,
        state_store: OrchestrationStateStore | None = None,
        *,
        namespace: str = "plugin_events",
        max_events: int = 500,
    ) -> None:
        self._state_store = state_store
        self._namespace = namespace
        self._max_events = max(1, max_events)
        self._events: list[PluginLifecycleEvent] = []
        self._load()

    def record(
        self,
        event_type: str,
        plugin_name: str,
        *,
        version: str = "",
        details: dict[str, Any] | None = None,
    ) -> PluginLifecycleEvent:
        """Append and persist a plugin lifecycle event."""
        event = PluginLifecycleEvent(
            event_type=event_type,
            plugin_name=plugin_name,
            version=version,
            details=dict(details or {}),
        )
        self._events.append(event)
        self._events = self._events[-self._max_events :]
        self._persist()
        return event

    def list(
        self,
        *,
        plugin_name: str | None = None,
        limit: int = 50,
    ) -> list[PluginLifecycleEvent]:
        """Return newest-first events, optionally filtered by plugin."""
        filtered = self._events
        if plugin_name:
            filtered = [event for event in filtered if event.plugin_name == plugin_name]
        return list(reversed(filtered[-max(1, limit) :]))

    def _load(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace(self._namespace)
        raw_events = payload.get("events", [])
        if not isinstance(raw_events, list):
            return
        self._events = []
        for raw in raw_events:
            if not isinstance(raw, dict):
                continue
            try:
                self._events.append(PluginLifecycleEvent.model_validate(raw))
            except Exception:
                continue

    def _persist(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            self._namespace,
            {
                "events": [event.model_dump(mode="json") for event in self._events],
            },
        )
