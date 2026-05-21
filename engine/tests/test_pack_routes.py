"""Tests for pack management API endpoints.

Tests cover: list packs, get pack, install, uninstall, enable, disable,
search, and sync endpoints with proper auth and tenant scoping.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent33.api.routes.packs import router
from agent33.packs.marketplace import LocalPackMarketplace
from agent33.packs.models import PackSource
from agent33.packs.registry import PackRegistry
from agent33.packs.rollback import PackRollbackManager
from agent33.packs.trust_manager import TrustPolicyManager
from agent33.services.orchestration_state import OrchestrationStateStore
from agent33.skills.registry import SkillRegistry


def _write_pack(
    base: Path,
    *,
    name: str = "test-pack",
    version: str = "1.0.0",
    pack_dependencies: list[tuple[str, str]] | None = None,
) -> Path:
    """Create a minimal valid pack directory."""
    pack_dir = base / name
    pack_dir.mkdir(parents=True, exist_ok=True)
    dependency_yaml = ""
    if pack_dependencies:
        dependency_items = "\n".join(
            f'    - name: {dep_name}\n      version_constraint: "{constraint}"'
            for dep_name, constraint in pack_dependencies
        )
        dependency_yaml = f"\ndependencies:\n  packs:\n{dependency_items}\n"
    manifest_yaml = textwrap.dedent(f"""\
        name: {name}
        version: {version}
        description: Pack {name}
        author: tester
        tags:
          - test
        skills:
          - name: skill-1
            path: skills/skill-1
        """)

    (pack_dir / "PACK.yaml").write_text(
        manifest_yaml + dependency_yaml,
        encoding="utf-8",
    )
    sdir = pack_dir / "skills" / "skill-1"
    sdir.mkdir(parents=True)
    (sdir / "SKILL.md").write_text(
        f"---\nname: skill-1\ndescription: Skill from {name}\n---\n# S1\n",
        encoding="utf-8",
    )
    return pack_dir


def _create_test_app(pack_registry: PackRegistry | None = None) -> FastAPI:
    """Create a minimal FastAPI app with the packs router for testing."""
    app = FastAPI()
    app.include_router(router)

    if pack_registry is not None:
        app.state.pack_registry = pack_registry

    # Mock auth middleware: inject a fake user with tenant_id
    from starlette.middleware.base import BaseHTTPMiddleware

    class FakeAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Any, call_next: Any) -> Any:
            user = MagicMock()
            user.tenant_id = "test-tenant"
            user.scopes = [
                "agents:read",
                "agents:write",
                "admin",
            ]
            request.state.user = user
            return await call_next(request)

    app.add_middleware(FakeAuthMiddleware)
    return app


class TestPackRoutesWithoutRegistry:
    """Test endpoints when pack registry is not initialized."""

    def test_list_packs_no_registry(self) -> None:
        app = _create_test_app(pack_registry=None)
        client = TestClient(app)
        resp = client.get("/v1/packs")
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Pack registry not initialized"

    def test_list_enabled_no_registry(self) -> None:
        app = _create_test_app(pack_registry=None)
        client = TestClient(app)
        resp = client.get("/v1/packs/enabled")
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Pack registry not initialized"

    def test_search_no_registry(self) -> None:
        app = _create_test_app(pack_registry=None)
        client = TestClient(app)
        resp = client.get("/v1/packs/search", params={"q": "test"})
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Pack registry not initialized"

    def test_hub_search_no_hub_returns_503(self) -> None:
        """hub_search must raise 503 when pack_hub is absent, not an empty-200."""
        app = _create_test_app(pack_registry=None)
        # pack_hub is not set — _get_pack_hub returns None
        client = TestClient(app)
        resp = client.get("/v1/packs/hub/search", params={"q": "test"})
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Pack hub not initialized"

    def test_check_all_compliance_no_registry_returns_503(self) -> None:
        """check_all_compliance must raise 503 when pack_registry is absent (secondary guard)."""
        app = _create_test_app(pack_registry=None)
        # Install a fake audit service so the first guard passes, but leave
        # pack_registry unset so the secondary registry guard triggers.
        fake_audit = MagicMock()
        app.state.pack_audit = fake_audit
        client = TestClient(app)
        resp = client.post("/v1/packs/compliance/check-all")
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Pack registry not initialized"


class TestPackRoutesWithRegistry:
    """Test endpoints with a functioning pack registry."""

    def _setup(
        self,
        tmp_path: Path,
        *,
        configure_marketplace: bool = True,
    ) -> tuple[TestClient, PackRegistry, Path, Path]:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        marketplace_dir = tmp_path / "marketplace"
        marketplace_dir.mkdir()
        state_store = OrchestrationStateStore(str(tmp_path / "pack-state.json"))
        skill_reg = SkillRegistry()
        marketplace = LocalPackMarketplace(marketplace_dir) if configure_marketplace else None
        trust_manager = TrustPolicyManager(state_store)
        pack_reg = PackRegistry(
            packs_dir=packs_dir,
            skill_registry=skill_reg,
            marketplace=marketplace,
            trust_policy_manager=trust_manager,
        )
        rollback_manager = PackRollbackManager(
            pack_reg,
            archive_dir=tmp_path / "rollback-archive",
            state_store=state_store,
        )
        app = _create_test_app(pack_registry=pack_reg)
        app.state.pack_trust_manager = trust_manager
        app.state.pack_rollback_manager = rollback_manager
        client = TestClient(app)
        return client, pack_reg, packs_dir, marketplace_dir

    def test_list_packs_empty(self, tmp_path: Path) -> None:
        client, _, _, _ = self._setup(tmp_path)
        resp = client.get("/v1/packs")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_list_packs_with_installed(self, tmp_path: Path) -> None:
        client, pack_reg, packs_dir, _ = self._setup(tmp_path)
        _write_pack(packs_dir, name="my-pack")
        pack_reg.discover()

        resp = client.get("/v1/packs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["packs"][0]["name"] == "my-pack"

    def test_get_pack_found(self, tmp_path: Path) -> None:
        client, pack_reg, packs_dir, _ = self._setup(tmp_path)
        _write_pack(packs_dir, name="detail-pack")
        pack_reg.discover()

        resp = client.get("/v1/packs/detail-pack")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "detail-pack"
        assert data["version"] == "1.0.0"
        assert data["author"] == "tester"
        assert data["enabled_for_tenant"] is False

    def test_get_pack_outcome_manifests_loads_bundled_workflows(self, tmp_path: Path) -> None:
        client, pack_reg, packs_dir, _ = self._setup(tmp_path)
        pack_dir = _write_pack(packs_dir, name="outcome-pack")
        outcomes_dir = pack_dir / "outcomes"
        workflows_dir = pack_dir / "workflows"
        outcomes_dir.mkdir()
        workflows_dir.mkdir()
        (pack_dir / "PACK.yaml").write_text(
            textwrap.dedent(
                """\
                name: outcome-pack
                version: 1.0.0
                description: Pack with outcome starters
                author: tester
                skills:
                  - name: skill-1
                    path: skills/skill-1
                outcome_packs:
                  - path: outcomes/founder-mvp.yaml
                    description: Founder starter
                """
            ),
            encoding="utf-8",
        )
        (outcomes_dir / "founder-mvp.yaml").write_text(
            textwrap.dedent(
                """\
                schema_version: "1"
                name: founder-mvp
                version: 1.0.0
                kind: outcome-pack
                description: Build an MVP plan.
                author: tester
                workflows:
                  - name: founder-mvp
                    path: workflows/founder-mvp.yaml
                presentation:
                  title: Founder MVP
                  summary: Build a first MVP plan.
                  expected_deliverables:
                    - MVP plan
                governance:
                  approval_required: true
                  risk_level: medium
                provenance:
                  trust_tier: official
                installation:
                  auto_enable: false
                artifacts:
                  - name: MVP plan
                    required: true
                """
            ),
            encoding="utf-8",
        )
        (workflows_dir / "founder-mvp.yaml").write_text(
            textwrap.dedent(
                """\
                name: founder-mvp
                version: 1.0.0
                description: Build an MVP plan.
                inputs:
                  idea:
                    type: string
                    required: true
                outputs:
                  plan:
                    type: object
                steps:
                  - id: plan
                    action: invoke-agent
                    agent: orchestrator
                    inputs:
                      idea: ${inputs.idea}
                """
            ),
            encoding="utf-8",
        )
        pack_reg.discover()

        resp = client.get("/v1/packs/outcome-pack/outcome-manifests")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["packs"][0]["manifest"]["name"] == "founder-mvp"
        assert data["packs"][0]["workflows"][0]["name"] == "founder-mvp"

    def test_get_pack_recovery_preview_surfaces_dependents_and_rollback(
        self,
        tmp_path: Path,
    ) -> None:
        client, pack_reg, packs_dir, _ = self._setup(tmp_path)
        _write_pack(packs_dir, name="base-utils", version="1.0.0")
        _write_pack(
            packs_dir,
            name="app-pack",
            pack_dependencies=[("base-utils", "^1.0.0")],
        )
        pack_reg.discover()
        client.app.state.pack_rollback_manager.archive_current("base-utils")

        resp = client.get(
            "/v1/packs/base-utils/recovery-preview",
            params={"target_version": "2.0.0"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["pack_name"] == "base-utils"
        assert data["installed_version"] == "1.0.0"
        assert data["target_version"] == "2.0.0"
        assert data["affected_skills"] == ["base-utils/skill-1"]
        assert data["can_uninstall_safely"] is False
        assert data["can_upgrade_safely"] is False
        assert data["can_rollback"] is True
        assert data["dependents"] == [
            {
                "name": "app-pack",
                "version": "1.0.0",
                "version_constraint": "^1.0.0",
                "status": "installed",
            }
        ]
        assert data["archived_versions"][0]["version"] == "1.0.0"
        assert "Upgrade would break dependent" in data["compatibility_errors"][0]
        assert "Do not upgrade base-utils to 2.0.0" in data["recommended_action"]

    def test_get_pack_recovery_preview_allows_safe_pack(self, tmp_path: Path) -> None:
        client, pack_reg, packs_dir, _ = self._setup(tmp_path)
        _write_pack(packs_dir, name="standalone-pack")
        pack_reg.discover()

        resp = client.get("/v1/packs/standalone-pack/recovery-preview")

        assert resp.status_code == 200
        data = resp.json()
        assert data["dependents"] == []
        assert data["compatibility_errors"] == []
        assert data["can_uninstall_safely"] is True
        assert data["can_upgrade_safely"] is True
        assert data["can_rollback"] is False
        assert "No dependent packs are blocking this change" in data["recommended_action"]

    def test_get_pack_includes_skill_category_and_provenance(self, tmp_path: Path) -> None:
        client, pack_reg, packs_dir, _ = self._setup(tmp_path)
        pack_dir = packs_dir / "metadata-pack"
        pack_dir.mkdir(parents=True, exist_ok=True)
        (pack_dir / "PACK.yaml").write_text(
            textwrap.dedent(
                """\
                name: metadata-pack
                version: 1.0.0
                description: Metadata pack
                author: tester
                skills:
                  - name: planning-with-files
                    path: skills/workflow/planning-with-files
                """
            ),
            encoding="utf-8",
        )
        skill_dir = pack_dir / "skills" / "workflow" / "planning-with-files"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            textwrap.dedent(
                """\
                ---
                name: planning-with-files
                description: Planning support
                provenance: imported-evokore
                ---
                # Planning
                """
            ),
            encoding="utf-8",
        )
        pack_reg.discover()

        resp = client.get("/v1/packs/metadata-pack")

        assert resp.status_code == 200
        data = resp.json()
        assert data["skills"][0]["category"] == "workflow"
        assert data["skills"][0]["provenance"] == "imported-evokore"

    def test_get_pack_not_found(self, tmp_path: Path) -> None:
        client, _, _, _ = self._setup(tmp_path)
        resp = client.get("/v1/packs/nonexistent")
        assert resp.status_code == 404

    def test_install_pack(self, tmp_path: Path) -> None:
        client, _, _, _ = self._setup(tmp_path)
        pack_path = _write_pack(tmp_path / "source", name="new-pack")

        resp = client.post(
            "/v1/packs/install",
            json={"source_type": "local", "path": str(pack_path)},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["success"] is True
        assert data["pack_name"] == "new-pack"
        assert data["skills_loaded"] == 1

    def test_install_invalid_path(self, tmp_path: Path) -> None:
        client, _, _, _ = self._setup(tmp_path)
        resp = client.post(
            "/v1/packs/install",
            json={"source_type": "local", "path": "/nonexistent/path"},
        )
        assert resp.status_code == 400

    def test_install_marketplace_pack(self, tmp_path: Path) -> None:
        client, pack_reg, _, marketplace_dir = self._setup(tmp_path)
        _write_pack(marketplace_dir / "v1", name="market-pack")

        resp = client.post(
            "/v1/packs/install",
            json={"source_type": "marketplace", "name": "market-pack"},
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["success"] is True
        assert data["pack_name"] == "market-pack"
        assert pack_reg.get("market-pack") is not None

    def test_install_marketplace_pack_requires_configured_marketplace(
        self, tmp_path: Path
    ) -> None:
        client, _, _, _ = self._setup(tmp_path, configure_marketplace=False)

        resp = client.post(
            "/v1/packs/install",
            json={"source_type": "marketplace", "name": "market-pack"},
        )

        assert resp.status_code == 400
        assert resp.json()["detail"] == {
            "message": "Failed to install pack 'market-pack'",
            "errors": ["Marketplace registry is not configured"],
        }

    def test_install_marketplace_pack_requires_name(self, tmp_path: Path) -> None:
        client, _, _, _ = self._setup(tmp_path)

        resp = client.post(
            "/v1/packs/install",
            json={"source_type": "marketplace"},
        )

        assert resp.status_code == 400
        assert resp.json()["detail"] == {
            "message": "Failed to install pack 'unknown'",
            "errors": ["Marketplace installs require a pack name"],
        }

    def test_uninstall_pack(self, tmp_path: Path) -> None:
        client, pack_reg, packs_dir, _ = self._setup(tmp_path)
        _write_pack(packs_dir, name="removable")
        pack_reg.discover()

        resp = client.delete("/v1/packs/removable")
        assert resp.status_code == 204

    def test_uninstall_not_found(self, tmp_path: Path) -> None:
        client, _, _, _ = self._setup(tmp_path)
        resp = client.delete("/v1/packs/ghost")
        assert resp.status_code == 404

    def test_enable_pack(self, tmp_path: Path) -> None:
        client, pack_reg, packs_dir, _ = self._setup(tmp_path)
        _write_pack(packs_dir, name="enableable")
        pack_reg.discover()

        resp = client.post("/v1/packs/enableable/enable")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["action"] == "enabled"
        assert data["pack_name"] == "enableable"

    def test_enable_not_installed(self, tmp_path: Path) -> None:
        client, _, _, _ = self._setup(tmp_path)
        resp = client.post("/v1/packs/ghost/enable")
        assert resp.status_code == 404

    def test_disable_pack(self, tmp_path: Path) -> None:
        client, pack_reg, packs_dir, _ = self._setup(tmp_path)
        _write_pack(packs_dir, name="disableable")
        pack_reg.discover()
        pack_reg.enable("disableable", "test-tenant")

        resp = client.post("/v1/packs/disableable/disable")
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "disabled"

    def test_search_packs(self, tmp_path: Path) -> None:
        client, pack_reg, packs_dir, _ = self._setup(tmp_path)
        _write_pack(packs_dir, name="kubernetes-ops")
        _write_pack(packs_dir, name="data-analysis")
        pack_reg.discover()

        resp = client.get("/v1/packs/search", params={"q": "kubernetes"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["results"][0]["name"] == "kubernetes-ops"

    def test_list_enabled_packs(self, tmp_path: Path) -> None:
        client, pack_reg, packs_dir, _ = self._setup(tmp_path)
        _write_pack(packs_dir, name="enabled-pack")
        pack_reg.discover()
        pack_reg.enable("enabled-pack", "test-tenant")

        resp = client.get("/v1/packs/enabled")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["tenant_id"] == "test-tenant"

    def test_sync_pack(self, tmp_path: Path) -> None:
        client, pack_reg, packs_dir, _ = self._setup(tmp_path)
        _write_pack(packs_dir, name="syncable")
        pack_reg.discover()

        resp = client.post("/v1/packs/syncable/sync")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["pack_name"] == "syncable"

    def test_get_pack_trust_policy(self, tmp_path: Path) -> None:
        client, _, _, _ = self._setup(tmp_path)

        resp = client.get("/v1/packs/trust/policy")

        assert resp.status_code == 200
        assert resp.json()["policy"]["require_signature"] is False

    def test_update_pack_trust_policy(self, tmp_path: Path) -> None:
        client, _, _, _ = self._setup(tmp_path)

        resp = client.put(
            "/v1/packs/trust/policy",
            json={"require_signature": True, "allowed_signers": ["ops-team"]},
        )

        assert resp.status_code == 200
        assert resp.json()["policy"]["require_signature"] is True
        assert resp.json()["policy"]["allowed_signers"] == ["ops-team"]

    def test_get_pack_trust_for_installed_pack(self, tmp_path: Path) -> None:
        client, pack_reg, _, marketplace_dir = self._setup(tmp_path)
        _write_pack(marketplace_dir / "v1", name="trusted-pack")
        pack_reg.install(PackSource(source_type="marketplace", name="trusted-pack"))

        resp = client.get("/v1/packs/trusted-pack/trust")

        assert resp.status_code == 200
        assert resp.json()["pack_name"] == "trusted-pack"
        assert resp.json()["allowed"] is True

    def test_get_enablement_matrix(self, tmp_path: Path) -> None:
        client, pack_reg, packs_dir, _ = self._setup(tmp_path)
        _write_pack(packs_dir, name="matrix-pack")
        pack_reg.discover()
        pack_reg.enable("matrix-pack", "test-tenant")

        resp = client.get("/v1/packs/enablement/matrix")

        assert resp.status_code == 200
        assert resp.json()["matrix"]["matrix-pack"]["test-tenant"] is True

    def test_update_enablement_matrix(self, tmp_path: Path) -> None:
        client, pack_reg, packs_dir, _ = self._setup(tmp_path)
        _write_pack(packs_dir, name="matrix-pack")
        pack_reg.discover()

        resp = client.put(
            "/v1/packs/enablement/matrix",
            json={"matrix": {"matrix-pack": {"tenant-b": True}}},
        )

        assert resp.status_code == 200
        assert pack_reg.is_enabled("matrix-pack", "tenant-b") is True

    def test_upgrade_and_rollback_pack(self, tmp_path: Path) -> None:
        client, pack_reg, _, marketplace_dir = self._setup(tmp_path)
        _write_pack(marketplace_dir / "v1", name="upgrade-pack")
        _write_pack(marketplace_dir / "v2", name="upgrade-pack")
        version_file = marketplace_dir / "v2" / "upgrade-pack" / "PACK.yaml"
        version_file.write_text(
            version_file.read_text(encoding="utf-8").replace("1.0.0", "2.0.0"),
            encoding="utf-8",
        )

        install_resp = client.post(
            "/v1/packs/install",
            json={"source_type": "marketplace", "name": "upgrade-pack", "version": "1.0.0"},
        )
        assert install_resp.status_code == 201
        pack_reg.enable("upgrade-pack", "test-tenant")

        upgrade_resp = client.post(
            "/v1/packs/upgrade-pack/upgrade",
            json={"source_type": "marketplace", "version": "2.0.0"},
        )

        assert upgrade_resp.status_code == 200
        assert pack_reg.get("upgrade-pack").version == "2.0.0"  # type: ignore[union-attr]
        assert pack_reg.is_enabled("upgrade-pack", "test-tenant") is True

        rollback_resp = client.post("/v1/packs/upgrade-pack/rollback?version=1.0.0")

        assert rollback_resp.status_code == 200
        assert rollback_resp.json()["restored_from_version"] == "1.0.0"
        assert pack_reg.get("upgrade-pack").version == "1.0.0"  # type: ignore[union-attr]
        assert pack_reg.is_enabled("upgrade-pack", "test-tenant") is True
