"""Context transfer between sessions for agent handoffs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent33.memory.session import SessionManager


class ContextTransfer:
    """Copies specified context fields between sessions."""

    def __init__(self, session_manager: SessionManager) -> None:
        self._sm = session_manager

    def transfer(
        self,
        source_session: str,
        target_session: str,
        fields: list[str],
    ) -> dict[str, Any]:
        """Copy *fields* from source session data to target session data.

        Returns the dict of transferred key-value pairs.
        """
        source = self._sm.get(source_session)
        transferred: dict[str, Any] = {}
        for f in fields:
            if f in source.data:
                transferred[f] = source.data[f]

        if transferred:
            self._sm.update(target_session, transferred)

        return transferred
