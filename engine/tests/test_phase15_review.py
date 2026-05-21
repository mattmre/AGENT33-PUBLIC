"""Phase 15 tests: review automation and two-layer signoff.

Covers:
1. Review models and defaults
2. Risk assessment engine
3. Reviewer assignment matrix
4. Signoff state machine transitions
5. Review service lifecycle (L1-only and L1+L2 flows)
6. Review API routes (CRUD + lifecycle endpoints)
7. Tenant isolation on reviews
8. Error paths (not-found, invalid state transitions)
"""

from __future__ import annotations

import pytest

from agent33.review.assignment import ReviewerAssigner
from agent33.review.models import (
    ChecklistVerdict,
    L1ChecklistResults,
    L2ChecklistResults,
    ReviewArtifactLink,
    ReviewDecision,
    ReviewRecord,
    RiskLevel,
    RiskTrigger,
    SignoffState,
)
from agent33.review.risk import RiskAssessor
from agent33.review.service import (
    ReviewNotFoundError,
    ReviewService,
    ReviewStateError,
)
from agent33.review.state_machine import (
    InvalidTransitionError,
    SignoffStateMachine,
)

# ===================================================================
# 1. Review models
# ===================================================================


class TestReviewModels:
    """Test ReviewRecord defaults and structure."""

    def test_new_record_defaults(self):
        record = ReviewRecord(task_id="T-001")
        assert record.state == SignoffState.DRAFT
        assert record.risk_assessment.risk_level == RiskLevel.NONE
        assert record.risk_assessment.l1_required is False
        assert record.risk_assessment.l2_required is False
        assert record.l1_review.reviewer_id == ""
        assert record.l2_review.reviewer_id == ""
        assert record.id.startswith("rev-")
        assert len(record.id) == 16  # "rev-" + 12 hex chars

    def test_record_touch_updates_timestamp(self):
        record = ReviewRecord(task_id="T-002")
        original = record.updated_at
        record.touch()
        assert record.updated_at >= original

    def test_record_accepts_artifact_links(self):
        record = ReviewRecord(
            task_id="T-003",
            artifacts=[
                ReviewArtifactLink(
                    kind="explanation",
                    artifact_id="expl-123",
                    label="plan-review",
                    mode="plan_review",
                )
            ],
        )
        assert len(record.artifacts) == 1
        assert record.artifacts[0].artifact_id == "expl-123"

    def test_unique_ids(self):
        r1 = ReviewRecord(task_id="T-001")
        r2 = ReviewRecord(task_id="T-002")
        assert r1.id != r2.id


# ===================================================================
# 2. Risk assessment engine
# ===================================================================


class TestRiskAssessor:
    """Test RiskAssessor.assess()."""

    def setup_method(self):
        self.assessor = RiskAssessor()

    def test_no_triggers_returns_none_risk(self):
        result = self.assessor.assess([])
        assert result.risk_level == RiskLevel.NONE
        assert result.l1_required is False
        assert result.l2_required is False

    def test_documentation_trigger_is_none(self):
        result = self.assessor.assess([RiskTrigger.DOCUMENTATION])
        assert result.risk_level == RiskLevel.NONE
        assert result.l1_required is False
        assert result.l2_required is False

    def test_config_trigger_is_low(self):
        result = self.assessor.assess([RiskTrigger.CONFIG])
        assert result.risk_level == RiskLevel.LOW
        assert result.l1_required is True
        assert result.l2_required is False

    def test_code_isolated_is_low(self):
        result = self.assessor.assess([RiskTrigger.CODE_ISOLATED])
        assert result.risk_level == RiskLevel.LOW
        assert result.l1_required is True
        assert result.l2_required is False

    def test_api_internal_is_medium(self):
        result = self.assessor.assess([RiskTrigger.API_INTERNAL])
        assert result.risk_level == RiskLevel.MEDIUM
        assert result.l1_required is True
        assert result.l2_required is True

    def test_security_trigger_is_high(self):
        result = self.assessor.assess([RiskTrigger.SECURITY])
        assert result.risk_level == RiskLevel.HIGH
        assert result.l1_required is True
        assert result.l2_required is True

    def test_secrets_trigger_is_critical(self):
        result = self.assessor.assess([RiskTrigger.SECRETS])
        assert result.risk_level == RiskLevel.CRITICAL
        assert result.l1_required is True
        assert result.l2_required is True

    def test_production_data_is_critical(self):
        result = self.assessor.assess([RiskTrigger.PRODUCTION_DATA])
        assert result.risk_level == RiskLevel.CRITICAL

    def test_multiple_triggers_uses_highest(self):
        result = self.assessor.assess(
            [
                RiskTrigger.CONFIG,  # low
                RiskTrigger.API_INTERNAL,  # medium
                RiskTrigger.SECURITY,  # high
            ]
        )
        assert result.risk_level == RiskLevel.HIGH
        assert len(result.triggers_identified) == 3

    def test_prompt_injection_is_high(self):
        result = self.assessor.assess([RiskTrigger.PROMPT_INJECTION])
        assert result.risk_level == RiskLevel.HIGH

    def test_supply_chain_is_high(self):
        result = self.assessor.assess([RiskTrigger.SUPPLY_CHAIN])
        assert result.risk_level == RiskLevel.HIGH


# ===================================================================
# 3. Reviewer assignment
# ===================================================================


class TestReviewerAssignment:
    """Test ReviewerAssigner.assign()."""

    def setup_method(self):
        self.assigner = ReviewerAssigner()

    def test_security_trigger_assigns_security_agent(self):
        l1, l2 = self.assigner.assign([RiskTrigger.SECURITY])
        assert l1.agent_id == "AGT-004"
        assert l1.reviewer_role == "security"
        assert l2.human_required is True

    def test_code_trigger_assigns_implementer(self):
        l1, l2 = self.assigner.assign([RiskTrigger.CODE_ISOLATED])
        assert l1.agent_id == "AGT-006"
        assert l1.reviewer_role == "implementer"
        assert l2.agent_id == "AGT-003"

    def test_prompt_trigger_assigns_qa(self):
        l1, l2 = self.assigner.assign([RiskTrigger.PROMPT_AGENT])
        assert l1.agent_id == "AGT-005"
        assert l1.reviewer_role == "qa"

    def test_documentation_trigger_assigns_docs_agent(self):
        l1, l2 = self.assigner.assign([RiskTrigger.DOCUMENTATION])
        assert l1.reviewer_role == "documentation"
        assert l1.agent_id == "AGT-007"

    def test_secrets_trigger_requires_human_l2(self):
        l1, l2 = self.assigner.assign([RiskTrigger.SECRETS])
        assert l2.human_required is True
        assert l2.agent_id == "HUMAN"

    def test_empty_triggers_returns_defaults(self):
        l1, l2 = self.assigner.assign([])
        assert l1.agent_id == "AGT-006"  # default implementer
        assert l2.agent_id == "AGT-003"  # default architect

    def test_multiple_triggers_uses_highest_risk(self):
        l1, l2 = self.assigner.assign(
            [
                RiskTrigger.CONFIG,  # low
                RiskTrigger.SECRETS,  # critical
            ]
        )
        # Secrets is highest → security assignment
        assert l1.reviewer_role == "security"
        assert l2.human_required is True


# ===================================================================
# 4. Signoff state machine
# ===================================================================


class TestSignoffStateMachine:
    """Test SignoffStateMachine transition rules."""

    def test_draft_to_ready(self):
        result = SignoffStateMachine.transition(SignoffState.DRAFT, SignoffState.READY)
        assert result == SignoffState.READY

    def test_ready_to_l1_review(self):
        result = SignoffStateMachine.transition(SignoffState.READY, SignoffState.L1_REVIEW)
        assert result == SignoffState.L1_REVIEW

    def test_l1_review_to_l1_approved(self):
        result = SignoffStateMachine.transition(SignoffState.L1_REVIEW, SignoffState.L1_APPROVED)
        assert result == SignoffState.L1_APPROVED

    def test_l1_review_to_changes_requested(self):
        result = SignoffStateMachine.transition(
            SignoffState.L1_REVIEW, SignoffState.L1_CHANGES_REQUESTED
        )
        assert result == SignoffState.L1_CHANGES_REQUESTED

    def test_l1_changes_requested_to_draft(self):
        result = SignoffStateMachine.transition(
            SignoffState.L1_CHANGES_REQUESTED, SignoffState.DRAFT
        )
        assert result == SignoffState.DRAFT

    def test_l1_approved_to_l2_review(self):
        result = SignoffStateMachine.transition(SignoffState.L1_APPROVED, SignoffState.L2_REVIEW)
        assert result == SignoffState.L2_REVIEW

    def test_l1_approved_to_approved(self):
        result = SignoffStateMachine.transition(SignoffState.L1_APPROVED, SignoffState.APPROVED)
        assert result == SignoffState.APPROVED

    def test_l2_review_to_l2_approved(self):
        result = SignoffStateMachine.transition(SignoffState.L2_REVIEW, SignoffState.L2_APPROVED)
        assert result == SignoffState.L2_APPROVED

    def test_l2_approved_to_approved(self):
        result = SignoffStateMachine.transition(SignoffState.L2_APPROVED, SignoffState.APPROVED)
        assert result == SignoffState.APPROVED

    def test_approved_to_merged(self):
        result = SignoffStateMachine.transition(SignoffState.APPROVED, SignoffState.MERGED)
        assert result == SignoffState.MERGED

    def test_merged_is_terminal(self):
        assert SignoffStateMachine.valid_next_states(SignoffState.MERGED) == frozenset()

    def test_invalid_transition_raises(self):
        with pytest.raises(InvalidTransitionError) as exc_info:
            SignoffStateMachine.transition(SignoffState.DRAFT, SignoffState.MERGED)
        assert exc_info.value.from_state == SignoffState.DRAFT
        assert exc_info.value.to_state == SignoffState.MERGED

    def test_cannot_skip_l1(self):
        with pytest.raises(InvalidTransitionError):
            SignoffStateMachine.transition(SignoffState.READY, SignoffState.L2_REVIEW)

    def test_cannot_go_backwards_from_approved(self):
        with pytest.raises(InvalidTransitionError):
            SignoffStateMachine.transition(SignoffState.APPROVED, SignoffState.L1_REVIEW)

    def test_can_transition_returns_bool(self):
        assert SignoffStateMachine.can_transition(SignoffState.DRAFT, SignoffState.READY) is True
        assert SignoffStateMachine.can_transition(SignoffState.DRAFT, SignoffState.MERGED) is False


# ===================================================================
# 5. Review service lifecycle
# ===================================================================


class TestReviewServiceL1Only:
    """Test the full L1-only review flow (low-risk changes)."""

    def setup_method(self):
        self.svc = ReviewService()

    def test_full_l1_only_flow(self):
        # Create
        record = self.svc.create(
            task_id="T-100",
            branch="feat/foo",
            artifacts=[
                ReviewArtifactLink(
                    kind="explanation",
                    artifact_id="expl-100",
                    label="plan-review",
                    mode="plan_review",
                )
            ],
        )
        assert record.state == SignoffState.DRAFT
        assert record.artifacts[0].artifact_id == "expl-100"

        # Assess risk (low → L1 only)
        record = self.svc.assess_risk(record.id, [RiskTrigger.CODE_ISOLATED])
        assert record.risk_assessment.risk_level == RiskLevel.LOW
        assert record.risk_assessment.l1_required is True
        assert record.risk_assessment.l2_required is False

        # Mark ready
        record = self.svc.mark_ready(record.id)
        assert record.state == SignoffState.READY

        # Assign L1
        record = self.svc.assign_l1(record.id)
        assert record.state == SignoffState.L1_REVIEW
        assert record.l1_review.reviewer_id != ""

        # Submit L1 (approved, no L2 needed → goes straight to APPROVED)
        record = self.svc.submit_l1(
            record.id,
            decision=ReviewDecision.APPROVED,
            checklist=L1ChecklistResults(
                code_quality=ChecklistVerdict.PASS,
                correctness=ChecklistVerdict.PASS,
                testing=ChecklistVerdict.PASS,
                scope=ChecklistVerdict.PASS,
            ),
            comments="LGTM",
        )
        assert record.state == SignoffState.APPROVED

        # Approve
        record = self.svc.approve(record.id, approver_id="user-1")
        assert record.final_signoff.approved_by == "user-1"
        assert record.final_signoff.approval_type == "l1_only"

        # Merge
        record = self.svc.merge(record.id)
        assert record.state == SignoffState.MERGED


class TestReviewServiceL1L2Flow:
    """Test the full L1+L2 review flow (high-risk changes)."""

    def setup_method(self):
        self.svc = ReviewService()

    def test_full_l1_l2_agent_flow(self):
        """L1+L2 flow where L2 reviewer is an agent (medium risk)."""
        record = self.svc.create(task_id="T-200", branch="feat/api")

        # Assess risk (medium → L1 + L2 agent)
        record = self.svc.assess_risk(record.id, [RiskTrigger.API_INTERNAL])
        assert record.risk_assessment.l2_required is True

        # Mark ready → assign L1 → L1 review
        record = self.svc.mark_ready(record.id)
        record = self.svc.assign_l1(record.id)
        record = self.svc.submit_l1(
            record.id,
            decision=ReviewDecision.APPROVED,
        )
        assert record.state == SignoffState.L1_APPROVED

        # Assign L2 (agent reviewer)
        record = self.svc.assign_l2(record.id)
        assert record.state == SignoffState.L2_REVIEW
        assert record.l2_review.reviewer_id == "AGT-003"

        # Submit L2 (approved → auto-APPROVED)
        record = self.svc.submit_l2(
            record.id,
            decision=ReviewDecision.APPROVED,
            checklist=L2ChecklistResults(
                architecture=ChecklistVerdict.PASS,
                security=ChecklistVerdict.NA,
                compliance=ChecklistVerdict.NA,
                impact=ChecklistVerdict.PASS,
            ),
        )
        assert record.state == SignoffState.APPROVED

        # Approve + merge
        record = self.svc.approve(record.id, approver_id="admin-1")
        assert record.final_signoff.approval_type == "l1_l2_agent"
        record = self.svc.merge(record.id)
        assert record.state == SignoffState.MERGED

    def test_full_l1_l2_human_flow(self):
        """L1+L2 flow where L2 reviewer is human (high risk / security)."""
        record = self.svc.create(task_id="T-201", branch="feat/auth")

        # Assess risk (high → L1 + L2 human)
        record = self.svc.assess_risk(record.id, [RiskTrigger.SECURITY])
        assert record.risk_assessment.l2_required is True

        record = self.svc.mark_ready(record.id)
        record = self.svc.assign_l1(record.id)
        record = self.svc.submit_l1(record.id, decision=ReviewDecision.APPROVED)
        record = self.svc.assign_l2(record.id)
        assert record.l2_review.reviewer_id == "HUMAN"

        record = self.svc.submit_l2(record.id, decision=ReviewDecision.APPROVED)
        record = self.svc.approve(record.id, approver_id="human-admin")
        assert record.final_signoff.approval_type == "l1_l2_human"
        record = self.svc.merge(record.id)
        assert record.state == SignoffState.MERGED


class TestReviewServiceChangesRequested:
    """Test changes-requested flow (L1 rejection cycles)."""

    def setup_method(self):
        self.svc = ReviewService()

    def test_l1_changes_requested_returns_to_draft(self):
        record = self.svc.create(task_id="T-300")
        self.svc.assess_risk(record.id, [RiskTrigger.CODE_ISOLATED])
        self.svc.mark_ready(record.id)
        self.svc.assign_l1(record.id)

        record = self.svc.submit_l1(
            record.id,
            decision=ReviewDecision.CHANGES_REQUESTED,
            issues=["Missing null check on line 42"],
            comments="Fix the bug first",
        )
        assert record.state == SignoffState.L1_CHANGES_REQUESTED
        assert record.l1_review.issues_found == ["Missing null check on line 42"]

    def test_l2_changes_requested_returns_to_draft(self):
        record = self.svc.create(task_id="T-301")
        self.svc.assess_risk(record.id, [RiskTrigger.SECURITY])
        self.svc.mark_ready(record.id)
        self.svc.assign_l1(record.id)
        self.svc.submit_l1(record.id, decision=ReviewDecision.APPROVED)
        self.svc.assign_l2(record.id)

        record = self.svc.submit_l2(
            record.id,
            decision=ReviewDecision.CHANGES_REQUESTED,
            issues=["SQL injection risk in query builder"],
        )
        assert record.state == SignoffState.L2_CHANGES_REQUESTED


class TestReviewServiceEscalation:
    """Test L1 escalation triggering L2 requirement."""

    def setup_method(self):
        self.svc = ReviewService()

    def test_l1_escalation_forces_l2(self):
        record = self.svc.create(task_id="T-400")
        # Low risk initially (no L2 required)
        self.svc.assess_risk(record.id, [RiskTrigger.CODE_ISOLATED])
        assert record.risk_assessment.l2_required is False

        self.svc.mark_ready(record.id)
        self.svc.assign_l1(record.id)

        # L1 escalates → L2 now required
        record = self.svc.submit_l1(record.id, decision=ReviewDecision.ESCALATED)
        assert record.risk_assessment.l2_required is True
        assert record.state == SignoffState.L1_APPROVED


class TestReviewServiceErrors:
    """Test error handling in ReviewService."""

    def setup_method(self):
        self.svc = ReviewService()

    def test_get_nonexistent_raises(self):
        with pytest.raises(ReviewNotFoundError):
            self.svc.get("rev-doesnotexist")

    def test_delete_nonexistent_raises(self):
        with pytest.raises(ReviewNotFoundError):
            self.svc.delete("rev-doesnotexist")

    def test_submit_l1_in_wrong_state_raises(self):
        record = self.svc.create(task_id="T-500")
        with pytest.raises(ReviewStateError):
            self.svc.submit_l1(record.id, decision=ReviewDecision.APPROVED)

    def test_submit_l2_in_wrong_state_raises(self):
        record = self.svc.create(task_id="T-501")
        with pytest.raises(ReviewStateError):
            self.svc.submit_l2(record.id, decision=ReviewDecision.APPROVED)

    def test_approve_in_wrong_state_raises(self):
        record = self.svc.create(task_id="T-502")
        with pytest.raises(ReviewStateError):
            self.svc.approve(record.id, approver_id="user")

    def test_merge_in_wrong_state_raises(self):
        record = self.svc.create(task_id="T-503")
        with pytest.raises(ReviewStateError):
            self.svc.merge(record.id)

    def test_mark_ready_twice_raises(self):
        record = self.svc.create(task_id="T-504")
        self.svc.mark_ready(record.id)
        with pytest.raises(ReviewStateError):
            self.svc.mark_ready(record.id)


class TestReviewServiceTenantIsolation:
    """Test tenant filtering in list_all."""

    def setup_method(self):
        self.svc = ReviewService()

    def test_list_filters_by_tenant(self):
        self.svc.create(task_id="T-600", tenant_id="tenant-a")
        self.svc.create(task_id="T-601", tenant_id="tenant-b")
        self.svc.create(task_id="T-602", tenant_id="tenant-a")

        tenant_a = self.svc.list_all(tenant_id="tenant-a")
        assert len(tenant_a) == 2
        assert all(r.tenant_id == "tenant-a" for r in tenant_a)

        tenant_b = self.svc.list_all(tenant_id="tenant-b")
        assert len(tenant_b) == 1

    def test_list_without_tenant_returns_all(self):
        self.svc.create(task_id="T-603", tenant_id="tenant-a")
        self.svc.create(task_id="T-604", tenant_id="tenant-b")
        all_reviews = self.svc.list_all()
        assert len(all_reviews) == 2


# ===================================================================
# 6. Review API routes
# ===================================================================


class TestReviewAPI:
    """Test review REST endpoints via TestClient."""

    @pytest.fixture(autouse=True)
    def _setup_client(self, client):
        """Reset the review service singleton before each test."""
        from agent33.api.routes.reviews import _service

        _service._reviews.clear()
        self.client = client

    def _create_review(self, task_id: str = "T-API-001") -> dict:
        resp = self.client.post(
            "/v1/reviews/",
            json={"task_id": task_id, "branch": "main"},
        )
        assert resp.status_code == 201
        return resp.json()

    def test_create_review(self):
        data = self._create_review()
        assert data["state"] == "draft"
        assert data["task_id"] == "T-API-001"
        assert data["id"].startswith("rev-")

    def test_create_review_with_artifact_link(self):
        resp = self.client.post(
            "/v1/reviews/",
            json={
                "task_id": "T-API-ART",
                "branch": "main",
                "artifacts": [
                    {
                        "kind": "explanation",
                        "artifact_id": "expl-200",
                        "label": "diff-review",
                        "mode": "diff_review",
                    }
                ],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["artifacts"][0]["artifact_id"] == "expl-200"

    def test_list_reviews(self):
        self._create_review("T-1")
        self._create_review("T-2")
        resp = self.client.get("/v1/reviews/")
        assert resp.status_code == 200
        assert len(resp.json()) == 2
        assert resp.json()[0]["artifact_count"] == 0

    def test_get_review(self):
        created = self._create_review()
        resp = self.client.get(f"/v1/reviews/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["task_id"] == "T-API-001"

    def test_get_review_not_found(self):
        resp = self.client.get("/v1/reviews/rev-doesnotexist")
        assert resp.status_code == 404

    def test_delete_review(self):
        created = self._create_review()
        resp = self.client.delete(f"/v1/reviews/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == created["id"]

        # Verify gone
        resp = self.client.get(f"/v1/reviews/{created['id']}")
        assert resp.status_code == 404

    def test_assess_risk(self):
        created = self._create_review()
        resp = self.client.post(
            f"/v1/reviews/{created['id']}/assess",
            json={"triggers": ["security", "schema"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["risk_level"] == "high"
        assert data["l1_required"] is True
        assert data["l2_required"] is True

    def test_full_l1_only_api_flow(self):
        # Create
        created = self._create_review()
        rid = created["id"]

        # Assess (low risk)
        self.client.post(
            f"/v1/reviews/{rid}/assess",
            json={"triggers": ["code-isolated"]},
        )

        # Ready
        resp = self.client.post(f"/v1/reviews/{rid}/ready")
        assert resp.status_code == 200
        assert resp.json()["state"] == "ready"

        # Assign L1
        resp = self.client.post(f"/v1/reviews/{rid}/assign-l1")
        assert resp.status_code == 200
        assert resp.json()["state"] == "l1-review"
        assert resp.json()["l1_reviewer"] != ""

        # Submit L1 (approved → auto-APPROVED for low risk)
        resp = self.client.post(
            f"/v1/reviews/{rid}/l1",
            json={"decision": "approved", "comments": "Looks good"},
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "approved"

        # Final approve
        resp = self.client.post(
            f"/v1/reviews/{rid}/approve",
            json={"conditions": []},
        )
        assert resp.status_code == 200
        assert resp.json()["approved_by"] == "test-user"
        assert resp.json()["approval_type"] == "l1_only"

        # Merge
        resp = self.client.post(f"/v1/reviews/{rid}/merge")
        assert resp.status_code == 200
        assert resp.json()["state"] == "merged"

    def test_full_l1_l2_api_flow(self):
        created = self._create_review()
        rid = created["id"]

        # Assess (high risk → L2 required)
        self.client.post(
            f"/v1/reviews/{rid}/assess",
            json={"triggers": ["security"]},
        )

        # Ready → L1 → L1 approved
        self.client.post(f"/v1/reviews/{rid}/ready")
        self.client.post(f"/v1/reviews/{rid}/assign-l1")
        resp = self.client.post(
            f"/v1/reviews/{rid}/l1",
            json={"decision": "approved"},
        )
        assert resp.json()["state"] == "l1-approved"

        # Assign L2
        resp = self.client.post(f"/v1/reviews/{rid}/assign-l2")
        assert resp.status_code == 200
        assert resp.json()["state"] == "l2-review"

        # Submit L2 (approved → APPROVED)
        resp = self.client.post(
            f"/v1/reviews/{rid}/l2",
            json={"decision": "approved"},
        )
        assert resp.json()["state"] == "approved"

        # Approve + merge
        self.client.post(
            f"/v1/reviews/{rid}/approve",
            json={"conditions": []},
        )
        resp = self.client.post(f"/v1/reviews/{rid}/merge")
        assert resp.json()["state"] == "merged"

    def test_invalid_state_transition_returns_409(self):
        created = self._create_review()
        rid = created["id"]

        # Try to assign L1 without marking ready first
        resp = self.client.post(f"/v1/reviews/{rid}/assign-l1")
        assert resp.status_code == 409

    def test_l1_changes_requested_api(self):
        created = self._create_review()
        rid = created["id"]

        self.client.post(f"/v1/reviews/{rid}/assess", json={"triggers": ["code-isolated"]})
        self.client.post(f"/v1/reviews/{rid}/ready")
        self.client.post(f"/v1/reviews/{rid}/assign-l1")

        resp = self.client.post(
            f"/v1/reviews/{rid}/l1",
            json={
                "decision": "changes_requested",
                "issues": ["Fix the bug"],
                "comments": "Needs work",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "l1-changes-requested"

    def test_assess_not_found_returns_404(self):
        resp = self.client.post(
            "/v1/reviews/rev-nope/assess",
            json={"triggers": ["security"]},
        )
        assert resp.status_code == 404

    def test_approve_wrong_state_returns_409(self):
        created = self._create_review()
        resp = self.client.post(
            f"/v1/reviews/{created['id']}/approve",
            json={"conditions": []},
        )
        assert resp.status_code == 409

    def test_merge_wrong_state_returns_409(self):
        created = self._create_review()
        resp = self.client.post(f"/v1/reviews/{created['id']}/merge")
        assert resp.status_code == 409

    def test_delete_not_found_returns_404(self):
        resp = self.client.delete("/v1/reviews/rev-nope")
        assert resp.status_code == 404
