"""Tests for the GET /v1/research/providers/status endpoint and ProviderStatusInfo model."""

from __future__ import annotations

import contextlib
from datetime import UTC
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio

from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.web_research.models import (
    ProviderAuthState,
    ProviderStatusInfo,
    ResearchProviderKind,
    ResearchProviderStatus,
    ResearchTrustLevel,
    WebFetchArtifact,
    WebResearchCitation,
    WebResearchResult,
)
from agent33.web_research.service import WebResearchService

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _auth_headers(*, scopes: list[str] | None = None) -> dict[str, str]:
    token = create_access_token(
        "status-user",
        scopes=scopes or [],
        tenant_id="tenant-a",
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestProviderStatusInfoModel:
    """Validate ProviderStatusInfo construction and serialization."""

    def test_construction_with_defaults(self) -> None:
        info = ProviderStatusInfo(name="SearXNG", enabled=True, status="ok")
        assert info.name == "SearXNG"
        assert info.enabled is True
        assert info.status == "ok"
        assert info.last_check is None
        assert info.total_calls == 0
        assert info.success_rate == 1.0

    def test_construction_with_all_fields(self) -> None:
        from datetime import datetime

        ts = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
        info = ProviderStatusInfo(
            name="Governed HTTP Fetch",
            enabled=False,
            status="unconfigured",
            last_check=ts,
            total_calls=42,
            success_rate=0.85,
        )
        assert info.name == "Governed HTTP Fetch"
        assert info.enabled is False
        assert info.status == "unconfigured"
        assert info.last_check == ts
        assert info.total_calls == 42
        assert info.success_rate == pytest.approx(0.85)

    def test_serialization_roundtrip(self) -> None:
        info = ProviderStatusInfo(name="Test", enabled=True, status="ok")
        data = info.model_dump()
        restored = ProviderStatusInfo.model_validate(data)
        assert restored.name == "Test"
        assert restored.enabled is True
        assert restored.status == "ok"
        assert restored.last_check is None


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------


class TestProviderStatusSummary:
    """Test WebResearchService.provider_status_summary()."""

    def _make_service(self) -> WebResearchService:
        mock_search = MagicMock()
        mock_search.provider_id = "searxng"
        mock_search.diagnostics.return_value = ResearchProviderStatus(
            provider_id="searxng",
            display_name="SearXNG",
            kind=ResearchProviderKind.SEARCH,
            status="ok",
            auth_state=ProviderAuthState.NOT_REQUIRED,
            configured=True,
            capabilities=["search", "snippets"],
            is_default=True,
        )
        mock_search.search = AsyncMock(return_value=[])

        mock_fetch = MagicMock()
        mock_fetch.provider_id = "web_fetch"
        mock_fetch.diagnostics.return_value = ResearchProviderStatus(
            provider_id="web_fetch",
            display_name="Governed HTTP Fetch",
            kind=ResearchProviderKind.FETCH,
            status="ok",
            auth_state=ProviderAuthState.NOT_REQUIRED,
            configured=True,
            capabilities=["fetch", "allowlist-enforced"],
        )
        mock_fetch.fetch = AsyncMock(return_value=None)

        return WebResearchService(
            search_providers=[mock_search],
            fetch_providers=[mock_fetch],
            default_search_provider="searxng",
            default_fetch_provider="web_fetch",
        )

    def test_returns_correct_number_of_summaries(self) -> None:
        service = self._make_service()
        summaries = service.provider_status_summary()
        assert len(summaries) == 2

    def test_maps_display_name_to_name_field(self) -> None:
        service = self._make_service()
        summaries = service.provider_status_summary()
        names = {s.name for s in summaries}
        assert "SearXNG" in names
        assert "Governed HTTP Fetch" in names

    def test_maps_configured_to_enabled(self) -> None:
        service = self._make_service()
        summaries = service.provider_status_summary()
        for s in summaries:
            assert s.enabled is True

    def test_unconfigured_provider_shows_disabled(self) -> None:
        mock_search = MagicMock()
        mock_search.provider_id = "disabled"
        mock_search.diagnostics.return_value = ResearchProviderStatus(
            provider_id="disabled",
            display_name="Disabled Provider",
            kind=ResearchProviderKind.SEARCH,
            status="unconfigured",
            auth_state=ProviderAuthState.MISSING,
            configured=False,
        )
        mock_search.search = AsyncMock(return_value=[])

        service = WebResearchService(
            search_providers=[mock_search],
            fetch_providers=[],
            default_search_provider="disabled",
            default_fetch_provider="none",
        )
        summaries = service.provider_status_summary()
        assert len(summaries) == 1
        assert summaries[0].enabled is False
        assert summaries[0].status == "unconfigured"

    def test_preserves_status_string(self) -> None:
        service = self._make_service()
        summaries = service.provider_status_summary()
        statuses = {s.status for s in summaries}
        assert "ok" in statuses


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def _install_web_research_service() -> Any:
    """Install a mock-backed research service on app.state for route tests."""
    mock_search_provider = MagicMock()
    mock_search_provider.provider_id = "searxng"
    mock_search_provider.diagnostics.return_value = ResearchProviderStatus(
        provider_id="searxng",
        display_name="SearXNG",
        kind=ResearchProviderKind.SEARCH,
        status="ok",
        auth_state=ProviderAuthState.NOT_REQUIRED,
        configured=True,
        capabilities=["search", "snippets"],
        is_default=True,
    )
    citation = WebResearchCitation(
        title="Test",
        url="https://example.com/test",
        display_url="example.com/test",
        domain="example.com",
        provider_id="searxng",
        trust_level=ResearchTrustLevel.SEARCH_INDEXED,
        trust_reason="Indexed",
    )
    mock_search_provider.search = AsyncMock(
        return_value=[
            WebResearchResult(
                title="Test",
                url="https://example.com/test",
                snippet="Test snippet",
                provider_id="searxng",
                rank=1,
                domain="example.com",
                display_url="example.com/test",
                trust_level=ResearchTrustLevel.SEARCH_INDEXED,
                trust_reason="Indexed",
                citation=citation,
            ),
        ]
    )

    mock_fetch_provider = MagicMock()
    mock_fetch_provider.provider_id = "web_fetch"
    mock_fetch_provider.diagnostics.return_value = ResearchProviderStatus(
        provider_id="web_fetch",
        display_name="Governed HTTP Fetch",
        kind=ResearchProviderKind.FETCH,
        status="ok",
        auth_state=ProviderAuthState.NOT_REQUIRED,
        configured=True,
        capabilities=["fetch", "allowlist-enforced"],
    )
    mock_fetch_provider.fetch = AsyncMock(
        return_value=WebFetchArtifact(
            url="https://example.com/page",
            provider_id="web_fetch",
            status_code=200,
            content="<html>OK</html>",
            content_preview="<html>OK</html>",
            trust_level=ResearchTrustLevel.FETCH_VERIFIED,
            trust_reason="Fetched",
            citation=WebResearchCitation(
                title="example.com/page",
                url="https://example.com/page",
                display_url="example.com/page",
                domain="example.com",
                provider_id="web_fetch",
                trust_level=ResearchTrustLevel.FETCH_VERIFIED,
                trust_reason="Fetched",
            ),
        )
    )

    service = WebResearchService(
        search_providers=[mock_search_provider],
        fetch_providers=[mock_fetch_provider],
        default_search_provider="searxng",
        default_fetch_provider="web_fetch",
    )

    original = getattr(app.state, "web_research_service", None)
    app.state.web_research_service = service

    from agent33.api.routes.research import set_research_service

    set_research_service(service)

    yield service

    set_research_service(None)
    if original is not None:
        app.state.web_research_service = original
    else:
        with contextlib.suppress(AttributeError):
            del app.state.web_research_service


@pytest_asyncio.fixture()
async def async_client() -> Any:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


class TestProviderStatusRoute:
    """API route tests for GET /v1/research/providers/status."""

    async def test_returns_200_with_provider_list(self, async_client: httpx.AsyncClient) -> None:
        headers = _auth_headers(scopes=["agents:read"])
        resp = await async_client.get("/v1/research/providers/status", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2

    async def test_response_shape_matches_provider_status_info(
        self, async_client: httpx.AsyncClient
    ) -> None:
        headers = _auth_headers(scopes=["agents:read"])
        resp = await async_client.get("/v1/research/providers/status", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        for item in data:
            assert "name" in item
            assert "enabled" in item
            assert "status" in item
            assert "last_check" in item
            assert "total_calls" in item
            assert "success_rate" in item

    async def test_includes_searxng_provider(self, async_client: httpx.AsyncClient) -> None:
        headers = _auth_headers(scopes=["agents:read"])
        resp = await async_client.get("/v1/research/providers/status", headers=headers)
        data = resp.json()
        names = {p["name"] for p in data}
        assert "SearXNG" in names

    async def test_includes_fetch_provider(self, async_client: httpx.AsyncClient) -> None:
        headers = _auth_headers(scopes=["agents:read"])
        resp = await async_client.get("/v1/research/providers/status", headers=headers)
        data = resp.json()
        names = {p["name"] for p in data}
        assert "Governed HTTP Fetch" in names

    async def test_enabled_field_reflects_configured_state(
        self, async_client: httpx.AsyncClient
    ) -> None:
        headers = _auth_headers(scopes=["agents:read"])
        resp = await async_client.get("/v1/research/providers/status", headers=headers)
        data = resp.json()
        for item in data:
            assert item["enabled"] is True

    async def test_no_auth_returns_401(self, async_client: httpx.AsyncClient) -> None:
        resp = await async_client.get("/v1/research/providers/status")
        assert resp.status_code == 401

    async def test_wrong_scope_returns_403(self, async_client: httpx.AsyncClient) -> None:
        headers = _auth_headers(scopes=["sessions:write"])
        resp = await async_client.get("/v1/research/providers/status", headers=headers)
        assert resp.status_code == 403

    async def test_agents_read_scope_is_sufficient(self, async_client: httpx.AsyncClient) -> None:
        """The endpoint requires agents:read, not the higher tools:execute scope."""
        headers = _auth_headers(scopes=["agents:read"])
        resp = await async_client.get("/v1/research/providers/status", headers=headers)
        assert resp.status_code == 200

    async def test_service_unavailable_when_no_service_installed(
        self, async_client: httpx.AsyncClient
    ) -> None:
        """If the service is removed, the endpoint should return 503."""
        from agent33.api.routes.research import set_research_service

        set_research_service(None)
        original = getattr(app.state, "web_research_service", None)
        with contextlib.suppress(AttributeError):
            del app.state.web_research_service

        try:
            headers = _auth_headers(scopes=["agents:read"])
            resp = await async_client.get("/v1/research/providers/status", headers=headers)
            assert resp.status_code == 503
            assert "not initialized" in resp.json()["detail"]
        finally:
            if original is not None:
                app.state.web_research_service = original
                set_research_service(original)
