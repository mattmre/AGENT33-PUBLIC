"""Plugin doctor diagnostics."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.plugins.config_store import PluginConfigStore
    from agent33.plugins.installer import PluginInstaller
    from agent33.plugins.registry import PluginRegistry


class PluginDoctorCheck(BaseModel):
    """Single plugin diagnostic check."""

    name: str
    status: str
    message: str
    remediation: str = ""


class PluginPermissionInventory(BaseModel):
    """Permission visibility for one plugin."""

    plugin_name: str = ""
    requested: list[str] = Field(default_factory=list)
    granted: list[str] = Field(default_factory=list)
    denied: list[str] = Field(default_factory=list)


class PluginDoctorReport(BaseModel):
    """Aggregated plugin diagnostic report."""

    plugin_name: str
    state: str
    overall_status: str
    checks: list[PluginDoctorCheck] = Field(default_factory=list)
    permissions: PluginPermissionInventory = Field(default_factory=PluginPermissionInventory)
    install_source: str = ""
    installed_path: str = ""


class PluginDoctor:
    """Run plugin diagnostics against the current registry state."""

    def __init__(
        self,
        plugin_registry: PluginRegistry,
        *,
        config_store: PluginConfigStore | None = None,
        installer: PluginInstaller | None = None,
    ) -> None:
        self._plugin_registry = plugin_registry
        self._config_store = config_store
        self._installer = installer

    async def diagnose(self, plugin_name: str, *, tenant_id: str = "") -> PluginDoctorReport:
        """Build a doctor report for one plugin."""
        entry = self._plugin_registry.get(plugin_name, tenant_id=tenant_id)
        if entry is None:
            raise KeyError(f"Plugin '{plugin_name}' not found")

        checks: list[PluginDoctorCheck] = []
        requested = sorted(permission.value for permission in entry.manifest.permissions)
        granted = []
        denied = requested
        if entry.instance is not None:
            granted = sorted(entry.instance.context.granted_permissions)
            denied = sorted(set(requested) - set(granted))

        checks.append(
            PluginDoctorCheck(
                name="manifest",
                status="ok",
                message=f"Manifest loaded for {entry.manifest.name} v{entry.manifest.version}",
            )
        )

        version_violations = self._plugin_registry.check_version_constraints()
        related_violations = [
            violation
            for violation in version_violations
            if f"'{entry.manifest.name}'" in violation
        ]
        if related_violations:
            checks.append(
                PluginDoctorCheck(
                    name="dependencies",
                    status="error",
                    message=related_violations[0],
                    remediation="Align plugin dependency versions before enabling",
                )
            )
        else:
            checks.append(
                PluginDoctorCheck(
                    name="dependencies",
                    status="ok",
                    message="Required plugin dependencies are satisfied",
                )
            )

        config_record = None
        if self._config_store is not None:
            config_record = self._config_store.get(entry.manifest.name, tenant_id=tenant_id)
        checks.append(
            PluginDoctorCheck(
                name="config",
                status="ok",
                message=(
                    "Persisted config loaded"
                    if config_record is not None
                    else "No persisted config found; defaults will be used"
                ),
            )
        )

        install_record = (
            self._installer.get_record(entry.manifest.name) if self._installer else None
        )
        if install_record is not None:
            source_exists = Path(install_record.source_path).exists()
            checks.append(
                PluginDoctorCheck(
                    name="source",
                    status="ok" if source_exists else "error",
                    message=(
                        f"Install source available at {install_record.source_path}"
                        if source_exists
                        else f"Install source missing at {install_record.source_path}"
                    ),
                    remediation=(
                        ""
                        if source_exists
                        else "Restore the linked source or reinstall the plugin"
                    ),
                )
            )

        state_status = "ok"
        remediation = ""
        if entry.state.value == "error":
            state_status = "error"
            remediation = "Inspect plugin error details and reload or reinstall the plugin"
        elif entry.state.value != "active":
            state_status = "warning"
            remediation = "Enable the plugin if it should be active"
        checks.append(
            PluginDoctorCheck(
                name="state",
                status=state_status,
                message=f"Plugin state is {entry.state.value}",
                remediation=remediation,
            )
        )

        if entry.instance is not None and hasattr(entry.instance, "health_check"):
            try:
                result = await entry.instance.health_check()
            except Exception as exc:
                checks.append(
                    PluginDoctorCheck(
                        name="health_check",
                        status="error",
                        message=f"Health check failed: {exc}",
                        remediation="Fix the plugin runtime error and reload it",
                    )
                )
            else:
                healthy = True
                message = "Health check passed"
                if isinstance(result, dict):
                    healthy = bool(result.get("healthy", True))
                    message = str(result.get("message", message))
                checks.append(
                    PluginDoctorCheck(
                        name="health_check",
                        status="ok" if healthy else "warning",
                        message=message,
                        remediation="" if healthy else "Review plugin health output",
                    )
                )

        statuses = {check.status for check in checks}
        overall_status = "healthy"
        if "error" in statuses:
            overall_status = "broken"
        elif "warning" in statuses:
            overall_status = "degraded"

        return PluginDoctorReport(
            plugin_name=entry.manifest.name,
            state=entry.state.value,
            overall_status=overall_status,
            checks=checks,
            permissions=PluginPermissionInventory(
                plugin_name=entry.manifest.name,
                requested=requested,
                granted=granted,
                denied=denied,
            ),
            install_source=install_record.source_path if install_record is not None else "",
            installed_path=install_record.installed_path if install_record is not None else "",
        )

    async def diagnose_all(self, *, tenant_id: str = "") -> list[PluginDoctorReport]:
        """Run diagnostics across all discovered plugins."""
        reports: list[PluginDoctorReport] = []
        for manifest in self._plugin_registry.list_all(tenant_id=tenant_id):
            reports.append(await self.diagnose(manifest.name, tenant_id=tenant_id))
        return reports
