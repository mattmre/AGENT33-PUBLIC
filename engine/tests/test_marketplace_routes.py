"""Tests for marketplace pack discovery and installation routes."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent33.api.routes.marketplace import router
from agent33.packs.marketplace import LocalPackMarketplace
from agent33.packs.registry import PackRegistry
from agent33.skills.registry import SkillRegistry

if TYPE_CHECKING:
    from pathlib import Path


def _write_pack(base: Path, *, name: str, version: str) -> Path:
    """Create a minimal valid pack directory."""
    pack_dir = base / f"{name}-{version}"
    pack_dir.mkdir(parents=True, exist_ok=True)

    (pack_dir / "PACK.yaml").write_text(
        textwrap.dedent(f"""\
        name: {name}
        version: {version}
        description: Pack {name} {version}
        author: tester
        tags:
          - test
        skills:
          - name: skill-1
            path: skills/skill-1
        """),
        encoding="utf-8",
    )
    skill_dir = pack_dir / "skills" / "skill-1"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: skill-1\ndescription: Skill from marketplace\n---\n# Skill\n",
        encoding="utf-8",
    )
    return pack_dir


def _create_test_app(
    tmp_path: Path,
    *,
    configure_marketplace: bool = True,
    configure_registry_marketplace: bool | None = None,
) -> TestClient:
    """Create a minimal FastAPI app with the marketplace router."""
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    marketplace_dir = tmp_path / "marketplace"
    marketplace_dir.mkdir()
    if configure_registry_marketplace is None:
        configure_registry_marketplace = configure_marketplace
    if configure_marketplace:
        _write_pack(marketplace_dir, name="analytics-pack", version="1.0.0")
        _write_pack(marketplace_dir, name="analytics-pack", version="2.0.0")
        _write_pack(marketplace_dir, name="ops-pack", version="1.2.0")

    skill_registry = SkillRegistry()
    app = FastAPI()
    app.include_router(router)
    marketplace = LocalPackMarketplace(marketplace_dir) if configure_marketplace else None
    if configure_marketplace:
        app.state.pack_marketplace = marketplace
    app.state.pack_registry = PackRegistry(
        packs_dir=packs_dir,
        skill_registry=skill_registry,
        marketplace=marketplace if configure_registry_marketplace else None,
    )

    from starlette.middleware.base import BaseHTTPMiddleware

    class FakeAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Any, call_next: Any) -> Any:
            user = MagicMock()
            user.tenant_id = "test-tenant"
            user.scopes = ["agents:read", "agents:write", "admin"]
            request.state.user = user
            return await call_next(request)

    app.add_middleware(FakeAuthMiddleware)
    return TestClient(app)


class TestMarketplaceRoutes:
    """Marketplace route coverage."""

    def test_list_marketplace_packs(self, tmp_path: Path) -> None:
        client = _create_test_app(tmp_path)

        response = client.get("/v1/marketplace/packs")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert [item["name"] for item in data["packs"]] == ["analytics-pack", "ops-pack"]
        assert data["packs"][0]["sources"] == ["local"]
        assert data["packs"][0]["trust_level"] == "untrusted"

    def test_get_marketplace_pack_detail(self, tmp_path: Path) -> None:
        client = _create_test_app(tmp_path)

        response = client.get("/v1/marketplace/packs/analytics-pack")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "analytics-pack"
        assert data["latest_version"] == "2.0.0"
        assert [item["version"] for item in data["versions"]] == ["2.0.0", "1.0.0"]
        assert data["versions"][0]["source_name"] == "local"
        assert data["versions"][0]["trust_level"] == "untrusted"

    def test_list_marketplace_versions(self, tmp_path: Path) -> None:
        client = _create_test_app(tmp_path)

        response = client.get("/v1/marketplace/packs/analytics-pack/versions")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert [item["version"] for item in data["versions"]] == ["2.0.0", "1.0.0"]

    def test_search_marketplace(self, tmp_path: Path) -> None:
        client = _create_test_app(tmp_path)

        response = client.get("/v1/marketplace/search", params={"q": "analytics"})

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["name"] == "analytics-pack"

    def test_install_marketplace_pack(self, tmp_path: Path) -> None:
        client = _create_test_app(tmp_path)

        response = client.post(
            "/v1/marketplace/install",
            json={"name": "analytics-pack", "version": "1.0.0"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["pack_name"] == "analytics-pack"
        assert data["version"] == "1.0.0"

    def test_install_marketplace_pack_requires_configured_marketplace(
        self, tmp_path: Path
    ) -> None:
        client = _create_test_app(tmp_path, configure_marketplace=False)

        response = client.post(
            "/v1/marketplace/install",
            json={"name": "analytics-pack", "version": "1.0.0"},
        )

        assert response.status_code == 503
        assert response.json()["detail"] == "Marketplace catalog not initialized"

    def test_install_marketplace_pack_requires_marketplace_on_registry(
        self, tmp_path: Path
    ) -> None:
        client = _create_test_app(
            tmp_path,
            configure_marketplace=True,
            configure_registry_marketplace=False,
        )

        response = client.post(
            "/v1/marketplace/install",
            json={"name": "analytics-pack", "version": "1.0.0"},
        )

        assert response.status_code == 503
        assert response.json()["detail"] == "Marketplace catalog not initialized"

    def test_install_marketplace_pack_requires_name(self, tmp_path: Path) -> None:
        client = _create_test_app(tmp_path)

        response = client.post(
            "/v1/marketplace/install",
            json={"version": "1.0.0"},
        )

        assert response.status_code == 422

    def test_refresh_marketplace(self, tmp_path: Path) -> None:
        client = _create_test_app(tmp_path)

        response = client.post("/v1/marketplace/refresh")

        assert response.status_code == 200
        assert response.json()["refreshed"] is True

    def test_list_marketplace_packs_no_marketplace_returns_503(
        self, tmp_path: Path
    ) -> None:
        client = _create_test_app(tmp_path, configure_marketplace=False)

        response = client.get("/v1/marketplace/packs")

        assert response.status_code == 503
        assert response.json()["detail"] == "Marketplace catalog not initialized"

    def test_list_marketplace_versions_no_marketplace_returns_503(
        self, tmp_path: Path
    ) -> None:
        client = _create_test_app(tmp_path, configure_marketplace=False)

        response = client.get("/v1/marketplace/packs/analytics-pack/versions")

        assert response.status_code == 503
        assert response.json()["detail"] == "Marketplace catalog not initialized"

    def test_search_marketplace_no_marketplace_returns_503(
        self, tmp_path: Path
    ) -> None:
        client = _create_test_app(tmp_path, configure_marketplace=False)

        response = client.get("/v1/marketplace/search", params={"q": "analytics"})

        assert response.status_code == 503
        assert response.json()["detail"] == "Marketplace catalog not initialized"
