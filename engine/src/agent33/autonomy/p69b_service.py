"""P69b: Human-in-the-loop tool approval — service layer.

Persistence is optional: pass a P69bPersistence instance at construction to
enable SQLite-backed storage so PausedInvocation records survive process
restarts.  Without it the service operates purely in-memory (backwards
compatible with the original PR #401 behaviour).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from agent33.autonomy.p69b_models import (
    PausedInvocation,
    PausedInvocationStatus,
    ToolApprovalInvalidState,
    ToolApprovalNonceReplay,
    ToolApprovalTimeout,
)

if TYPE_CHECKING:
    from agent33.autonomy.p69b_persistence import P69bPersistence

logger = structlog.get_logger()


class P69bService:
    """Service for P69b tool approval pause/resume operations.

    When constructed with a ``persistence`` argument the service:
    - Saves every new PausedInvocation to SQLite after adding it to ``_store``.
    - Saves every update (approve / deny / timeout) to SQLite.
    - Re-hydrates ``_store`` from the DB on startup via
      ``_load_from_persistence()`` so state survives process restarts.

    Without ``persistence`` the service is purely in-memory, which keeps
    existing tests working without any modification.
    """

    def __init__(
        self,
        *,
        timeout_seconds: int = 300,
        persistence: P69bPersistence | None = None,
    ) -> None:
        self._store: dict[str, PausedInvocation] = {}
        self._timeout_seconds = timeout_seconds
        self._persistence = persistence
        if persistence is not None:
            self._load_from_persistence()

    # ------------------------------------------------------------------
    # Startup hydration
    # ------------------------------------------------------------------

    def _load_from_persistence(self) -> None:
        """Re-hydrate _store with PENDING records loaded from the DB.

        Only PENDING records that have not yet expired are loaded; resolved or
        timed-out records are left in the DB for audit purposes but are not
        put back into the live in-memory store.
        """
        if self._persistence is None:
            return
        records = self._persistence.load_pending()
        for record in records:
            self._store[record.id] = record
        logger.info("p69b_store_hydrated", count=len(records))

    # ------------------------------------------------------------------
    # Feature flag / headless mode
    # ------------------------------------------------------------------

    def is_enabled(self) -> bool:
        """Return True when P69b is active.

        Checks (in priority order):
        1. File-based kill switch: /tmp/agent33_disable_p69b (takes precedence).
        2. Env var P69B_TOOL_APPROVAL_ENABLED must be "true" (case-insensitive).
        """
        import os
        from pathlib import Path

        if Path("/tmp/agent33_disable_p69b").exists():
            return False
        return os.environ.get("P69B_TOOL_APPROVAL_ENABLED", "false").lower() == "true"

    def headless_mode(self) -> str | None:
        """Return 'approve', 'deny', or None (interactive mode).

        Reads AGENT33_HEADLESS_TOOL_APPROVAL. Values other than 'approve' or
        'deny' are treated as interactive (None).
        """
        import os

        val = os.environ.get("AGENT33_HEADLESS_TOOL_APPROVAL", "").lower()
        return val if val in ("approve", "deny") else None

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def pause(
        self,
        invocation_id: str,
        tenant_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        nonce: str,
    ) -> PausedInvocation:
        """Create a PausedInvocation record and store it.

        Raises ToolApprovalNonceReplay if the nonce has already been consumed
        by a prior record in this store.
        """
        for record in self._store.values():
            if record.nonce == nonce and record.status == PausedInvocationStatus.CONSUMED:
                raise ToolApprovalNonceReplay(f"Nonce already consumed: {nonce}")

        expires_at = datetime.now(UTC) + timedelta(seconds=self._timeout_seconds)
        record = PausedInvocation(
            invocation_id=invocation_id,
            tenant_id=tenant_id,
            tool_name=tool_name,
            tool_input=tool_input,
            nonce=nonce,
            expires_at=expires_at,
        )
        self._store[record.id] = record
        if self._persistence is not None:
            self._persistence.save(record)
        return record

    def resume(
        self,
        approval_id: str,
        *,
        approved: bool,
        approved_by: str = "",
    ) -> PausedInvocation:
        """Approve or deny a pending approval record.

        Raises:
            ToolApprovalInvalidState: Record not found or not in PENDING state.
            ToolApprovalTimeout: Approval window has elapsed.
        """
        record = self._store.get(approval_id)
        if record is None:
            raise ToolApprovalInvalidState(f"No approval record: {approval_id}")
        if record.status != PausedInvocationStatus.PENDING:
            raise ToolApprovalInvalidState(f"Record not in PENDING state: {record.status}")
        if datetime.now(UTC) > record.expires_at:
            updated = record.model_copy(
                update={
                    "status": PausedInvocationStatus.TIMED_OUT,
                    "resolved_at": datetime.now(UTC),
                }
            )
            self._store[approval_id] = updated
            if self._persistence is not None:
                self._persistence.save(updated)
            raise ToolApprovalTimeout(f"Approval expired at {record.expires_at}")

        new_status = PausedInvocationStatus.APPROVED if approved else PausedInvocationStatus.DENIED
        updated = record.model_copy(
            update={
                "status": new_status,
                "resolved_at": datetime.now(UTC),
                "approved_by": approved_by,
            }
        )
        self._store[approval_id] = updated
        if self._persistence is not None:
            self._persistence.save(updated)
        return updated

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_pending(self, invocation_id: str) -> list[PausedInvocation]:
        """Return all PENDING records for the given invocation_id."""
        return [
            r
            for r in self._store.values()
            if r.invocation_id == invocation_id and r.status == PausedInvocationStatus.PENDING
        ]

    def get_all_pending(self, tenant_id: str) -> list[PausedInvocation]:
        """Return all PENDING records for the given tenant, ordered by created_at asc."""
        records = [
            r
            for r in self._store.values()
            if r.tenant_id == tenant_id and r.status == PausedInvocationStatus.PENDING
        ]
        records.sort(key=lambda r: r.created_at)
        return records
