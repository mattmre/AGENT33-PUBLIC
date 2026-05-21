"""Agent-to-agent pack sharing service.

Enables agents in multi-agent workflows to recommend and transfer packs
to peer agents via ``pack_ref`` keys in workflow inputs/outputs.  The
:class:`PackSharingService` scans workflow data for ``pack_ref`` entries,
resolves them against the :class:`PackRegistry`, and enables them for
the target session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel

if TYPE_CHECKING:
    from agent33.packs.registry import PackRegistry

logger = structlog.get_logger()


class PackShareRequest(BaseModel):
    """Payload that agent A puts in its output for agent B to consume."""

    pack_ref: str  # pack name (must be installed in PackRegistry)
    reason: str = ""  # why this pack was recommended


class PackSharingService:
    """Resolves ``pack_ref`` keys in workflow inputs and enables shared packs."""

    def __init__(self, registry: PackRegistry) -> None:
        self._registry = registry

    def extract_share_requests(self, inputs: dict[str, Any]) -> list[PackShareRequest]:
        """Scan workflow inputs for ``pack_ref`` keys and return share requests.

        Supports:
        - Top-level ``pack_ref: "pack-name"``
        - Top-level ``pack_ref: {"pack_ref": "pack-name", "reason": "..."}``
        - Nested dicts containing ``pack_ref`` keys at any depth
        - Lists of share request dicts under ``pack_refs``
        """
        found: list[PackShareRequest] = []
        self._scan_dict(inputs, found)
        return found

    def apply_shares(
        self,
        requests: list[PackShareRequest],
        session_id: str,
    ) -> list[str]:
        """Enable shared packs for *session_id*.

        Returns the list of pack names that were successfully enabled.
        Packs that are not installed are logged and skipped (no error raised).
        """
        applied: list[str] = []

        for req in requests:
            pack = self._registry.get(req.pack_ref)
            if pack is None:
                logger.warning(
                    "pack_share_not_installed",
                    pack_ref=req.pack_ref,
                    reason=req.reason,
                    session_id=session_id,
                )
                continue

            try:
                self._registry.enable_for_session(req.pack_ref, session_id, source="shared")
                applied.append(req.pack_ref)
                logger.info(
                    "pack_share_applied",
                    pack_ref=req.pack_ref,
                    reason=req.reason,
                    session_id=session_id,
                )
            except ValueError as exc:
                logger.warning(
                    "pack_share_enable_failed",
                    pack_ref=req.pack_ref,
                    error=str(exc),
                    session_id=session_id,
                )

        return applied

    # -- Internal scanning --------------------------------------------------

    def _scan_dict(
        self,
        data: dict[str, Any],
        results: list[PackShareRequest],
    ) -> None:
        """Recursively scan a dict for ``pack_ref`` keys."""
        # Direct pack_ref at this level
        if "pack_ref" in data:
            req = self._parse_pack_ref(data["pack_ref"], data.get("reason", ""))
            if req is not None:
                results.append(req)

        # List of pack refs under pack_refs key
        if "pack_refs" in data and isinstance(data["pack_refs"], list):
            for item in data["pack_refs"]:
                if isinstance(item, str):
                    results.append(PackShareRequest(pack_ref=item))
                elif isinstance(item, dict) and "pack_ref" in item:
                    req = self._parse_pack_ref(item["pack_ref"], item.get("reason", ""))
                    if req is not None:
                        results.append(req)

        # Recurse into nested dicts
        for key, value in data.items():
            if key in ("pack_ref", "pack_refs"):
                continue  # already handled
            if isinstance(value, dict):
                self._scan_dict(value, results)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        self._scan_dict(item, results)

    @staticmethod
    def _parse_pack_ref(value: Any, default_reason: str = "") -> PackShareRequest | None:
        """Parse a pack_ref value into a PackShareRequest."""
        if isinstance(value, str) and value:
            return PackShareRequest(pack_ref=value, reason=default_reason)
        if isinstance(value, dict) and "pack_ref" in value:
            return PackShareRequest(
                pack_ref=str(value["pack_ref"]),
                reason=str(value.get("reason", default_reason)),
            )
        return None
