"""Tests for aggregated local and remote marketplace views."""

from __future__ import annotations

import json
import textwrap
import zipfile
from pathlib import Path

from agent33.packs.marketplace import LocalPackMarketplace
from agent33.packs.marketplace_aggregator import MarketplaceAggregator
from agent33.packs.remote_marketplace import RemoteMarketplaceConfig, RemotePackMarketplace


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


def _make_remote_marketplace(
    tmp_path: Path,
    *,
    source_name: str,
    packs_data: list[dict],
    sub_dir: str = "",
) -> RemotePackMarketplace:
    """Create a RemotePackMarketplace from in-memory data."""
    idx_dir = tmp_path / "indices" / (sub_dir or source_name)
    idx_dir.mkdir(parents=True, exist_ok=True)
    index_path = idx_dir / "index.json"
    index_path.write_text(
        json.dumps({"packs": packs_data}),
        encoding="utf-8",
    )
    return RemotePackMarketplace(
        RemoteMarketplaceConfig(name=source_name, index_url=index_path.as_uri()),
        cache_dir=tmp_path / "cache" / source_name,
    )


def test_marketplace_aggregator_merges_sources(tmp_path: Path) -> None:
    _write_pack(tmp_path / "local", name="ops-pack", version="1.0.0")
    remote_pack = _write_pack(tmp_path / "remote", name="ops-pack", version="2.0.0")
    archive_path = tmp_path / "ops-pack-2.0.0.zip"
    _zip_pack(remote_pack, archive_path)
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "packs": [
                    {
                        "name": "ops-pack",
                        "versions": [{"version": "2.0.0", "download_url": archive_path.as_uri()}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    aggregator = MarketplaceAggregator(
        [
            LocalPackMarketplace(tmp_path / "local"),
            RemotePackMarketplace(
                RemoteMarketplaceConfig(name="community", index_url=index_path.as_uri()),
                cache_dir=tmp_path / "cache",
            ),
        ]
    )

    record = aggregator.get_pack("ops-pack")
    assert record is not None
    assert record.latest_version == "2.0.0"
    assert sorted({item.source_name for item in record.versions}) == ["community", "local"]


def test_aggregate_catalogs_from_multiple_sources(tmp_path: Path) -> None:
    """Aggregator merges packs from two different remote sources."""
    remote_a = _make_remote_marketplace(
        tmp_path,
        source_name="source-a",
        packs_data=[
            {
                "name": "pack-alpha",
                "description": "From A",
                "versions": [{"version": "1.0.0", "download_url": "file:///a.zip"}],
            }
        ],
    )
    remote_b = _make_remote_marketplace(
        tmp_path,
        source_name="source-b",
        packs_data=[
            {
                "name": "pack-beta",
                "description": "From B",
                "versions": [{"version": "2.0.0", "download_url": "file:///b.zip"}],
            }
        ],
    )

    aggregator = MarketplaceAggregator([remote_a, remote_b])
    all_packs = aggregator.list_packs()
    names = {p.name for p in all_packs}
    assert names == {"pack-alpha", "pack-beta"}


def test_version_dedup_across_sources(tmp_path: Path) -> None:
    """Same pack from two sources merges versions correctly (no dedup, all listed)."""
    remote_a = _make_remote_marketplace(
        tmp_path,
        source_name="src-a",
        packs_data=[
            {
                "name": "shared-pack",
                "description": "From A",
                "versions": [
                    {"version": "1.0.0", "download_url": "file:///a1.zip"},
                    {"version": "2.0.0", "download_url": "file:///a2.zip"},
                ],
            }
        ],
    )
    remote_b = _make_remote_marketplace(
        tmp_path,
        source_name="src-b",
        packs_data=[
            {
                "name": "shared-pack",
                "description": "From B",
                "versions": [
                    {"version": "2.0.0", "download_url": "file:///b2.zip"},
                    {"version": "3.0.0", "download_url": "file:///b3.zip"},
                ],
            }
        ],
    )

    aggregator = MarketplaceAggregator([remote_a, remote_b])
    record = aggregator.get_pack("shared-pack")
    assert record is not None
    # latest should be 3.0.0 from src-b
    assert record.latest_version == "3.0.0"

    # All versions from both sources are present
    all_versions = [(v.version, v.source_name) for v in record.versions]
    assert ("3.0.0", "src-b") in all_versions
    assert ("2.0.0", "src-a") in all_versions or ("2.0.0", "src-b") in all_versions
    assert ("1.0.0", "src-a") in all_versions
    # Both 2.0.0 entries should be present (from src-a and src-b)
    version_2_entries = [v for v in record.versions if v.version == "2.0.0"]
    assert len(version_2_entries) == 2


def test_empty_source_handling(tmp_path: Path) -> None:
    """An aggregator with an empty source should not crash and return other results."""
    empty_source = _make_remote_marketplace(
        tmp_path,
        source_name="empty-src",
        packs_data=[],
    )
    populated_source = _make_remote_marketplace(
        tmp_path,
        source_name="full-src",
        packs_data=[
            {
                "name": "real-pack",
                "description": "Exists",
                "versions": [{"version": "1.0.0", "download_url": "file:///r.zip"}],
            }
        ],
    )

    aggregator = MarketplaceAggregator([empty_source, populated_source])
    packs = aggregator.list_packs()
    assert len(packs) == 1
    assert packs[0].name == "real-pack"


def test_resolve_delegates_to_correct_source(tmp_path: Path) -> None:
    """Resolve picks the correct source marketplace to download from."""
    pack_dir_a = _write_pack(tmp_path / "packs-a", name="resolve-pack", version="1.0.0")
    archive_a = tmp_path / "resolve-pack-1.0.0.zip"
    _zip_pack(pack_dir_a, archive_a)

    pack_dir_b = _write_pack(tmp_path / "packs-b", name="resolve-pack", version="2.0.0")
    archive_b = tmp_path / "resolve-pack-2.0.0.zip"
    _zip_pack(pack_dir_b, archive_b)

    remote_a = _make_remote_marketplace(
        tmp_path,
        source_name="source-a",
        packs_data=[
            {
                "name": "resolve-pack",
                "description": "From A",
                "versions": [{"version": "1.0.0", "download_url": archive_a.as_uri()}],
            }
        ],
    )
    remote_b = _make_remote_marketplace(
        tmp_path,
        source_name="source-b",
        packs_data=[
            {
                "name": "resolve-pack",
                "description": "From B",
                "versions": [{"version": "2.0.0", "download_url": archive_b.as_uri()}],
            }
        ],
    )

    aggregator = MarketplaceAggregator([remote_a, remote_b])

    # Resolve v1 should delegate to source-a
    resolved_v1 = aggregator.resolve("resolve-pack", "1.0.0")
    assert resolved_v1 is not None
    assert resolved_v1.source_name == "source-a"
    assert (resolved_v1.pack_dir / "PACK.yaml").is_file()

    # Resolve v2 should delegate to source-b
    resolved_v2 = aggregator.resolve("resolve-pack", "2.0.0")
    assert resolved_v2 is not None
    assert resolved_v2.source_name == "source-b"
    assert (resolved_v2.pack_dir / "PACK.yaml").is_file()


def test_search_across_aggregated_sources(tmp_path: Path) -> None:
    """Search returns results from multiple sources matching the query."""
    remote_a = _make_remote_marketplace(
        tmp_path,
        source_name="search-a",
        packs_data=[
            {
                "name": "devops-tools",
                "description": "DevOps automation",
                "versions": [{"version": "1.0.0", "download_url": "file:///a.zip"}],
            },
            {
                "name": "data-tools",
                "description": "Data pipeline",
                "versions": [{"version": "1.0.0", "download_url": "file:///b.zip"}],
            },
        ],
    )
    remote_b = _make_remote_marketplace(
        tmp_path,
        source_name="search-b",
        packs_data=[
            {
                "name": "ml-tools",
                "description": "Machine learning tools",
                "versions": [{"version": "2.0.0", "download_url": "file:///c.zip"}],
            },
            {
                "name": "ui-components",
                "description": "Frontend bits",
                "versions": [{"version": "1.0.0", "download_url": "file:///d.zip"}],
            },
        ],
    )

    aggregator = MarketplaceAggregator([remote_a, remote_b])
    results = aggregator.search("tools")
    names = {r.name for r in results}
    assert names == {"devops-tools", "data-tools", "ml-tools"}
    # "ui-components" should NOT appear (no "tools" in name/description/tags)
    assert "ui-components" not in names


def test_aggregator_with_no_sources(tmp_path: Path) -> None:
    """Aggregator with no sources returns empty list without error."""
    aggregator = MarketplaceAggregator([])
    assert aggregator.list_packs() == []
    assert aggregator.search("anything") == []
    assert aggregator.get_pack("nonexistent") is None
    assert aggregator.resolve("nonexistent") is None


def test_resolve_nonexistent_pack_returns_none(tmp_path: Path) -> None:
    """Resolve for a pack not in any source returns None."""
    remote = _make_remote_marketplace(
        tmp_path,
        source_name="some-src",
        packs_data=[
            {
                "name": "existing",
                "description": "Exists",
                "versions": [{"version": "1.0.0", "download_url": "file:///e.zip"}],
            }
        ],
    )
    aggregator = MarketplaceAggregator([remote])
    assert aggregator.resolve("ghost-pack") is None
