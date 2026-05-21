"""Abstract protocol definitions for messaging subsystem."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@runtime_checkable
class MessageBusProtocol(Protocol):
    """Protocol for message bus backends."""

    async def publish(self, subject: str, data: bytes) -> None: ...
    async def subscribe(
        self, subject: str, handler: Callable[[bytes], Awaitable[None]]
    ) -> None: ...
    async def unsubscribe(self, subject: str) -> None: ...
    async def close(self) -> None: ...
