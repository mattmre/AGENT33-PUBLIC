"""FastAPI routes for governed mutation audit records."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from agent33.security.permissions import require_scope
from agent33.tools.mutation_audit import MutationAuditStore

router = APIRouter(prefix="/v1/tools/mutations", tags=["tool-mutations"])

_store = MutationAuditStore()


def set_mutation_audit_store(store: MutationAuditStore) -> None:
    """Inject a shared mutation audit store instance."""
    global _store  # noqa: PLW0603
    _store = store


def get_mutation_audit_store() -> MutationAuditStore:
    """Return the shared mutation audit store."""
    return _store


def _reset_mutation_audit_store() -> None:
    """Reset the shared mutation audit store for tests."""
    global _store  # noqa: PLW0603
    _store = MutationAuditStore()


def _get_token_payload(request: Request) -> Any:
    payload = getattr(request.state, "user", None)
    if payload is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return payload


@router.get("", dependencies=[require_scope("workflows:read")])
async def list_mutation_records(
    request: Request,
    limit: int = 100,
) -> list[dict[str, Any]]:
    token_payload = _get_token_payload(request)
    tenant_id = token_payload.tenant_id or ""
    records = _store.list_records(tenant_id=tenant_id, limit=limit)
    return [record.model_dump(mode="json") for record in records]


@router.get("/{mutation_id}", dependencies=[require_scope("workflows:read")])
async def get_mutation_record(request: Request, mutation_id: str) -> dict[str, Any]:
    token_payload = _get_token_payload(request)
    tenant_id = token_payload.tenant_id or ""
    record = _store.get_record(mutation_id, tenant_id=tenant_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Mutation record not found: {mutation_id}")
    return record.model_dump(mode="json")
