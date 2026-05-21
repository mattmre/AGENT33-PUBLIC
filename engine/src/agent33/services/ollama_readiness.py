"""Ollama readiness probes for beginner setup UX."""

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


class OllamaModelDetails(BaseModel):
    """Subset of Ollama model metadata that is safe to show in setup UI."""

    family: str | None = None
    families: list[str] = Field(default_factory=list)
    format: str | None = None
    parameter_size: str | None = None
    quantization_level: str | None = None


class OllamaModelSummary(BaseModel):
    """Frontend-friendly local Ollama model entry."""

    name: str
    model: str | None = None
    modified_at: str | None = None
    size: int | None = None
    digest: str | None = None
    details: OllamaModelDetails = Field(default_factory=OllamaModelDetails)


class OllamaStatusResponse(BaseModel):
    """Ollama status and model availability for setup UX."""

    provider: Literal["ollama"] = "ollama"
    state: Literal["available", "empty", "unavailable", "error"]
    ok: bool
    base_url: str
    default_model: str
    checked_at: datetime
    count: int = 0
    models: list[OllamaModelSummary] = Field(default_factory=list)
    message: str


class OllamaModelsResponse(BaseModel):
    """Ollama model list response."""

    provider: Literal["ollama"] = "ollama"
    state: Literal["available", "empty", "unavailable", "error"]
    ok: bool
    base_url: str
    count: int = 0
    models: list[OllamaModelSummary] = Field(default_factory=list)
    message: str


@dataclass(slots=True)
class _OllamaFetchResult:
    status_code: int | None
    payload: Any = None
    error: str | None = None


FetchOllamaPayload = Callable[[str], Awaitable[_OllamaFetchResult]]

_ALLOWED_OLLAMA_OVERRIDE_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


def normalize_ollama_base_url(base_url: str) -> str:
    """Return the Ollama root URL used for native /api/* readiness probes."""

    normalized = base_url.strip().rstrip("/")
    if normalized.lower().endswith("/v1"):
        normalized = normalized[:-3].rstrip("/")
    return normalized


class OllamaReadinessService:
    """Probe Ollama without sending prompts, credentials, or project data."""

    def __init__(
        self,
        settings: Settings,
        *,
        timeout_seconds: float = 5.0,
        fetcher: FetchOllamaPayload | None = None,
    ) -> None:
        self._settings = settings
        self._timeout_seconds = timeout_seconds
        self._fetcher = fetcher or self._fetch
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

    async def status(self, base_url: str | None = None) -> OllamaStatusResponse:
        """Return service reachability and available local model metadata."""

        checked_at = datetime.now(UTC)
        configured_base_url = normalize_ollama_base_url(self._settings.runtime_ollama_base_url)
        resolved_base_url = configured_base_url
        if base_url is not None and base_url.strip():
            resolved_base_url = normalize_ollama_base_url(base_url)
            if not self._is_safe_override_base_url(resolved_base_url, configured_base_url):
                return OllamaStatusResponse(
                    state="error",
                    ok=False,
                    base_url=resolved_base_url,
                    default_model=self._settings.ollama_default_model,
                    checked_at=checked_at,
                    message=(
                        "Ollama base URL overrides must use http(s) and point to the "
                        "configured runtime host, localhost, or host.docker.internal."
                    ),
                )

        result = await self._fetcher(f"{resolved_base_url}/api/tags")
        if result.error or result.status_code != 200:
            detail = result.error or f"HTTP {result.status_code}"
            return OllamaStatusResponse(
                state="unavailable",
                ok=False,
                base_url=resolved_base_url,
                default_model=self._settings.ollama_default_model,
                checked_at=checked_at,
                message=f"Ollama is not reachable at {resolved_base_url}: {detail}",
            )

        payload = result.payload if isinstance(result.payload, dict) else {}
        raw_models = payload.get("models")
        if not isinstance(raw_models, list):
            return OllamaStatusResponse(
                state="error",
                ok=False,
                base_url=resolved_base_url,
                default_model=self._settings.ollama_default_model,
                checked_at=checked_at,
                message="Ollama responded, but /api/tags returned an unexpected payload.",
            )

        models: list[OllamaModelSummary] = []
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            model = self._normalize_model(item)
            if model is not None:
                models.append(model)

        if not models:
            return OllamaStatusResponse(
                state="empty",
                ok=False,
                base_url=resolved_base_url,
                default_model=self._settings.ollama_default_model,
                checked_at=checked_at,
                message="Ollama is running, but no local models are installed yet.",
            )

        return OllamaStatusResponse(
            state="available",
            ok=True,
            base_url=resolved_base_url,
            default_model=self._settings.ollama_default_model,
            checked_at=checked_at,
            count=len(models),
            models=models,
            message=f"Detected {len(models)} local Ollama model{'s' if len(models) != 1 else ''}.",
        )

    async def models(self, base_url: str | None = None) -> OllamaModelsResponse:
        """Return the model-list portion of the status response."""

        status = await self.status(base_url)
        return OllamaModelsResponse(
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

    async def _fetch(self, url: str) -> _OllamaFetchResult:
        try:
            async with self._client_lock:
                if self._client is None or self._client.is_closed:
                    self._client = httpx.AsyncClient(timeout=self._timeout_seconds)
                client = self._client
            response = await client.get(url)
            payload = response.json()
            return _OllamaFetchResult(status_code=response.status_code, payload=payload)
        except (httpx.HTTPError, ValueError) as exc:
            return _OllamaFetchResult(status_code=None, error=str(exc))

    @staticmethod
    def _is_safe_override_base_url(base_url: str, configured_base_url: str) -> bool:
        if base_url == configured_base_url:
            return True

        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            return False

        host = parsed.hostname.lower()
        if host in _ALLOWED_OLLAMA_OVERRIDE_HOSTS:
            return True

        try:
            return ip_address(host).is_loopback
        except ValueError:
            return False

    @staticmethod
    def _normalize_model(item: dict[str, Any]) -> OllamaModelSummary | None:
        resolved_name = str(item.get("name") or item.get("model") or "").strip()
        if not resolved_name:
            return None

        raw_details = item.get("details")
        details: dict[str, Any] = raw_details if isinstance(raw_details, dict) else {}
        families = details.get("families")
        return OllamaModelSummary(
            name=resolved_name,
            model=str(item["model"]) if item.get("model") is not None else None,
            modified_at=str(item["modified_at"]) if item.get("modified_at") is not None else None,
            size=item.get("size") if isinstance(item.get("size"), int) else None,
            digest=str(item["digest"]) if item.get("digest") is not None else None,
            details=OllamaModelDetails(
                family=str(details["family"]) if details.get("family") is not None else None,
                families=(
                    [str(family) for family in families] if isinstance(families, list) else []
                ),
                format=str(details["format"]) if details.get("format") is not None else None,
                parameter_size=(
                    str(details["parameter_size"])
                    if details.get("parameter_size") is not None
                    else None
                ),
                quantization_level=(
                    str(details["quantization_level"])
                    if details.get("quantization_level") is not None
                    else None
                ),
            ),
        )
