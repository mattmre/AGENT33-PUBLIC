"""Tool gateway contract preview routes."""

from __future__ import annotations

from fastapi import APIRouter

from agent33.api.routes.tool_mutations import get_mutation_audit_store
from agent33.security.permissions import require_scope
from agent33.tools.gateway_contract import (
    ToolGatewayResult,
    ToolRequest,
    integrate_tool_request,
    preview_tool_request,
)

router = APIRouter(prefix="/v1/tools/gateway", tags=["tool-gateway"])


@router.post("/requests/preview", dependencies=[require_scope("tools:execute")])
async def preview_gateway_request(request: ToolRequest) -> ToolGatewayResult:
    """Validate and hash a ToolRequest before execution integration."""
    return preview_tool_request(request)


@router.post("/requests/integrate", dependencies=[require_scope("tools:execute")])
async def integrate_gateway_request(request: ToolRequest) -> ToolGatewayResult:
    """Preview a ToolRequest and attach gateway proof/audit metadata."""
    return integrate_tool_request(request, audit_store=get_mutation_audit_store())
