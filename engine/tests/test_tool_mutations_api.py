"""Tests for the mutation audit API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.tools.mutation_audit import MutationAuditRecord


def _headers(*, tenant_id: str = "") -> dict[str, str]:
    token = create_access_token("mutation-user", scopes=["workflows:read"], tenant_id=tenant_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def reset_mutation_audit_store() -> None:
    from agent33.api.routes.tool_mutations import _reset_mutation_audit_store

    _reset_mutation_audit_store()
    yield
    _reset_mutation_audit_store()


def test_mutation_audit_api_lists_records(client: TestClient) -> None:
    from agent33.api.routes.tool_mutations import get_mutation_audit_store

    store = get_mutation_audit_store()
    store.record(
        MutationAuditRecord(
            requested_by="tester",
            tenant_id="tenant-a",
            status="applied",
            summary="Applied patch.",
        )
    )

    response = client.get("/v1/tools/mutations")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["summary"] == "Applied patch."


def test_mutation_audit_api_enforces_tenant_isolation() -> None:
    tenant_client = TestClient(app, headers=_headers(tenant_id="tenant-a"))
    try:
        from agent33.api.routes.tool_mutations import (
            _reset_mutation_audit_store,
            get_mutation_audit_store,
        )

        # Lifespan re-inits the store from the persisted file; reset to a fresh in-memory
        # store so this test is isolated from data accumulated across prior runs.
        _reset_mutation_audit_store()
        store = get_mutation_audit_store()
        tenant_a_record = store.record(
            MutationAuditRecord(
                requested_by="tenant-a-user",
                tenant_id="tenant-a",
                status="applied",
                summary="Tenant A patch.",
            )
        )
        tenant_b_record = store.record(
            MutationAuditRecord(
                requested_by="tenant-b-user",
                tenant_id="tenant-b",
                status="applied",
                summary="Tenant B patch.",
            )
        )

        list_response = tenant_client.get("/v1/tools/mutations")
        assert list_response.status_code == 200
        payload = list_response.json()
        assert len(payload) == 1
        assert payload[0]["summary"] == "Tenant A patch."

        get_response = tenant_client.get(f"/v1/tools/mutations/{tenant_a_record.mutation_id}")
        assert get_response.status_code == 200

        hidden_response = tenant_client.get(f"/v1/tools/mutations/{tenant_b_record.mutation_id}")
        assert hidden_response.status_code == 404
    finally:
        tenant_client.close()
