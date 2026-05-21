"""Health check endpoints."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, Request, Response

from agent33.config import settings
from agent33.llm.runtime_config import llamacpp_enabled, resolve_default_model

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)
_HEALTHY_REQUIRED_STATES = {"ok", "configured"}
_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
_ANTHROPIC_HEADERS = {"anthropic-version": "2023-06-01"}
_MODEL_PREFIX_PROVIDER_MAP: tuple[tuple[str, str], ...] = (
    ("openrouter/", "openrouter"),
    ("openai/", "openai"),
    ("ollama/", "ollama"),
    ("lmstudio/", "lmstudio"),
    ("llamacpp/", "llamacpp"),
    ("gpt-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("claude-", "anthropic"),
    ("ft:gpt-", "openai"),
    ("airllm-", "airllm"),
)
_LOCAL_RUNTIME_LM_STUDIO_ENGINES = {"lmstudio", "lm-studio"}
_LOCAL_RUNTIME_OLLAMA_ENGINES = {"ollama"}


def _get_adapters() -> dict[str, Any]:
    """Import the adapter registry lazily to avoid circular imports."""
    from agent33.api.routes.webhooks import _adapters

    return _adapters


def _default_provider_name() -> str:
    """Resolve the provider backing the default chat model."""
    default_model = resolve_default_model().strip()
    if not default_model:
        return "llamacpp" if llamacpp_enabled() else "ollama"

    if "/" in default_model:
        provider_name, _model_name = default_model.split("/", 1)
        if provider_name in {
            "anthropic",
            "openai",
            "openrouter",
            "ollama",
            "lmstudio",
            "llamacpp",
            "airllm",
        }:
            return provider_name

    for prefix, provider_name in _MODEL_PREFIX_PROVIDER_MAP:
        if default_model.startswith(prefix):
            return provider_name

    return "llamacpp" if llamacpp_enabled() else "ollama"


def _required_runtime_services() -> set[str]:
    """Return the services the current runtime configuration actually depends on."""
    required = {"redis", "postgres", "nats"}
    provider_name = _default_provider_name()
    startup_engine = settings.local_orchestration_engine.strip().lower()

    if provider_name in {"anthropic", "ollama", "openai", "openrouter"}:
        required.add(provider_name)
    elif provider_name in {"llamacpp", "lmstudio"}:
        required.add("local_orchestration")

    if startup_engine in _LOCAL_RUNTIME_OLLAMA_ENGINES | _LOCAL_RUNTIME_LM_STUDIO_ENGINES:
        required.add("local_orchestration")

    if settings.embedding_provider == "ollama":
        required.add("ollama")
    elif settings.embedding_provider == "jina":
        required.add("jina")

    if settings.voice_daemon_transport == "sidecar" or settings.voice_sidecar_url.strip():
        required.add("voice_sidecar")

    if settings.voice_tts_provider == "elevenlabs" or settings.voice_elevenlabs_enabled:
        required.add("elevenlabs")

    return required


async def _probe_catalog(base_url: str, headers: dict[str, str]) -> str:
    """Check a provider's model catalog endpoint."""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{base_url.rstrip('/')}/models", headers=headers)
            return "ok" if response.status_code == 200 else "degraded"
    except Exception:
        return "unavailable"


async def _probe_ollama(required_services: set[str]) -> str:
    """Check the Ollama dependency required by the active runtime."""
    base_url = settings.runtime_ollama_base_url.rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{base_url}/api/tags")
            if response.status_code != 200:
                return "degraded"

            payload = response.json()
            raw_models = payload.get("models") if isinstance(payload, dict) else None
            if not isinstance(raw_models, list):
                return "degraded"

            model_names = {
                str(item.get("name") or item.get("model") or "").strip().lower()
                for item in raw_models
                if isinstance(item, dict)
            }
            model_names.discard("")
            if not model_names:
                return "degraded"

            expected_models = {
                settings.embedding_default_model.strip().lower()
                for _ in [None]
                if settings.embedding_provider == "ollama" and "ollama" in required_services
            }
            if _default_provider_name() == "ollama":
                configured_default = settings.ollama_default_model.strip().lower()
                if configured_default:
                    expected_models.add(configured_default)

            for configured_model in expected_models:
                if not _ollama_model_is_installed(configured_model, model_names):
                    return "degraded"

            return "ok"
    except Exception:
        return "unavailable"


async def _probe_local_orchestration() -> str:
    """Check the configured startup runtime without sending prompts."""
    engine = settings.local_orchestration_engine.strip().lower()
    runtime_flavor = "local-orchestration"
    base_url = settings.runtime_local_orchestration_base_url.rstrip("/")
    configured_model = settings.local_orchestration_model.strip().lower()
    path = "/models"

    if engine in _LOCAL_RUNTIME_OLLAMA_ENGINES:
        runtime_flavor = "ollama"
        base_url = settings.runtime_ollama_base_url.rstrip("/")
        path = "/api/tags"
    elif engine in _LOCAL_RUNTIME_LM_STUDIO_ENGINES:
        runtime_flavor = "lm-studio"
        base_url = settings.runtime_lm_studio_base_url.rstrip("/")
        path = "/models"

    if not base_url:
        return "unconfigured"

    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{base_url}{path}")
            if response.status_code != 200:
                return "degraded"

            payload = response.json()
            model_names = _extract_runtime_model_names(payload, runtime_flavor)
            if not model_names:
                return "degraded"
            if configured_model and not _ollama_model_is_installed(configured_model, model_names):
                return "degraded"
            return "ok"
    except Exception:
        return "unavailable"


def _extract_runtime_model_names(payload: Any, runtime_flavor: str) -> set[str]:
    """Return normalized model names from a startup runtime listing payload."""
    if not isinstance(payload, dict):
        return set()

    if runtime_flavor == "ollama":
        raw_models = payload.get("models")
        if not isinstance(raw_models, list):
            return set()
        return {
            str(item.get("name") or item.get("model") or "").strip().lower()
            for item in raw_models
            if isinstance(item, dict) and str(item.get("name") or item.get("model") or "").strip()
        }

    raw_models = payload.get("data")
    if not isinstance(raw_models, list):
        return set()
    return {
        str(item.get("id") or item.get("name") or "").strip().lower()
        for item in raw_models
        if isinstance(item, dict) and str(item.get("id") or item.get("name") or "").strip()
    }


def _ollama_model_is_installed(configured_model: str, installed_models: set[str]) -> bool:
    """Return True when the configured Ollama model appears in the installed set."""
    normalized = configured_model.strip().lower()
    if not normalized:
        return True

    configured_aliases = {normalized, normalized.removesuffix(":latest")}
    for model_name in installed_models:
        normalized_model = model_name.strip().lower()
        if not normalized_model:
            continue
        installed_aliases = {normalized_model, normalized_model.removesuffix(":latest")}
        if configured_aliases & installed_aliases:
            return True
        if any(
            normalized_model.startswith(f"{alias}:") or alias.startswith(f"{normalized_model}:")
            for alias in configured_aliases
            if alias
        ):
            return True
    return False


def _required_service_healthy(status: str) -> bool:
    """Return True when a required dependency is in an acceptable state."""
    return status in _HEALTHY_REQUIRED_STATES


def _anthropic_api_key() -> str:
    """Return the Anthropic key when present in the process environment."""
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


async def _core_dependency_checks(required_services: set[str] | None = None) -> dict[str, str]:
    """Probe the dependencies required for normal API operation."""
    checks: dict[str, str] = {}
    required = required_services or _required_runtime_services()

    if "ollama" in required:
        checks["ollama"] = await _probe_ollama(required)
    else:
        checks["ollama"] = "configured" if settings.runtime_ollama_base_url else "unconfigured"

    if "local_orchestration" in required:
        checks["local_orchestration"] = await _probe_local_orchestration()
    else:
        checks["local_orchestration"] = (
            "configured" if settings.runtime_local_orchestration_base_url else "unconfigured"
        )

    try:
        import redis.asyncio as aioredis

        redis_client = aioredis.from_url(settings.redis_url)  # type: ignore[no-untyped-call]
        await asyncio.wait_for(redis_client.ping(), timeout=3)
        await redis_client.aclose()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"

    try:
        import asyncpg

        connection = await asyncio.wait_for(
            asyncpg.connect(
                settings.database_url.replace("+asyncpg", "").replace("postgresql", "postgres")
            ),
            timeout=3,
        )
        await asyncio.wait_for(connection.execute("SELECT 1"), timeout=3)
        await connection.close()
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "unavailable"

    try:
        import nats

        nc = await asyncio.wait_for(nats.connect(settings.nats_url), timeout=3)
        await nc.close()
        checks["nats"] = "ok"
    except Exception:
        checks["nats"] = "unavailable"

    return checks


@router.get("/health")
async def health(request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    """Aggregate health check for all services."""
    checks: dict[str, str] = {}
    include_external_checks = request is not None
    required_services = _required_runtime_services()

    if include_external_checks:
        # Route requests get the full dependency probe set. Direct test calls
        # without a Request object only exercise channel aggregation.
        checks.update(await _core_dependency_checks(required_services))

        # External Integrations
        if settings.openai_api_key.get_secret_value():
            if "openai" in required_services:
                openai_base_url = settings.openai_base_url.strip() or "https://api.openai.com/v1"
                checks["openai"] = await _probe_catalog(
                    openai_base_url,
                    {
                        "Authorization": f"Bearer {settings.openai_api_key.get_secret_value()}",
                    },
                )
            else:
                checks["openai"] = "configured"
        else:
            checks["openai"] = "unconfigured"

        if settings.openrouter_api_key.get_secret_value():
            if "openrouter" in required_services:
                checks["openrouter"] = await _probe_catalog(
                    settings.openrouter_base_url,
                    {
                        "Authorization": (
                            f"Bearer {settings.openrouter_api_key.get_secret_value()}"
                        ),
                        "HTTP-Referer": settings.openrouter_site_url,
                        "X-OpenRouter-Title": settings.openrouter_app_name,
                    },
                )
            else:
                checks["openrouter"] = "configured"
        else:
            checks["openrouter"] = "unconfigured"

        anthropic_api_key = _anthropic_api_key()
        if anthropic_api_key:
            if "anthropic" in required_services:
                checks["anthropic"] = await _probe_catalog(
                    _ANTHROPIC_BASE_URL,
                    {
                        **_ANTHROPIC_HEADERS,
                        "x-api-key": anthropic_api_key,
                    },
                )
            else:
                checks["anthropic"] = "configured"
        else:
            checks["anthropic"] = "unconfigured"

        if settings.elevenlabs_api_key.get_secret_value():
            if "elevenlabs" in required_services:
                checks["elevenlabs"] = await _probe_catalog(
                    "https://api.elevenlabs.io/v1",
                    {"xi-api-key": settings.elevenlabs_api_key.get_secret_value()},
                )
            else:
                checks["elevenlabs"] = "configured"
        else:
            checks["elevenlabs"] = "unconfigured"

        if settings.jina_api_key.get_secret_value():
            # Jina reader uses a simple ping since /models isn't universally standard
            checks["jina"] = "configured"
        else:
            checks["jina"] = "unconfigured"

    # Messaging channels
    adapters = _get_adapters()
    for platform, adapter in adapters.items():
        try:
            result = await adapter.health_check()
            checks[f"channel:{platform}"] = result.status
        except Exception:
            checks[f"channel:{platform}"] = "unavailable"

    app_state = request.app.state if request is not None else None

    voice_probe = getattr(app_state, "voice_sidecar_probe", None)
    if voice_probe is not None:
        voice_snapshot = await voice_probe.health_snapshot()
        checks["voice_sidecar"] = str(voice_snapshot.get("status", "unavailable"))
    else:
        checks["voice_sidecar"] = "unconfigured"

    status_line_service = getattr(app_state, "status_line_service", None)
    if status_line_service is not None:
        status_line_snapshot = await status_line_service.health_snapshot()
        checks["status_line"] = str(status_line_snapshot.get("status", "unavailable"))
    else:
        checks["status_line"] = "unconfigured"

    # Connector fleet (MCP proxy + boundary connectors)
    proxy_manager = getattr(app_state, "proxy_manager", None)
    if proxy_manager is not None:
        fleet = proxy_manager.health_summary()
        fleet_total = fleet.get("total", 0)
        fleet_healthy = fleet.get("healthy", 0)
        fleet_degraded = fleet.get("degraded", 0)
        if fleet_total == 0:
            checks["connectors"] = "idle"
        elif fleet_healthy == fleet_total:
            checks["connectors"] = "ok"
        elif fleet_degraded > 0 or fleet_healthy > 0:
            checks["connectors"] = "degraded"
        else:
            checks["connectors"] = "unavailable"
    else:
        checks["connectors"] = "unconfigured"

    # Emit health check metrics when a metrics collector is available
    collector = getattr(app_state, "metrics_collector", None)
    if collector is not None:
        for svc_name, svc_status in checks.items():
            collector.observe(
                "health_check_result",
                1.0 if svc_status == "ok" else 0.0,
                {"service": svc_name},
            )

    required_snapshot = {
        service_name: checks[service_name]
        for service_name in sorted(required_services)
        if service_name in checks
    }
    failures = {
        service_name: service_status
        for service_name, service_status in required_snapshot.items()
        if not _required_service_healthy(service_status)
    }
    warnings = {
        service_name: service_status
        for service_name, service_status in checks.items()
        if service_name not in required_services and service_status in {"degraded", "unavailable"}
    }
    channel_failures = {
        service_name: service_status
        for service_name, service_status in warnings.items()
        if service_name.startswith("channel:")
    }
    health_result: dict[str, Any] = {
        "status": "healthy" if not failures and not channel_failures else "degraded",
        "services": checks,
        "required_services": required_snapshot,
    }
    if warnings:
        health_result["warnings"] = warnings

    # Attach runtime version info if available
    runtime_info = getattr(app_state, "runtime_version_info", None)
    if runtime_info is not None:
        health_result["runtime_version"] = runtime_info.version
        health_result["git_short_hash"] = runtime_info.git_short_hash

    return health_result


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Lightweight process health for liveness probes."""
    return {"status": "healthy"}


@router.get("/readyz")
async def readyz(request: Request, response: Response) -> dict[str, Any]:
    """Kubernetes readiness probe for active runtime dependencies."""
    required_services = _required_runtime_services()
    checks = await _core_dependency_checks(required_services)

    if "openai" in required_services:
        if settings.openai_api_key.get_secret_value():
            openai_base_url = settings.openai_base_url.strip() or "https://api.openai.com/v1"
            checks["openai"] = await _probe_catalog(
                openai_base_url,
                {"Authorization": f"Bearer {settings.openai_api_key.get_secret_value()}"},
            )
        else:
            checks["openai"] = "unconfigured"

    if "openrouter" in required_services:
        if settings.openrouter_api_key.get_secret_value():
            checks["openrouter"] = await _probe_catalog(
                settings.openrouter_base_url,
                {
                    "Authorization": f"Bearer {settings.openrouter_api_key.get_secret_value()}",
                    "HTTP-Referer": settings.openrouter_site_url,
                    "X-OpenRouter-Title": settings.openrouter_app_name,
                },
            )
        else:
            checks["openrouter"] = "unconfigured"

    if "anthropic" in required_services:
        anthropic_api_key = _anthropic_api_key()
        if anthropic_api_key:
            checks["anthropic"] = await _probe_catalog(
                _ANTHROPIC_BASE_URL,
                {
                    **_ANTHROPIC_HEADERS,
                    "x-api-key": anthropic_api_key,
                },
            )
        else:
            checks["anthropic"] = "unconfigured"

    if "jina" in required_services:
        checks["jina"] = (
            "configured" if settings.jina_api_key.get_secret_value() else "unconfigured"
        )

    if "voice_sidecar" in required_services:
        voice_probe = getattr(request.app.state, "voice_sidecar_probe", None)
        if voice_probe is None:
            checks["voice_sidecar"] = "unconfigured"
        else:
            voice_snapshot = await voice_probe.health_snapshot()
            checks["voice_sidecar"] = str(voice_snapshot.get("status", "unavailable"))

    ready_checks = {
        service_name: checks[service_name]
        for service_name in sorted(required_services)
        if service_name in checks
    }
    healthy = all(_required_service_healthy(status) for status in ready_checks.values())
    response.status_code = 200 if healthy else 503
    return {
        "status": "healthy" if healthy else "degraded",
        "services": ready_checks,
    }


@router.get("/health/channels")
async def channel_health() -> dict[str, Any]:
    """Detailed health check for all registered messaging channels."""
    adapters = _get_adapters()
    results: dict[str, Any] = {}
    for platform, adapter in adapters.items():
        try:
            result = await adapter.health_check()
            results[platform] = result.model_dump()
        except Exception as exc:
            results[platform] = {
                "platform": platform,
                "status": "unavailable",
                "detail": str(exc),
            }
    return {"channels": results}
