"""OpenRouter catalog normalization and connectivity probing."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.config import Settings


class OpenRouterCatalogError(RuntimeError):
    """Raised when the OpenRouter catalog cannot be fetched or normalized."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class OpenRouterPricing(BaseModel):
    """Normalized pricing fields for frontend tables."""

    prompt: float | None = None
    completion: float | None = None
    cache_read: float | None = None
    request: float | None = None
    image: float | None = None
    web_search: float | None = None
    additional: dict[str, float] = Field(default_factory=dict)


class OpenRouterCapabilities(BaseModel):
    """Derived capability flags plus modality metadata."""

    modality: str | None = None
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    supports_tools: bool = False
    supports_reasoning: bool = False
    supports_structured_outputs: bool = False
    supports_image_input: bool = False
    supports_image_output: bool = False
    supports_audio_input: bool = False
    supports_file_input: bool = False


class OpenRouterTopProvider(BaseModel):
    """Useful routing and moderation metadata from OpenRouter."""

    context_length: int | None = None
    max_completion_tokens: int | None = None
    is_moderated: bool | None = None


class OpenRouterModelSummary(BaseModel):
    """Frontend-friendly OpenRouter model entry."""

    id: str
    canonical_slug: str | None = None
    name: str
    description: str | None = None
    provider: str | None = None
    vendor: str | None = None
    hugging_face_id: str | None = None
    context_length: int | None = None
    max_completion_tokens: int | None = None
    moderated: bool | None = None
    is_free: bool = False
    pricing: OpenRouterPricing = Field(default_factory=OpenRouterPricing)
    supported_parameters: list[str] = Field(default_factory=list)
    capabilities: OpenRouterCapabilities = Field(default_factory=OpenRouterCapabilities)
    provider_limits: dict[str, Any] | None = None
    top_provider: OpenRouterTopProvider = Field(default_factory=OpenRouterTopProvider)
    default_parameters: dict[str, Any] = Field(default_factory=dict)
    knowledge_cutoff: str | None = None
    expiration_date: str | None = None
    details_path: str | None = None


class OpenRouterModelsResponse(BaseModel):
    """Normalized catalog response."""

    source: Literal["openrouter"] = "openrouter"
    cached: bool = False
    fetched_at: datetime
    expires_at: datetime
    count: int = 0
    models: list[OpenRouterModelSummary] = Field(default_factory=list)


class OpenRouterProbeCheck(BaseModel):
    """Single probe step result."""

    status: Literal["ok", "error", "unconfigured"]
    ok: bool = False
    http_status: int | None = None
    detail: str | None = None


class OpenRouterProbeResponse(BaseModel):
    """Connectivity status for the setup UX."""

    provider: Literal["openrouter"] = "openrouter"
    state: Literal["unconfigured", "configured", "connected", "error"]
    configured: bool
    checked_at: datetime
    catalog: OpenRouterProbeCheck
    authenticated: OpenRouterProbeCheck
    message: str


class OpenRouterProbeRequest(BaseModel):
    """Optional draft OpenRouter settings to probe before saving."""

    openrouter_api_key: str | None = None
    openrouter_base_url: str | None = None
    openrouter_site_url: str | None = None
    openrouter_app_name: str | None = None
    openrouter_app_category: str | None = None
    default_model: str | None = None


@dataclass(slots=True)
class _FetchResult:
    status_code: int | None
    payload: Any = None
    error: str | None = None
    detail: str | None = None


@dataclass(slots=True)
class _CatalogCacheEntry:
    url: str
    response: OpenRouterModelsResponse
    expires_monotonic: float


@dataclass(slots=True)
class _EffectiveProbeConfig:
    base_url: str
    api_key: str
    site_url: str
    app_name: str
    app_category: str


FetchOpenRouterPayload = Callable[[str, dict[str, str]], Awaitable[_FetchResult]]


class OpenRouterCatalogService:
    """Fetch, normalize, cache, and probe the OpenRouter model catalog."""

    def __init__(
        self,
        settings: Settings,
        *,
        ttl_seconds: int = 60,
        timeout_seconds: float = 10.0,
        clock: Callable[[], float] | None = None,
        fetcher: FetchOpenRouterPayload | None = None,
    ) -> None:
        self._settings = settings
        self._ttl_seconds = ttl_seconds
        self._timeout_seconds = timeout_seconds
        self._clock = clock or time.monotonic
        self._fetcher = fetcher or self._fetch
        self._cache: _CatalogCacheEntry | None = None

    async def list_models(self) -> OpenRouterModelsResponse:
        """Return the normalized public OpenRouter catalog with short TTL caching."""
        catalog_url = self._catalog_url()
        now = self._clock()
        if (
            self._cache is not None
            and self._cache.url == catalog_url
            and now < self._cache.expires_monotonic
        ):
            return self._cache.response.model_copy(update={"cached": True})

        result = await self._fetcher(catalog_url, self._build_headers(authenticated=False))
        self._ensure_success(result, "OpenRouter model catalog")

        payload = result.payload if isinstance(result.payload, dict) else {}
        items = payload.get("data")
        if not isinstance(items, list):
            raise OpenRouterCatalogError("OpenRouter model catalog returned an unexpected payload")

        models = [self._normalize_model(item) for item in items if isinstance(item, dict)]
        fetched_at = datetime.now(UTC)
        response = OpenRouterModelsResponse(
            fetched_at=fetched_at,
            expires_at=fetched_at + timedelta(seconds=self._ttl_seconds),
            count=len(models),
            models=models,
        )
        self._cache = _CatalogCacheEntry(
            url=catalog_url,
            response=response,
            expires_monotonic=now + self._ttl_seconds,
        )
        return response

    async def probe(
        self,
        request: OpenRouterProbeRequest | None = None,
    ) -> OpenRouterProbeResponse:
        """Run public and authenticated OpenRouter checks for setup UX."""
        checked_at = datetime.now(UTC)
        probe_config = self._effective_probe_config(request)
        configured = bool(probe_config.api_key)

        catalog_url = self._catalog_url(probe_config.base_url)
        public_result = await self._fetcher(
            catalog_url,
            self._build_headers(authenticated=False, probe_config=probe_config),
        )
        if public_result.error or public_result.status_code != 200:
            public_detail = public_result.error or self._extract_error_detail(public_result)
            return OpenRouterProbeResponse(
                state="error",
                configured=configured,
                checked_at=checked_at,
                catalog=OpenRouterProbeCheck(
                    status="error",
                    ok=False,
                    http_status=public_result.status_code,
                    detail=public_detail,
                ),
                authenticated=OpenRouterProbeCheck(
                    status="unconfigured" if not configured else "error",
                    ok=False,
                    detail=("Authenticated check skipped because the public catalog probe failed"),
                ),
                message="OpenRouter catalog is unreachable",
            )

        items = (
            public_result.payload.get("data") if isinstance(public_result.payload, dict) else None
        )
        catalog_count = len(items) if isinstance(items, list) else 0
        catalog_check = OpenRouterProbeCheck(
            status="ok",
            ok=True,
            http_status=200,
            detail=f"Loaded {catalog_count} models from the public catalog",
        )

        if not configured:
            return OpenRouterProbeResponse(
                state="unconfigured",
                configured=False,
                checked_at=checked_at,
                catalog=catalog_check,
                authenticated=OpenRouterProbeCheck(
                    status="unconfigured",
                    ok=False,
                    detail="OPENROUTER_API_KEY is not configured",
                ),
                message=(
                    "OpenRouter catalog is reachable. Configure an API key "
                    "to enable authenticated use."
                ),
            )

        result = await self._fetcher(
            catalog_url,
            self._build_headers(authenticated=True, probe_config=probe_config),
        )
        auth_check = self._build_probe_check(result)
        if auth_check.ok:
            return OpenRouterProbeResponse(
                state="connected",
                configured=True,
                checked_at=checked_at,
                catalog=catalog_check,
                authenticated=auth_check,
                message="OpenRouter public and authenticated checks succeeded.",
            )

        return OpenRouterProbeResponse(
            state="configured",
            configured=True,
            checked_at=checked_at,
            catalog=catalog_check,
            authenticated=auth_check,
            message="OpenRouter public catalog is reachable, but the authenticated check failed.",
        )

    async def _fetch(self, url: str, headers: dict[str, str]) -> _FetchResult:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(url, headers=headers)
        except Exception as exc:
            return _FetchResult(status_code=None, error=str(exc))

        detail: str | None = None
        payload: Any = None
        try:
            payload = response.json()
        except ValueError:
            if response.text:
                detail = response.text[:500]

        return _FetchResult(
            status_code=response.status_code,
            payload=payload,
            detail=detail,
        )

    def _catalog_url(self, base_url: str | None = None) -> str:
        effective_base_url = (base_url or self._settings.openrouter_base_url).rstrip("/")
        return f"{effective_base_url}/models"

    def _build_headers(
        self,
        *,
        authenticated: bool,
        probe_config: _EffectiveProbeConfig | None = None,
    ) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        effective_config = probe_config or self._effective_probe_config(None)
        if self._is_openrouter_base_url(effective_config.base_url):
            site_url = effective_config.site_url
            app_name = effective_config.app_name
            category = effective_config.app_category
            if site_url:
                headers["HTTP-Referer"] = site_url
            if app_name:
                headers["X-OpenRouter-Title"] = app_name
            if category:
                headers["X-OpenRouter-Categories"] = category

        if authenticated:
            api_key = effective_config.api_key
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _is_openrouter_base_url(self, base_url: str) -> bool:
        parsed = urlparse(base_url.rstrip("/"))
        return parsed.netloc.lower() == "openrouter.ai" and parsed.path.endswith("/api/v1")

    def _effective_probe_config(
        self,
        request: OpenRouterProbeRequest | None,
    ) -> _EffectiveProbeConfig:
        if request is None:
            return _EffectiveProbeConfig(
                base_url=self._settings.openrouter_base_url.strip(),
                api_key=self._settings.openrouter_api_key.get_secret_value().strip(),
                site_url=self._settings.openrouter_site_url.strip(),
                app_name=self._settings.openrouter_app_name.strip(),
                app_category=self._settings.openrouter_app_category.strip(),
            )

        return _EffectiveProbeConfig(
            base_url=(request.openrouter_base_url or self._settings.openrouter_base_url).strip(),
            api_key=(
                request.openrouter_api_key
                if request.openrouter_api_key is not None
                else self._settings.openrouter_api_key.get_secret_value()
            ).strip(),
            site_url=(request.openrouter_site_url or self._settings.openrouter_site_url).strip(),
            app_name=(request.openrouter_app_name or self._settings.openrouter_app_name).strip(),
            app_category=(
                request.openrouter_app_category or self._settings.openrouter_app_category
            ).strip(),
        )

    def _ensure_success(self, result: _FetchResult, label: str) -> None:
        if result.error:
            raise OpenRouterCatalogError(f"{label} request failed: {result.error}")
        if result.status_code != 200:
            detail = self._extract_error_detail(result)
            raise OpenRouterCatalogError(
                f"{label} request returned HTTP {result.status_code}"
                + (f": {detail}" if detail else "")
            )

    def _build_probe_check(self, result: _FetchResult) -> OpenRouterProbeCheck:
        if result.error:
            return OpenRouterProbeCheck(status="error", ok=False, detail=result.error)
        if result.status_code == 200:
            return OpenRouterProbeCheck(
                status="ok",
                ok=True,
                http_status=200,
                detail="Authenticated OpenRouter catalog request succeeded",
            )
        return OpenRouterProbeCheck(
            status="error",
            ok=False,
            http_status=result.status_code,
            detail=self._extract_error_detail(result),
        )

    def _extract_error_detail(self, result: _FetchResult) -> str | None:
        payload = result.payload
        if isinstance(payload, dict):
            for key in ("error", "message", "detail"):
                value = payload.get(key)
                if isinstance(value, dict):
                    nested = value.get("message")
                    if nested:
                        return str(nested)
                if value:
                    return str(value)
        return result.detail

    def _normalize_model(self, raw: dict[str, Any]) -> OpenRouterModelSummary:
        model_id = self._as_str(raw.get("id")) or ""
        vendor = model_id.split("/", 1)[0] if "/" in model_id else None
        architecture_raw = raw.get("architecture")
        architecture: dict[str, Any] = (
            architecture_raw if isinstance(architecture_raw, dict) else {}
        )
        supported_parameters = [
            str(value) for value in raw.get("supported_parameters", []) if value is not None
        ]
        input_modalities = self._as_str_list(architecture.get("input_modalities"))
        output_modalities = self._as_str_list(architecture.get("output_modalities"))
        top_provider_raw_raw = raw.get("top_provider")
        top_provider_raw: dict[str, Any] = (
            top_provider_raw_raw if isinstance(top_provider_raw_raw, dict) else {}
        )
        top_provider = OpenRouterTopProvider(
            context_length=self._as_int(top_provider_raw.get("context_length")),
            max_completion_tokens=self._as_int(top_provider_raw.get("max_completion_tokens")),
            is_moderated=self._as_bool(top_provider_raw.get("is_moderated")),
        )
        pricing = self._normalize_pricing(raw.get("pricing"))

        return OpenRouterModelSummary(
            id=model_id,
            canonical_slug=self._as_str(raw.get("canonical_slug")),
            name=self._as_str(raw.get("name")) or model_id,
            description=self._as_str(raw.get("description")),
            provider=vendor,
            vendor=vendor,
            hugging_face_id=self._as_str(raw.get("hugging_face_id")),
            context_length=top_provider.context_length or self._as_int(raw.get("context_length")),
            max_completion_tokens=top_provider.max_completion_tokens,
            moderated=top_provider.is_moderated,
            is_free=pricing.prompt == 0.0 and pricing.completion == 0.0,
            pricing=pricing,
            supported_parameters=supported_parameters,
            capabilities=OpenRouterCapabilities(
                modality=self._as_str(architecture.get("modality")),
                input_modalities=input_modalities,
                output_modalities=output_modalities,
                supports_tools=(
                    "tools" in supported_parameters or "tool_choice" in supported_parameters
                ),
                supports_reasoning=(
                    "reasoning" in supported_parameters
                    or "include_reasoning" in supported_parameters
                ),
                supports_structured_outputs=(
                    "structured_outputs" in supported_parameters
                    or "response_format" in supported_parameters
                ),
                supports_image_input="image" in input_modalities,
                supports_image_output="image" in output_modalities,
                supports_audio_input="audio" in input_modalities,
                supports_file_input="file" in input_modalities,
            ),
            provider_limits=(
                raw.get("per_request_limits")
                if isinstance(raw.get("per_request_limits"), dict)
                else None
            ),
            top_provider=top_provider,
            default_parameters=(
                raw.get("default_parameters")
                if isinstance(raw.get("default_parameters"), dict)
                else {}
            ),
            knowledge_cutoff=self._as_str(raw.get("knowledge_cutoff")),
            expiration_date=self._as_str(raw.get("expiration_date")),
            details_path=self._as_str(
                raw.get("links", {}).get("details") if isinstance(raw.get("links"), dict) else None
            ),
        )

    def _normalize_pricing(self, raw: Any) -> OpenRouterPricing:
        if not isinstance(raw, dict):
            return OpenRouterPricing()

        additional: dict[str, float] = {}
        normalized: dict[str, float | dict[str, float] | None] = {
            "prompt": self._as_float(raw.get("prompt")),
            "completion": self._as_float(raw.get("completion")),
            "cache_read": self._as_float(raw.get("input_cache_read")),
            "request": self._as_float(raw.get("request")),
            "image": self._as_float(raw.get("image")),
            "web_search": self._as_float(raw.get("web_search")),
        }

        for key, value in raw.items():
            if key in {
                "prompt",
                "completion",
                "input_cache_read",
                "request",
                "image",
                "web_search",
            }:
                continue
            parsed = self._as_float(value)
            if parsed is not None:
                additional[key] = parsed

        return OpenRouterPricing(**normalized, additional=additional)

    def _as_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _as_str_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if item is not None]

    def _as_int(self, value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _as_float(self, value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _as_bool(self, value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.lower()
            if lowered in {"true", "1", "yes"}:
                return True
            if lowered in {"false", "0", "no"}:
                return False
        return bool(value)
