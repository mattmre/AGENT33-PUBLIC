from __future__ import annotations

import pytest

from agent33.review.models import (
    L1ChecklistResults,
    ReviewArtifactLink,
    ReviewDecision,
    RiskTrigger,
    SignoffState,
)
from agent33.review.service import ReviewNotFoundError, ReviewService
from agent33.services.orchestration_state import OrchestrationStateStore


def _service_for(path) -> ReviewService:
    return ReviewService(state_store=OrchestrationStateStore(str(path)))


def test_review_records_survive_service_restart(tmp_path) -> None:
    state_path = tmp_path / "orchestration_state.json"
    service = _service_for(state_path)

    record = service.create(
        task_id="T-RESTART-001",
        branch="feature/restart-safe-reviews",
        tenant_id="tenant-a",
        artifacts=[
            ReviewArtifactLink(
                kind="explanation",
                artifact_id="artifact-1",
                label="operator plan",
                mode="plan_review",
            )
        ],
    )
    service.assess_risk(record.id, [RiskTrigger.CODE_ISOLATED])
    service.mark_ready(record.id)
    service.assign_l1(record.id)
    service.submit_l1(
        record.id,
        decision=ReviewDecision.APPROVED,
        checklist=L1ChecklistResults(),
        comments="safe isolated change",
    )
    service.approve(record.id, approver_id="operator-1", conditions=["tests pass"])

    restarted = _service_for(state_path)
    restored = restarted.get(record.id)

    assert restored.task_id == "T-RESTART-001"
    assert restored.branch == "feature/restart-safe-reviews"
    assert restored.tenant_id == "tenant-a"
    assert restored.state == SignoffState.APPROVED
    assert restored.artifacts[0].artifact_id == "artifact-1"
    assert restored.final_signoff.approved_by == "operator-1"
    assert restored.final_signoff.conditions == ["tests pass"]


def test_review_delete_persists_across_restart(tmp_path) -> None:
    state_path = tmp_path / "orchestration_state.json"
    service = _service_for(state_path)
    record = service.create(task_id="T-DELETE-001")

    service.delete(record.id)
    restarted = _service_for(state_path)

    with pytest.raises(ReviewNotFoundError):
        restarted.get(record.id)


def test_review_tenant_filter_survives_restart(tmp_path) -> None:
    state_path = tmp_path / "orchestration_state.json"
    service = _service_for(state_path)
    service.create(task_id="T-TENANT-A", tenant_id="tenant-a")
    service.create(task_id="T-TENANT-B", tenant_id="tenant-b")

    restarted = _service_for(state_path)

    tenant_a_reviews = restarted.list_all(tenant_id="tenant-a")
    assert [review.task_id for review in tenant_a_reviews] == ["T-TENANT-A"]
