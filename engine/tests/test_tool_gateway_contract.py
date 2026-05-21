from __future__ import annotations

from fastapi.testclient import TestClient

from agent33.api.routes.tool_gateway import router
from agent33.api.routes.tool_mutations import _reset_mutation_audit_store, get_mutation_audit_store
from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.tools.gateway_contract import (
    ToolRequest,
    ToolRiskClass,
    integrate_tool_request,
    permission_scope_for,
    preview_tool_request,
    request_hash,
)
from agent33.tools.mutation_audit import MutationAuditStore


def test_tool_request_hash_is_stable_and_excludes_idempotency_key() -> None:
    request = ToolRequest(
        tool_name="apply_patch",
        action="preview",
        params={"path": "README.md"},
        idempotency_key="operator-key",
        risk_class=ToolRiskClass.MUTATION,
    )
    same_request = request.model_copy(update={"idempotency_key": "another-key"})

    assert request_hash(request) == request_hash(same_request)


def test_gateway_preview_classifies_mutations() -> None:
    result = preview_tool_request(
        ToolRequest(
            tool_name="apply_patch",
            action="apply",
            dry_run=False,
            risk_class=ToolRiskClass.MUTATION,
        )
    )

    assert result.mutation_expected is True
    assert result.accepted is False
    assert result.permission_scope == "tools:execute"


def test_read_request_uses_read_scope() -> None:
    request = ToolRequest(tool_name="catalog", action="list", risk_class=ToolRiskClass.READ)

    assert permission_scope_for(request) == "workflows:read"
    assert preview_tool_request(request).accepted is True


def test_tool_gateway_preview_route_registered() -> None:
    paths = {route.path for route in router.routes}

    assert "/v1/tools/gateway/requests/preview" in paths or "/requests/preview" in paths
    assert "/v1/tools/gateway/requests/integrate" in paths or "/requests/integrate" in paths


def test_gateway_integration_records_mutation_preview() -> None:
    store = MutationAuditStore()

    result = integrate_tool_request(
        ToolRequest(
            tool_name="apply_patch",
            action="preview",
            tenant_id="tenant-a",
            risk_class=ToolRiskClass.MUTATION,
        ),
        audit_store=store,
    )

    assert result.receipt is not None
    assert result.receipt.mutation_id
    records = store.list_records(tenant_id="tenant-a")
    assert len(records) == 1
    assert records[0].status == "preview"
    assert records[0].summary == "Gateway preview for apply_patch:preview"


def test_tool_gateway_preview_endpoint() -> None:
    token = create_access_token("tool-user", scopes=["tools:execute"], tenant_id="tenant-a")
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

    response = client.post(
        "/v1/tools/gateway/requests/preview",
        json={
            "tool_name": "apply_patch",
            "action": "preview",
            "params": {"path": "README.md"},
            "risk_class": "mutation",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mutation_expected"] is True
    assert body["accepted"] is True
    assert body["idempotency_key"]


def test_tool_gateway_integrate_endpoint_records_audit() -> None:
    _reset_mutation_audit_store()
    token = create_access_token("tool-user", scopes=["tools:execute"], tenant_id="tenant-a")
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

    response = client.post(
        "/v1/tools/gateway/requests/integrate",
        json={
            "tool_name": "apply_patch",
            "action": "preview",
            "tenant_id": "tenant-a",
            "params": {"path": "README.md"},
            "risk_class": "mutation",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["receipt"]["mutation_id"]
    assert body["receipt"]["evidence_uri"].startswith("tool-gateway:")
    assert get_mutation_audit_store().get_record(
        body["receipt"]["mutation_id"],
        tenant_id="tenant-a",
    )
