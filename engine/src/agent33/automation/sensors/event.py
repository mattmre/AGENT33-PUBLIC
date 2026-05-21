"""In-memory event pub/sub sensor."""

from __future__ import annotations

import dataclasses
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True, slots=True)
class Event:
    """An emitted event."""

    event_type: str
    data: dict[str, Any]


class EventSensor:
    """Simple in-memory publish/subscribe system for internal events."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[Event], Awaitable[Any]]]] = defaultdict(list)

    def subscribe(
        self,
        event_type: str,
        callback: Callable[[Event], Awaitable[Any]],
    ) -> None:
        """Register a callback for the given event type.

        Parameters
        ----------
        event_type:
            Event type string to listen for.
        callback:
            Async callable invoked with an :class:`Event` when emitted.
        """
        self._subscribers[event_type].append(callback)
        logger.info(
            "Subscribed to event type %s (total subscribers: %d)",
            event_type,
            len(self._subscribers[event_type]),
        )

    async def emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Emit an event, notifying all subscribers of the given type.

        Parameters
        ----------
        event_type:
            Event type string.
        data:
            Arbitrary event payload.
        """
        event = Event(event_type=event_type, data=data or {})
        callbacks = self._subscribers.get(event_type, [])
        logger.debug("Emitting event %s to %d subscribers", event_type, len(callbacks))
        for cb in callbacks:
            try:
                await cb(event)
            except Exception:
                logger.exception("Error in event subscriber for %s", event_type)
