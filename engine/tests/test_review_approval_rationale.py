"""Tests for the extended review approval with rationale.

Covers: approve_with_rationale service method, new state transitions
(APPROVED -> CHANGES_REQUESTED -> READY, APPROVED -> DEFERRED -> READY),
the API endpoint, and error paths.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes import workflows
from agent33.main import app
from agent33.review.models import (
    ReviewDecision,
    RiskTrigger,
    SignoffState,
)
from agent33.review.service import ReviewService, ReviewStateError
from agent33.review.state_machine import SignoffStateMachine
from agent33.security import auth
from agent33.security.auth import create_access_token


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Reset global state between tests."""
    workflows.reset_workflow_state()
    auth._api_keys.clear()
    yield
    workflows.reset_workflow_state()
    auth._api_keys.clear()


def _auth_headers(
    *,
    subject: str = "test-user",
    tenant_id: str = "t1",
    scopes: list[str] | None = None,
) -> dict[str, str]:
    token = create_access_token(
        subject,
        scopes=scopes or ["workflows:read", "workflows:write"],
        tenant_id=tenant_id,
    )
    return {"Authorization": f"Bearer {token}"}


def _advance_to_approved(service: ReviewService, review_id: str) -> None:
    """Advance a review through the full signoff pipeline to APPROVED state."""
    service.assess_risk(review_id, [RiskTrigger.CODE_ISOLATED])
    service.mark_ready(review_id)
    service.assign_l1(review_id)
    service.submit_l1(review_id, decision=ReviewDecision.APPROVED)


# ---------------------------------------------------------------------------
# State machine unit tests
# ---------------------------------------------------------------------------


class TestExtendedStateTransitions:
    def test_approved_to_changes_requested(self) -> None:
        result = SignoffStateMachine.transition(
            SignoffState.APPROVED, SignoffState.CHANGES_REQUESTED
        )
        assert result == SignoffState.CHANGES_REQUESTED

    def test_changes_requested_to_ready(self) -> None:
        result = SignoffStateMachine.transition(SignoffState.CHANGES_REQUESTED, SignoffState.READY)
        assert result == SignoffState.READY

    def test_approved_to_deferred(self) -> None:
        result = SignoffStateMachine.transition(SignoffState.APPROVED, SignoffState.DEFERRED)
        assert result == SignoffState.DEFERRED

    def test_deferred_to_ready(self) -> None:
        result = SignoffStateMachine.transition(SignoffState.DEFERRED, SignoffState.READY)
        assert result == SignoffState.READY

    def test_approved_to_merged_still_valid(self) -> None:
        result = SignoffStateMachine.transition(SignoffState.APPROVED, SignoffState.MERGED)
        assert result == SignoffState.MERGED

    def test_valid_next_states_for_approved(self) -> None:
        next_states = SignoffStateMachine.valid_next_states(SignoffState.APPROVED)
        assert SignoffState.MERGED in next_states
        assert SignoffState.CHANGES_REQUESTED in next_states
        assert SignoffState.DEFERRED in next_states


# ---------------------------------------------------------------------------
# Service layer tests
# ---------------------------------------------------------------------------


class TestApproveWithRationaleService:
    def test_approve_with_rationale_approved(self) -> None:
        service = ReviewService()
        record = service.create(task_id="task-1", tenant_id="t1")
        _advance_to_approved(service, record.id)

        result = service.approve_with_rationale(
            record.id,
            approver_id="operator-1",
            decision="approved",
            rationale="All checks pass.",
            conditions=["Monitor for 24h"],
        )
        assert result.state == SignoffState.APPROVED
        assert result.final_signoff.approved_by == "operator-1"
        assert result.final_signoff.rationale == "All checks pass."
        assert result.final_signoff.conditions == ["Monitor for 24h"]
        assert result.final_signoff.approval_type == "l1_only"

    def test_approve_with_rationale_changes_requested(self) -> None:
        service = ReviewService()
        record = service.create(task_id="task-2", tenant_id="t1")
        _advance_to_approved(service, record.id)

        result = service.approve_with_rationale(
            record.id,
            approver_id="operator-1",
            decision="changes_requested",
            rationale="Missing test coverage.",
            modification_summary="Add unit tests for edge cases.",
        )
        assert result.state == SignoffState.CHANGES_REQUESTED
        assert result.final_signoff.rationale == "Missing test coverage."
        assert result.final_signoff.modification_summary == "Add unit tests for edge cases."

    def test_approve_with_rationale_deferred(self) -> None:
        service = ReviewService()
        record = service.create(task_id="task-3", tenant_id="t1")
        _advance_to_approved(service, record.id)

        result = service.approve_with_rationale(
            record.id,
            approver_id="operator-1",
            decision="deferred",
            rationale="Need more data before deciding.",
        )
        assert result.state == SignoffState.DEFERRED
        assert result.final_signoff.rationale == "Need more data before deciding."

    def test_approve_with_rationale_escalated(self) -> None:
        service = ReviewService()
        record = service.create(task_id="task-4", tenant_id="t1")
        _advance_to_approved(service, record.id)

        result = service.approve_with_rationale(
            record.id,
            approver_id="operator-1",
            decision="escalated",
            rationale="Requires architect review.",
        )
        # Escalated keeps it in APPROVED state
        assert result.state == SignoffState.APPROVED
        assert result.final_signoff.rationale == "Requires architect review."

    def test_approve_with_linked_intake(self) -> None:
        service = ReviewService()
        record = service.create(task_id="task-5", tenant_id="t1")
        _advance_to_approved(service, record.id)

        result = service.approve_with_rationale(
            record.id,
            approver_id="operator-1",
            decision="approved",
            rationale="Linked to intake.",
            linked_intake_id="intake-abc123",
        )
        assert result.final_signoff.linked_intake_id == "intake-abc123"

    def test_approve_with_rationale_wrong_state(self) -> None:
        service = ReviewService()
        record = service.create(task_id="task-6", tenant_id="t1")
        # Still in DRAFT state
        with pytest.raises(ReviewStateError, match="Cannot apply rationale"):
            service.approve_with_rationale(
                record.id,
                approver_id="operator-1",
                decision="approved",
            )

    def test_changes_requested_then_ready_cycle(self) -> None:
        """Verify the full cycle: APPROVED -> CHANGES_REQUESTED -> READY."""
        service = ReviewService()
        record = service.create(task_id="task-7", tenant_id="t1")
        _advance_to_approved(service, record.id)

        service.approve_with_rationale(
            record.id,
            approver_id="op-1",
            decision="changes_requested",
            rationale="Needs fix.",
        )
        assert service.get(record.id).state == SignoffState.CHANGES_REQUESTED

        # Author addresses changes and moves back to READY
        service._transition(service.get(record.id), SignoffState.READY)
        assert service.get(record.id).state == SignoffState.READY

    def test_deferred_then_ready_cycle(self) -> None:
        """Verify the full cycle: APPROVED -> DEFERRED -> READY."""
        service = ReviewService()
        record = service.create(task_id="task-8", tenant_id="t1")
        _advance_to_approved(service, record.id)

        service.approve_with_rationale(
            record.id,
            approver_id="op-1",
            decision="deferred",
            rationale="Later.",
        )
        assert service.get(record.id).state == SignoffState.DEFERRED

        service._transition(service.get(record.id), SignoffState.READY)
        assert service.get(record.id).state == SignoffState.READY


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


class TestApproveWithRationaleAPI:
    def _create_and_advance_review(self, client: TestClient) -> str:
        """Create a review and advance it to APPROVED via API."""
        headers = _auth_headers()

        resp = client.post(
            "/v1/reviews/",
            json={"task_id": "api-task-1", "branch": "main"},
            headers=headers,
        )
        assert resp.status_code == 201
        review_id = resp.json()["id"]

        # Assess risk
        client.post(
            f"/v1/reviews/{review_id}/assess",
            json={"triggers": ["code-isolated"]},
            headers=headers,
        )
        # Mark ready
        client.post(f"/v1/reviews/{review_id}/ready", headers=headers)
        # Assign L1
        client.post(f"/v1/reviews/{review_id}/assign-l1", headers=headers)
        # Submit L1 approved
        client.post(
            f"/v1/reviews/{review_id}/l1",
            json={
                "decision": "approved",
                "checklist": {
                    "code_quality": "pass",
                    "correctness": "pass",
                    "testing": "pass",
                    "scope": "pass",
                },
                "issues": [],
                "comments": "LGTM",
            },
            headers=headers,
        )

        # Verify the review is in APPROVED state
        get_resp = client.get(f"/v1/reviews/{review_id}", headers=headers)
        assert get_resp.json()["state"] == "approved"

        return review_id

    def test_approve_with_rationale_endpoint(self) -> None:
        client = TestClient(app)
        review_id = self._create_and_advance_review(client)

        resp = client.post(
            f"/v1/reviews/{review_id}/approve-with-rationale",
            json={
                "decision": "approved",
                "rationale": "Ship it.",
                "conditions": ["Run smoke tests"],
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "approved"
        assert body["decision"] == "approved"
        assert body["approved_by"] == "test-user"
        assert body["rationale"] == "Ship it."

    def test_changes_requested_via_api(self) -> None:
        client = TestClient(app)
        review_id = self._create_and_advance_review(client)

        resp = client.post(
            f"/v1/reviews/{review_id}/approve-with-rationale",
            json={
                "decision": "changes_requested",
                "rationale": "Missing tests.",
                "modification_summary": "Add coverage for edge cases.",
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "changes-requested"
        assert resp.json()["decision"] == "changes_requested"

    def test_deferred_via_api(self) -> None:
        client = TestClient(app)
        review_id = self._create_and_advance_review(client)

        resp = client.post(
            f"/v1/reviews/{review_id}/approve-with-rationale",
            json={
                "decision": "deferred",
                "rationale": "Waiting on external dependency.",
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "deferred"

    def test_invalid_decision_rejected(self) -> None:
        client = TestClient(app)
        review_id = self._create_and_advance_review(client)

        resp = client.post(
            f"/v1/reviews/{review_id}/approve-with-rationale",
            json={
                "decision": "yolo",
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 422

    def test_wrong_state_returns_409(self) -> None:
        client = TestClient(app)
        headers = _auth_headers()
        resp = client.post(
            "/v1/reviews/",
            json={"task_id": "wrong-state-task", "branch": "main"},
            headers=headers,
        )
        review_id = resp.json()["id"]

        resp = client.post(
            f"/v1/reviews/{review_id}/approve-with-rationale",
            json={"decision": "approved"},
            headers=headers,
        )
        assert resp.status_code == 409

    def test_not_found_returns_404(self) -> None:
        client = TestClient(app)
        resp = client.post(
            "/v1/reviews/nonexistent-id/approve-with-rationale",
            json={"decision": "approved"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 404

    def test_auth_required(self) -> None:
        client = TestClient(app)
        resp = client.post(
            "/v1/reviews/some-id/approve-with-rationale",
            json={"decision": "approved"},
        )
        assert resp.status_code == 401

    def test_request_approver_id_is_ignored(self) -> None:
        client = TestClient(app)
        review_id = self._create_and_advance_review(client)

        resp = client.post(
            f"/v1/reviews/{review_id}/approve-with-rationale",
            json={
                "approver_id": "impersonated-user",
                "decision": "approved",
                "rationale": "Ship it.",
            },
            headers=_auth_headers(subject="actual-user"),
        )

        assert resp.status_code == 200
        assert resp.json()["approved_by"] == "actual-user"

    def test_cross_tenant_review_access_returns_404(self) -> None:
        client = TestClient(app)
        review_id = self._create_and_advance_review(client)

        get_resp = client.get(
            f"/v1/reviews/{review_id}",
            headers=_auth_headers(subject="other-user", tenant_id="t2"),
        )
        assert get_resp.status_code == 404

        approve_resp = client.post(
            f"/v1/reviews/{review_id}/approve-with-rationale",
            json={"decision": "approved", "rationale": "Ship it."},
            headers=_auth_headers(subject="other-user", tenant_id="t2"),
        )
        assert approve_resp.status_code == 404

    def test_admin_with_tenant_creates_tenant_scoped_review(self) -> None:
        client = TestClient(app)

        create_resp = client.post(
            "/v1/reviews/",
            json={"task_id": "tenant-admin-task", "branch": "main"},
            headers=_auth_headers(subject="tenant-admin", tenant_id="t1", scopes=["admin"]),
        )
        assert create_resp.status_code == 201
        review_id = create_resp.json()["id"]

        get_resp = client.get(
            f"/v1/reviews/{review_id}",
            headers=_auth_headers(subject="tenant-user", tenant_id="t1"),
        )
        assert get_resp.status_code == 200
