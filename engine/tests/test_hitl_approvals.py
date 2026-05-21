"""HITL approval lifecycle tests for governed tool execution."""

from __future__ import annotations

import pytest

from agent33.agents.definition import AutonomyLevel
from agent33.security.approval_tokens import ApprovalTokenManager
from agent33.tools.approvals import ApprovalReason, ApprovalStatus, ToolApprovalService
from agent33.tools.base import ToolContext
from agent33.tools.governance import ToolGovernance


def test_tool_policy_ask_creates_pending_approval() -> None:
    approvals = ToolApprovalService()
    governance = ToolGovernance(approval_service=approvals)
    context = ToolContext(
        user_scopes=["tools:execute"],
        tool_policies={"file_ops": "ask"},
        requested_by="requester-1",
        tenant_id="tenant-a",
    )

    allowed = governance.pre_execute_check(
        "file_ops",
        {"operation": "write", "path": "src/file.py"},
        context,
    )

    assert allowed is False
    requests = approvals.list_requests()
    assert len(requests) == 1
    request = requests[0]
    assert request.reason == ApprovalReason.TOOL_POLICY_ASK
    assert request.status == ApprovalStatus.PENDING
    assert request.requested_by == "requester-1"


def test_supervised_destructive_flow_consumes_approved_token() -> None:
    approvals = ToolApprovalService()
    governance = ToolGovernance(approval_service=approvals)
    context = ToolContext(user_scopes=["tools:execute"], requested_by="requester-2")

    allowed = governance.pre_execute_check(
        "file_ops",
        {"operation": "write", "path": "src/file.py"},
        context,
        autonomy_level=AutonomyLevel.SUPERVISED,
    )
    assert allowed is False

    request = approvals.list_requests()[0]
    approvals.decide(
        request.approval_id,
        approved=True,
        reviewed_by="operator",
        review_note="approved for one execution",
    )

    second_allowed = governance.pre_execute_check(
        "file_ops",
        {
            "operation": "write",
            "path": "src/file.py",
            "__approval_id": request.approval_id,
        },
        context,
        autonomy_level=AutonomyLevel.SUPERVISED,
    )
    assert second_allowed is True
    assert approvals.get_request(request.approval_id).status == ApprovalStatus.CONSUMED


def test_approved_request_still_respects_command_allowlist() -> None:
    approvals = ToolApprovalService()
    governance = ToolGovernance(approval_service=approvals)
    context = ToolContext(
        user_scopes=["tools:execute"],
        tool_policies={"shell": "ask"},
        command_allowlist=["python"],
        requested_by="requester-allowlist",
    )

    allowed = governance.pre_execute_check(
        "shell",
        {"command": "git status"},
        context,
    )
    assert allowed is False

    request = approvals.list_requests()[0]
    approvals.decide(
        request.approval_id,
        approved=True,
        reviewed_by="operator",
        review_note="approved pending policy checks",
    )

    second_allowed = governance.pre_execute_check(
        "shell",
        {
            "command": "git status",
            "__approval_id": request.approval_id,
        },
        context,
    )
    assert second_allowed is False
    assert approvals.get_request(request.approval_id).status == ApprovalStatus.APPROVED


def test_apply_patch_requires_supervised_approval() -> None:
    approvals = ToolApprovalService()
    governance = ToolGovernance(approval_service=approvals)
    context = ToolContext(user_scopes=["tools:execute"], requested_by="requester-3")

    allowed = governance.pre_execute_check(
        "apply_patch",
        {"patch": "*** Begin Patch\n*** Add File: note.txt\n+hi\n*** End Patch"},
        context,
        autonomy_level=AutonomyLevel.SUPERVISED,
    )
    assert allowed is False

    request = approvals.list_requests()[0]
    approvals.decide(
        request.approval_id,
        approved=True,
        reviewed_by="operator",
        review_note="approved for patch apply",
    )

    second_allowed = governance.pre_execute_check(
        "apply_patch",
        {
            "patch": "*** Begin Patch\n*** Add File: note.txt\n+hi\n*** End Patch",
            "__approval_id": request.approval_id,
        },
        context,
        autonomy_level=AutonomyLevel.SUPERVISED,
    )
    assert second_allowed is True
    assert approvals.get_request(request.approval_id).status == ApprovalStatus.CONSUMED


def test_supervised_destructive_flow_consumes_approval_token() -> None:
    approvals = ToolApprovalService()
    token_manager = ApprovalTokenManager(secret="test-secret")
    governance = ToolGovernance(
        approval_service=approvals,
        approval_token_manager=token_manager,
    )
    context = ToolContext(
        user_scopes=["tools:execute"],
        requested_by="requester-2",
        tenant_id="tenant-a",
    )

    allowed = governance.pre_execute_check(
        "file_ops",
        {"operation": "write", "path": "src/file.py"},
        context,
        autonomy_level=AutonomyLevel.SUPERVISED,
    )
    assert allowed is False

    request = approvals.list_requests()[0]
    approved = approvals.decide(
        request.approval_id,
        approved=True,
        reviewed_by="operator",
        review_note="approved for one execution",
    )
    assert approved is not None

    token = token_manager.issue(
        approved,
        arguments={"operation": "write", "path": "src/file.py"},
    )
    second_allowed = governance.pre_execute_check(
        "file_ops",
        {
            "operation": "write",
            "path": "src/file.py",
            "__approval_token": token,
        },
        context,
        autonomy_level=AutonomyLevel.SUPERVISED,
    )
    assert second_allowed is True
    assert approvals.get_request(request.approval_id).status == ApprovalStatus.CONSUMED


@pytest.fixture(autouse=True)
def reset_tool_approval_route_singleton() -> None:
    from agent33.api.routes.tool_approvals import _reset_tool_approval_service

    _reset_tool_approval_service()
    yield
    _reset_tool_approval_service()


def test_tool_approval_api_list_and_decide(client) -> None:
    from agent33.api.routes.tool_approvals import get_tool_approval_service

    service = get_tool_approval_service()
    request = service.request(
        reason=ApprovalReason.TOOL_POLICY_ASK,
        tool_name="file_ops",
        operation="write",
        requested_by="api-user",
    )

    list_response = client.get("/v1/approvals/tools")
    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed
    assert listed[0]["approval_id"] == request.approval_id

    decision_response = client.post(
        f"/v1/approvals/tools/{request.approval_id}/decision",
        json={"decision": "approve"},
    )
    assert decision_response.status_code == 200
    result = decision_response.json()
    assert result["status"] == "approved"
    assert result["reviewed_by"] == "test-user"


def test_tool_approval_api_invalid_status_filter_returns_400(client) -> None:
    response = client.get("/v1/approvals/tools", params={"status": "invalid"})
    assert response.status_code == 400


def test_tool_approval_api_tenant_isolation() -> None:
    """Requests created for one tenant are invisible to another tenant's list."""
    from agent33.api.routes.tool_approvals import get_tool_approval_service

    service = get_tool_approval_service()
    service.request(
        reason=ApprovalReason.TOOL_POLICY_ASK,
        tool_name="file_ops",
        requested_by="user-a",
        tenant_id="tenant-a",
    )
    service.request(
        reason=ApprovalReason.TOOL_POLICY_ASK,
        tool_name="file_ops",
        requested_by="user-b",
        tenant_id="tenant-b",
    )

    tenant_a_items = service.list_requests(tenant_id="tenant-a")
    assert len(tenant_a_items) == 1
    assert tenant_a_items[0].tenant_id == "tenant-a"

    tenant_b_items = service.list_requests(tenant_id="tenant-b")
    assert len(tenant_b_items) == 1
    assert tenant_b_items[0].tenant_id == "tenant-b"


def test_consume_if_approved_validates_tenant() -> None:
    """Cross-tenant consumption must be blocked."""
    service = ToolApprovalService()
    req = service.request(
        reason=ApprovalReason.TOOL_POLICY_ASK,
        tool_name="file_ops",
        operation="write",
        tenant_id="tenant-a",
    )
    service.decide(req.approval_id, approved=True, reviewed_by="op")

    # Wrong tenant cannot consume
    assert (
        service.consume_if_approved(
            req.approval_id, tool_name="file_ops", operation="write", tenant_id="tenant-b"
        )
        is False
    )
    assert service.get_request(req.approval_id).status == ApprovalStatus.APPROVED

    # Correct tenant can consume
    assert (
        service.consume_if_approved(
            req.approval_id, tool_name="file_ops", operation="write", tenant_id="tenant-a"
        )
        is True
    )
    assert service.get_request(req.approval_id).status == ApprovalStatus.CONSUMED


def test_review_note_concatenation() -> None:
    """Consuming a request with an existing review_note appends correctly."""
    service = ToolApprovalService()
    req = service.request(
        reason=ApprovalReason.TOOL_POLICY_ASK,
        tool_name="shell",
    )
    service.decide(req.approval_id, approved=True, reviewed_by="op", review_note="LGTM")
    service.consume_if_approved(req.approval_id, tool_name="shell")
    expected = "LGTM Consumed by governed execution."
    assert service.get_request(req.approval_id).review_note == expected
