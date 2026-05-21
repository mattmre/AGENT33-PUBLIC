"""Lifecycle state machine for CandidateAsset.

Enforces the canonical ``candidate → validated → published → revoked``
transition graph defined by architectural decision #18.

CLEAN-ROOM RESTRICTION
=======================
No code in this file may originate from the EvoMap/Evolver project.  All
logic is derived exclusively from AGENT33's own architectural decisions #17
and #18 as documented in ``docs/phases/PHASE-PLAN-POST-P72-2026.md`` and
``docs/research/evolver-clean-room-guardrails.md``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agent33.ingestion.models import CandidateAsset, CandidateStatus


class CandidateTransitionError(Exception):
    """Raised when a requested lifecycle transition is not permitted.

    Provides a human-readable message that names both the current and the
    requested target status so callers can surface meaningful error detail.
    """

    def __init__(self, current: CandidateStatus, target: CandidateStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(
            f"Cannot transition from {current.value!r} to {target.value!r}: "
            "transition is not permitted by the candidate lifecycle."
        )


class CandidateStateMachine:
    """Enforces valid lifecycle transitions for CandidateAsset.

    Valid transitions:
      CANDIDATE  → VALIDATED   (validate)
      CANDIDATE  → REVOKED     (revoke — reject without review)
      VALIDATED  → PUBLISHED   (promote)
      VALIDATED  → REVOKED     (revoke — fail validation)
      PUBLISHED  → REVOKED     (revoke — post-publish retract)

    Invalid transitions raise ``CandidateTransitionError``.

    ``VALID_TRANSITIONS`` is the single source of truth for this graph.
    No other code in this module or its siblings performs inline status
    comparisons — the service layer delegates entirely to this class.
    """

    VALID_TRANSITIONS: dict[CandidateStatus, set[CandidateStatus]] = {
        CandidateStatus.CANDIDATE: {CandidateStatus.VALIDATED, CandidateStatus.REVOKED},
        CandidateStatus.VALIDATED: {CandidateStatus.PUBLISHED, CandidateStatus.REVOKED},
        CandidateStatus.PUBLISHED: {CandidateStatus.REVOKED},
        CandidateStatus.REVOKED: set(),  # terminal state
    }

    def transition(
        self,
        asset: CandidateAsset,
        target: CandidateStatus,
        *,
        operator: str | None = None,
        reason: str | None = None,
    ) -> CandidateAsset:
        """Apply a lifecycle transition and return an updated ``CandidateAsset``.

        The returned object is a new instance (via ``model_copy``); the caller
        is responsible for persisting it.

        Args:
            asset: The asset whose status is to be changed.
            target: The desired target status.
            operator: Optional identifier of the human or system initiating the
                transition (stored for audit purposes on revocation).
            reason: Optional free-text reason.  Required semantically when
                ``target`` is ``REVOKED``; the service layer enforces this.

        Returns:
            A new ``CandidateAsset`` with the updated status, timestamps, and
            (if applicable) revocation_reason.

        Raises:
            CandidateTransitionError: If the transition from the asset's current
                status to ``target`` is not in ``VALID_TRANSITIONS``.
        """
        allowed = self.VALID_TRANSITIONS.get(asset.status, set())
        if target not in allowed:
            raise CandidateTransitionError(asset.status, target)

        now = datetime.now(UTC)
        updates: dict[str, object] = {
            "status": target,
            "updated_at": now,
        }

        if target == CandidateStatus.VALIDATED:
            updates["validated_at"] = now
        elif target == CandidateStatus.PUBLISHED:
            updates["published_at"] = now
        elif target == CandidateStatus.REVOKED:
            updates["revoked_at"] = now
            if reason is not None:
                updates["revocation_reason"] = reason

        return asset.model_copy(update=updates)
