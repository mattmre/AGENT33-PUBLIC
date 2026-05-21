"""Marketplace catalog primitives for pack discovery and installation."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 -- Pydantic needs Path at runtime
from typing import Protocol

import structlog
from pydantic import BaseModel, Field

from agent33.packs.loader import load_pack_manifest
from agent33.packs.provenance_models import PackProvenance, TrustLevel
from agent33.packs.version import Version

logger = structlog.get_logger()


class MarketplacePackVersion(BaseModel):
    """A single marketplace pack version."""

    version: str
    pack_dir: Path | None = None
    description: str = ""
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    category: str = ""
    skills_count: int = 0
    source_name: str = "local"
    source_type: str = "local"
    trust_level: TrustLevel | None = None
    download_url: str = ""
    provenance: PackProvenance | None = None

    model_config = {"arbitrary_types_allowed": True}


class MarketplacePackRecord(BaseModel):
    """Marketplace listing grouped by pack name."""

    name: str
    description: str = ""
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    category: str = ""
    latest_version: str
    versions: list[MarketplacePackVersion] = Field(default_factory=list)


class MarketplaceResolvedPack(BaseModel):
    """A resolved marketplace pack ready for installation."""

    pack_dir: Path
    version: str
    source_name: str
    source_type: str
    provenance: PackProvenance | None = None

    model_config = {"arbitrary_types_allowed": True}


class PackMarketplace(Protocol):
    """Protocol shared by local, remote, and aggregated marketplaces."""

    source_name: str

    def invalidate(self) -> None: ...
    def refresh(self) -> None: ...
    def list_packs(self) -> list[MarketplacePackRecord]: ...
    def search(self, query: str) -> list[MarketplacePackRecord]: ...
    def get_pack(self, name: str) -> MarketplacePackRecord | None: ...
    def list_versions(self, name: str) -> list[MarketplacePackVersion]: ...
    def resolve(self, name: str, version: str = "") -> MarketplaceResolvedPack | None: ...


class LocalPackMarketplace:
    """Filesystem-backed marketplace catalog for pack discovery."""

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir
        self._records: dict[str, MarketplacePackRecord] = {}
        self._catalog_loaded = False
        self.source_name = "local"

    def _build_records(self) -> dict[str, MarketplacePackRecord]:
        """Scan the marketplace directory and return the current catalog."""
        grouped: dict[str, list[MarketplacePackVersion]] = {}
        manifest_dirs: set[Path] = set()
        if self._root_dir.is_dir():
            manifest_dirs.update(path.parent for path in self._root_dir.rglob("PACK.yaml"))
            manifest_dirs.update(path.parent for path in self._root_dir.rglob("pack.yaml"))

        for pack_dir in sorted(manifest_dirs):
            try:
                manifest = load_pack_manifest(pack_dir)
                Version.parse(manifest.version)
            except Exception:
                logger.warning(
                    "marketplace_manifest_load_failed",
                    path=str(pack_dir),
                    exc_info=True,
                )
                continue

            grouped.setdefault(manifest.name, []).append(
                MarketplacePackVersion(
                    version=manifest.version,
                    pack_dir=pack_dir,
                    description=manifest.description,
                    author=manifest.author,
                    tags=manifest.tags,
                    category=manifest.category,
                    skills_count=len(manifest.skills),
                    source_name=self.source_name,
                    source_type="local",
                    trust_level=TrustLevel.UNTRUSTED,
                )
            )

        records: dict[str, MarketplacePackRecord] = {}
        for name, versions in grouped.items():
            ordered = sorted(
                versions,
                key=lambda item: Version.parse(item.version),
                reverse=True,
            )
            latest = ordered[0]
            records[name] = MarketplacePackRecord(
                name=name,
                description=latest.description,
                author=latest.author,
                tags=list(latest.tags),
                category=latest.category,
                latest_version=latest.version,
                versions=ordered,
            )

        return records

    def invalidate(self) -> None:
        """Discard the cached catalog so the next read performs a fresh scan."""
        self._records = {}
        self._catalog_loaded = False

    def _ensure_loaded(self) -> None:
        """Populate the catalog on first use."""
        if not self._catalog_loaded:
            self.refresh()

    def refresh(self) -> None:
        """Rebuild the marketplace catalog from disk."""
        self._records = self._build_records()
        self._catalog_loaded = True

    def list_packs(self) -> list[MarketplacePackRecord]:
        """List marketplace packs sorted by name."""
        self._ensure_loaded()
        return [self._records[name] for name in sorted(self._records)]

    def search(self, query: str) -> list[MarketplacePackRecord]:
        """Search marketplace packs by name, description, or tags."""
        query_lower = query.lower()
        return [
            record
            for record in self.list_packs()
            if query_lower in record.name.lower()
            or query_lower in record.description.lower()
            or any(query_lower in tag.lower() for tag in record.tags)
        ]

    def get_pack(self, name: str) -> MarketplacePackRecord | None:
        """Return a single marketplace pack by name."""
        self._ensure_loaded()
        return self._records.get(name)

    def list_versions(self, name: str) -> list[MarketplacePackVersion]:
        """List versions for a marketplace pack, newest first."""
        record = self.get_pack(name)
        if record is None:
            return []
        return list(record.versions)

    def resolve(self, name: str, version: str = "") -> MarketplaceResolvedPack | None:
        """Resolve a marketplace pack name/version to a concrete directory."""
        versions = self.list_versions(name)
        if not versions:
            return None
        if not version:
            latest = versions[0]
            if latest.pack_dir is None:
                return None
            return MarketplaceResolvedPack(
                pack_dir=latest.pack_dir,
                version=latest.version,
                source_name=latest.source_name,
                source_type=latest.source_type,
                provenance=latest.provenance,
            )
        for item in versions:
            if item.version == version:
                if item.pack_dir is None:
                    return None
                return MarketplaceResolvedPack(
                    pack_dir=item.pack_dir,
                    version=item.version,
                    source_name=item.source_name,
                    source_type=item.source_type,
                    provenance=item.provenance,
                )
        return None
