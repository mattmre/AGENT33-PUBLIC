"""Hook protocol definition and base implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agent33.hooks.models import HookContext


class HookAbortError(Exception):
    """Raised when a hook chain aborts and the caller should not proceed."""

    def __init__(self, reason: str = "") -> None:
        self.reason = reason
        super().__init__(reason)


class Hook(Protocol):
    """Base hook protocol. All hooks implement this interface."""

    @property
    def name(self) -> str: ...

    @property
    def event_type(self) -> str: ...

    @property
    def priority(self) -> int: ...

    @property
    def enabled(self) -> bool: ...

    @property
    def tenant_id(self) -> str: ...

    async def execute(
        self,
        context: HookContext,
        call_next: Callable[[HookContext], Awaitable[HookContext]],
    ) -> HookContext: ...


class BaseHook:
    """Convenient base class for concrete hook implementations.

    Subclasses override :meth:`execute` with their custom logic.
    Provides sensible defaults for the protocol properties.
    """

    def __init__(
        self,
        *,
        name: str,
        event_type: str,
        priority: int = 100,
        enabled: bool = True,
        tenant_id: str = "",
    ) -> None:
        self._name = name
        self._event_type = event_type
        self._priority = priority
        self._enabled = enabled
        self._tenant_id = tenant_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def event_type(self) -> str:
        return self._event_type

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    async def execute(
        self,
        context: HookContext,
        call_next: Callable[[HookContext], Awaitable[HookContext]],
    ) -> HookContext:
        """Default implementation delegates to the next hook."""
        return await call_next(context)
