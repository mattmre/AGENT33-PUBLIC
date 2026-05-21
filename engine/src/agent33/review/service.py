"""Review service: orchestrates the two-layer review lifecycle.

Provides CRUD, risk assessment, reviewer assignment, and state transitions
for :class:`ReviewRecord` instances.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import ValidationError

if TYPE_CHECKING:
    from agent33.services.orchestration_state import OrchestrationStateStore

from agent33.review.assignment import ReviewerAssigner
from agent33.review.models import (
    FinalSignoff,
    L1ChecklistResults,
    L2ChecklistResults,
    ReviewArtifactLink,
    ReviewDecision,
    ReviewRecord,
    RiskTrigger,
    SignoffState,
)
from agent33.review.risk import RiskAssessor
from agent33.review.state_machine import InvalidTransitionError, SignoffStateMachine

logger = logging.getLogger(__name__)


def _sanitize_log_value(value: str) -> str:
    """Escape line breaks in user-controlled values before logging."""
    return value.replace("\r", "\\r").replace("\n", "\\n")


class ReviewNotFoundError(Exception):
    """Raised when a review record is not found."""


class ReviewStateError(Exception):
    """Raised when an operation is invalid for the current review state."""


class ReviewService:
    """Review lifecycle manager with optional durable state.

    Thread-safety note: the service is *not* thread-safe.  For concurrent
    access behind an async web server this is acceptable because the event
    loop is single-threaded.
    """

    def __init__(self, state_store: OrchestrationStateStore | None = None) -> None:
        self._state_store = state_store
        self._reviews: dict[str, ReviewRecord] = {}
        self._risk_assessor = RiskAssessor()
        self._assigner = ReviewerAssigner()
        if state_store is None:
            logger.warning(
                "review_service_no_persistence: state_store is None, all review records "
                "are in-memory only and will be lost on restart. Set "
                "ORCHESTRATION_STATE_STORE_PATH to enable durable persistence."
            )
        self._load_state()

    def _persist_state(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            "reviews",
            {
                "records": {
                    review_id: review.model_dump(mode="json")
                    for review_id, review in self._reviews.items()
                }
            },
        )

    def _load_state(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace("reviews")
        records_payload = payload.get("records", {})
        if not isinstance(records_payload, dict):
            return
        for review_id, review_data in records_payload.items():
            if not isinstance(review_id, str):
                continue
            try:
                record = ReviewRecord.model_validate(review_data)
            except ValidationError:
                logger.warning("review_restore_failed id=%s", review_id)
                continue
            self._reviews[review_id] = record

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        task_id: str,
        branch: str = "",
        pr_number: int | None = None,
        tenant_id: str = "",
        artifacts: list[ReviewArtifactLink] | None = None,
    ) -> ReviewRecord:
        """Create a new review record in DRAFT state."""
        record = ReviewRecord(
            task_id=task_id,
            branch=branch,
            pr_number=pr_number,
            tenant_id=tenant_id,
            artifacts=artifacts or [],
        )
        self._reviews[record.id] = record
        logger.info("review_created id=%s task=%s", record.id, _sanitize_log_value(task_id))
        self._persist_state()
        return record

    def get(self, review_id: str) -> ReviewRecord:
        """Retrieve a review by ID or raise :class:`ReviewNotFoundError`."""
        record = self._reviews.get(review_id)
        if record is None:
            raise ReviewNotFoundError(f"Review not found: {review_id}")
        return record

    def list_all(self, tenant_id: str | None = None) -> list[ReviewRecord]:
        """Return all reviews, optionally filtered by tenant."""
        if tenant_id is not None:
            return [r for r in self._reviews.values() if r.tenant_id == tenant_id]
        return list(self._reviews.values())

    def delete(self, review_id: str) -> None:
        """Remove a review record."""
        if review_id not in self._reviews:
            raise ReviewNotFoundError(f"Review not found: {review_id}")
        del self._reviews[review_id]
        logger.info("review_deleted id=%s", review_id)
        self._persist_state()

    # ------------------------------------------------------------------
    # Risk assessment
    # ------------------------------------------------------------------

    def assess_risk(
        self,
        review_id: str,
        triggers: list[RiskTrigger],
    ) -> ReviewRecord:
        """Run risk assessment and update the review record."""
        record = self.get(review_id)
        assessment = self._risk_assessor.assess(triggers)
        record.risk_assessment = assessment
        record.touch()
        logger.info(
            "risk_assessed id=%s level=%s l1=%s l2=%s",
            review_id,
            assessment.risk_level.value,
            assessment.l1_required,
            assessment.l2_required,
        )
        self._persist_state()
        return record

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _transition(self, record: ReviewRecord, to_state: SignoffState) -> None:
        """Apply a state transition, raising on invalid moves."""
        try:
            new_state = SignoffStateMachine.transition(record.state, to_state)
        except InvalidTransitionError as exc:
            raise ReviewStateError(str(exc)) from exc
        record.state = new_state
        record.touch()

    def mark_ready(self, review_id: str) -> ReviewRecord:
        """Move review from DRAFT to READY."""
        record = self.get(review_id)
        self._transition(record, SignoffState.READY)
        self._persist_state()
        return record

    def assign_l1(self, review_id: str) -> ReviewRecord:
        """Assign an L1 reviewer and move to L1_REVIEW."""
        record = self.get(review_id)
        self._transition(record, SignoffState.L1_REVIEW)

        l1, _ = self._assigner.assign(record.risk_assessment.triggers_identified)
        record.l1_review.reviewer_id = l1.agent_id
        record.l1_review.reviewer_role = l1.reviewer_role
        record.l1_review.assigned_at = datetime.now(UTC)
        record.touch()
        logger.info(
            "l1_assigned id=%s reviewer=%s role=%s",
            review_id,
            l1.agent_id,
            l1.reviewer_role,
        )
        self._persist_state()
        return record

    def submit_l1(
        self,
        review_id: str,
        decision: ReviewDecision,
        checklist: L1ChecklistResults | None = None,
        issues: list[str] | None = None,
        comments: str = "",
    ) -> ReviewRecord:
        """Submit L1 review decision."""
        record = self.get(review_id)

        if record.state != SignoffState.L1_REVIEW:
            raise ReviewStateError(f"Cannot submit L1 review in state {record.state.value}")

        record.l1_review.decision = decision
        record.l1_review.completed_at = datetime.now(UTC)
        record.l1_review.comments = comments
        if issues:
            record.l1_review.issues_found = issues
        if checklist:
            record.l1_review.checklist_results = checklist.model_dump()

        if decision == ReviewDecision.APPROVED:
            if record.risk_assessment.l2_required:
                self._transition(record, SignoffState.L1_APPROVED)
            else:
                self._transition(record, SignoffState.L1_APPROVED)
                self._transition(record, SignoffState.APPROVED)
        elif decision == ReviewDecision.CHANGES_REQUESTED:
            self._transition(record, SignoffState.L1_CHANGES_REQUESTED)
        elif decision == ReviewDecision.ESCALATED:
            # Escalation triggers L2 requirement
            record.risk_assessment.l2_required = True
            self._transition(record, SignoffState.L1_APPROVED)

        logger.info("l1_submitted id=%s decision=%s", review_id, decision.value)
        self._persist_state()
        return record

    def assign_l2(self, review_id: str) -> ReviewRecord:
        """Assign an L2 reviewer and move to L2_REVIEW."""
        record = self.get(review_id)
        self._transition(record, SignoffState.L2_REVIEW)

        _, l2 = self._assigner.assign(record.risk_assessment.triggers_identified)
        record.l2_review.reviewer_id = l2.agent_id
        record.l2_review.reviewer_role = l2.reviewer_role
        record.l2_review.assigned_at = datetime.now(UTC)
        record.touch()
        logger.info(
            "l2_assigned id=%s reviewer=%s role=%s",
            review_id,
            l2.agent_id,
            l2.reviewer_role,
        )
        self._persist_state()
        return record

    def submit_l2(
        self,
        review_id: str,
        decision: ReviewDecision,
        checklist: L2ChecklistResults | None = None,
        issues: list[str] | None = None,
        comments: str = "",
    ) -> ReviewRecord:
        """Submit L2 review decision."""
        record = self.get(review_id)

        if record.state != SignoffState.L2_REVIEW:
            raise ReviewStateError(f"Cannot submit L2 review in state {record.state.value}")

        record.l2_review.decision = decision
        record.l2_review.completed_at = datetime.now(UTC)
        record.l2_review.comments = comments
        if issues:
            record.l2_review.issues_found = issues
        if checklist:
            record.l2_review.checklist_results = checklist.model_dump()

        if decision == ReviewDecision.APPROVED:
            self._transition(record, SignoffState.L2_APPROVED)
            self._transition(record, SignoffState.APPROVED)
        elif decision == ReviewDecision.CHANGES_REQUESTED:
            self._transition(record, SignoffState.L2_CHANGES_REQUESTED)
        elif decision == ReviewDecision.ESCALATED:
            # Escalation keeps it in L2 but flags for human
            self._transition(record, SignoffState.L2_CHANGES_REQUESTED)

        logger.info("l2_submitted id=%s decision=%s", review_id, decision.value)
        self._persist_state()
        return record

    def approve(
        self,
        review_id: str,
        approver_id: str,
        conditions: list[str] | None = None,
    ) -> ReviewRecord:
        """Record final signoff on an APPROVED review."""
        record = self.get(review_id)

        if record.state != SignoffState.APPROVED:
            raise ReviewStateError(f"Cannot approve review in state {record.state.value}")

        # Determine approval type
        if record.l2_review.decision is not None:
            if record.l2_review.reviewer_id == "HUMAN":
                approval_type = "l1_l2_human"
            else:
                approval_type = "l1_l2_agent"
        else:
            approval_type = "l1_only"

        record.final_signoff = FinalSignoff(
            approved_by=approver_id,
            approved_at=datetime.now(UTC),
            approval_type=approval_type,
            conditions=conditions or [],
        )
        record.touch()
        logger.info(
            "review_approved id=%s by=%s type=%s",
            review_id,
            _sanitize_log_value(approver_id),
            approval_type,
        )
        self._persist_state()
        return record

    def approve_with_rationale(
        self,
        review_id: str,
        approver_id: str,
        decision: str,
        rationale: str = "",
        modification_summary: str = "",
        conditions: list[str] | None = None,
        linked_intake_id: str | None = None,
    ) -> ReviewRecord:
        """Record a structured approval decision with rationale.

        Supports ``approved``, ``changes_requested``, ``escalated``, and
        ``deferred`` decisions. The review must be in APPROVED state.
        For ``changes_requested`` and ``deferred``, the review transitions
        to the corresponding state; for ``approved``, it stays in APPROVED
        (the caller should then call ``merge``).
        """
        record = self.get(review_id)

        if record.state != SignoffState.APPROVED:
            raise ReviewStateError(
                f"Cannot apply rationale approval in state {record.state.value}"
            )

        # Determine approval type
        if record.l2_review.decision is not None:
            if record.l2_review.reviewer_id == "HUMAN":
                approval_type = "l1_l2_human"
            else:
                approval_type = "l1_l2_agent"
        else:
            approval_type = "l1_only"

        record.final_signoff = FinalSignoff(
            approved_by=approver_id,
            approved_at=datetime.now(UTC),
            approval_type=approval_type,
            conditions=conditions or [],
            rationale=rationale,
            modification_summary=modification_summary,
            linked_intake_id=linked_intake_id,
        )

        # Apply state transition based on decision
        if decision == "changes_requested":
            self._transition(record, SignoffState.CHANGES_REQUESTED)
        elif decision == "deferred":
            self._transition(record, SignoffState.DEFERRED)
        else:
            # "approved" and "escalated" keep the record in APPROVED state
            record.touch()

        logger.info(
            "review_approved_with_rationale id=%s by=%s decision=%s",
            review_id,
            _sanitize_log_value(approver_id),
            decision,
        )
        self._persist_state()
        return record

    def merge(self, review_id: str) -> ReviewRecord:
        """Mark a review as MERGED (final state)."""
        record = self.get(review_id)
        self._transition(record, SignoffState.MERGED)
        logger.info("review_merged id=%s", review_id)
        self._persist_state()
        return record
