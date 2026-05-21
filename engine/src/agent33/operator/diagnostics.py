"""Diagnostic checks for the operator doctor endpoint."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from agent33.operator.models import CheckStatus, DiagnosticCheck

logger = logging.getLogger(__name__)

DiagnosticCheckFn = Callable[[Any], Awaitable[DiagnosticCheck]]


def _settings_for_state(app_state: Any) -> Any:
    """Return the app-specific Settings instance when present."""
    state_settings = getattr(app_state, "settings", None)
    if state_settings is not None:
        return state_settings

    from agent33.config import settings as global_settings

    return global_settings


async def check_database(app_state: Any) -> DiagnosticCheck:
    """DOC-01: PostgreSQL connectivity."""
    try:
        ltm = getattr(app_state, "long_term_memory", None)
        if ltm is None:
            return DiagnosticCheck(
                id="DOC-01",
                category="database",
                status=CheckStatus.ERROR,
                message="LongTermMemory not initialized",
                remediation="Verify DATABASE_URL is set and PostgreSQL is reachable",
            )
        # Attempt a lightweight probe
        engine = getattr(ltm, "_engine", None)
        if engine is not None:
            from sqlalchemy import text

            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return DiagnosticCheck(
                id="DOC-01",
                category="database",
                status=CheckStatus.OK,
                message="PostgreSQL connected",
            )
        # Engine not available but LTM exists -- partial
        return DiagnosticCheck(
            id="DOC-01",
            category="database",
            status=CheckStatus.WARNING,
            message="LongTermMemory exists but engine not inspectable",
            remediation="Check database connection pool health",
        )
    except Exception as exc:
        logger.debug("DOC-01 failed: %s", exc)
        return DiagnosticCheck(
            id="DOC-01",
            category="database",
            status=CheckStatus.ERROR,
            message=f"PostgreSQL check failed: {exc}",
            remediation="Verify DATABASE_URL and ensure PostgreSQL is running",
        )


async def check_redis(app_state: Any) -> DiagnosticCheck:
    """DOC-02: Redis connectivity."""
    try:
        redis_conn = getattr(app_state, "redis", None)
        if redis_conn is None:
            return DiagnosticCheck(
                id="DOC-02",
                category="redis",
                status=CheckStatus.WARNING,
                message="Redis not initialized",
                remediation="Set REDIS_URL and ensure Redis is running",
            )
        await redis_conn.ping()
        return DiagnosticCheck(
            id="DOC-02",
            category="redis",
            status=CheckStatus.OK,
            message="Redis connected",
        )
    except Exception as exc:
        logger.debug("DOC-02 failed: %s", exc)
        return DiagnosticCheck(
            id="DOC-02",
            category="redis",
            status=CheckStatus.ERROR,
            message=f"Redis check failed: {exc}",
            remediation="Verify REDIS_URL and ensure Redis is running",
        )


async def check_nats(app_state: Any) -> DiagnosticCheck:
    """DOC-03: NATS connectivity."""
    try:
        nats_bus = getattr(app_state, "nats_bus", None)
        if nats_bus is None:
            return DiagnosticCheck(
                id="DOC-03",
                category="nats",
                status=CheckStatus.WARNING,
                message="NATS bus not initialized",
                remediation="Set NATS_URL and ensure NATS server is running",
            )
        if nats_bus.is_connected:
            return DiagnosticCheck(
                id="DOC-03",
                category="nats",
                status=CheckStatus.OK,
                message="NATS connected",
            )
        return DiagnosticCheck(
            id="DOC-03",
            category="nats",
            status=CheckStatus.ERROR,
            message="NATS bus exists but not connected",
            remediation="Check NATS_URL and verify NATS server is reachable",
        )
    except Exception as exc:
        logger.debug("DOC-03 failed: %s", exc)
        return DiagnosticCheck(
            id="DOC-03",
            category="nats",
            status=CheckStatus.ERROR,
            message=f"NATS check failed: {exc}",
            remediation="Verify NATS_URL and ensure NATS is running",
        )


async def check_llm(app_state: Any) -> DiagnosticCheck:
    """DOC-04: LLM provider reachability."""
    try:
        model_router = getattr(app_state, "model_router", None)
        if model_router is None:
            return DiagnosticCheck(
                id="DOC-04",
                category="llm",
                status=CheckStatus.WARNING,
                message="Model router not initialized",
                remediation="Verify OLLAMA_BASE_URL or OPENAI_API_KEY is configured",
            )
        providers = getattr(model_router, "_providers", {})
        if not providers:
            return DiagnosticCheck(
                id="DOC-04",
                category="llm",
                status=CheckStatus.WARNING,
                message="No LLM providers registered",
                remediation="Configure at least one LLM provider (Ollama or OpenAI)",
            )
        return DiagnosticCheck(
            id="DOC-04",
            category="llm",
            status=CheckStatus.OK,
            message=f"{len(providers)} LLM provider(s) registered",
        )
    except Exception as exc:
        logger.debug("DOC-04 failed: %s", exc)
        return DiagnosticCheck(
            id="DOC-04",
            category="llm",
            status=CheckStatus.ERROR,
            message=f"LLM check failed: {exc}",
            remediation="Check LLM provider configuration",
        )


async def check_agents(app_state: Any) -> DiagnosticCheck:
    """DOC-05: Agent definitions directory and loaded agents."""
    try:
        registry = getattr(app_state, "agent_registry", None)
        if registry is None:
            return DiagnosticCheck(
                id="DOC-05",
                category="agents",
                status=CheckStatus.ERROR,
                message="Agent registry not initialized",
                remediation="Ensure AGENT_DEFINITIONS_DIR is set and contains JSON definitions",
            )
        count = len(registry.list_all())
        if count == 0:
            return DiagnosticCheck(
                id="DOC-05",
                category="agents",
                status=CheckStatus.WARNING,
                message="Agent registry is empty (0 definitions loaded)",
                remediation="Add agent JSON definitions to AGENT_DEFINITIONS_DIR",
            )
        return DiagnosticCheck(
            id="DOC-05",
            category="agents",
            status=CheckStatus.OK,
            message=f"{count} agent definition(s) loaded",
        )
    except Exception as exc:
        logger.debug("DOC-05 failed: %s", exc)
        return DiagnosticCheck(
            id="DOC-05",
            category="agents",
            status=CheckStatus.ERROR,
            message=f"Agent check failed: {exc}",
            remediation="Check AGENT_DEFINITIONS_DIR path and JSON validity",
        )


async def check_skills(app_state: Any) -> DiagnosticCheck:
    """DOC-06: Skills directory and loaded skills."""
    try:
        registry = getattr(app_state, "skill_registry", None)
        if registry is None:
            return DiagnosticCheck(
                id="DOC-06",
                category="skills",
                status=CheckStatus.WARNING,
                message="Skill registry not initialized",
                remediation="Ensure SKILL_DEFINITIONS_DIR is set",
            )
        count = len(registry.list_all())
        return DiagnosticCheck(
            id="DOC-06",
            category="skills",
            status=CheckStatus.OK if count > 0 else CheckStatus.WARNING,
            message=f"{count} skill(s) loaded",
            remediation="Add SKILL.md files to SKILL_DEFINITIONS_DIR" if count == 0 else None,
        )
    except Exception as exc:
        logger.debug("DOC-06 failed: %s", exc)
        return DiagnosticCheck(
            id="DOC-06",
            category="skills",
            status=CheckStatus.ERROR,
            message=f"Skill check failed: {exc}",
            remediation="Check SKILL_DEFINITIONS_DIR path and SKILL.md validity",
        )


async def check_plugins(app_state: Any) -> DiagnosticCheck:
    """DOC-07: Plugin directory and plugin states."""
    try:
        registry = getattr(app_state, "plugin_registry", None)
        if registry is None:
            return DiagnosticCheck(
                id="DOC-07",
                category="plugins",
                status=CheckStatus.WARNING,
                message="Plugin registry not initialized",
                remediation="Ensure PLUGIN_DEFINITIONS_DIR is set",
            )
        all_plugins = registry.list_all()
        count = len(all_plugins)
        error_count = 0
        for manifest in all_plugins:
            state = registry.get_state(manifest.name)
            if state is not None and state.value == "error":
                error_count += 1
        if error_count > 0:
            return DiagnosticCheck(
                id="DOC-07",
                category="plugins",
                status=CheckStatus.WARNING,
                message=f"{count} plugin(s), {error_count} in error state",
                remediation="Check plugin logs for load/enable failures",
            )
        return DiagnosticCheck(
            id="DOC-07",
            category="plugins",
            status=CheckStatus.OK,
            message=f"{count} plugin(s) loaded",
        )
    except Exception as exc:
        logger.debug("DOC-07 failed: %s", exc)
        return DiagnosticCheck(
            id="DOC-07",
            category="plugins",
            status=CheckStatus.ERROR,
            message=f"Plugin check failed: {exc}",
            remediation="Check plugin directory and manifests",
        )


async def check_packs(app_state: Any) -> DiagnosticCheck:
    """DOC-08: Pack directory and loadability."""
    try:
        registry = getattr(app_state, "pack_registry", None)
        if registry is None:
            return DiagnosticCheck(
                id="DOC-08",
                category="packs",
                status=CheckStatus.WARNING,
                message="Pack registry not initialized",
                remediation="Ensure PACK_DEFINITIONS_DIR is set",
            )
        all_packs = registry.list_all()
        count = len(all_packs)
        return DiagnosticCheck(
            id="DOC-08",
            category="packs",
            status=CheckStatus.OK,
            message=f"{count} pack(s) loaded",
        )
    except Exception as exc:
        logger.debug("DOC-08 failed: %s", exc)
        return DiagnosticCheck(
            id="DOC-08",
            category="packs",
            status=CheckStatus.ERROR,
            message=f"Pack check failed: {exc}",
            remediation="Check pack directory and PACK.yaml validity",
        )


async def check_security(app_state: Any) -> DiagnosticCheck:
    """DOC-09: Security configuration (JWT secret, DB credentials)."""
    from agent33.config import Settings

    issues: list[str] = []
    remediations: list[str] = []
    settings = _settings_for_state(app_state)
    default_jwt_secret = Settings.model_fields["jwt_secret"].default
    default_api_secret = Settings.model_fields["api_secret_key"].default

    if settings.jwt_secret.get_secret_value() == default_jwt_secret.get_secret_value():
        issues.append("JWT secret is using default value")
        remediations.append(
            "Set JWT_SECRET environment variable to a cryptographically random value"
        )

    if "agent33:agent33@" in settings.database_url:
        issues.append("Database credentials are using defaults")
        remediations.append("Set DATABASE_URL with rotated credentials")

    if settings.api_secret_key.get_secret_value() == default_api_secret.get_secret_value():
        issues.append("API secret key is using default value")
        remediations.append("Set API_SECRET_KEY to a strong random value")

    if issues:
        return DiagnosticCheck(
            id="DOC-09",
            category="security",
            status=CheckStatus.WARNING,
            message="; ".join(issues),
            remediation="; ".join(remediations),
        )
    return DiagnosticCheck(
        id="DOC-09",
        category="security",
        status=CheckStatus.OK,
        message="Security configuration looks good",
    )


async def check_config(app_state: Any) -> DiagnosticCheck:
    """DOC-10: General config validation (deprecated/conflicting values)."""
    issues: list[str] = []
    settings = _settings_for_state(app_state)

    # Check for potentially conflicting settings
    if settings.training_enabled and not settings.database_url:
        issues.append("training_enabled=True but no DATABASE_URL configured")

    if settings.embedding_cache_enabled and settings.embedding_cache_max_size < 1:
        issues.append("embedding_cache_enabled but max_size < 1")

    if issues:
        return DiagnosticCheck(
            id="DOC-10",
            category="config",
            status=CheckStatus.WARNING,
            message="; ".join(issues),
            remediation="Review configuration for consistency",
        )
    return DiagnosticCheck(
        id="DOC-10",
        category="config",
        status=CheckStatus.OK,
        message="No configuration issues detected",
    )


async def check_sessions(app_state: Any) -> DiagnosticCheck:
    """DOC-11: Operator session service availability."""
    try:
        session_svc = getattr(app_state, "operator_session_service", None)
        if session_svc is None:
            return DiagnosticCheck(
                id="DOC-11",
                category="sessions",
                status=CheckStatus.WARNING,
                message="Operator session service not initialized",
                remediation="Set OPERATOR_SESSION_ENABLED=true to enable session management",
            )
        return DiagnosticCheck(
            id="DOC-11",
            category="sessions",
            status=CheckStatus.OK,
            message="Operator session service is available",
        )
    except Exception as exc:
        logger.debug("DOC-11 failed: %s", exc)
        return DiagnosticCheck(
            id="DOC-11",
            category="sessions",
            status=CheckStatus.ERROR,
            message=f"Session service check failed: {exc}",
            remediation="Check operator session configuration",
        )


async def check_hooks(app_state: Any) -> DiagnosticCheck:
    """DOC-12: Hook registry and loaded hooks."""
    try:
        hook_registry = getattr(app_state, "hook_registry", None)
        if hook_registry is None:
            return DiagnosticCheck(
                id="DOC-12",
                category="hooks",
                status=CheckStatus.WARNING,
                message="Hook registry not initialized",
                remediation="Set HOOKS_ENABLED=true to enable the hook system",
            )
        count = hook_registry.count()
        if count == 0:
            return DiagnosticCheck(
                id="DOC-12",
                category="hooks",
                status=CheckStatus.WARNING,
                message="Hook registry loaded but contains 0 hooks",
                remediation="Add hook definitions or check HOOKS_DEFINITIONS_DIR",
            )
        return DiagnosticCheck(
            id="DOC-12",
            category="hooks",
            status=CheckStatus.OK,
            message=f"{count} hook(s) registered",
        )
    except Exception as exc:
        logger.debug("DOC-12 failed: %s", exc)
        return DiagnosticCheck(
            id="DOC-12",
            category="hooks",
            status=CheckStatus.ERROR,
            message=f"Hook registry check failed: {exc}",
            remediation="Check hooks configuration and definitions directory",
        )


async def check_scheduler(app_state: Any) -> DiagnosticCheck:
    """DOC-13: Workflow scheduler status and job count."""
    try:
        scheduler = getattr(app_state, "workflow_scheduler", None)
        if scheduler is None:
            return DiagnosticCheck(
                id="DOC-13",
                category="scheduler",
                status=CheckStatus.WARNING,
                message="Workflow scheduler not initialized",
                remediation="Scheduler is initialized during app lifespan startup",
            )
        jobs = scheduler.list_jobs()
        running = scheduler._scheduler.running if hasattr(scheduler, "_scheduler") else False
        if not running:
            return DiagnosticCheck(
                id="DOC-13",
                category="scheduler",
                status=CheckStatus.WARNING,
                message=f"Scheduler exists but not running ({len(jobs)} job(s))",
                remediation="The scheduler should be started during application startup",
            )
        return DiagnosticCheck(
            id="DOC-13",
            category="scheduler",
            status=CheckStatus.OK,
            message=f"Scheduler running with {len(jobs)} job(s)",
        )
    except Exception as exc:
        logger.debug("DOC-13 failed: %s", exc)
        return DiagnosticCheck(
            id="DOC-13",
            category="scheduler",
            status=CheckStatus.ERROR,
            message=f"Scheduler check failed: {exc}",
            remediation="Check scheduler configuration",
        )


async def check_mcp(app_state: Any) -> DiagnosticCheck:
    """DOC-14: MCP proxy reachability and fleet health."""
    try:
        proxy_manager = getattr(app_state, "proxy_manager", None)
        if proxy_manager is None:
            return DiagnosticCheck(
                id="DOC-14",
                category="mcp",
                status=CheckStatus.WARNING,
                message="MCP proxy manager not initialized",
                remediation="Set MCP_PROXY_ENABLED=true and provide MCP_PROXY_CONFIG_PATH",
            )
        settings = _settings_for_state(app_state)
        if not settings.mcp_proxy_enabled:
            return DiagnosticCheck(
                id="DOC-14",
                category="mcp",
                status=CheckStatus.OK,
                message="MCP proxy is disabled (not required)",
            )

        # Probe individual server health states
        servers = proxy_manager.list_servers()
        if not servers:
            return DiagnosticCheck(
                id="DOC-14",
                category="mcp",
                status=CheckStatus.OK,
                message="MCP proxy manager is available (0 servers configured)",
            )

        issues: list[str] = []
        for srv in servers:
            srv_id = srv.get("id", "unknown")
            srv_state = srv.get("state", "unknown")
            circuit_state = srv.get("circuit_state", "closed")

            if circuit_state == "open":
                issues.append(f"Server '{srv_id}' has circuit breaker OPEN")
            if srv_state in {"unhealthy", "cooldown"}:
                issues.append(f"Server '{srv_id}' is {srv_state.upper()}")

        if issues:
            return DiagnosticCheck(
                id="DOC-14",
                category="mcp",
                status=CheckStatus.WARNING,
                message=f"MCP fleet issues: {'; '.join(issues)}",
                remediation=(
                    "Check MCP proxy server logs and upstream connectivity. "
                    "Servers with open circuit breakers will auto-recover "
                    "after the recovery timeout."
                ),
            )

        return DiagnosticCheck(
            id="DOC-14",
            category="mcp",
            status=CheckStatus.OK,
            message=f"MCP proxy fleet healthy ({len(servers)} server(s))",
        )
    except Exception as exc:
        logger.debug("DOC-14 failed: %s", exc)
        return DiagnosticCheck(
            id="DOC-14",
            category="mcp",
            status=CheckStatus.ERROR,
            message=f"MCP proxy check failed: {exc}",
            remediation="Check MCP proxy configuration",
        )


async def check_voice(app_state: Any) -> DiagnosticCheck:
    """DOC-15: Voice sidecar status."""
    try:
        settings = _settings_for_state(app_state)
        if not settings.voice_daemon_enabled:
            return DiagnosticCheck(
                id="DOC-15",
                category="voice",
                status=CheckStatus.OK,
                message="Voice daemon is disabled (not required)",
            )
        probe = getattr(app_state, "voice_sidecar_probe", None)
        if probe is None:
            if settings.voice_daemon_transport == "stub":
                return DiagnosticCheck(
                    id="DOC-15",
                    category="voice",
                    status=CheckStatus.OK,
                    message="Voice daemon using stub transport",
                )
            return DiagnosticCheck(
                id="DOC-15",
                category="voice",
                status=CheckStatus.WARNING,
                message="Voice sidecar probe not initialized",
                remediation="Set VOICE_SIDECAR_URL or VOICE_DAEMON_URL for sidecar transport",
            )
        snapshot = await probe.health_snapshot()
        probe_status = str(snapshot.get("status", "unknown"))
        if probe_status == "ok":
            return DiagnosticCheck(
                id="DOC-15",
                category="voice",
                status=CheckStatus.OK,
                message="Voice sidecar is healthy",
            )
        return DiagnosticCheck(
            id="DOC-15",
            category="voice",
            status=CheckStatus.WARNING,
            message=f"Voice sidecar status: {probe_status}",
            remediation="Check voice sidecar logs and connectivity",
        )
    except Exception as exc:
        logger.debug("DOC-15 failed: %s", exc)
        return DiagnosticCheck(
            id="DOC-15",
            category="voice",
            status=CheckStatus.ERROR,
            message=f"Voice check failed: {exc}",
            remediation="Check voice daemon configuration and sidecar connectivity",
        )


async def check_backup(app_state: Any) -> DiagnosticCheck:
    """DOC-16: Backup service availability."""
    try:
        backup_svc = getattr(app_state, "backup_service", None)
        if backup_svc is None:
            return DiagnosticCheck(
                id="DOC-16",
                category="backup",
                status=CheckStatus.WARNING,
                message="Backup service not initialized",
                remediation="Set BACKUP_DIR to enable the backup service",
            )
        return DiagnosticCheck(
            id="DOC-16",
            category="backup",
            status=CheckStatus.OK,
            message="Backup service is available",
        )
    except Exception as exc:
        logger.debug("DOC-16 failed: %s", exc)
        return DiagnosticCheck(
            id="DOC-16",
            category="backup",
            status=CheckStatus.ERROR,
            message=f"Backup service check failed: {exc}",
            remediation="Check backup configuration",
        )


ALL_CHECKS: list[tuple[str, DiagnosticCheckFn]] = [
    ("DOC-01", check_database),
    ("DOC-02", check_redis),
    ("DOC-03", check_nats),
    ("DOC-04", check_llm),
    ("DOC-05", check_agents),
    ("DOC-06", check_skills),
    ("DOC-07", check_plugins),
    ("DOC-08", check_packs),
    ("DOC-09", check_security),
    ("DOC-10", check_config),
    ("DOC-11", check_sessions),
    ("DOC-12", check_hooks),
    ("DOC-13", check_scheduler),
    ("DOC-14", check_mcp),
    ("DOC-15", check_voice),
    ("DOC-16", check_backup),
]


async def run_all_checks(app_state: Any) -> list[DiagnosticCheck]:
    """Run every diagnostic check and return results."""
    results: list[DiagnosticCheck] = []
    for check_id, check_fn in ALL_CHECKS:
        try:
            result = await check_fn(app_state)
            results.append(result)
        except Exception as exc:
            logger.exception("Diagnostic check %s raised unexpectedly", check_fn.__name__)
            results.append(
                DiagnosticCheck(
                    id=check_id,
                    category="internal",
                    status=CheckStatus.ERROR,
                    message=f"Check raised unexpectedly: {exc}",
                )
            )
    return results
