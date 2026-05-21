"""Base messaging adapter protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agent33.messaging.models import ChannelHealthResult, Message


@runtime_checkable
class MessagingAdapter(Protocol):
    """Protocol that all platform messaging adapters must implement."""

    @property
    def platform(self) -> str:
        """Return the platform identifier (e.g. 'telegram', 'discord')."""
        ...

    async def send(self, channel_id: str, text: str) -> None:
        """Send a text message to the given channel."""
        ...

    async def receive(self) -> Message:
        """Block until the next inbound message is available and return it."""
        ...

    async def start(self) -> None:
        """Start the adapter (open connections, begin polling, etc.)."""
        ...

    async def stop(self) -> None:
        """Gracefully shut down the adapter."""
        ...

    async def health_check(self) -> ChannelHealthResult:
        """Probe upstream API connectivity and return health status."""
        ...
