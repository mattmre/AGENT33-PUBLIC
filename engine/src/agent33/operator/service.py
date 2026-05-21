"""Operator service -- aggregates health checks, config, diagnostics, and resets."""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import SecretStr

if TYPE_CHECKING:
    from agent33.config import Settings
from agent33.operator.diagnostics import run_all_checks
from agent33.operator.models import (
    BackupListResponse,
    CheckStatus,
    DiagnosticResult,
    OperatorConfig,
    PendingItems,
    ResetAction,
    ResetResult,
    ResetTarget,
    RuntimeInfo,
    SessionListResponse,
    SessionSummary,
    SubsystemInventory,
    SystemStatus,
    ToolSummaryItem,
    ToolSummaryResponse,
)

logger = structlog.get_logger()


class OperatorService:
    """Operator control-plane service.

    Reads subsystem registries and connections from ``app.state`` to provide
    aggregated status, diagnostics, config introspection, and reset operations.
    """

    def __init__(
        self,
        app_state: Any,
        settings: Settings,
        start_time: float,
    ) -> None:
        self._app_state = app_state
        self._settings = settings
        self._start_time = start_time

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def get_status(self) -> SystemStatus:
        """Build the aggregated system status."""
        # Inventories
        inventories: dict[str, SubsystemInventory] = {}

        # Agents
        agent_registry = getattr(self._app_state, "agent_registry", None)
        if agent_registry is not None:
            agent_list = agent_registry.list_all()
            inventories["agents"] = SubsystemInventory(
                count=len(agent_list),
                loaded=True,
            )
        else:
            inventories["agents"] = SubsystemInventory(count=0, loaded=False)

        # Tools
        tool_registry = getattr(self._app_state, "tool_registry", None)
        if tool_registry is not None:
            inventories["tools"] = SubsystemInventory(
                count=len(tool_registry.list_all()),
                loaded=True,
            )
        else:
            inventories["tools"] = SubsystemInventory(count=0, loaded=False)

        # Plugins
        plugin_registry = getattr(self._app_state, "plugin_registry", None)
        if plugin_registry is not None:
            all_plugins = plugin_registry.list_all()
            active_count = 0
            for manifest in all_plugins:
                state = plugin_registry.get_state(manifest.name)
                if state is not None and state.value == "active":
                    active_count += 1
            inventories["plugins"] = SubsystemInventory(
                count=len(all_plugins),
                loaded=True,
                active=active_count,
            )
        else:
            inventories["plugins"] = SubsystemInventory(count=0, loaded=False)

        # Packs
        pack_registry = getattr(self._app_state, "pack_registry", None)
        if pack_registry is not None:
            all_packs = pack_registry.list_all()
            inventories["packs"] = SubsystemInventory(
                count=len(all_packs),
                loaded=True,
            )
        else:
            inventories["packs"] = SubsystemInventory(count=0, loaded=False)

        # Skills
        skill_registry = getattr(self._app_state, "skill_registry", None)
        if skill_registry is not None:
            inventories["skills"] = SubsystemInventory(
                count=len(skill_registry.list_all()),
                loaded=True,
            )
        else:
            inventories["skills"] = SubsystemInventory(count=0, loaded=False)

        # Hooks
        hook_registry = getattr(self._app_state, "hook_registry", None)
        if hook_registry is not None:
            inventories["hooks"] = SubsystemInventory(
                count=hook_registry.count(),
                loaded=True,
                enabled=1 if self._settings.hooks_enabled else 0,
            )
        else:
            inventories["hooks"] = SubsystemInventory(count=0, loaded=False)

        process_manager = getattr(self._app_state, "process_manager_service", None)
        if process_manager is not None:
            process_inventory = process_manager.inventory()
            inventories["processes"] = SubsystemInventory(
                count=process_inventory["count"],
                loaded=True,
                active=process_inventory["active"],
            )
        else:
            inventories["processes"] = SubsystemInventory(count=0, loaded=False)

        multimodal_service = getattr(self._app_state, "multimodal_service", None)
        if multimodal_service is not None:
            voice_sessions = multimodal_service.list_voice_sessions(limit=1000)
            active_voice_sessions = [
                session for session in voice_sessions if session.state.value == "active"
            ]
            inventories["voice_sessions"] = SubsystemInventory(
                count=len(voice_sessions),
                loaded=True,
                active=len(active_voice_sessions),
            )
        else:
            inventories["voice_sessions"] = SubsystemInventory(count=0, loaded=False)

        # Proxy servers (MCP fleet)
        proxy_manager = getattr(self._app_state, "proxy_manager", None)
        if proxy_manager is not None:
            servers = proxy_manager.list_servers()
            healthy_count = sum(1 for s in servers if s.get("state") in {"healthy", "degraded"})
            inventories["proxy_servers"] = SubsystemInventory(
                count=len(servers),
                loaded=True,
                active=healthy_count,
            )
        else:
            inventories["proxy_servers"] = SubsystemInventory(count=0, loaded=False)

        # Runtime info
        now = time.time()
        start_dt = datetime.fromtimestamp(self._start_time, tz=UTC)
        runtime = RuntimeInfo(
            version="0.1.0",
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            uptime_seconds=round(now - self._start_time, 2),
            start_time=start_dt,
        )

        # Health summary (lightweight -- just check if key services are present)
        health: dict[str, Any] = {"status": "healthy", "services": {}}
        if getattr(self._app_state, "redis", None) is None:
            health["services"]["redis"] = "unavailable"
            health["status"] = "degraded"
        else:
            health["services"]["redis"] = "ok"

        nats_bus = getattr(self._app_state, "nats_bus", None)
        if nats_bus is None or not nats_bus.is_connected:
            health["services"]["nats"] = "unavailable"
            health["status"] = "degraded"
        else:
            health["services"]["nats"] = "ok"

        ltm = getattr(self._app_state, "long_term_memory", None)
        if ltm is None:
            health["services"]["postgres"] = "unavailable"
            health["status"] = "degraded"
        else:
            health["services"]["postgres"] = "ok"

        voice_probe = getattr(self._app_state, "voice_sidecar_probe", None)
        if voice_probe is not None:
            voice_snapshot = await voice_probe.health_snapshot()
            voice_status = str(voice_snapshot.get("status", "unavailable"))
            health["services"]["voice_sidecar"] = voice_status
            if voice_status in {"degraded", "unavailable"}:
                health["status"] = "degraded"
        else:
            health["services"]["voice_sidecar"] = "unconfigured"

        status_line_service = getattr(self._app_state, "status_line_service", None)
        if status_line_service is not None:
            status_line_snapshot = await status_line_service.health_snapshot()
            status_line_status = str(status_line_snapshot.get("status", "unavailable"))
            health["services"]["status_line"] = status_line_status
            if status_line_status in {"degraded", "unavailable"}:
                health["status"] = "degraded"
        else:
            health["services"]["status_line"] = "unconfigured"

        return SystemStatus(
            health=health,
            inventories=inventories,
            runtime=runtime,
            pending=PendingItems(),
        )

    # ------------------------------------------------------------------
    # Config (redacted)
    # ------------------------------------------------------------------

    def get_config(self) -> OperatorConfig:
        """Return the effective runtime configuration with secrets redacted."""
        s = self._settings

        def _redact(value: Any) -> Any:
            if isinstance(value, SecretStr):
                raw = value.get_secret_value()
                if not raw:
                    return ""
                return "***"
            return value

        groups: dict[str, dict[str, Any]] = {
            "database": {
                "database_url": _mask_db_url(s.database_url),
            },
            "redis": {
                "redis_url": s.redis_url,
            },
            "nats": {
                "nats_url": s.nats_url,
            },
            "ollama": {
                "ollama_base_url": s.ollama_base_url,
                "ollama_default_model": s.ollama_default_model,
            },
            "lm_studio": {
                "lm_studio_base_url": s.lm_studio_base_url,
                "lm_studio_default_model": s.lm_studio_default_model,
            },
            "local_orchestration": {
                "local_orchestration_base_url": s.local_orchestration_base_url,
                "local_orchestration_model": s.local_orchestration_model,
                "local_orchestration_engine": s.local_orchestration_engine,
            },
            "llm": {
                "default_model": s.default_model,
                "openai_api_key": _redact(s.openai_api_key),
                "openai_base_url": s.openai_base_url,
                "openrouter_api_key": _redact(s.openrouter_api_key),
                "openrouter_base_url": s.openrouter_base_url,
                "openrouter_site_url": s.openrouter_site_url,
                "openrouter_app_name": s.openrouter_app_name,
                "openrouter_app_category": s.openrouter_app_category,
                "openrouter_default_fallback_models": s.openrouter_default_fallback_models,
            },
            "agents": {
                "agent_definitions_dir": s.agent_definitions_dir,
            },
            "skills": {
                "skill_definitions_dir": s.skill_definitions_dir,
            },
            "plugins": {
                "plugin_definitions_dir": s.plugin_definitions_dir,
                "plugin_auto_enable": s.plugin_auto_enable,
            },
            "packs": {
                "pack_definitions_dir": s.pack_definitions_dir,
                "pack_auto_enable": s.pack_auto_enable,
            },
            "security": {
                "jwt_secret": _redact(s.jwt_secret),
                "jwt_algorithm": s.jwt_algorithm,
                "api_secret_key": _redact(s.api_secret_key),
                "encryption_key": _redact(s.encryption_key),
            },
            "environment": {
                "environment": s.environment,
            },
        }

        feature_flags: dict[str, bool] = {
            "hooks_enabled": s.hooks_enabled,
            "training_enabled": s.training_enabled,
            "airllm_enabled": s.airllm_enabled,
            "bm25_warmup_enabled": s.bm25_warmup_enabled,
            "rag_hybrid_enabled": s.rag_hybrid_enabled,
            "embedding_cache_enabled": s.embedding_cache_enabled,
            "plugin_auto_enable": s.plugin_auto_enable,
        }

        return OperatorConfig(groups=groups, feature_flags=feature_flags)

    # ------------------------------------------------------------------
    # Doctor
    # ------------------------------------------------------------------

    async def run_doctor(self) -> DiagnosticResult:
        """Run all diagnostic checks."""
        checks = await run_all_checks(self._app_state)
        overall = CheckStatus.OK
        for check in checks:
            if check.status == CheckStatus.ERROR:
                overall = CheckStatus.ERROR
                break
            if check.status == CheckStatus.WARNING and overall != CheckStatus.ERROR:
                overall = CheckStatus.WARNING
        return DiagnosticResult(
            overall=overall,
            checks=checks,
            timestamp=datetime.now(tz=UTC),
        )

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    async def reset(self, targets: list[ResetTarget]) -> ResetResult:
        """Reset specified operator state."""
        actions: list[ResetAction] = []
        effective_targets = set(targets)
        if ResetTarget.ALL in effective_targets:
            effective_targets = {ResetTarget.CACHES, ResetTarget.REGISTRIES}

        if ResetTarget.CACHES in effective_targets:
            actions.extend(await self._reset_caches())

        if ResetTarget.REGISTRIES in effective_targets:
            actions.extend(await self._reset_registries())

        return ResetResult(
            actions=actions,
            timestamp=datetime.now(tz=UTC),
        )

    async def _reset_caches(self) -> list[ResetAction]:
        """Clear in-memory caches."""
        actions: list[ResetAction] = []

        # Embedding cache
        cache = getattr(self._app_state, "embedding_cache", None)
        if cache is not None:
            try:
                cache.clear()
                actions.append(
                    ResetAction(
                        target="embedding_cache",
                        success=True,
                        detail="Embedding cache cleared",
                    )
                )
            except Exception as exc:
                actions.append(
                    ResetAction(
                        target="embedding_cache",
                        success=False,
                        detail=f"Failed to clear embedding cache: {exc}",
                    )
                )
        else:
            actions.append(
                ResetAction(
                    target="embedding_cache",
                    success=True,
                    detail="No embedding cache initialized (nothing to clear)",
                )
            )

        # BM25 index
        bm25 = getattr(self._app_state, "bm25_index", None)
        if bm25 is not None:
            try:
                bm25.clear()
                actions.append(
                    ResetAction(
                        target="bm25_index",
                        success=True,
                        detail="BM25 index cleared",
                    )
                )
            except Exception as exc:
                actions.append(
                    ResetAction(
                        target="bm25_index",
                        success=False,
                        detail=f"Failed to clear BM25 index: {exc}",
                    )
                )
        else:
            actions.append(
                ResetAction(
                    target="bm25_index",
                    success=True,
                    detail="No BM25 index initialized (nothing to clear)",
                )
            )

        return actions

    async def _reset_registries(self) -> list[ResetAction]:
        """Re-discover agents, skills, plugins, packs from disk."""
        actions: list[ResetAction] = []

        # Agent registry
        agent_registry = getattr(self._app_state, "agent_registry", None)
        if agent_registry is not None:
            try:
                defs_dir = Path(self._settings.agent_definitions_dir)
                if defs_dir.is_dir():
                    count = agent_registry.discover(defs_dir)
                    actions.append(
                        ResetAction(
                            target="agent_registry",
                            success=True,
                            detail=f"Re-discovered {count} agent definition(s)",
                        )
                    )
                else:
                    actions.append(
                        ResetAction(
                            target="agent_registry",
                            success=False,
                            detail=f"Agent definitions dir not found: {defs_dir}",
                        )
                    )
            except Exception as exc:
                actions.append(
                    ResetAction(
                        target="agent_registry",
                        success=False,
                        detail=f"Failed to re-discover agents: {exc}",
                    )
                )

        # Skill registry
        skill_registry = getattr(self._app_state, "skill_registry", None)
        if skill_registry is not None:
            try:
                skills_dir = Path(self._settings.skill_definitions_dir)
                if skills_dir.is_dir():
                    count = skill_registry.discover(skills_dir)
                    actions.append(
                        ResetAction(
                            target="skill_registry",
                            success=True,
                            detail=f"Re-discovered {count} skill(s)",
                        )
                    )
                else:
                    actions.append(
                        ResetAction(
                            target="skill_registry",
                            success=False,
                            detail=f"Skills dir not found: {skills_dir} (nothing to rediscover)",
                        )
                    )
            except Exception as exc:
                actions.append(
                    ResetAction(
                        target="skill_registry",
                        success=False,
                        detail=f"Failed to re-discover skills: {exc}",
                    )
                )

        # Pack registry
        pack_registry = getattr(self._app_state, "pack_registry", None)
        if pack_registry is not None:
            try:
                count = pack_registry.discover()
                actions.append(
                    ResetAction(
                        target="pack_registry",
                        success=True,
                        detail=f"Re-discovered {count} pack(s)",
                    )
                )
            except Exception as exc:
                actions.append(
                    ResetAction(
                        target="pack_registry",
                        success=False,
                        detail=f"Failed to re-discover packs: {exc}",
                    )
                )

        return actions

    # ------------------------------------------------------------------
    # Tools summary
    # ------------------------------------------------------------------

    def get_tools_summary(self) -> ToolSummaryResponse:
        """Return a lightweight listing of registered tools."""
        tool_registry = getattr(self._app_state, "tool_registry", None)
        if tool_registry is None:
            return ToolSummaryResponse(tools=[], count=0)

        items: list[ToolSummaryItem] = []
        for tool in tool_registry.list_all():
            entry = tool_registry.get_entry(tool.name)
            has_schema = hasattr(tool, "parameters_schema") and tool.parameters_schema is not None
            source = "builtin"
            tool_status = "active"
            if entry is not None:
                source = entry.provenance.repo_url if entry.provenance.repo_url else "builtin"
                tool_status = entry.status.value
            items.append(
                ToolSummaryItem(
                    name=tool.name,
                    source=source,
                    status=tool_status,
                    has_schema=has_schema,
                )
            )

        return ToolSummaryResponse(tools=items, count=len(items))

    # ------------------------------------------------------------------
    # Sessions (lightweight catalog)
    # ------------------------------------------------------------------

    async def get_sessions(
        self,
        status_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> SessionListResponse:
        """Return a lightweight session catalog.

        Delegates to SessionCatalog when available (Track 8). Falls back to
        degraded skeleton if neither the catalog nor Redis is accessible.
        """
        session_catalog = getattr(self._app_state, "session_catalog", None)
        if session_catalog is not None:
            from agent33.sessions.models import OperatorSessionStatus

            status_enum = OperatorSessionStatus(status_filter) if status_filter else None
            catalog_resp = await session_catalog.list_catalog(
                status=status_enum,
                limit=limit,
                offset=offset,
            )
            summaries: list[SessionSummary] = []
            for entry in catalog_resp.entries:
                summaries.append(
                    SessionSummary(
                        session_id=entry.session_id,
                        type="operator",
                        status=entry.status,
                        agent=entry.agent_name,
                        started_at=entry.started_at,
                        last_activity=entry.ended_at,
                        message_count=entry.event_count,
                        tenant_id=entry.tenant_id,
                    )
                )
            return SessionListResponse(
                sessions=summaries,
                count=len(summaries),
                total=catalog_resp.total,
                degraded=False,
            )

        redis_conn = getattr(self._app_state, "redis", None)
        if redis_conn is None:
            return SessionListResponse(
                sessions=[],
                count=0,
                total=0,
                degraded=True,
            )

        return SessionListResponse(
            sessions=[],
            count=0,
            total=0,
            degraded=False,
        )

    # ------------------------------------------------------------------
    # Backups
    # ------------------------------------------------------------------

    def get_backups(self) -> BackupListResponse:
        """Return backup catalog, delegating to the platform backup service when available."""
        backup_service = getattr(self._app_state, "backup_service", None)
        if backup_service is None:
            return BackupListResponse()
        result = backup_service.list_backups()
        return BackupListResponse(
            backups=result.backups,
            count=result.count,
            note="Platform backup inventory is available under /v1/backups",
        )


def _mask_db_url(url: str) -> str:
    """Mask credentials in a database URL."""
    if "://" in url and "@" in url:
        scheme_rest = url.split("://", 1)
        if len(scheme_rest) == 2:
            rest = scheme_rest[1]
            if "@" in rest:
                host_part = rest.split("@", 1)[1]
                return f"{scheme_rest[0]}://***:***@{host_part}"
    return url
