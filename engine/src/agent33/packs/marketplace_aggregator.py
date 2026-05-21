"""Aggregated marketplace view across local and remote sources."""

from __future__ import annotations

from agent33.packs.marketplace import (
    MarketplacePackRecord,
    MarketplacePackVersion,
    MarketplaceResolvedPack,
    PackMarketplace,
)
from agent33.packs.version import Version


class MarketplaceAggregator:
    """Combine multiple marketplace sources into a single catalog."""

    def __init__(self, marketplaces: list[PackMarketplace] | None = None) -> None:
        self._marketplaces = marketplaces or []
        self.source_name = "aggregated"
        self._by_source = {
            marketplace.source_name: marketplace for marketplace in self._marketplaces
        }

    def invalidate(self) -> None:
        for marketplace in self._marketplaces:
            marketplace.invalidate()

    def refresh(self) -> None:
        for marketplace in self._marketplaces:
            marketplace.refresh()

    def list_packs(self) -> list[MarketplacePackRecord]:
        merged: dict[str, list[MarketplacePackVersion]] = {}
        metadata: dict[str, MarketplacePackRecord] = {}
        for marketplace in self._marketplaces:
            for record in marketplace.list_packs():
                merged.setdefault(record.name, []).extend(record.versions)
                existing = metadata.get(record.name)
                if existing is None:
                    metadata[record.name] = record
                else:
                    metadata[record.name] = MarketplacePackRecord(
                        name=existing.name,
                        description=existing.description or record.description,
                        author=existing.author or record.author,
                        tags=existing.tags or record.tags,
                        category=existing.category or record.category,
                        latest_version=existing.latest_version,
                        versions=existing.versions,
                    )

        packs: list[MarketplacePackRecord] = []
        for name, versions in merged.items():
            ordered = sorted(
                versions,
                key=lambda item: (Version.parse(item.version), item.source_name),
                reverse=True,
            )
            latest = ordered[0]
            base = metadata[name]
            packs.append(
                MarketplacePackRecord(
                    name=name,
                    description=latest.description or base.description,
                    author=latest.author or base.author,
                    tags=list(latest.tags or base.tags),
                    category=latest.category or base.category,
                    latest_version=latest.version,
                    versions=ordered,
                )
            )
        return sorted(packs, key=lambda record: record.name)

    def search(self, query: str) -> list[MarketplacePackRecord]:
        query_lower = query.lower()
        return [
            record
            for record in self.list_packs()
            if query_lower in record.name.lower()
            or query_lower in record.description.lower()
            or any(query_lower in tag.lower() for tag in record.tags)
        ]

    def get_pack(self, name: str) -> MarketplacePackRecord | None:
        for record in self.list_packs():
            if record.name == name:
                return record
        return None

    def list_versions(self, name: str) -> list[MarketplacePackVersion]:
        record = self.get_pack(name)
        if record is None:
            return []
        return list(record.versions)

    def resolve(self, name: str, version: str = "") -> MarketplaceResolvedPack | None:
        versions = self.list_versions(name)
        if not versions:
            return None
        selected = (
            versions[0]
            if not version
            else next(
                (item for item in versions if item.version == version),
                None,
            )
        )
        if selected is None:
            return None
        source = self._by_source.get(selected.source_name)
        if source is None:
            return None
        return source.resolve(name, selected.version)
