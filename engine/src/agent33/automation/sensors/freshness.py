"""Freshness sensor -- tracks last-seen timestamps and reports stale items."""

from __future__ import annotations

import dataclasses
import logging
import time

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True, slots=True)
class FreshnessEntry:
    """A registered freshness item."""

    name: str
    max_age_seconds: float
    last_updated: float


@dataclasses.dataclass(frozen=True, slots=True)
class StaleItem:
    """An item that has exceeded its maximum allowed age."""

    name: str
    max_age_seconds: float
    last_updated: float
    age_seconds: float


class FreshnessSensor:
    """Monitors whether named items have been updated within a required window."""

    def __init__(self) -> None:
        self._entries: dict[str, FreshnessEntry] = {}

    def register(self, name: str, max_age_seconds: float) -> None:
        """Register an item to track.

        Parameters
        ----------
        name:
            Unique name for the item.
        max_age_seconds:
            Maximum time in seconds before the item is considered stale.
        """
        self._entries[name] = FreshnessEntry(
            name=name,
            max_age_seconds=max_age_seconds,
            last_updated=time.monotonic(),
        )
        logger.info("Registered freshness tracking for %s (max_age=%ss)", name, max_age_seconds)

    def update(self, name: str) -> None:
        """Record that the named item was just seen / refreshed.

        Raises
        ------
        KeyError:
            If the name has not been registered.
        """
        entry = self._entries.get(name)
        if entry is None:
            raise KeyError(f"Unknown freshness item: {name}")
        self._entries[name] = FreshnessEntry(
            name=entry.name,
            max_age_seconds=entry.max_age_seconds,
            last_updated=time.monotonic(),
        )

    def check(self) -> list[StaleItem]:
        """Return all items that have not been updated within their max age."""
        now = time.monotonic()
        stale: list[StaleItem] = []
        for entry in self._entries.values():
            age = now - entry.last_updated
            if age > entry.max_age_seconds:
                stale.append(
                    StaleItem(
                        name=entry.name,
                        max_age_seconds=entry.max_age_seconds,
                        last_updated=entry.last_updated,
                        age_seconds=age,
                    )
                )
        return stale
