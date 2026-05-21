"""Deterministic tool gateway request contract."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agent33.tools.mutation_audit import MutationAuditRecord, MutationAuditStore


class ToolRiskClass(StrEnum):
    READ = "read"
    MUTATION = "mutation"
    EXTERNAL_WRITE = "external_write"
    SHELL = "shell"


class ToolRequest(BaseModel):
    tool_name: str
    action: str
    tenant_id: str = ""
    run_id: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = True
    idempotency_key: str = ""
    risk_class: ToolRiskClass = ToolRiskClass.READ


class ToolExecutionReceipt(BaseModel):
    request_hash: str
    tool_name: str
    run_id: str = ""
    mutation_id: str = ""
    evidence_uri: str = ""
    success: bool = False


class ToolGatewayResult(BaseModel):
    request_hash: str
    idempotency_key: str
    risk_class: ToolRiskClass
    dry_run: bool
    mutation_expected: bool
    permission_scope: str
    accepted: bool
    reason: str
    receipt: ToolExecutionReceipt | None = None


def request_hash(request: ToolRequest) -> str:
    payload = request.model_dump(mode="json", exclude={"idempotency_key"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def permission_scope_for(request: ToolRequest) -> str:
    if request.risk_class == ToolRiskClass.READ:
        return "workflows:read"
    return "tools:execute"


def preview_tool_request(request: ToolRequest) -> ToolGatewayResult:
    digest = request_hash(request)
    idempotency_key = request.idempotency_key or digest[:16]
    mutation_expected = request.risk_class != ToolRiskClass.READ
    accepted = request.dry_run or not mutation_expected
    reason = (
        "Dry run accepted for gateway preview."
        if request.dry_run
        else "Mutating requests require approval and execution integration."
        if mutation_expected
        else "Read-only request accepted."
    )
    return ToolGatewayResult(
        request_hash=digest,
        idempotency_key=idempotency_key,
        risk_class=request.risk_class,
        dry_run=request.dry_run,
        mutation_expected=mutation_expected,
        permission_scope=permission_scope_for(request),
        accepted=accepted,
        reason=reason,
    )


def integrate_tool_request(
    request: ToolRequest,
    *,
    audit_store: MutationAuditStore | None = None,
) -> ToolGatewayResult:
    """Preview a request and attach proof from the gateway integration layer."""
    result = preview_tool_request(request)
    receipt = ToolExecutionReceipt(
        request_hash=result.request_hash,
        tool_name=request.tool_name,
        run_id=request.run_id,
        evidence_uri=f"tool-gateway:{result.request_hash}",
        success=result.accepted,
    )

    if result.mutation_expected and audit_store is not None:
        record = audit_store.record(
            MutationAuditRecord(
                tool_name=request.tool_name,
                tenant_id=request.tenant_id,
                dry_run=request.dry_run,
                status="preview" if request.dry_run else "blocked",
                success=result.accepted,
                summary=f"Gateway preview for {request.tool_name}:{request.action}",
            )
        )
        receipt.mutation_id = record.mutation_id

    return result.model_copy(update={"receipt": receipt})
