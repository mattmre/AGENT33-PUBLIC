"""Tests for P-PACK v2: Hub Client, Agent-to-Agent Sharing, Update Checks.

Covers:
- PackHub.search() with mocked HTTP returns filtered results
- PackHub.search() with tag filtering narrows results
- PackHub.search() respects limit parameter
- PackHub.get() returns matching entry
- PackHub.get() returns None for unknown pack
- PackHub.download() verifies sha256 on success
- PackHub.download() raises on sha256 mismatch
- PackHub.download() raises when download_url is empty
- PackHub.search() returns empty list when cache is absent (no error)
- PackHub.refresh_cache() saves to disk
- PackHub.list_cached() loads from disk
- PackSharingService.extract_share_requests() finds top-level pack_ref
- PackSharingService.extract_share_requests() finds nested pack_ref
- PackSharingService.extract_share_requests() handles pack_refs list
- PackSharingService.extract_share_requests() returns empty for no refs
- PackSharingService.apply_shares() enables packs for a session
- PackSharingService.apply_shares() skips missing packs
- PackSharingService.apply_shares() logs reason for sharing
- PackRegistry.check_for_updates() returns items where hub version > installed
- PackRegistry.check_for_updates() returns empty when hub has no updates
- PackRegistry.check_for_updates() skips packs not in hub
- invoke_agent.execute() applies pack sharing before invocation
- invoke_agent.set_pack_sharing_service() wiring
- CLI search command calls hub and prints results
- CLI install command prints entry details
- CLI publish command validates pack and prints PR template
- Hub API route /hub/search returns search results
- Hub API route /hub/entry/{name} returns entry
- Hub API route /hub/entry/{name} returns 404 for unknown
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent33.packs.hub import PackHub, PackHubConfig, PackHubEntry, PackRegistryPayload
from agent33.packs.models import InstalledPack, PackSkillEntry, PackStatus
from agent33.packs.sharing import PackShareRequest, PackSharingService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_ENTRIES = [
    PackHubEntry(
        name="code-review",
        version="2.0.0",
        description="Code review automation pack",
        author="tester",
        tags=["review", "automation"],
        download_url="https://example.com/code-review.yaml",
        sha256="abc123",
        install_count=100,
        rating=4.5,
    ),
    PackHubEntry(
        name="security-scan",
        version="1.5.0",
        description="Security scanning pack",
        author="sec-team",
        tags=["security", "scanning"],
        download_url="https://example.com/security-scan.yaml",
        sha256="def456",
        install_count=50,
        rating=4.0,
    ),
    PackHubEntry(
        name="data-pipeline",
        version="3.1.0",
        description="Data pipeline orchestration",
        author="data-team",
        tags=["data", "pipeline", "automation"],
        download_url="https://example.com/data-pipeline.yaml",
        sha256="ghi789",
        install_count=200,
        rating=4.8,
    ),
]


def _make_hub(
    entries: list[PackHubEntry] | None = None,
    config: PackHubConfig | None = None,
) -> PackHub:
    """Create a PackHub with pre-loaded cache (no network)."""
    hub = PackHub(config=config)
    hub._cache = entries or list(_SAMPLE_ENTRIES)
    hub._cache_loaded_at = 1e15  # far future to skip refresh
    return hub


def _make_installed_pack(
    name: str = "test-pack",
    version: str = "1.0.0",
) -> InstalledPack:
    """Create a minimal InstalledPack for testing."""
    return InstalledPack(
        name=name,
        version=version,
        description=f"{name} pack",
        author="tester",
        skills=[PackSkillEntry(name="skill-a", path="skills/a")],
        loaded_skill_names=[f"{name}/skill-a"],
        pack_dir=Path("/tmp/fake-packs") / name,
        status=PackStatus.INSTALLED,
    )


def _make_registry(packs: list[InstalledPack] | None = None) -> Any:
    """Build a PackRegistry with pre-loaded packs (no filesystem)."""
    from agent33.packs.provenance_models import PackTrustPolicy
    from agent33.packs.registry import PackRegistry

    registry = PackRegistry.__new__(PackRegistry)
    registry._packs_dir = Path("/tmp/fake-packs")
    registry._skill_registry = MagicMock()
    registry._installed = {}
    registry._enabled = {}
    registry._session_enabled = {}
    registry._session_pack_sources = {}
    registry._session_pack_sequence = {}
    registry._session_activation_counter = {}
    registry._session_tracking_lock = RLock()
    registry._marketplace = None
    registry._trust_policy = PackTrustPolicy()
    registry._trust_policy_manager = None
    registry._ppack_v3_enabled = False

    for p in packs or []:
        registry._installed[p.name] = p

    return registry


# ---------------------------------------------------------------------------
# PackHub.search() tests
# ---------------------------------------------------------------------------


class TestPackHubSearch:
    """PackHub.search() returns filtered results from cache."""

    async def test_search_by_name(self) -> None:
        """Search matches pack name substring."""
        hub = _make_hub()
        results = await hub.search("code")
        assert len(results) == 1
        assert results[0].name == "code-review"

    async def test_search_by_description(self) -> None:
        """Search matches pack description substring."""
        hub = _make_hub()
        results = await hub.search("orchestration")
        assert len(results) == 1
        assert results[0].name == "data-pipeline"

    async def test_search_by_tag(self) -> None:
        """Search matches pack tags."""
        hub = _make_hub()
        results = await hub.search("automation")
        assert len(results) == 2
        names = {r.name for r in results}
        assert names == {"code-review", "data-pipeline"}

    async def test_search_with_tag_filter(self) -> None:
        """Tag filter narrows results."""
        hub = _make_hub()
        results = await hub.search("automation", tags=["data"])
        assert len(results) == 1
        assert results[0].name == "data-pipeline"

    async def test_search_respects_limit(self) -> None:
        """Search returns at most `limit` results."""
        hub = _make_hub()
        results = await hub.search("", limit=1)
        # Empty string matches everything via name/description/tags
        # but limit caps it to 1
        assert len(results) <= 1

    async def test_search_empty_cache_no_error(self) -> None:
        """Search returns empty list when cache is absent (no crash)."""
        config = PackHubConfig(
            local_cache_path=Path("/tmp/nonexistent-agent33-cache.json"),
        )
        hub = PackHub(config=config)
        # Override _ensure_cache to avoid any network call
        hub._ensure_cache = AsyncMock()  # type: ignore[method-assign]
        results = await hub.search("anything")
        assert results == []


# ---------------------------------------------------------------------------
# PackHub.get() tests
# ---------------------------------------------------------------------------


class TestPackHubGet:
    """PackHub.get() returns entry by exact name."""

    async def test_get_existing(self) -> None:
        hub = _make_hub()
        entry = await hub.get("security-scan")
        assert entry is not None
        assert entry.name == "security-scan"
        assert entry.version == "1.5.0"

    async def test_get_nonexistent(self) -> None:
        hub = _make_hub()
        entry = await hub.get("does-not-exist")
        assert entry is None


# ---------------------------------------------------------------------------
# PackHub.download() tests
# ---------------------------------------------------------------------------


class TestPackHubDownload:
    """PackHub.download() fetches and verifies content."""

    async def test_download_verifies_sha256_success(self, tmp_path: Path) -> None:
        """Download succeeds when sha256 matches."""
        import hashlib

        content = b"name: test-pack\nversion: 1.0.0\n"
        expected_sha = hashlib.sha256(content).hexdigest()

        entry = PackHubEntry(
            name="test-pack",
            version="1.0.0",
            download_url="https://example.com/test-pack.yaml",
            sha256=expected_sha,
        )

        hub = _make_hub()

        mock_response = AsyncMock()
        mock_response.content = content
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agent33.packs.hub.httpx.AsyncClient", return_value=mock_client):
            path = await hub.download(entry, tmp_path)

        assert path.exists()
        assert path.read_bytes() == content

    async def test_download_raises_on_sha256_mismatch(self, tmp_path: Path) -> None:
        """Download raises ValueError when sha256 doesn't match."""
        entry = PackHubEntry(
            name="bad-pack",
            version="1.0.0",
            download_url="https://example.com/bad.yaml",
            sha256="0000000000000000000000000000000000000000000000000000000000000000",
        )

        hub = _make_hub()

        mock_response = AsyncMock()
        mock_response.content = b"some content"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("agent33.packs.hub.httpx.AsyncClient", return_value=mock_client),
            pytest.raises(ValueError, match="SHA-256 mismatch"),
        ):
            await hub.download(entry, tmp_path)

    async def test_download_raises_when_url_empty(self, tmp_path: Path) -> None:
        """Download raises ValueError when download_url is empty."""
        entry = PackHubEntry(name="no-url", version="1.0.0", download_url="")
        hub = _make_hub()

        with pytest.raises(ValueError, match="no download URL"):
            await hub.download(entry, tmp_path)


# ---------------------------------------------------------------------------
# PackHub cache persistence tests
# ---------------------------------------------------------------------------


class TestPackHubCache:
    """PackHub cache save/load from disk."""

    async def test_refresh_cache_saves_to_disk(self, tmp_path: Path) -> None:
        """refresh_cache persists entries to local_cache_path."""
        cache_path = tmp_path / "cache.json"
        config = PackHubConfig(local_cache_path=cache_path)
        hub = PackHub(config=config)

        payload = PackRegistryPayload(
            schema_version="1",
            updated_at="2026-04-05T00:00:00Z",
            packs=_SAMPLE_ENTRIES,
        )

        mock_response = AsyncMock()
        mock_response.json = MagicMock(return_value=payload.model_dump())
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agent33.packs.hub.httpx.AsyncClient", return_value=mock_client):
            await hub.refresh_cache()

        assert cache_path.is_file()
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        assert len(data["packs"]) == 3

    def test_list_cached_loads_from_disk(self, tmp_path: Path) -> None:
        """list_cached loads entries from disk when in-memory cache is empty."""
        cache_path = tmp_path / "cache.json"
        payload = PackRegistryPayload(
            schema_version="1",
            updated_at="2026-04-05T00:00:00Z",
            packs=_SAMPLE_ENTRIES[:1],
        )
        cache_path.write_text(
            json.dumps(payload.model_dump(), default=str),
            encoding="utf-8",
        )

        config = PackHubConfig(local_cache_path=cache_path)
        hub = PackHub(config=config)

        entries = hub.list_cached()
        assert len(entries) == 1
        assert entries[0].name == "code-review"


# ---------------------------------------------------------------------------
# PackSharingService tests
# ---------------------------------------------------------------------------


class TestPackSharingServiceExtract:
    """PackSharingService.extract_share_requests() scanning."""

    def test_extract_top_level_pack_ref(self) -> None:
        """Finds pack_ref at the top level of inputs."""
        registry = _make_registry()
        svc = PackSharingService(registry)

        inputs = {"pack_ref": "my-pack", "reason": "useful for coding"}
        reqs = svc.extract_share_requests(inputs)
        assert len(reqs) == 1
        assert reqs[0].pack_ref == "my-pack"
        assert reqs[0].reason == "useful for coding"

    def test_extract_nested_pack_ref(self) -> None:
        """Finds pack_ref in a nested dict."""
        registry = _make_registry()
        svc = PackSharingService(registry)

        inputs = {
            "agent_output": {
                "recommendation": {
                    "pack_ref": "security-pack",
                    "reason": "needs scanning",
                },
            },
        }
        reqs = svc.extract_share_requests(inputs)
        assert len(reqs) == 1
        assert reqs[0].pack_ref == "security-pack"

    def test_extract_pack_refs_list(self) -> None:
        """Finds pack_refs list of strings."""
        registry = _make_registry()
        svc = PackSharingService(registry)

        inputs = {"pack_refs": ["pack-a", "pack-b"]}
        reqs = svc.extract_share_requests(inputs)
        assert len(reqs) == 2
        names = {r.pack_ref for r in reqs}
        assert names == {"pack-a", "pack-b"}

    def test_extract_pack_refs_list_of_dicts(self) -> None:
        """Finds pack_refs list of dict entries."""
        registry = _make_registry()
        svc = PackSharingService(registry)

        inputs = {
            "pack_refs": [
                {"pack_ref": "pack-a", "reason": "alpha"},
                {"pack_ref": "pack-b", "reason": "beta"},
            ]
        }
        reqs = svc.extract_share_requests(inputs)
        assert len(reqs) == 2
        assert reqs[0].pack_ref == "pack-a"
        assert reqs[0].reason == "alpha"

    def test_extract_empty_inputs(self) -> None:
        """Returns empty list when no pack_ref keys exist."""
        registry = _make_registry()
        svc = PackSharingService(registry)

        reqs = svc.extract_share_requests({"message": "hello", "data": 42})
        assert reqs == []

    def test_extract_from_list_of_dicts_in_values(self) -> None:
        """Finds pack_ref inside a list of dicts nested in values."""
        registry = _make_registry()
        svc = PackSharingService(registry)

        inputs = {
            "steps": [
                {"step": 1, "pack_ref": "step-pack"},
                {"step": 2, "name": "no-ref"},
            ]
        }
        reqs = svc.extract_share_requests(inputs)
        assert len(reqs) == 1
        assert reqs[0].pack_ref == "step-pack"


class TestPackSharingServiceApply:
    """PackSharingService.apply_shares() enables packs."""

    def test_apply_enables_installed_pack(self) -> None:
        """Installed packs are enabled for the session."""
        pack = _make_installed_pack("my-pack")
        registry = _make_registry([pack])
        svc = PackSharingService(registry)

        requests = [PackShareRequest(pack_ref="my-pack", reason="agent A recommends")]
        applied = svc.apply_shares(requests, "sess-001")

        assert applied == ["my-pack"]
        assert len(registry.get_session_packs("sess-001")) == 1

    def test_apply_skips_missing_pack(self) -> None:
        """Packs not installed are skipped (no error)."""
        registry = _make_registry([])
        svc = PackSharingService(registry)

        requests = [PackShareRequest(pack_ref="ghost-pack")]
        applied = svc.apply_shares(requests, "sess-001")

        assert applied == []

    def test_apply_multiple_packs(self) -> None:
        """Multiple packs can be applied in one call."""
        p1 = _make_installed_pack("alpha")
        p2 = _make_installed_pack("beta")
        registry = _make_registry([p1, p2])
        svc = PackSharingService(registry)

        requests = [
            PackShareRequest(pack_ref="alpha", reason="for code"),
            PackShareRequest(pack_ref="beta", reason="for tests"),
            PackShareRequest(pack_ref="ghost", reason="not installed"),
        ]
        applied = svc.apply_shares(requests, "sess-002")

        assert set(applied) == {"alpha", "beta"}
        session_packs = registry.get_session_packs("sess-002")
        assert len(session_packs) == 2


# ---------------------------------------------------------------------------
# PackRegistry.check_for_updates() tests
# ---------------------------------------------------------------------------


class TestRegistryCheckForUpdates:
    """PackRegistry.check_for_updates() compares installed vs hub versions."""

    async def test_returns_updates_when_hub_has_newer(self) -> None:
        """Packs with newer hub versions appear in update list."""
        pack = _make_installed_pack("code-review", version="1.0.0")
        registry = _make_registry([pack])

        # Hub has version 2.0.0
        hub = _make_hub()

        updates = await registry.check_for_updates(hub)
        assert len(updates) == 1
        installed, hub_entry = updates[0]
        assert installed.name == "code-review"
        assert installed.version == "1.0.0"
        assert hub_entry.version == "2.0.0"

    async def test_returns_empty_when_up_to_date(self) -> None:
        """No updates when installed version matches hub."""
        pack = _make_installed_pack("code-review", version="2.0.0")
        registry = _make_registry([pack])

        hub = _make_hub()

        updates = await registry.check_for_updates(hub)
        assert len(updates) == 0

    async def test_skips_packs_not_in_hub(self) -> None:
        """Packs not found in the hub are skipped."""
        pack = _make_installed_pack("my-private-pack", version="1.0.0")
        registry = _make_registry([pack])

        hub = _make_hub()

        updates = await registry.check_for_updates(hub)
        assert len(updates) == 0

    async def test_skips_invalid_version_strings(self) -> None:
        """Packs with non-semver versions are skipped without error."""
        pack = _make_installed_pack("code-review", version="latest")
        registry = _make_registry([pack])

        hub = _make_hub()

        updates = await registry.check_for_updates(hub)
        assert len(updates) == 0


# ---------------------------------------------------------------------------
# invoke_agent pack sharing integration
# ---------------------------------------------------------------------------


class TestInvokeAgentPackSharing:
    """invoke_agent.execute() applies pack sharing."""

    async def test_execute_applies_pack_shares(self) -> None:
        """Pack refs in inputs are shared before agent invocation."""
        from agent33.workflows.actions import invoke_agent

        pack = _make_installed_pack("shared-pack")
        registry = _make_registry([pack])
        svc = PackSharingService(registry)

        # Wire up
        old_service = invoke_agent._pack_sharing_service
        old_registry = invoke_agent._agent_registry
        try:
            invoke_agent._pack_sharing_service = svc

            async def fake_handler(inputs: dict[str, Any]) -> dict[str, Any]:
                return {"status": "done"}

            invoke_agent._agent_registry["test-agent"] = fake_handler

            result = await invoke_agent.execute(
                "test-agent",
                {
                    "pack_ref": "shared-pack",
                    "session_id": "sess-share-01",
                    "message": "hello",
                },
            )
            assert result == {"status": "done"}

            # The pack should be enabled for the session
            session_packs = registry.get_session_packs("sess-share-01")
            assert len(session_packs) == 1
            assert session_packs[0].name == "shared-pack"
        finally:
            invoke_agent._pack_sharing_service = old_service
            invoke_agent._agent_registry = old_registry

    async def test_execute_works_without_sharing_service(self) -> None:
        """Agent invocation works when sharing service is not wired."""
        from agent33.workflows.actions import invoke_agent

        old_service = invoke_agent._pack_sharing_service
        old_registry = invoke_agent._agent_registry
        try:
            invoke_agent._pack_sharing_service = None

            async def fake_handler(inputs: dict[str, Any]) -> dict[str, Any]:
                return {"ok": True}

            invoke_agent._agent_registry["basic-agent"] = fake_handler

            result = await invoke_agent.execute("basic-agent", {"message": "test"})
            assert result == {"ok": True}
        finally:
            invoke_agent._pack_sharing_service = old_service
            invoke_agent._agent_registry = old_registry

    def test_set_pack_sharing_service_wiring(self) -> None:
        """set_pack_sharing_service stores the service on the module."""
        from agent33.workflows.actions import invoke_agent

        old = invoke_agent._pack_sharing_service
        try:
            mock_svc = MagicMock()
            invoke_agent.set_pack_sharing_service(mock_svc)
            assert invoke_agent._pack_sharing_service is mock_svc
        finally:
            invoke_agent._pack_sharing_service = old


# ---------------------------------------------------------------------------
# CLI tests (P-PACK v2)
# ---------------------------------------------------------------------------


class TestCLISearch:
    """CLI packs search command."""

    def test_search_shows_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Search command calls hub API and prints results."""
        import httpx
        from typer.testing import CliRunner

        from agent33.cli.main import app

        class FakeResponse:
            status_code = 200

            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict[str, Any]:
                return {
                    "results": [
                        {
                            "name": "code-review",
                            "version": "2.0.0",
                            "description": "Code review pack",
                            "tags": ["review"],
                        },
                    ],
                    "count": 1,
                    "query": "code",
                }

        captured_urls: list[str] = []

        def mock_get(url: str, **kwargs: Any) -> FakeResponse:
            captured_urls.append(url)
            return FakeResponse()

        monkeypatch.setattr(httpx, "get", mock_get)

        runner = CliRunner()
        result = runner.invoke(app, ["packs", "search", "code"])
        assert result.exit_code == 0
        assert "code-review" in result.output
        assert "v2.0.0" in result.output
        assert any("/hub/search" in u for u in captured_urls)

    def test_search_no_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Search command with no results prints message."""
        import httpx
        from typer.testing import CliRunner

        from agent33.cli.main import app

        class FakeResponse:
            status_code = 200

            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict[str, Any]:
                return {"results": [], "count": 0, "query": "xyz"}

        monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResponse())

        runner = CliRunner()
        result = runner.invoke(app, ["packs", "search", "xyz"])
        assert result.exit_code == 0
        assert "No packs found" in result.output

    def test_search_json_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Search command supports machine-readable JSON output."""
        import httpx
        from typer.testing import CliRunner

        from agent33.cli.main import app

        class FakeResponse:
            status_code = 200

            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict[str, Any]:
                return {
                    "results": [
                        {
                            "name": "code-review",
                            "version": "2.0.0",
                            "description": "Code review pack",
                            "tags": ["review"],
                        }
                    ],
                    "count": 1,
                    "query": "code",
                }

        monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResponse())

        runner = CliRunner()
        result = runner.invoke(app, ["packs", "search", "code", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["count"] == 1
        assert payload["results"][0]["name"] == "code-review"

    def test_search_plain_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Search command supports compact plain output."""
        import httpx
        from typer.testing import CliRunner

        from agent33.cli.main import app

        class FakeResponse:
            status_code = 200

            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict[str, Any]:
                return {
                    "results": [
                        {
                            "name": "code-review",
                            "version": "2.0.0",
                            "description": "Code review pack",
                            "tags": ["review", "security"],
                        }
                    ],
                    "count": 1,
                    "query": "code",
                }

        monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResponse())

        runner = CliRunner()
        result = runner.invoke(app, ["packs", "search", "code", "--plain"])
        assert result.exit_code == 0
        assert result.output.strip() == "code-review\t2.0.0\tCode review pack\treview,security"

    def test_search_rejects_conflicting_output_flags(self) -> None:
        """Search command rejects --json and --plain together."""
        from typer.testing import CliRunner

        from agent33.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["packs", "search", "code", "--json", "--plain"])
        assert result.exit_code != 0
        assert "Use only one of --json or --plain" in result.output


class TestCLIInstall:
    """CLI packs install command."""

    def test_install_prints_entry_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Install command fetches entry and prints details."""
        import httpx
        from typer.testing import CliRunner

        from agent33.cli.main import app

        call_count = 0

        class GetResponse:
            status_code = 200

            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict[str, Any]:
                return {
                    "entry": {
                        "name": "cool-pack",
                        "version": "1.0.0",
                        "description": "A cool pack",
                        "author": "dev",
                    }
                }

        class PostResponse:
            status_code = 201

            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict[str, Any]:
                return {
                    "success": True,
                    "pack_name": "cool-pack",
                    "version": "1.0.0",
                    "skills_loaded": 2,
                }

        def mock_get(url: str, **kwargs: Any) -> GetResponse:
            nonlocal call_count
            call_count += 1
            return GetResponse()

        def mock_post(url: str, **kwargs: Any) -> PostResponse:
            return PostResponse()

        monkeypatch.setattr(httpx, "get", mock_get)
        monkeypatch.setattr(httpx, "post", mock_post)

        runner = CliRunner()
        result = runner.invoke(app, ["packs", "install", "cool-pack"])
        assert result.exit_code == 0
        assert "Found: cool-pack v1.0.0" in result.output
        assert "Installed:" in result.output


class TestCLIPublish:
    """CLI packs publish command."""

    def test_publish_validates_and_prints_template(self, tmp_path: Path) -> None:
        """Publish validates pack and prints PR template."""
        import textwrap

        from typer.testing import CliRunner

        from agent33.cli.main import app

        pack_dir = tmp_path / "my-pack"
        pack_dir.mkdir()
        (pack_dir / "PACK.yaml").write_text(
            textwrap.dedent("""\
                schema_version: "1"
                name: my-pack
                version: "1.0.0"
                description: "A publishable pack"
                author: dev
                skills:
                  - name: skill-a
                    path: skills/a
            """),
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(app, ["packs", "publish", str(pack_dir)])
        assert result.exit_code == 0
        assert "validated successfully" in result.output
        assert "agent33-pack-registry" in result.output
        assert "registry.json" in result.output


# ---------------------------------------------------------------------------
# Hub API route tests
# ---------------------------------------------------------------------------


class TestHubAPIRoutes:
    """API routes for hub search and entry lookup."""

    async def test_hub_search_returns_results(self) -> None:
        """GET /v1/packs/hub/search returns matching entries."""
        from unittest.mock import patch as sync_patch

        from agent33.api.routes.packs import hub_search

        mock_hub = MagicMock()
        mock_hub.search = AsyncMock(return_value=_SAMPLE_ENTRIES[:1])

        mock_request = MagicMock()
        mock_request.app.state.pack_hub = mock_hub

        with sync_patch(
            "agent33.api.routes.packs._get_pack_hub",
            return_value=mock_hub,
        ):
            result = await hub_search(mock_request, q="code", tags="", limit=10)

        assert result["count"] == 1
        assert result["results"][0]["name"] == "code-review"
        assert result["query"] == "code"

    async def test_hub_search_no_hub_returns_empty(self) -> None:
        """GET /v1/packs/hub/search returns empty when hub is None."""
        from agent33.api.routes.packs import hub_search

        mock_request = MagicMock()
        mock_request.app.state = MagicMock(spec=[])  # no pack_hub attribute

        result = await hub_search(mock_request, q="anything", tags="", limit=10)
        assert result["results"] == []
        assert result["count"] == 0

    async def test_hub_get_entry_returns_entry(self) -> None:
        """GET /v1/packs/hub/entry/{name} returns matching entry."""
        from unittest.mock import patch as sync_patch

        from agent33.api.routes.packs import hub_get_entry

        mock_hub = MagicMock()
        mock_hub.get = AsyncMock(return_value=_SAMPLE_ENTRIES[1])

        mock_request = MagicMock()
        mock_request.app.state.pack_hub = mock_hub

        with sync_patch(
            "agent33.api.routes.packs._get_pack_hub",
            return_value=mock_hub,
        ):
            result = await hub_get_entry("security-scan", mock_request)

        assert result["entry"]["name"] == "security-scan"
        assert result["entry"]["version"] == "1.5.0"

    async def test_hub_get_entry_not_found(self) -> None:
        """GET /v1/packs/hub/entry/{name} returns 404 for unknown pack."""
        from unittest.mock import patch as sync_patch

        from fastapi import HTTPException

        from agent33.api.routes.packs import hub_get_entry

        mock_hub = MagicMock()
        mock_hub.get = AsyncMock(return_value=None)

        mock_request = MagicMock()
        mock_request.app.state.pack_hub = mock_hub

        with (
            sync_patch(
                "agent33.api.routes.packs._get_pack_hub",
                return_value=mock_hub,
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await hub_get_entry("unknown-pack", mock_request)

        assert exc_info.value.status_code == 404

    async def test_hub_get_entry_no_hub_returns_503(self) -> None:
        """GET /v1/packs/hub/entry/{name} returns 503 when hub is None."""
        from fastapi import HTTPException

        from agent33.api.routes.packs import hub_get_entry

        mock_request = MagicMock()
        mock_request.app.state = MagicMock(spec=[])

        with pytest.raises(HTTPException) as exc_info:
            await hub_get_entry("any-pack", mock_request)

        assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# PackHubEntry model tests
# ---------------------------------------------------------------------------


class TestPackHubEntryModel:
    """PackHubEntry Pydantic model validation."""

    def test_defaults(self) -> None:
        """Defaults are populated correctly."""
        entry = PackHubEntry(name="test", version="1.0.0")
        assert entry.tags == []
        assert entry.install_count == 0
        assert entry.rating == 0.0
        assert entry.sha256 == ""
        assert entry.download_url == ""

    def test_full_entry(self) -> None:
        """All fields can be set."""
        entry = PackHubEntry(
            name="full",
            version="2.0.0",
            description="Full entry",
            author="author",
            tags=["tag1", "tag2"],
            download_url="https://example.com/pack.yaml",
            sha256="abcdef",
            install_count=42,
            rating=4.5,
        )
        assert entry.name == "full"
        assert entry.rating == 4.5
        assert len(entry.tags) == 2
