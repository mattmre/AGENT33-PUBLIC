from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent33.resources.manifest import ResourceKind, ResourceManifest, validate_resource_manifest


def test_resource_manifest_validates_minimal_payload() -> None:
    manifest = validate_resource_manifest(
        {
            "id": "pack.safe-ops",
            "name": "Safe Ops Pack",
            "version": "1.0.0",
            "kind": "pack",
        }
    )

    assert manifest.kind == ResourceKind.PACK
    assert manifest.rollback.supported is True
    assert manifest.permissions == []


def test_resource_manifest_normalizes_tags() -> None:
    manifest = ResourceManifest(
        id="skill.research",
        name="Research Skill",
        version="0.1.0",
        kind=ResourceKind.SKILL,
        tags=["Research", " research ", "Evidence"],
    )

    assert manifest.tags == ["evidence", "research"]


def test_resource_manifest_models_permissions_and_trust() -> None:
    manifest = validate_resource_manifest(
        {
            "id": "plugin.github",
            "name": "GitHub Plugin",
            "version": "2.0.0",
            "kind": "plugin",
            "permissions": [{"scope": "github:write", "reason": "Post PR comments"}],
            "trust": {
                "publisher": "agent33",
                "source_url": "https://example.invalid/plugin",
                "sha256": "abc123",
                "verified": True,
            },
        }
    )

    assert manifest.permissions[0].scope == "github:write"
    assert manifest.trust.verified is True
    assert manifest.trust.publisher == "agent33"


def test_resource_manifest_rejects_blank_required_fields() -> None:
    with pytest.raises(ValidationError):
        ResourceManifest(id=" ", name="Resource", version="1.0.0", kind=ResourceKind.PACK)
