"""API response and request Pydantic models for plugin endpoints."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Any

from pydantic import BaseModel, Field

from agent33.plugins.installer import PluginInstallMode


class PluginSummary(BaseModel):
    """Compact plugin info for list responses."""

    name: str
    version: str
    description: str
    state: str
    author: str
    tags: list[str]
    contributions_summary: dict[str, int] = Field(
        default_factory=dict,
        description='Counts per contribution type, e.g. {"skills": 2, "tools": 1}.',
    )


class PluginDetail(BaseModel):
    """Full plugin info for detail responses."""

    name: str
    version: str
    description: str
    author: str
    license: str
    homepage: str
    repository: str
    state: str
    status: str
    permissions: list[str]
    granted_permissions: list[str]
    denied_permissions: list[str]
    contributions: dict[str, list[str]]
    dependencies: list[dict[str, Any]]
    tags: list[str]
    tenant_config: dict[str, Any] | None = None
    error: str | None = None


class PluginConfigUpdate(BaseModel):
    """Request body for plugin config updates."""

    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool | None = None
    permission_overrides: dict[str, bool] | None = None


class PluginHealthResponse(BaseModel):
    """Health check result for a plugin."""

    plugin_name: str
    healthy: bool
    details: dict[str, Any] = Field(default_factory=dict)


class PluginInstallRequest(BaseModel):
    """Install or link a plugin from a local source path."""

    source_path: str
    mode: PluginInstallMode = PluginInstallMode.COPY
    enable: bool | None = None


class PluginInstallResponse(BaseModel):
    """Result from install, link, or update operations."""

    success: bool
    plugin_name: str
    version: str = ""
    mode: PluginInstallMode = PluginInstallMode.COPY
    linked: bool = False
    installed_path: str = ""
    source_path: str = ""
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PluginLifecycleEventResponse(BaseModel):
    """Serialized lifecycle event for API responses."""

    event_type: str
    plugin_name: str
    version: str = ""
    timestamp: datetime
    details: dict[str, Any] = Field(default_factory=dict)


class PluginEventsResponse(BaseModel):
    """Lifecycle event list wrapper."""

    plugin_name: str | None = None
    count: int = 0
    events: list[PluginLifecycleEventResponse] = Field(default_factory=list)


class PluginPermissionInventory(BaseModel):
    """Requested, granted, and denied permissions for a plugin."""

    plugin_name: str
    requested: list[str] = Field(default_factory=list)
    granted: list[str] = Field(default_factory=list)
    denied: list[str] = Field(default_factory=list)


class PluginDoctorCheckResponse(BaseModel):
    """One plugin doctor check."""

    name: str
    status: str
    message: str
    remediation: str = ""


class PluginDoctorReportResponse(BaseModel):
    """Full doctor report for one plugin."""

    plugin_name: str
    state: str
    overall_status: str
    checks: list[PluginDoctorCheckResponse] = Field(default_factory=list)
    permissions: PluginPermissionInventory
    install_source: str = ""
    installed_path: str = ""


class PluginDoctorSummaryResponse(BaseModel):
    """Wrapper for all plugin doctor reports."""

    count: int
    reports: list[PluginDoctorReportResponse] = Field(default_factory=list)


class PluginSearchResponse(BaseModel):
    """Search results wrapper."""

    query: str
    count: int
    plugins: list[PluginSummary]


class PluginDiscoverResponse(BaseModel):
    """Response from discovery scan."""

    discovered: int
    total: int
