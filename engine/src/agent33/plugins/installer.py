"""Plugin installation and update flows for local sources."""

from __future__ import annotations

import hashlib
import shutil
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from agent33.plugins.loader import load_manifest

if TYPE_CHECKING:
    from agent33.plugins.registry import PluginRegistry
    from agent33.services.orchestration_state import OrchestrationStateStore

    from .events import PluginEventStore


class PluginInstallMode(StrEnum):
    """Supported local install modes."""

    COPY = "copy"
    LINK = "link"


class PluginInstallRecord(BaseModel):
    """Persisted install metadata for a managed plugin."""

    plugin_name: str
    source_path: str
    installed_path: str
    mode: PluginInstallMode
    version: str
    linked: bool = False
    installed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    installer_identity: str = ""
    integrity_hash: str = ""


class PluginInstallResult(BaseModel):
    """User-facing result for install or update operations."""

    success: bool
    plugin_name: str
    version: str = ""
    mode: PluginInstallMode = PluginInstallMode.COPY
    linked: bool = False
    installed_path: str = ""
    source_path: str = ""
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PluginInstaller:
    """Manage plugin install, link, and update operations."""

    def __init__(
        self,
        plugin_registry: PluginRegistry,
        *,
        plugins_dir: Path,
        context_factory: object,
        event_store: PluginEventStore | None = None,
        state_store: OrchestrationStateStore | None = None,
        namespace: str = "plugin_installations",
        auto_enable: bool = True,
    ) -> None:
        self._plugin_registry = plugin_registry
        self._plugins_dir = plugins_dir
        self._context_factory = context_factory
        self._event_store = event_store
        self._state_store = state_store
        self._namespace = namespace
        self._auto_enable = auto_enable
        self._records: dict[str, PluginInstallRecord] = {}
        self._load()

    async def install_from_local(
        self,
        source_path: Path,
        *,
        mode: PluginInstallMode = PluginInstallMode.COPY,
        requested_by: str = "",
        enable: bool | None = None,
    ) -> PluginInstallResult:
        """Install or link a plugin from a local directory."""
        source_dir = source_path.resolve()
        if not source_dir.is_dir():
            return PluginInstallResult(
                success=False,
                plugin_name="",
                mode=mode,
                errors=[f"Plugin source path not found: {source_dir}"],
            )

        manifest = load_manifest(source_dir)
        if self._plugin_registry.get(manifest.name) is not None:
            return PluginInstallResult(
                success=False,
                plugin_name=manifest.name,
                version=manifest.version,
                mode=mode,
                errors=[f"Plugin '{manifest.name}' is already installed"],
            )

        target_dir = (
            source_dir if mode == PluginInstallMode.LINK else self._plugins_dir / manifest.name
        )
        if mode == PluginInstallMode.COPY:
            self._plugins_dir.mkdir(parents=True, exist_ok=True)
            if target_dir.exists():
                return PluginInstallResult(
                    success=False,
                    plugin_name=manifest.name,
                    version=manifest.version,
                    mode=mode,
                    errors=[f"Plugin install target already exists: {target_dir}"],
                )
            shutil.copytree(source_dir, target_dir)

        self._plugin_registry.discover_plugin(target_dir)
        await self._plugin_registry.load(manifest.name, self._context_factory)
        if enable if enable is not None else self._auto_enable:
            await self._plugin_registry.enable(manifest.name)

        record = PluginInstallRecord(
            plugin_name=manifest.name,
            source_path=str(source_dir),
            installed_path=str(target_dir),
            mode=mode,
            version=manifest.version,
            linked=mode == PluginInstallMode.LINK,
            installer_identity=requested_by,
            integrity_hash=self._fingerprint(target_dir),
        )
        self._records[manifest.name] = record
        self._persist()
        if self._event_store is not None:
            self._event_store.record(
                "linked" if mode == PluginInstallMode.LINK else "installed",
                manifest.name,
                version=manifest.version,
                details={
                    "source_path": str(source_dir),
                    "installed_path": str(target_dir),
                    "requested_by": requested_by,
                },
            )
        return PluginInstallResult(
            success=True,
            plugin_name=manifest.name,
            version=manifest.version,
            mode=mode,
            linked=record.linked,
            installed_path=record.installed_path,
            source_path=record.source_path,
        )

    async def update(
        self,
        name: str,
        *,
        requested_by: str = "",
        enable: bool | None = None,
    ) -> PluginInstallResult:
        """Refresh a plugin from its recorded source path."""
        record = self._records.get(name)
        if record is None:
            return PluginInstallResult(
                success=False,
                plugin_name=name,
                errors=[f"Plugin '{name}' does not have install metadata"],
            )

        source_dir = Path(record.source_path)
        if not source_dir.is_dir():
            return PluginInstallResult(
                success=False,
                plugin_name=name,
                version=record.version,
                mode=record.mode,
                linked=record.linked,
                installed_path=record.installed_path,
                source_path=record.source_path,
                errors=[f"Plugin source path not found: {source_dir}"],
            )

        existing = self._plugin_registry.get(name)
        if existing is not None:
            await self._plugin_registry.unload(name)
            self._plugin_registry.remove(name)

        target_dir = Path(record.installed_path)
        if record.mode == PluginInstallMode.COPY:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source_dir, target_dir)
        else:
            target_dir = source_dir.resolve()

        manifest = load_manifest(target_dir)
        self._plugin_registry.discover_plugin(target_dir)
        await self._plugin_registry.load(name, self._context_factory)
        if enable if enable is not None else self._auto_enable:
            await self._plugin_registry.enable(name)

        updated = record.model_copy(
            update={
                "version": manifest.version,
                "installed_path": str(target_dir),
                "updated_at": datetime.now(UTC),
                "installer_identity": requested_by or record.installer_identity,
                "integrity_hash": self._fingerprint(target_dir),
            }
        )
        self._records[name] = updated
        self._persist()
        if self._event_store is not None:
            self._event_store.record(
                "updated",
                name,
                version=manifest.version,
                details={
                    "source_path": str(source_dir),
                    "installed_path": str(target_dir),
                    "requested_by": requested_by,
                    "mode": updated.mode.value,
                },
            )
        return PluginInstallResult(
            success=True,
            plugin_name=name,
            version=manifest.version,
            mode=updated.mode,
            linked=updated.linked,
            installed_path=updated.installed_path,
            source_path=updated.source_path,
        )

    def get_record(self, name: str) -> PluginInstallRecord | None:
        """Return persisted install metadata for a plugin."""
        return self._records.get(name)

    def list_records(self) -> list[PluginInstallRecord]:
        """Return all install records sorted by plugin name."""
        return [self._records[name] for name in sorted(self._records)]

    def _fingerprint(self, plugin_dir: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(plugin_dir.rglob("*")):
            if not path.is_file():
                continue
            digest.update(path.relative_to(plugin_dir).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def _load(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace(self._namespace)
        raw_records = payload.get("records", {})
        if not isinstance(raw_records, dict):
            return
        self._records = {}
        for key, value in raw_records.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            try:
                self._records[key] = PluginInstallRecord.model_validate(value)
            except Exception:
                continue

    def _persist(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            self._namespace,
            {
                "records": {
                    key: value.model_dump(mode="json") for key, value in self._records.items()
                },
            },
        )
