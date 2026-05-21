"""Tests for tool catalog API routes: list, detail, schema, categories, providers, search."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes.tool_catalog import set_catalog_service
from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.tools.catalog import (
    CatalogEntry,
    ToolCatalogService,
)
from agent33.tools.registry_entry import ToolRegistryEntry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _client(scopes: list[str], tenant_id: str = "") -> TestClient:
    token = create_access_token("test-user", scopes=scopes, tenant_id=tenant_id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture()
def tools_client() -> TestClient:
    return _client(["tools:execute"], tenant_id="tenant-a")


@pytest.fixture()
def admin_client() -> TestClient:
    return _client(["admin"])


@pytest.fixture()
def no_scope_client() -> TestClient:
    return _client([], tenant_id="tenant-a")


@pytest.fixture()
def anon_client() -> TestClient:
    return TestClient(app)


def _make_tool(name: str, description: str = "A tool") -> Any:
    return SimpleNamespace(name=name, description=description)


def _make_entry(
    name: str,
    version: str = "1.0.0",
    tags: list[str] | None = None,
    parameters_schema: dict[str, Any] | None = None,
) -> ToolRegistryEntry:
    return ToolRegistryEntry(
        tool_id=name,
        name=name,
        version=version,
        tags=tags or [],
        parameters_schema=parameters_schema or {},
    )


def _build_catalog_service() -> ToolCatalogService:
    """Build a catalog service with known test data."""
    tool_reg = MagicMock()
    shell = _make_tool("shell", "Run shell commands")
    web_fetch = _make_tool("web_fetch", "Fetch web URLs")
    tool_reg.list_all.return_value = [shell, web_fetch]

    shell_entry = _make_entry(
        "shell",
        version="2.0.0",
        tags=["system", "cli"],
        parameters_schema={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    )
    web_entry = _make_entry("web_fetch", version="1.0.0", tags=["network"])

    _entries = {"shell": shell_entry, "web_fetch": web_entry}
    _tools = {"shell": shell, "web_fetch": web_fetch}
    tool_reg.get_entry.side_effect = lambda n: _entries.get(n)
    tool_reg.get.side_effect = lambda n: _tools.get(n)
    tool_reg.list_entries.return_value = [shell_entry, web_entry]

    return ToolCatalogService(tool_registry=tool_reg)


@pytest.fixture(autouse=True)
def _setup_catalog() -> Any:
    """Wire up the test catalog service for all tests."""
    svc = _build_catalog_service()
    set_catalog_service(svc)
    yield
    set_catalog_service(None)


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestAuth:
    """Verify auth enforcement on catalog endpoints."""

    def test_anon_gets_401(self, anon_client: TestClient) -> None:
        resp = anon_client.get("/v1/catalog/tools")
        assert resp.status_code == 401

    def test_no_scope_gets_403(self, no_scope_client: TestClient) -> None:
        resp = no_scope_client.get("/v1/catalog/tools")
        assert resp.status_code == 403

    def test_tools_scope_allowed(self, tools_client: TestClient) -> None:
        resp = tools_client.get("/v1/catalog/tools")
        assert resp.status_code == 200

    def test_tools_scope_without_tenant_gets_403(self) -> None:
        resp = _client(["tools:execute"]).get("/v1/catalog/tools")
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Tenant context required for authenticated principal"

    def test_admin_allowed(self, admin_client: TestClient) -> None:
        resp = admin_client.get("/v1/catalog/tools")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /v1/catalog/tools
# ---------------------------------------------------------------------------


class TestListTools:
    """Browse all tools."""

    def test_returns_all_tools(self, tools_client: TestClient) -> None:
        resp = tools_client.get("/v1/catalog/tools")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["tools"]) == 2

    def test_response_shape(self, tools_client: TestClient) -> None:
        resp = tools_client.get("/v1/catalog/tools")
        body = resp.json()
        assert "tools" in body
        assert "total" in body
        assert "limit" in body
        assert "offset" in body
        # Verify each tool entry has expected fields
        tool = body["tools"][0]
        assert "name" in tool
        assert "description" in tool
        assert "provider" in tool
        assert "has_schema" in tool
        assert "enabled" in tool

    def test_filter_by_category(self, tools_client: TestClient) -> None:
        resp = tools_client.get("/v1/catalog/tools?category=system")
        body = resp.json()
        assert body["total"] == 1
        assert body["tools"][0]["name"] == "shell"

    def test_filter_by_provider(self, tools_client: TestClient) -> None:
        resp = tools_client.get("/v1/catalog/tools?provider=builtin")
        body = resp.json()
        assert body["total"] == 2

    def test_search_query(self, tools_client: TestClient) -> None:
        resp = tools_client.get("/v1/catalog/tools?search=shell")
        body = resp.json()
        assert body["total"] == 1
        assert body["tools"][0]["name"] == "shell"

    def test_pagination(self, tools_client: TestClient) -> None:
        resp = tools_client.get("/v1/catalog/tools?limit=1&offset=0")
        body = resp.json()
        assert body["total"] == 2
        assert len(body["tools"]) == 1
        assert body["limit"] == 1
        assert body["offset"] == 0

    def test_pagination_offset(self, tools_client: TestClient) -> None:
        resp = tools_client.get("/v1/catalog/tools?limit=1&offset=1")
        body = resp.json()
        assert body["total"] == 2
        assert len(body["tools"]) == 1

    def test_route_passes_tenant_filter_to_service(self) -> None:
        service = MagicMock(spec=ToolCatalogService)
        service.list_tools.return_value = ToolCatalogService().list_tools()
        set_catalog_service(service)
        client = _client(["tools:execute"], tenant_id="tenant-a")

        resp = client.get("/v1/catalog/tools")

        assert resp.status_code == 200
        service.list_tools.assert_called_once_with(
            category=None,
            provider=None,
            search=None,
            limit=50,
            offset=0,
            tenant_id="tenant-a",
        )

    def test_route_prefers_test_override_over_app_state_service(self) -> None:
        previous_service = getattr(app.state, "tool_catalog_service", None)
        stale_service = MagicMock(spec=ToolCatalogService)
        stale_service.list_tools.side_effect = AssertionError("stale app.state service used")
        app.state.tool_catalog_service = stale_service

        service = MagicMock(spec=ToolCatalogService)
        service.list_tools.return_value = ToolCatalogService().list_tools()
        set_catalog_service(service)
        client = _client(["tools:execute"], tenant_id="tenant-a")

        try:
            resp = client.get("/v1/catalog/tools")
        finally:
            if previous_service is None:
                delattr(app.state, "tool_catalog_service")
            else:
                app.state.tool_catalog_service = previous_service

        assert resp.status_code == 200
        service.list_tools.assert_called_once_with(
            category=None,
            provider=None,
            search=None,
            limit=50,
            offset=0,
            tenant_id="tenant-a",
        )


# ---------------------------------------------------------------------------
# GET /v1/catalog/tools/{name}
# ---------------------------------------------------------------------------


class TestGetToolDetail:
    """Get detail for a single tool."""

    def test_found(self, tools_client: TestClient) -> None:
        resp = tools_client.get("/v1/catalog/tools/shell")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "shell"
        assert body["description"] == "Run shell commands"
        assert body["version"] == "2.0.0"
        assert body["has_schema"] is True
        assert body["parameters_schema"]["type"] == "object"

    def test_not_found(self, tools_client: TestClient) -> None:
        resp = tools_client.get("/v1/catalog/tools/nonexistent")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /v1/catalog/tools/{name}/schema
# ---------------------------------------------------------------------------


class TestGetToolSchema:
    """Get just the JSON Schema for a tool."""

    def test_schema_returned(self, tools_client: TestClient) -> None:
        resp = tools_client.get("/v1/catalog/tools/shell/schema")
        assert resp.status_code == 200
        schema = resp.json()
        assert schema["type"] == "object"
        assert "command" in schema["properties"]
        assert "command" in schema["required"]

    def test_no_schema_404(self, tools_client: TestClient) -> None:
        resp = tools_client.get("/v1/catalog/tools/web_fetch/schema")
        assert resp.status_code == 404
        assert "No JSON Schema" in resp.json()["detail"]

    def test_missing_tool_404(self, tools_client: TestClient) -> None:
        resp = tools_client.get("/v1/catalog/tools/unknown/schema")
        assert resp.status_code == 404

    def test_route_uses_single_tool_lookup(self) -> None:
        service = MagicMock(spec=ToolCatalogService)
        service.get_tool.return_value = CatalogEntry(
            name="shell",
            parameters_schema={
                "type": "object",
                "properties": {"command": {"type": "string"}},
            },
            has_schema=True,
        )
        set_catalog_service(service)
        client = _client(["tools:execute"], tenant_id="tenant-a")

        resp = client.get("/v1/catalog/tools/shell/schema")

        assert resp.status_code == 200
        service.get_tool.assert_called_once_with("shell", tenant_id="tenant-a")


# ---------------------------------------------------------------------------
# GET /v1/catalog/categories
# ---------------------------------------------------------------------------


class TestListCategories:
    """List categories with counts."""

    def test_categories_returned(self, tools_client: TestClient) -> None:
        resp = tools_client.get("/v1/catalog/categories")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) >= 1
        # Check shape
        entry = body[0]
        assert "category" in entry
        assert "count" in entry

    def test_category_counts_correct(self, tools_client: TestClient) -> None:
        resp = tools_client.get("/v1/catalog/categories")
        cat_map = {c["category"]: c["count"] for c in resp.json()}
        assert cat_map["system"] == 1
        assert cat_map["network"] == 1


# ---------------------------------------------------------------------------
# GET /v1/catalog/providers
# ---------------------------------------------------------------------------


class TestListProviders:
    """List providers with counts."""

    def test_providers_returned(self, tools_client: TestClient) -> None:
        resp = tools_client.get("/v1/catalog/providers")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        entry = body[0]
        assert "provider" in entry
        assert "count" in entry

    def test_provider_counts_correct(self, tools_client: TestClient) -> None:
        resp = tools_client.get("/v1/catalog/providers")
        prov_map = {p["provider"]: p["count"] for p in resp.json()}
        assert prov_map["builtin"] == 2


# ---------------------------------------------------------------------------
# POST /v1/catalog/search
# ---------------------------------------------------------------------------


class TestSearchEndpoint:
    """Search with POST body."""

    def test_search_by_query(self, tools_client: TestClient) -> None:
        resp = tools_client.post("/v1/catalog/search", json={"query": "shell"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["tools"][0]["name"] == "shell"

    def test_search_by_categories(self, tools_client: TestClient) -> None:
        resp = tools_client.post("/v1/catalog/search", json={"categories": ["network"]})
        body = resp.json()
        assert body["total"] == 1
        assert body["tools"][0]["name"] == "web_fetch"

    def test_search_by_tags(self, tools_client: TestClient) -> None:
        resp = tools_client.post("/v1/catalog/search", json={"tags": ["cli"]})
        body = resp.json()
        assert body["total"] == 1
        assert body["tools"][0]["name"] == "shell"

    def test_search_combined(self, tools_client: TestClient) -> None:
        resp = tools_client.post(
            "/v1/catalog/search",
            json={"query": "fetch", "categories": ["network"]},
        )
        body = resp.json()
        assert body["total"] == 1

    def test_search_no_results(self, tools_client: TestClient) -> None:
        resp = tools_client.post("/v1/catalog/search", json={"query": "nonexistent"})
        body = resp.json()
        assert body["total"] == 0
        assert body["tools"] == []

    def test_search_with_pagination(self, tools_client: TestClient) -> None:
        resp = tools_client.post("/v1/catalog/search", json={"limit": 1, "offset": 0})
        body = resp.json()
        assert body["total"] == 2
        assert len(body["tools"]) == 1
        assert body["limit"] == 1

    def test_search_auth_required(self, anon_client: TestClient) -> None:
        resp = anon_client.post("/v1/catalog/search", json={"query": "shell"})
        assert resp.status_code == 401
