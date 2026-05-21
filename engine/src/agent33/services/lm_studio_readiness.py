"""LM Studio readiness probes for beginner setup UX."""

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

if TYPE_CHECKING:
    from agent33.config import Settings


class LMStudioModelSummary(BaseModel):
    """Frontend-friendly local LM Studio model entry."""

    id: str
    name: str
    owned_by: str | None = None
    created: int | None = None
    context_length: int | None = None


class LMStudioStatusResponse(BaseModel):
    """LM Studio status and model availability for setup UX."""

    provider: Literal["lm-studio"] = "lm-studio"
    state: Literal["available", "empty", "unavailable", "error"]
    ok: bool
    base_url: str
    default_model: str
    checked_at: datetime
    count: int = 0
    models: list[LMStudioModelSummary] = Field(default_factory=list)
    message: str


class LMStudioModelsResponse(BaseModel):
    """LM Studio model list response."""

    provider: Literal["lm-studio"] = "lm-studio"
    state: Literal["available", "empty", "unavailable", "error"]
    ok: bool
    base_url: str
    count: int = 0
    models: list[LMStudioModelSummary] = Field(default_factory=list)
    message: str


@dataclass(slots=True)
class _LMStudioFetchResult:
    status_code: int | None
    payload: Any = None
    error: str | None = None


FetchLMStudioPayload = Callable[[str], Awaitable[_LMStudioFetchResult]]

_ALLOWED_LM_STUDIO_OVERRIDE_HOSTS = {
    "localhost",
    "127.0.0.1",
    "::1",
    "host.docker.internal",
}


def normalize_lm_studio_base_url(base_url: str) -> str:
    """Return the OpenAI-compatible LM Studio /v1 base URL."""

    normalized = base_url.strip().rstrip("/")
    if not normalized or normalized.lower().endswith("/v1"):
        return normalized
    return f"{normalized}/v1"


class LMStudioReadinessService:
    """Probe LM Studio without sending prompts, credentials, or project data."""

    def __init__(
        self,
        settings: Settings,
        *,
        timeout_seconds: float = 5.0,
        fetcher: FetchLMStudioPayload | None = None,
    ) -> None:
        self._settings = settings
        self._timeout_seconds = timeout_seconds
        self._fetcher = fetcher or self._fetch
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

    async def status(self, base_url: str | None = None) -> LMStudioStatusResponse:
        """Return service reachability and available local model metadata."""

        checked_at = datetime.now(UTC)
        configured_base_url = normalize_lm_studio_base_url(
            self._settings.runtime_lm_studio_base_url
        )
        resolved_base_url = configured_base_url
        if base_url is not None and base_url.strip():
            resolved_base_url = normalize_lm_studio_base_url(base_url)
            if not self._is_safe_override_base_url(resolved_base_url, configured_base_url):
                return LMStudioStatusResponse(
                    state="error",
                    ok=False,
                    base_url=resolved_base_url,
                    default_model=self._settings.lm_studio_default_model,
                    checked_at=checked_at,
                    message=(
                        "LM Studio base URL overrides must use http(s) and either exactly "
                        "match the configured runtime base URL or point to localhost, "
                        "host.docker.internal, or a loopback IP address."
                    ),
                )

        result = await self._fetcher(f"{resolved_base_url}/models")
        if result.error or result.status_code != 200:
            detail = result.error or f"HTTP {result.status_code}"
            return LMStudioStatusResponse(
                state="unavailable",
                ok=False,
                base_url=resolved_base_url,
                default_model=self._settings.lm_studio_default_model,
                checked_at=checked_at,
                message=f"LM Studio is not reachable at {resolved_base_url}: {detail}",
            )

        payload = result.payload if isinstance(result.payload, dict) else {}
        raw_models = payload.get("data")
        if not isinstance(raw_models, list):
            return LMStudioStatusResponse(
                state="error",
                ok=False,
                base_url=resolved_base_url,
                default_model=self._settings.lm_studio_default_model,
                checked_at=checked_at,
                message="LM Studio responded, but /v1/models returned an unexpected payload.",
            )

        models: list[LMStudioModelSummary] = []
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            model = self._normalize_model(item)
            if model is not None:
                models.append(model)

        if not models:
            return LMStudioStatusResponse(
                state="empty",
                ok=False,
                base_url=resolved_base_url,
                default_model=self._settings.lm_studio_default_model,
                checked_at=checked_at,
                message=(
                    "LM Studio is running, but no models are loaded or listed through "
                    "/v1/models yet."
                ),
            )

        return LMStudioStatusResponse(
            state="available",
            ok=True,
            base_url=resolved_base_url,
            default_model=self._settings.lm_studio_default_model,
            checked_at=checked_at,
            count=len(models),
            models=models,
            message=f"Detected {len(models)} LM Studio model{'s' if len(models) != 1 else ''}.",
        )

    async def models(self, base_url: str | None = None) -> LMStudioModelsResponse:
        """Return the model-list portion of the status response."""

        status = await self.status(base_url)
        return LMStudioModelsResponse(
            state=status.state,
            ok=status.ok,
            base_url=status.base_url,
            count=status.count,
            models=status.models,
            message=status.message,
        )

    async def aclose(self) -> None:
        """Close the pooled HTTP client when the application shuts down."""

        async with self._client_lock:
            if self._client is not None:
                await self._client.aclose()
                self._client = None

    async def _fetch(self, url: str) -> _LMStudioFetchResult:
        try:
            async with self._client_lock:
                if self._client is None or self._client.is_closed:
                    self._client = httpx.AsyncClient(timeout=self._timeout_seconds)
                client = self._client
            response = await client.get(url)
            payload = response.json()
            return _LMStudioFetchResult(status_code=response.status_code, payload=payload)
        except (httpx.HTTPError, ValueError) as exc:
            return _LMStudioFetchResult(status_code=None, error=str(exc))

    @staticmethod
    def _is_safe_override_base_url(base_url: str, configured_base_url: str) -> bool:
        if base_url == configured_base_url:
            return True

        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            return False

        host = parsed.hostname.lower()
        if host in _ALLOWED_LM_STUDIO_OVERRIDE_HOSTS:
            return True

        try:
            return ip_address(host).is_loopback
        except ValueError:
            return False

    @staticmethod
    def _normalize_model(item: dict[str, Any]) -> LMStudioModelSummary | None:
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            return None

        context_length = item.get("context_length")
        return LMStudioModelSummary(
            id=model_id,
            name=model_id,
            owned_by=str(item["owned_by"]) if item.get("owned_by") is not None else None,
            created=item.get("created") if isinstance(item.get("created"), int) else None,
            context_length=context_length if isinstance(context_length, int) else None,
        )
