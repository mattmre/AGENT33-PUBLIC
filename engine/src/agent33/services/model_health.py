"""Unified local model health for beginner setup UX."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import ip_address
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from agent33.services.lm_studio_readiness import normalize_lm_studio_base_url
from agent33.services.ollama_readiness import normalize_ollama_base_url

if TYPE_CHECKING:
    from agent33.config import Settings
    from agent33.services.lm_studio_readiness import (
        LMStudioReadinessService,
        LMStudioStatusResponse,
    )
    from agent33.services.ollama_readiness import (
        OllamaReadinessService,
        OllamaStatusResponse,
    )

LocalModelProvider = Literal["ollama", "lm-studio", "local-orchestration"]
LocalModelProviderState = Literal["available", "empty", "unavailable", "error"]
UnifiedModelHealthState = Literal["ready", "needs_attention", "unavailable"]
TaskModelRouteKind = Literal["coding", "research", "quick_task", "long_context", "local_private"]


class LocalModelProviderHealth(BaseModel):
    """Provider-level model health safe for operator setup UI."""

    provider: LocalModelProvider
    label: str
    state: LocalModelProviderState
    ok: bool
    base_url: str
    default_model: str
    checked_at: datetime
    model_count: int = 0
    message: str
    action: str


class UnifiedModelHealthResponse(BaseModel):
    """Combined local runtime health across supported beginner providers."""

    provider_count: int = 0
    ready_provider_count: int = 0
    attention_provider_count: int = 0
    total_model_count: int = 0
    overall_state: UnifiedModelHealthState
    summary: str
    checked_at: datetime
    providers: list[LocalModelProviderHealth] = Field(default_factory=list)


class TaskModelRoutingRequest(BaseModel):
    """Operator request for task-to-model routing."""

    task_kind: TaskModelRouteKind
    objective: str = ""


class TaskModelRoutingResponse(BaseModel):
    """Auditable model recommendation for a task class."""

    task_kind: TaskModelRouteKind
    recommended_provider: LocalModelProvider | None
    recommended_model: str
    fallback_models: list[str] = Field(default_factory=list)
    readiness: Literal["ready", "needs_setup", "unavailable"]
    reason: str
    checked_at: datetime


class JudgmentPanelRequest(BaseModel):
    """High-impact proposal review request."""

    proposal_id: str
    title: str
    summary: str
    evidence: list[str] = Field(default_factory=list)
    rollback_plan: str = ""
    tests: list[str] = Field(default_factory=list)
    risk_notes: str = ""


class JudgmentPanelVote(BaseModel):
    provider: LocalModelProvider
    model: str
    decision: Literal["approve", "revise", "block"]
    reasons: list[str] = Field(default_factory=list)


class JudgmentPanelResponse(BaseModel):
    proposal_id: str
    readiness: Literal["ready", "needs_setup", "blocked"]
    consensus: Literal["approve", "revise", "block", "unavailable"]
    ready_model_count: int
    required_model_count: int
    votes: list[JudgmentPanelVote] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)
    checked_at: datetime


class LocalOrchestrationStatusResponse(BaseModel):
    """OpenAI-compatible local orchestration runtime health."""

    provider: Literal["local-orchestration"] = "local-orchestration"
    state: LocalModelProviderState
    ok: bool
    base_url: str
    default_model: str
    checked_at: datetime
    count: int = 0
    message: str


@dataclass(slots=True)
class _LocalOrchestrationFetchResult:
    status_code: int | None
    payload: Any = None
    error: str | None = None


FetchLocalOrchestrationPayload = Callable[[str], Awaitable[_LocalOrchestrationFetchResult]]

_ALLOWED_LOCAL_ORCHESTRATION_OVERRIDE_HOSTS = {
    "localhost",
    "127.0.0.1",
    "::1",
    "host.docker.internal",
}
_LOCAL_ORCHESTRATION_OLLAMA_ENGINES = {"ollama"}
_LOCAL_ORCHESTRATION_LM_STUDIO_ENGINES = {"lmstudio", "lm-studio"}
_LOCAL_ORCHESTRATION_OPENAI_COMPATIBLE_ENGINES = {
    "llama.cpp",
    "llamacpp",
    "llama-cpp",
    "vllm",
    "v-llm",
    "tgi",
    "text-generation-inference",
    "textgenerationinference",
    "openai-compatible",
    "openai_compatible",
    "local-openai",
}


def _normalized_engine(engine: str) -> str:
    return engine.strip().lower().replace(" ", "").replace("_", "-")


def _local_runtime_flavor(engine: str) -> Literal["ollama", "lm-studio", "local-orchestration"]:
    normalized = _normalized_engine(engine)
    if normalized in _LOCAL_ORCHESTRATION_OLLAMA_ENGINES:
        return "ollama"
    if normalized in _LOCAL_ORCHESTRATION_LM_STUDIO_ENGINES:
        return "lm-studio"
    return "local-orchestration"


def normalize_local_orchestration_base_url(base_url: str, *, engine: str = "") -> str:
    """Return the effective base URL for the configured startup runtime."""

    runtime_flavor = _local_runtime_flavor(engine)
    if runtime_flavor == "ollama":
        return normalize_ollama_base_url(base_url)
    if runtime_flavor == "lm-studio":
        return normalize_lm_studio_base_url(base_url)

    normalized = base_url.strip().rstrip("/")
    if not normalized or normalized.lower().endswith("/v1"):
        return normalized
    return f"{normalized}/v1"


class LocalOrchestrationReadinessService:
    """Probe the local orchestration server without sending prompts or project data."""

    def __init__(
        self,
        settings: Settings,
        *,
        timeout_seconds: float = 5.0,
        fetcher: FetchLocalOrchestrationPayload | None = None,
    ) -> None:
        self._settings = settings
        self._timeout_seconds = timeout_seconds
        self._fetcher = fetcher or self._fetch

    @property
    def label(self) -> str:
        """Return a short operator-facing label for the configured engine."""

        return self._label_for_engine(self._settings.local_orchestration_engine)

    async def status(self, base_url: str | None = None) -> LocalOrchestrationStatusResponse:
        """Return service reachability and available local model metadata."""

        checked_at = datetime.now(UTC)
        runtime_flavor = _local_runtime_flavor(self._settings.local_orchestration_engine)
        configured_base_url = self._configured_base_url(runtime_flavor)
        configured_model = self._configured_default_model(runtime_flavor)
        resolved_base_url = configured_base_url
        if base_url is not None and base_url.strip():
            resolved_base_url = normalize_local_orchestration_base_url(
                base_url,
                engine=self._settings.local_orchestration_engine,
            )
            if not self._is_safe_override_base_url(resolved_base_url, configured_base_url):
                return LocalOrchestrationStatusResponse(
                    state="error",
                    ok=False,
                    base_url=resolved_base_url,
                    default_model=configured_model,
                    checked_at=checked_at,
                    message=(
                        "Local orchestration base URL overrides must use http(s) and either "
                        "exactly match the configured runtime base URL or point to "
                        "localhost, host.docker.internal, or a loopback IP address."
                    ),
                )

        if not resolved_base_url:
            return LocalOrchestrationStatusResponse(
                state="unavailable",
                ok=False,
                base_url="",
                default_model=configured_model,
                checked_at=checked_at,
                message="Local orchestration is not configured yet.",
            )

        if runtime_flavor == "ollama":
            return await self._status_from_ollama(
                base_url=resolved_base_url,
                default_model=configured_model,
                checked_at=checked_at,
            )

        return await self._status_from_openai_compatible(
            base_url=resolved_base_url,
            default_model=configured_model,
            checked_at=checked_at,
        )

    def _configured_base_url(
        self,
        runtime_flavor: Literal["ollama", "lm-studio", "local-orchestration"],
    ) -> str:
        if runtime_flavor == "ollama":
            return normalize_local_orchestration_base_url(
                self._settings.runtime_ollama_base_url,
                engine=self._settings.local_orchestration_engine,
            )
        if runtime_flavor == "lm-studio":
            return normalize_local_orchestration_base_url(
                self._settings.runtime_lm_studio_base_url,
                engine=self._settings.local_orchestration_engine,
            )
        return normalize_local_orchestration_base_url(
            self._settings.runtime_local_orchestration_base_url,
            engine=self._settings.local_orchestration_engine,
        )

    def _configured_default_model(
        self,
        runtime_flavor: Literal["ollama", "lm-studio", "local-orchestration"],
    ) -> str:
        configured = self._settings.local_orchestration_model.strip()
        if configured:
            return configured
        if runtime_flavor == "ollama":
            return self._settings.ollama_default_model
        if runtime_flavor == "lm-studio":
            return self._settings.lm_studio_default_model
        return self._settings.local_orchestration_model

    async def _status_from_openai_compatible(
        self,
        *,
        base_url: str,
        default_model: str,
        checked_at: datetime,
    ) -> LocalOrchestrationStatusResponse:
        result = await self._fetcher(f"{base_url}/models")
        if result.error or result.status_code != 200:
            detail = result.error or f"HTTP {result.status_code}"
            return LocalOrchestrationStatusResponse(
                state="unavailable",
                ok=False,
                base_url=base_url,
                default_model=default_model,
                checked_at=checked_at,
                message=f"Local orchestration is not reachable at {base_url}: {detail}",
            )

        payload = result.payload if isinstance(result.payload, dict) else {}
        raw_models = payload.get("data")
        if not isinstance(raw_models, list):
            return LocalOrchestrationStatusResponse(
                state="error",
                ok=False,
                base_url=base_url,
                default_model=default_model,
                checked_at=checked_at,
                message=(
                    "Local orchestration responded, but /v1/models returned an unexpected payload."
                ),
            )

        models = [
            item
            for item in raw_models
            if isinstance(item, dict) and str(item.get("id") or item.get("name") or "").strip()
        ]
        if not models:
            return LocalOrchestrationStatusResponse(
                state="empty",
                ok=False,
                base_url=base_url,
                default_model=default_model,
                checked_at=checked_at,
                message="Local orchestration is running, but no models are loaded yet.",
            )

        model_ids = [
            str(item.get("id") or item.get("name") or "").strip()
            for item in models
            if isinstance(item, dict)
        ]
        if not self._configured_model_is_listed(default_model, model_ids):
            return LocalOrchestrationStatusResponse(
                state="error",
                ok=False,
                base_url=base_url,
                default_model=default_model,
                checked_at=checked_at,
                count=len(model_ids),
                message=(
                    "Local orchestration is reachable, but the configured startup model "
                    f"{default_model} is not listed."
                ),
            )

        return LocalOrchestrationStatusResponse(
            state="available",
            ok=True,
            base_url=base_url,
            default_model=default_model,
            checked_at=checked_at,
            count=len(model_ids),
            message=(
                f"Detected {len(model_ids)} local orchestration model"
                f"{'s' if len(model_ids) != 1 else ''}."
            ),
        )

    async def _status_from_ollama(
        self,
        *,
        base_url: str,
        default_model: str,
        checked_at: datetime,
    ) -> LocalOrchestrationStatusResponse:
        result = await self._fetcher(f"{base_url}/api/tags")
        if result.error or result.status_code != 200:
            detail = result.error or f"HTTP {result.status_code}"
            return LocalOrchestrationStatusResponse(
                state="unavailable",
                ok=False,
                base_url=base_url,
                default_model=default_model,
                checked_at=checked_at,
                message=f"Ollama startup runtime is not reachable at {base_url}: {detail}",
            )

        payload = result.payload if isinstance(result.payload, dict) else {}
        raw_models = payload.get("models")
        if not isinstance(raw_models, list):
            return LocalOrchestrationStatusResponse(
                state="error",
                ok=False,
                base_url=base_url,
                default_model=default_model,
                checked_at=checked_at,
                message="Ollama responded, but /api/tags returned an unexpected payload.",
            )

        model_ids = [
            str(item.get("name") or item.get("model") or "").strip()
            for item in raw_models
            if isinstance(item, dict) and str(item.get("name") or item.get("model") or "").strip()
        ]
        if not model_ids:
            return LocalOrchestrationStatusResponse(
                state="empty",
                ok=False,
                base_url=base_url,
                default_model=default_model,
                checked_at=checked_at,
                message=(
                    "Ollama startup runtime is running, but no local models are installed yet."
                ),
            )
        if not self._configured_model_is_listed(default_model, model_ids):
            return LocalOrchestrationStatusResponse(
                state="error",
                ok=False,
                base_url=base_url,
                default_model=default_model,
                checked_at=checked_at,
                count=len(model_ids),
                message=(
                    "Ollama is reachable, but the configured startup model "
                    f"{default_model} is not installed."
                ),
            )

        return LocalOrchestrationStatusResponse(
            state="available",
            ok=True,
            base_url=base_url,
            default_model=default_model,
            checked_at=checked_at,
            count=len(model_ids),
            message=(
                f"Detected {len(model_ids)} startup Ollama model"
                f"{'s' if len(model_ids) != 1 else ''}."
            ),
        )

    async def _fetch(self, url: str) -> _LocalOrchestrationFetchResult:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(url)
                payload = response.json()
                return _LocalOrchestrationFetchResult(
                    status_code=response.status_code, payload=payload
                )
        except (httpx.HTTPError, ValueError) as exc:
            return _LocalOrchestrationFetchResult(status_code=None, error=str(exc))

    @staticmethod
    def _is_safe_override_base_url(base_url: str, configured_base_url: str) -> bool:
        if base_url == configured_base_url:
            return True

        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            return False

        host = parsed.hostname.lower()
        if host in _ALLOWED_LOCAL_ORCHESTRATION_OVERRIDE_HOSTS:
            return True

        try:
            return ip_address(host).is_loopback
        except ValueError:
            return False

    @staticmethod
    def _label_for_engine(engine: str) -> str:
        normalized = engine.strip()
        if not normalized:
            return "Local runtime"

        lower = normalized.lower().replace(" ", "")
        if lower in _LOCAL_ORCHESTRATION_OLLAMA_ENGINES:
            return "Ollama"
        if lower in _LOCAL_ORCHESTRATION_LM_STUDIO_ENGINES:
            return "LM Studio"
        if lower in {"llama.cpp", "llamacpp", "llama-cpp"}:
            return "llama.cpp"
        if lower in {"vllm", "v-llm"}:
            return "vLLM"
        if lower in {"tgi", "text-generation-inference", "textgenerationinference"}:
            return "TGI"
        if any(ch.isupper() for ch in normalized):
            return normalized
        return normalized.replace("_", " ").replace("-", " ").title()

    @staticmethod
    def _configured_model_is_listed(configured_model: str, model_ids: list[str]) -> bool:
        normalized_configured = configured_model.strip().lower()
        if not normalized_configured:
            return True

        configured_aliases = {
            normalized_configured,
            normalized_configured.removesuffix(":latest"),
        }
        for model_id in model_ids:
            normalized_model_id = model_id.strip().lower()
            if not normalized_model_id:
                continue
            model_aliases = {
                normalized_model_id,
                normalized_model_id.removesuffix(":latest"),
            }
            if configured_aliases & model_aliases:
                return True
            if any(
                normalized_model_id.startswith(f"{alias}:")
                or alias.startswith(f"{normalized_model_id}:")
                for alias in configured_aliases
                if alias
            ):
                return True
        return False


class ModelHealthService:
    """Aggregate local model readiness without duplicating provider probes."""

    def __init__(
        self,
        *,
        ollama_service: OllamaReadinessService,
        lm_studio_service: LMStudioReadinessService,
        local_orchestration_service: LocalOrchestrationReadinessService,
    ) -> None:
        self._ollama_service = ollama_service
        self._lm_studio_service = lm_studio_service
        self._local_orchestration_service = local_orchestration_service

    async def status(
        self,
        *,
        ollama_base_url: str | None = None,
        lm_studio_base_url: str | None = None,
        local_orchestration_base_url: str | None = None,
    ) -> UnifiedModelHealthResponse:
        """Return a unified health summary for local model providers."""

        checked_at = datetime.now(UTC)
        results = await asyncio.gather(
            self._ollama_service.status(base_url=ollama_base_url),
            self._lm_studio_service.status(base_url=lm_studio_base_url),
            self._local_orchestration_service.status(base_url=local_orchestration_base_url),
            return_exceptions=True,
        )
        providers = [
            self._coerce_result(
                results[0],
                checked_at,
                provider="ollama",
                label="Ollama",
            ),
            self._coerce_result(
                results[1],
                checked_at,
                provider="lm-studio",
                label="LM Studio",
            ),
            self._coerce_result(
                results[2],
                checked_at,
                provider="local-orchestration",
                label=self._local_orchestration_service.label,
            ),
        ]
        ready_provider_count = sum(1 for provider in providers if provider.ok)
        attention_provider_count = sum(
            1 for provider in providers if provider.state in {"empty", "error"}
        )
        total_model_count = sum(provider.model_count for provider in providers)
        overall_state = self._overall_state(
            ready_provider_count=ready_provider_count,
            attention_provider_count=attention_provider_count,
        )

        return UnifiedModelHealthResponse(
            provider_count=len(providers),
            ready_provider_count=ready_provider_count,
            attention_provider_count=attention_provider_count,
            total_model_count=total_model_count,
            overall_state=overall_state,
            summary=self._summary(
                overall_state=overall_state,
                ready_provider_count=ready_provider_count,
                total_model_count=total_model_count,
            ),
            checked_at=checked_at,
            providers=providers,
        )

    @staticmethod
    def _overall_state(
        *,
        ready_provider_count: int,
        attention_provider_count: int,
    ) -> UnifiedModelHealthState:
        if ready_provider_count > 0:
            return "ready"
        if attention_provider_count > 0:
            return "needs_attention"
        return "unavailable"

    @staticmethod
    def _summary(
        *,
        overall_state: UnifiedModelHealthState,
        ready_provider_count: int,
        total_model_count: int,
    ) -> str:
        if overall_state == "ready":
            provider_label = "runtime" if ready_provider_count == 1 else "runtimes"
            model_label = "model" if total_model_count == 1 else "models"
            return (
                f"{ready_provider_count} local {provider_label} ready with "
                f"{total_model_count} detected {model_label}."
            )
        if overall_state == "needs_attention":
            return (
                "Local model setup needs attention. Install or load a model, or start "
                "Ollama, LM Studio, or the local orchestration server."
            )
        return (
            "No local model runtime is reachable yet. Start Ollama, LM Studio, or the "
            "local orchestration server to use local models."
        )

    @staticmethod
    def _coerce_result(
        result: OllamaStatusResponse
        | LMStudioStatusResponse
        | LocalOrchestrationStatusResponse
        | BaseException,
        checked_at: datetime,
        *,
        provider: LocalModelProvider,
        label: str,
    ) -> LocalModelProviderHealth:
        if isinstance(result, BaseException):
            return LocalModelProviderHealth(
                provider=provider,
                label=label,
                state="error",
                ok=False,
                base_url="",
                default_model="",
                checked_at=checked_at,
                message=f"Could not check {label}: {result}",
                action=f"Check the {label} runtime configuration.",
            )
        return LocalModelProviderHealth(
            provider=provider,
            label=label,
            state=result.state,
            ok=result.ok,
            base_url=result.base_url,
            default_model=result.default_model,
            checked_at=result.checked_at,
            model_count=result.count,
            message=result.message,
            action=ModelHealthService._action_for_state(label, result.state),
        )

    @staticmethod
    def _action_for_state(provider_label: str, state: LocalModelProviderState) -> str:
        if state == "available":
            return f"Choose a detected {provider_label} model for local workflows."
        if state == "empty":
            return f"Install or load a model in {provider_label}, then refresh health."
        if state == "unavailable":
            return f"Start {provider_label}, then refresh health."
        return f"Check the {provider_label} base URL and runtime settings."


def recommend_model_for_task(
    request: TaskModelRoutingRequest,
    health: UnifiedModelHealthResponse,
) -> TaskModelRoutingResponse:
    """Recommend an available model/provider for a task class using health data."""
    ready = [provider for provider in health.providers if provider.ok and provider.model_count > 0]
    if not ready:
        return TaskModelRoutingResponse(
            task_kind=request.task_kind,
            recommended_provider=None,
            recommended_model="",
            fallback_models=[],
            readiness="unavailable",
            reason="No model provider is ready with at least one model.",
            checked_at=health.checked_at,
        )

    preferred_order: dict[TaskModelRouteKind, tuple[LocalModelProvider, ...]] = {
        "coding": ("local-orchestration", "lm-studio", "ollama"),
        "research": ("local-orchestration", "lm-studio", "ollama"),
        "quick_task": ("ollama", "lm-studio", "local-orchestration"),
        "long_context": ("lm-studio", "local-orchestration", "ollama"),
        "local_private": ("ollama", "lm-studio", "local-orchestration"),
    }
    by_provider = {provider.provider: provider for provider in ready}
    selected = next(
        (
            by_provider[provider]
            for provider in preferred_order[request.task_kind]
            if provider in by_provider
        ),
        ready[0],
    )
    fallbacks = [
        provider.default_model
        for provider in ready
        if provider.provider != selected.provider and provider.default_model
    ]
    return TaskModelRoutingResponse(
        task_kind=request.task_kind,
        recommended_provider=selected.provider,
        recommended_model=selected.default_model,
        fallback_models=fallbacks,
        readiness="ready",
        reason=(
            f"{selected.label} is ready and best matches the "
            f"{request.task_kind.replace('_', ' ')} task policy."
        ),
        checked_at=health.checked_at,
    )


def build_judgment_panel(
    request: JudgmentPanelRequest,
    health: UnifiedModelHealthResponse,
    *,
    required_model_count: int = 2,
) -> JudgmentPanelResponse:
    """Build a readiness-gated deterministic judgment panel from provider health."""
    ready = [provider for provider in health.providers if provider.ok and provider.model_count > 0]
    if len(ready) < required_model_count:
        return JudgmentPanelResponse(
            proposal_id=request.proposal_id,
            readiness="needs_setup",
            consensus="unavailable",
            ready_model_count=len(ready),
            required_model_count=required_model_count,
            failure_reasons=[
                (
                    f"Judgment panel requires {required_model_count} ready model providers; "
                    f"{len(ready)} ready."
                )
            ],
            checked_at=health.checked_at,
        )

    votes = [
        JudgmentPanelVote(
            provider=provider.provider,
            model=provider.default_model,
            decision=_judge_proposal(request, provider.provider),
            reasons=_judgment_reasons(request),
        )
        for provider in ready[:required_model_count]
    ]
    decisions = [vote.decision for vote in votes]
    if "block" in decisions:
        consensus: Literal["approve", "revise", "block", "unavailable"] = "block"
    elif all(decision == "approve" for decision in decisions):
        consensus = "approve"
    else:
        consensus = "revise"

    return JudgmentPanelResponse(
        proposal_id=request.proposal_id,
        readiness="ready",
        consensus=consensus,
        ready_model_count=len(ready),
        required_model_count=required_model_count,
        votes=votes,
        checked_at=health.checked_at,
    )


def _judge_proposal(
    request: JudgmentPanelRequest,
    provider: LocalModelProvider,
) -> Literal["approve", "revise", "block"]:
    missing = _missing_proposal_controls(request)
    risk_text = f"{request.summary} {request.risk_notes}".lower()
    if "destructive" in risk_text and not request.rollback_plan.strip():
        return "block"
    if missing:
        return "revise"
    if provider == "ollama" and "external credential" in risk_text:
        return "revise"
    return "approve"


def _judgment_reasons(request: JudgmentPanelRequest) -> list[str]:
    missing = _missing_proposal_controls(request)
    reasons: list[str] = []
    if missing:
        reasons.append(f"Missing proposal controls: {', '.join(missing)}.")
    else:
        reasons.append("Evidence, rollback, and test controls are present.")
    if request.risk_notes.strip():
        reasons.append("Risk notes supplied for panel review.")
    return reasons


def _missing_proposal_controls(request: JudgmentPanelRequest) -> list[str]:
    missing: list[str] = []
    if not request.evidence:
        missing.append("evidence")
    if not request.rollback_plan.strip():
        missing.append("rollback_plan")
    if not request.tests:
        missing.append("tests")
    return missing
