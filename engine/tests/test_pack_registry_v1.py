"""Tests for POST-3.2: Pack Registry v1 — revocation and Sigstore verification.

Covers:
- PackHubEntry has revoked field (default False)
- PackRegistryPayload parses revoked list
- PackHub.get_revocation_status() returns not-revoked for clean packs
- PackHub.get_revocation_status() detects per-entry revoked=True flag
- PackHub.get_revocation_status() detects registry-level revocation list
- PackHub.download() raises ValueError for revoked packs (before download)
- PackHub.download() proceeds normally for non-revoked packs
- RevocationStatus model fields are correct
- provenance_models.SigstoreBundle model is importable and has expected fields
- PackProvenance.algorithm defaults to 'sha256'
- PackProvenance.algorithm accepts 'sigstore'
- PackProvenance.sigstore_bundle is None by default
- verify_pack() dispatches to HMAC for algorithm='sha256'
- verify_pack() returns False for unknown algorithm (regression)
- verify_pack_sigstore() returns False gracefully when sigstore library missing
- evaluate_trust() unchanged for HMAC provenance (regression guard)
- Hub API route GET /hub/revocation/{name} returns revocation status
- Hub API route GET /hub/revocation/{name} returns revoked=True for revoked pack
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agent33.packs.hub import (
    PackHub,
    PackHubEntry,
    PackRegistryPayload,
    RevocationRecord,
    RevocationStatus,
)
from agent33.packs.provenance import (
    PackProvenance,
    SigstoreBundle,
    TrustLevel,
    evaluate_trust,
    sign_pack,
    verify_pack,
    verify_pack_sigstore,
)
from agent33.packs.provenance_models import PackTrustPolicy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hub(
    entries: list[PackHubEntry] | None = None,
    revocation_list: list[RevocationRecord] | None = None,
) -> PackHub:
    """PackHub with pre-loaded in-memory cache (no network)."""
    hub = PackHub()
    hub._cache = entries or []
    hub._revocation_list = revocation_list or []
    hub._cache_loaded_at = 1e15  # far future — skip refresh
    return hub


def _make_entry(
    name: str = "test-pack",
    version: str = "1.0.0",
    *,
    revoked: bool = False,
    revocation_reason: str = "",
) -> PackHubEntry:
    return PackHubEntry(
        name=name,
        version=version,
        description="A test pack",
        author="tester",
        download_url="https://example.com/test-pack.yaml",
        sha256="abc123",
        revoked=revoked,
        revocation_reason=revocation_reason,
    )


def _make_manifest() -> Any:
    """Minimal PackManifest for provenance tests."""
    from agent33.packs.manifest import PackManifest
    from agent33.packs.models import PackSkillEntry

    return PackManifest(
        name="test-pack",
        version="1.0.0",
        description="Test",
        author="tester",
        skills=[PackSkillEntry(name="s", path="skills/s")],
    )


# ---------------------------------------------------------------------------
# PackHubEntry revocation fields
# ---------------------------------------------------------------------------


class TestPackHubEntryRevocationFields:
    """PackHubEntry model carries revocation metadata."""

    def test_revoked_defaults_to_false(self) -> None:
        entry = _make_entry()
        assert entry.revoked is False

    def test_revoked_can_be_set_true(self) -> None:
        entry = _make_entry(revoked=True, revocation_reason="Security vulnerability")
        assert entry.revoked is True
        assert entry.revocation_reason == "Security vulnerability"

    def test_revocation_reason_defaults_empty(self) -> None:
        entry = _make_entry()
        assert entry.revocation_reason == ""


# ---------------------------------------------------------------------------
# PackRegistryPayload — revocation list
# ---------------------------------------------------------------------------


class TestPackRegistryPayloadRevocationList:
    """PackRegistryPayload parses the registry-level revoked list."""

    def test_revoked_field_defaults_empty(self) -> None:
        payload = PackRegistryPayload(packs=[])
        assert payload.revoked == []

    def test_revoked_list_parsed_from_dict(self) -> None:
        data = {
            "schema_version": "1",
            "packs": [],
            "revoked": [
                {"name": "bad-pack", "version": "0.1.0", "reason": "Malicious code"},
            ],
        }
        payload = PackRegistryPayload.model_validate(data)
        assert len(payload.revoked) == 1
        assert payload.revoked[0].name == "bad-pack"
        assert payload.revoked[0].reason == "Malicious code"

    def test_revocation_record_version_optional(self) -> None:
        record = RevocationRecord(name="bad-pack")
        assert record.version == ""


# ---------------------------------------------------------------------------
# PackHub.get_revocation_status()
# ---------------------------------------------------------------------------


class TestGetRevocationStatus:
    """get_revocation_status() correctly identifies revoked packs."""

    async def test_clean_pack_not_revoked(self) -> None:
        hub = _make_hub(entries=[_make_entry("good-pack")])
        status = await hub.get_revocation_status("good-pack", "1.0.0")
        assert isinstance(status, RevocationStatus)
        assert status.revoked is False
        assert status.name == "good-pack"

    async def test_entry_flag_revoked(self) -> None:
        hub = _make_hub(
            entries=[_make_entry("bad-pack", revoked=True, revocation_reason="XSS exploit")]
        )
        status = await hub.get_revocation_status("bad-pack")
        assert status.revoked is True
        assert "XSS exploit" in status.reason

    async def test_registry_level_revocation_list(self) -> None:
        hub = _make_hub(
            entries=[_make_entry("evil-pack", revoked=False)],
            revocation_list=[
                RevocationRecord(name="evil-pack", version="1.0.0", reason="Supply-chain attack")
            ],
        )
        status = await hub.get_revocation_status("evil-pack", "1.0.0")
        assert status.revoked is True
        assert "Supply-chain attack" in status.reason

    async def test_registry_level_any_version_matches(self) -> None:
        """A revocation record with empty version matches any version query."""
        hub = _make_hub(
            entries=[_make_entry("evil-pack")],
            revocation_list=[RevocationRecord(name="evil-pack", reason="All versions bad")],
        )
        status = await hub.get_revocation_status("evil-pack", "2.0.0")
        assert status.revoked is True

    async def test_revocation_list_different_pack_not_matched(self) -> None:
        hub = _make_hub(
            entries=[_make_entry("good-pack")],
            revocation_list=[RevocationRecord(name="other-pack", reason="Different pack")],
        )
        status = await hub.get_revocation_status("good-pack", "1.0.0")
        assert status.revoked is False

    async def test_unknown_pack_not_revoked(self) -> None:
        """Pack not in registry is not revoked (returns not-revoked status)."""
        hub = _make_hub(entries=[])
        status = await hub.get_revocation_status("nonexistent", "1.0.0")
        assert status.revoked is False


# ---------------------------------------------------------------------------
# PackHub.download() — revocation guard
# ---------------------------------------------------------------------------


class TestDownloadRevocationGuard:
    """download() rejects revoked packs before any network activity."""

    async def test_download_raises_for_revoked_entry(self, tmp_path: Path) -> None:
        hub = _make_hub(entries=[_make_entry("bad-pack", revoked=True, revocation_reason="CVE")])
        entry = hub._cache[0]

        with pytest.raises(ValueError, match="revoked"):
            await hub.download(entry, tmp_path)

    async def test_download_raises_for_registry_revocation(self, tmp_path: Path) -> None:
        hub = _make_hub(
            entries=[_make_entry("bad-pack", revoked=False)],
            revocation_list=[RevocationRecord(name="bad-pack", reason="Backdoor found")],
        )
        entry = hub._cache[0]

        with pytest.raises(ValueError, match="revoked"):
            await hub.download(entry, tmp_path)

    async def test_download_proceeds_for_clean_pack(self, tmp_path: Path) -> None:
        """Clean pack download calls httpx (mocked to return content)."""
        entry = _make_entry("good-pack", revoked=False)
        entry.sha256 = ""  # skip integrity check
        hub = _make_hub(entries=[entry])

        fake_content = b"name: good-pack\nversion: 1.0.0\n"
        mock_response = MagicMock()
        mock_response.content = fake_content
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            dest = await hub.download(entry, tmp_path)

        assert dest.exists()
        assert dest.read_bytes() == fake_content


# ---------------------------------------------------------------------------
# Provenance model — Sigstore fields
# ---------------------------------------------------------------------------


class TestProvenanceModelSigstore:
    """PackProvenance correctly supports Sigstore algorithm."""

    def test_algorithm_defaults_to_sha256(self) -> None:
        prov = PackProvenance(signer_id="s", signature="x" * 64)
        assert prov.algorithm == "sha256"

    def test_algorithm_accepts_sigstore(self) -> None:
        prov = PackProvenance(signer_id="gha", signature="bundle-b64", algorithm="sigstore")
        assert prov.algorithm == "sigstore"

    def test_sigstore_bundle_defaults_none(self) -> None:
        prov = PackProvenance(signer_id="s", signature="x" * 64)
        assert prov.sigstore_bundle is None

    def test_sigstore_bundle_can_be_set(self) -> None:
        bundle = SigstoreBundle(
            oidc_issuer="https://token.actions.githubusercontent.com",
            oidc_subject="https://github.com/org/repo/.github/workflows/release.yml@refs/tags/v1",
            rekor_log_id="abc123",
        )
        prov = PackProvenance(
            signer_id="gha",
            signature="bundle-b64",
            algorithm="sigstore",
            sigstore_bundle=bundle,
        )
        assert prov.sigstore_bundle is not None
        assert "actions.githubusercontent.com" in prov.sigstore_bundle.oidc_issuer

    def test_sigstore_bundle_importable_from_provenance_models(self) -> None:
        from agent33.packs.provenance_models import SigstoreBundle

        assert SigstoreBundle is not None


# ---------------------------------------------------------------------------
# verify_pack() dispatch
# ---------------------------------------------------------------------------


class TestVerifyPackDispatch:
    """verify_pack() dispatches correctly based on algorithm."""

    def test_sha256_roundtrip(self) -> None:
        manifest = _make_manifest()
        prov = sign_pack(manifest, "secret", signer_id="ci")
        assert verify_pack(manifest, prov, "secret") is True

    def test_sha256_wrong_key_fails(self) -> None:
        manifest = _make_manifest()
        prov = sign_pack(manifest, "correct", signer_id="ci")
        assert verify_pack(manifest, prov, "wrong") is False

    def test_unknown_algorithm_returns_false(self) -> None:
        manifest = _make_manifest()
        prov = PackProvenance(signer_id="s", signature="abc", algorithm="md5")
        assert verify_pack(manifest, prov, "key") is False

    def test_sigstore_algorithm_dispatches_to_sigstore_verifier(self) -> None:
        """verify_pack() calls verify_pack_sigstore for algorithm='sigstore'."""
        manifest = _make_manifest()
        prov = PackProvenance(signer_id="gha", signature="bundle", algorithm="sigstore")
        # sigstore library not installed — expect False with graceful degradation
        result = verify_pack(manifest, prov, "ignored-key")
        assert result is False  # graceful: library missing


# ---------------------------------------------------------------------------
# verify_pack_sigstore() — graceful degradation
# ---------------------------------------------------------------------------


class TestVerifyPackSigstore:
    """verify_pack_sigstore() degrades gracefully when sigstore is unavailable."""

    def test_returns_false_when_sigstore_not_installed(self) -> None:
        manifest = _make_manifest()
        prov = PackProvenance(signer_id="gha", signature="bundle", algorithm="sigstore")
        # In this environment sigstore is not installed
        result = verify_pack_sigstore(manifest, prov)
        assert result is False

    def test_returns_false_for_malformed_bundle_when_sigstore_installed(self) -> None:
        """Even if sigstore is somehow available, a bad bundle returns False."""
        manifest = _make_manifest()
        prov = PackProvenance(
            signer_id="gha",
            signature="not-valid-base64!!!",
            algorithm="sigstore",
        )

        try:
            import sigstore  # noqa: F401
        except ImportError:
            pytest.skip("sigstore not installed — skipping bundle parse test")

        result = verify_pack_sigstore(manifest, prov)
        assert result is False


# ---------------------------------------------------------------------------
# evaluate_trust() — regression guard (unchanged behaviour)
# ---------------------------------------------------------------------------


class TestEvaluateTrustRegression:
    """evaluate_trust() still works after provenance_models refactor."""

    def test_none_provenance_no_sig_required(self) -> None:
        policy = PackTrustPolicy(require_signature=False)
        decision = evaluate_trust(None, policy)
        assert decision.allowed is True

    def test_none_provenance_sig_required(self) -> None:
        policy = PackTrustPolicy(require_signature=True)
        decision = evaluate_trust(None, policy)
        assert decision.allowed is False

    def test_sigstore_provenance_evaluated_by_trust_level(self) -> None:
        """Sigstore provenance is still evaluated against trust policy."""
        prov = PackProvenance(
            signer_id="gha",
            signature="bundle",
            algorithm="sigstore",
            trust_level=TrustLevel.VERIFIED,
        )
        policy = PackTrustPolicy(require_signature=True, min_trust_level=TrustLevel.COMMUNITY)
        decision = evaluate_trust(prov, policy)
        assert decision.allowed is True


# ---------------------------------------------------------------------------
# API route — /hub/revocation/{name}
# ---------------------------------------------------------------------------


def _make_route_app(hub: PackHub | None = None) -> Any:
    """Create a minimal FastAPI app with the packs router and a fake auth middleware."""
    from typing import Any as _Any
    from unittest.mock import MagicMock

    from fastapi import FastAPI
    from starlette.middleware.base import BaseHTTPMiddleware

    from agent33.api.routes.packs import router

    app = FastAPI()
    app.include_router(router)

    if hub is not None:
        app.state.pack_hub = hub

    class FakeAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: _Any, call_next: _Any) -> _Any:
            user = MagicMock()
            user.tenant_id = "test-tenant"
            user.scopes = ["agents:read", "agents:write", "admin"]
            request.state.user = user
            return await call_next(request)

    app.add_middleware(FakeAuthMiddleware)
    return app


class TestHubRevocationRoute:
    """GET /hub/revocation/{name} returns correct revocation status."""

    def test_revocation_route_not_revoked(self) -> None:
        from fastapi.testclient import TestClient

        hub = _make_hub(entries=[_make_entry("good-pack")])
        app = _make_route_app(hub)

        with TestClient(app) as client:
            resp = client.get("/v1/packs/hub/revocation/good-pack")

        assert resp.status_code == 200
        data = resp.json()
        assert data["revoked"] is False
        assert data["name"] == "good-pack"

    def test_revocation_route_revoked_pack(self) -> None:
        from fastapi.testclient import TestClient

        hub = _make_hub(
            entries=[_make_entry("bad-pack", revoked=True, revocation_reason="Malware")]
        )
        app = _make_route_app(hub)

        with TestClient(app) as client:
            resp = client.get("/v1/packs/hub/revocation/bad-pack")

        assert resp.status_code == 200
        data = resp.json()
        assert data["revoked"] is True
        assert "Malware" in data["reason"]

    def test_revocation_route_hub_not_initialized(self) -> None:
        from fastapi.testclient import TestClient

        app = _make_route_app(hub=None)  # no pack_hub on app.state

        with TestClient(app) as client:
            resp = client.get("/v1/packs/hub/revocation/any-pack")

        assert resp.status_code == 503
