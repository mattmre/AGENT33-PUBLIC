"""Shared test fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from agent33.api.route_approvals import APPROVAL_TOKEN_HEADER
from agent33.api.routes.tool_approvals import (
    _reset_tool_approval_service,
    _resolve_approval_token_manager,
    get_tool_approval_service,
    set_approval_token_manager,
)
from agent33.main import app
from agent33.security.auth import create_access_token, verify_token
from agent33.tools.approvals import ApprovalReason, ApprovalRiskTier

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    """Disable rate limiting for every test.

    The RateLimiter is a module-level singleton whose token-bucket counters
    persist across the entire pytest process.  Without this reset, tests that
    make many requests (e.g. seed helpers that POST 15+ signals) exhaust the
    burst allowance and subsequent requests receive 429s.

    Setting the default tier to UNLIMITED ensures the middleware never rejects
    a request.  The dedicated ``test_rate_limiter.py`` tests create their own
    RateLimiter instances and are unaffected.
    """
    from agent33.security.rate_limiter import RateLimitTier

    rate_limiter = getattr(app.state, "rate_limiter", None)
    if rate_limiter is not None:
        rate_limiter.reset_all()
        rate_limiter.default_tier = RateLimitTier.UNLIMITED


@pytest.fixture(autouse=True)
def _reset_route_approval_state() -> None:
    """Isolate approval-request and token state between tests."""
    _reset_tool_approval_service()
    set_approval_token_manager(None)
    app.state.approval_token_manager = None
    yield
    _reset_tool_approval_service()
    set_approval_token_manager(None)
    app.state.approval_token_manager = None


@pytest.fixture
def auth_token() -> str:
    return create_access_token("test-user", scopes=["admin"])


@pytest.fixture
def client(auth_token: str) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {auth_token}"})


@pytest.fixture
def sample_agent_def() -> dict[str, Any]:
    return {
        "name": "test-agent",
        "version": "1.0.0",
        "role": "worker",
        "description": "Agent for test registration flows",
        "inputs": {"prompt": {"type": "string", "description": "User prompt"}},
        "outputs": {"result": {"type": "string", "description": "Agent output"}},
        "constraints": {
            "max_tokens": 256,
            "timeout_seconds": 10,
            "max_retries": 0,
        },
    }


def _normalize_route_arguments(route_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if route_name == "workflows.create":
        from agent33.api.routes.workflows import WorkflowCreateRequest

        return WorkflowCreateRequest.model_validate(arguments).model_dump(mode="json")
    if route_name == "agents.create":
        from agent33.agents.definition import AgentDefinition

        return AgentDefinition.model_validate(arguments).model_dump(mode="json")
    if route_name == "agents.update":
        from agent33.agents.definition import AgentDefinition

        normalized = dict(arguments)
        normalized["definition"] = AgentDefinition.model_validate(
            arguments.get("definition", {}),
        ).model_dump(mode="json")
        return normalized
    return dict(arguments)


@pytest.fixture
def route_approval_headers() -> Callable[..., dict[str, str]]:
    """Issue a valid approval token bound to an exact route mutation payload."""

    def _issue(
        client: TestClient,
        *,
        route_name: str,
        operation: str,
        arguments: dict[str, Any],
        details: str = "",
        risk_tier: ApprovalRiskTier = ApprovalRiskTier.MEDIUM,
        one_time: bool = True,
        ttl_seconds: int = 300,
        authorization: str | None = None,
    ) -> dict[str, str]:
        auth_header = authorization or str(client.headers.get("Authorization", ""))
        token = auth_header.removeprefix("Bearer").strip()
        payload = verify_token(token)
        requested_by = payload.sub or "test-user"
        normalized_arguments = _normalize_route_arguments(route_name, arguments)
        service = get_tool_approval_service()
        approval = service.request(
            reason=ApprovalReason.ROUTE_MUTATION,
            tool_name=f"route:{route_name}",
            operation=operation,
            command=f"{operation} {route_name}",
            requested_by=requested_by,
            tenant_id=payload.tenant_id or "",
            details=details,
            arguments=normalized_arguments,
            risk_tier=risk_tier,
        )
        approved = service.decide(
            approval.approval_id,
            approved=True,
            reviewed_by=requested_by,
            review_note="pytest auto-approval",
        )
        assert approved is not None
        token_manager = _resolve_approval_token_manager()
        assert token_manager is not None
        headers = dict(getattr(client, "headers", {}))
        if auth_header:
            headers["Authorization"] = auth_header
        headers[APPROVAL_TOKEN_HEADER] = token_manager.issue(
            approved,
            arguments=normalized_arguments,
            one_time=one_time,
            ttl_seconds=ttl_seconds,
        )
        return headers

    return _issue
