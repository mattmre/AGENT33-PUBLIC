"""Tests for remote pack marketplace sources."""

from __future__ import annotations

import json
import textwrap
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from agent33.packs.remote_marketplace import (
    RemoteMarketplaceConfig,
    RemotePackIndex,
    RemotePackMarketplace,
)


def _write_pack(base: Path, *, name: str, version: str) -> Path:
    pack_dir = base / f"{name}-{version}"
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "PACK.yaml").write_text(
        textwrap.dedent(
            f"""\
            name: {name}
            version: {version}
            description: Pack {name}
            author: tester
            skills:
              - name: skill-1
                path: skills/skill-1
            """
        ),
        encoding="utf-8",
    )
    skill_dir = pack_dir / "skills" / "skill-1"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: skill-1\ndescription: Skill\n---\n# Skill\n",
        encoding="utf-8",
    )
    return pack_dir


def _zip_pack(pack_dir: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w") as archive:
        for path in pack_dir.rglob("*"):
            archive.write(path, arcname=str(Path(pack_dir.name) / path.relative_to(pack_dir)))


def _write_index(tmp_path: Path, packs_data: list[dict]) -> Path:
    """Write a JSON index file and return its path."""
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps({"packs": packs_data}),
        encoding="utf-8",
    )
    return index_path


def test_remote_marketplace_lists_and_resolves_pack(tmp_path: Path) -> None:
    pack_dir = _write_pack(tmp_path / "packs", name="remote-pack", version="1.2.0")
    archive_path = tmp_path / "remote-pack-1.2.0.zip"
    _zip_pack(pack_dir, archive_path)
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "packs": [
                    {
                        "name": "remote-pack",
                        "description": "Remote pack",
                        "versions": [
                            {
                                "version": "1.2.0",
                                "download_url": archive_path.as_uri(),
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    marketplace = RemotePackMarketplace(
        RemoteMarketplaceConfig(name="community", index_url=index_path.as_uri()),
        cache_dir=tmp_path / "cache",
    )

    packs = marketplace.list_packs()
    assert [record.name for record in packs] == ["remote-pack"]
    assert packs[0].versions[0].source_name == "community"

    resolved = marketplace.resolve("remote-pack", "1.2.0")
    assert resolved is not None
    assert (resolved.pack_dir / "PACK.yaml").is_file()


def test_fetch_index_returns_correct_catalog(tmp_path: Path) -> None:
    """Fetching index from local file URI returns correctly parsed catalog."""
    pack_dir = _write_pack(tmp_path / "packs", name="idx-pack", version="3.0.0")
    archive_path = tmp_path / "idx-pack-3.0.0.zip"
    _zip_pack(pack_dir, archive_path)
    index_path = _write_index(
        tmp_path,
        [
            {
                "name": "idx-pack",
                "description": "Index test pack",
                "author": "test-author",
                "tags": ["devops"],
                "versions": [
                    {"version": "3.0.0", "download_url": archive_path.as_uri()},
                ],
            }
        ],
    )

    marketplace = RemotePackMarketplace(
        RemoteMarketplaceConfig(name="test-source", index_url=index_path.as_uri()),
        cache_dir=tmp_path / "cache",
    )
    packs = marketplace.list_packs()
    assert len(packs) == 1
    assert packs[0].name == "idx-pack"
    assert packs[0].description == "Index test pack"
    assert packs[0].latest_version == "3.0.0"
    assert packs[0].versions[0].source_name == "test-source"


def test_cache_ttl_stale_triggers_refresh(tmp_path: Path) -> None:
    """When the cached index exceeds TTL, a fresh fetch should occur."""
    index_path = _write_index(
        tmp_path,
        [
            {
                "name": "ttl-pack",
                "description": "TTL test",
                "versions": [
                    {"version": "1.0.0", "download_url": "file:///dummy.zip"},
                ],
            }
        ],
    )

    marketplace = RemotePackMarketplace(
        RemoteMarketplaceConfig(
            name="ttl-source",
            index_url=index_path.as_uri(),
            cache_ttl_seconds=60,
        ),
        cache_dir=tmp_path / "cache",
    )

    # First call populates cache
    packs_first = marketplace.list_packs()
    assert len(packs_first) == 1

    # Manually make the cached index stale
    assert marketplace._index is not None
    marketplace._index = RemotePackIndex(
        source="ttl-source",
        fetched_at=datetime.now(UTC) - timedelta(seconds=120),
        packs=marketplace._index.packs,
    )

    # Update the index file to include a second pack
    _write_index(
        tmp_path,
        [
            {
                "name": "ttl-pack",
                "description": "TTL test",
                "versions": [
                    {"version": "1.0.0", "download_url": "file:///dummy.zip"},
                ],
            },
            {
                "name": "new-pack",
                "description": "Added after TTL",
                "versions": [
                    {"version": "1.0.0", "download_url": "file:///dummy2.zip"},
                ],
            },
        ],
    )

    # Second call should refresh because the index is stale
    packs_second = marketplace.list_packs()
    assert len(packs_second) == 2
    names = {p.name for p in packs_second}
    assert "new-pack" in names


def test_search_by_name_returns_matching_packs(tmp_path: Path) -> None:
    """Search filters catalog by pack name substring."""
    index_path = _write_index(
        tmp_path,
        [
            {
                "name": "web-tools",
                "description": "Web tools",
                "versions": [{"version": "1.0.0", "download_url": "file:///a.zip"}],
            },
            {
                "name": "db-tools",
                "description": "Database tools",
                "versions": [{"version": "1.0.0", "download_url": "file:///b.zip"}],
            },
            {
                "name": "analytics-pack",
                "description": "Analytics",
                "versions": [{"version": "2.0.0", "download_url": "file:///c.zip"}],
            },
        ],
    )

    marketplace = RemotePackMarketplace(
        RemoteMarketplaceConfig(name="search-src", index_url=index_path.as_uri()),
        cache_dir=tmp_path / "cache",
    )

    results = marketplace.search("tools")
    assert len(results) == 2
    assert {r.name for r in results} == {"web-tools", "db-tools"}


def test_download_and_extract_pack(tmp_path: Path) -> None:
    """Download resolves to an extracted pack directory with PACK.yaml."""
    pack_dir = _write_pack(tmp_path / "packs", name="dl-pack", version="2.0.0")
    archive_path = tmp_path / "dl-pack-2.0.0.zip"
    _zip_pack(pack_dir, archive_path)
    index_path = _write_index(
        tmp_path,
        [
            {
                "name": "dl-pack",
                "description": "Download test",
                "versions": [
                    {"version": "2.0.0", "download_url": archive_path.as_uri()},
                ],
            }
        ],
    )

    marketplace = RemotePackMarketplace(
        RemoteMarketplaceConfig(name="dl-source", index_url=index_path.as_uri()),
        cache_dir=tmp_path / "cache",
    )

    resolved = marketplace.resolve("dl-pack", "2.0.0")
    assert resolved is not None
    assert resolved.version == "2.0.0"
    assert (resolved.pack_dir / "PACK.yaml").is_file()
    assert (resolved.pack_dir / "skills" / "skill-1" / "SKILL.md").is_file()


def test_malicious_zip_path_traversal_rejected(tmp_path: Path) -> None:
    """A zip archive with path-traversal entries should be rejected."""
    archive_path = tmp_path / "malicious.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("../../etc/passwd", "root:x:0:0:root:/root:/bin/bash")

    index_path = _write_index(
        tmp_path,
        [
            {
                "name": "evil-pack",
                "description": "Malicious",
                "versions": [
                    {"version": "1.0.0", "download_url": archive_path.as_uri()},
                ],
            }
        ],
    )

    marketplace = RemotePackMarketplace(
        RemoteMarketplaceConfig(name="evil-source", index_url=index_path.as_uri()),
        cache_dir=tmp_path / "cache",
    )

    with pytest.raises(ValueError, match="escapes target directory"):
        marketplace.resolve("evil-pack", "1.0.0")


def test_malicious_zip_absolute_path_rejected(tmp_path: Path) -> None:
    """A zip archive with absolute-path entries should be rejected."""
    archive_path = tmp_path / "absolute.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("C:/Windows/System32/drivers/etc/hosts", "127.0.0.1 localhost")

    index_path = _write_index(
        tmp_path,
        [
            {
                "name": "absolute-pack",
                "description": "Absolute path entry",
                "versions": [
                    {"version": "1.0.0", "download_url": archive_path.as_uri()},
                ],
            }
        ],
    )

    marketplace = RemotePackMarketplace(
        RemoteMarketplaceConfig(name="absolute-source", index_url=index_path.as_uri()),
        cache_dir=tmp_path / "cache",
    )

    with pytest.raises(ValueError, match="absolute path entry"):
        marketplace.resolve("absolute-pack", "1.0.0")


def test_malicious_zip_symlink_rejected(tmp_path: Path) -> None:
    """A zip archive with symlink entries should be rejected."""
    archive_path = tmp_path / "symlink.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        symlink_info = zipfile.ZipInfo("packs/link")
        symlink_info.create_system = 3
        symlink_info.external_attr = 0o120777 << 16
        zf.writestr(symlink_info, "target")

    index_path = _write_index(
        tmp_path,
        [
            {
                "name": "symlink-pack",
                "description": "Symlink entry",
                "versions": [
                    {"version": "1.0.0", "download_url": archive_path.as_uri()},
                ],
            }
        ],
    )

    marketplace = RemotePackMarketplace(
        RemoteMarketplaceConfig(name="symlink-source", index_url=index_path.as_uri()),
        cache_dir=tmp_path / "cache",
    )

    with pytest.raises(ValueError, match="symlink entry"):
        marketplace.resolve("symlink-pack", "1.0.0")


def test_http_error_graceful_handling(tmp_path: Path) -> None:
    """HTTP errors during index fetch should propagate as httpx exceptions."""
    marketplace = RemotePackMarketplace(
        RemoteMarketplaceConfig(
            name="http-err",
            index_url="http://localhost:19999/nonexistent-index.json",
        ),
        cache_dir=tmp_path / "cache",
    )

    # httpx will raise a connection error when connecting to a bad host/port
    with pytest.raises(httpx.ConnectError):
        marketplace.list_packs()


def test_empty_index_returns_empty_catalog(tmp_path: Path) -> None:
    """An index with no packs should produce an empty catalog without errors."""
    index_path = _write_index(tmp_path, [])

    marketplace = RemotePackMarketplace(
        RemoteMarketplaceConfig(name="empty-src", index_url=index_path.as_uri()),
        cache_dir=tmp_path / "cache",
    )

    packs = marketplace.list_packs()
    assert packs == []


def test_pack_version_listing_from_remote(tmp_path: Path) -> None:
    """list_versions returns all versions for a pack, ordered newest-first."""
    pack_v1 = _write_pack(tmp_path / "packs", name="ver-pack", version="1.0.0")
    pack_v2 = _write_pack(tmp_path / "packs2", name="ver-pack", version="2.0.0")
    archive_v1 = tmp_path / "ver-pack-1.0.0.zip"
    archive_v2 = tmp_path / "ver-pack-2.0.0.zip"
    _zip_pack(pack_v1, archive_v1)
    _zip_pack(pack_v2, archive_v2)

    index_path = _write_index(
        tmp_path,
        [
            {
                "name": "ver-pack",
                "description": "Versioned pack",
                "versions": [
                    {"version": "1.0.0", "download_url": archive_v1.as_uri()},
                    {"version": "2.0.0", "download_url": archive_v2.as_uri()},
                ],
            }
        ],
    )

    marketplace = RemotePackMarketplace(
        RemoteMarketplaceConfig(name="ver-source", index_url=index_path.as_uri()),
        cache_dir=tmp_path / "cache",
    )

    versions = marketplace.list_versions("ver-pack")
    assert len(versions) == 2
    assert versions[0].version == "2.0.0"  # newest first
    assert versions[1].version == "1.0.0"


def test_resolve_nonexistent_pack_returns_none(tmp_path: Path) -> None:
    """Resolving a pack that does not exist in the index returns None."""
    index_path = _write_index(tmp_path, [])

    marketplace = RemotePackMarketplace(
        RemoteMarketplaceConfig(name="none-src", index_url=index_path.as_uri()),
        cache_dir=tmp_path / "cache",
    )

    assert marketplace.resolve("nonexistent") is None


def test_resolve_nonexistent_version_returns_none(tmp_path: Path) -> None:
    """Resolving a version that does not exist for a known pack returns None."""
    index_path = _write_index(
        tmp_path,
        [
            {
                "name": "some-pack",
                "description": "Exists",
                "versions": [
                    {"version": "1.0.0", "download_url": "file:///dummy.zip"},
                ],
            }
        ],
    )

    marketplace = RemotePackMarketplace(
        RemoteMarketplaceConfig(name="ver-miss", index_url=index_path.as_uri()),
        cache_dir=tmp_path / "cache",
    )

    assert marketplace.resolve("some-pack", "9.9.9") is None


def test_invalidate_clears_cache(tmp_path: Path) -> None:
    """invalidate() forces a fresh fetch on next access."""
    index_path = _write_index(
        tmp_path,
        [
            {
                "name": "inv-pack",
                "description": "Invalidate test",
                "versions": [
                    {"version": "1.0.0", "download_url": "file:///dummy.zip"},
                ],
            }
        ],
    )

    marketplace = RemotePackMarketplace(
        RemoteMarketplaceConfig(
            name="inv-src",
            index_url=index_path.as_uri(),
            cache_ttl_seconds=9999,
        ),
        cache_dir=tmp_path / "cache",
    )

    # Populate cache
    assert len(marketplace.list_packs()) == 1

    # Rewrite index with additional pack
    _write_index(
        tmp_path,
        [
            {
                "name": "inv-pack",
                "description": "Invalidate test",
                "versions": [
                    {"version": "1.0.0", "download_url": "file:///dummy.zip"},
                ],
            },
            {
                "name": "extra-pack",
                "description": "Added",
                "versions": [
                    {"version": "1.0.0", "download_url": "file:///extra.zip"},
                ],
            },
        ],
    )

    # Without invalidation, cache TTL is very long so it would not refresh
    marketplace.invalidate()
    packs = marketplace.list_packs()
    assert len(packs) == 2
