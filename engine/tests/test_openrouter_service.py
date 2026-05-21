"""Unit tests for OpenRouter catalog normalization and probing."""

from __future__ import annotations

from typing import Any

from pydantic import SecretStr

from agent33.config import Settings
from agent33.services.openrouter_catalog import (
    OpenRouterCatalogError,
    OpenRouterCatalogService,
    OpenRouterProbeRequest,
    _FetchResult,
)


def _sample_catalog_payload() -> dict[str, Any]:
    return {
        "data": [
            {
                "id": "openai/gpt-5.5",
                "canonical_slug": "openai/gpt-5.5-20260423",
                "name": "OpenAI: GPT-5.5",
                "description": "Flagship reasoning model",
                "context_length": 1050000,
                "hugging_face_id": "",
                "architecture": {
                    "modality": "text+image+file->text",
                    "input_modalities": ["text", "image", "file"],
                    "output_modalities": ["text"],
                },
                "pricing": {
                    "prompt": "0.000005",
                    "completion": "0.00003",
                    "input_cache_read": "0.0000005",
                    "web_search": "0.01",
                },
                "top_provider": {
                    "context_length": 1050000,
                    "max_completion_tokens": 128000,
                    "is_moderated": True,
                },
                "per_request_limits": {"prompt_tokens": 1048576},
                "supported_parameters": [
                    "reasoning",
                    "response_format",
                    "structured_outputs",
                    "tool_choice",
                    "tools",
                ],
                "default_parameters": {"temperature": None},
                "knowledge_cutoff": None,
                "expiration_date": None,
                "links": {"details": "/api/v1/models/openai/gpt-5.5/endpoints"},
            },
            {
                "id": "deepseek/deepseek-v4-flash:free",
                "name": "DeepSeek: Flash Free",
                "description": "Budget option",
                "context_length": 262144,
                "architecture": {
                    "modality": "text->text",
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                },
                "pricing": {
                    "prompt": "0",
                    "completion": "0",
                    "request": "0",
                },
                "top_provider": {
                    "context_length": 262144,
                    "max_completion_tokens": 32768,
                    "is_moderated": False,
                },
                "per_request_limits": None,
                "supported_parameters": ["temperature"],
                "default_parameters": {"temperature": 0.7},
                "links": {"details": "/api/v1/models/deepseek/deepseek-v4-flash/endpoints"},
            },
        ]
    }


class _SequenceFetcher:
    def __init__(self, responses: list[_FetchResult]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def __call__(self, url: str, headers: dict[str, str]) -> _FetchResult:
        self.calls.append((url, headers))
        if not self._responses:
            raise AssertionError("No more fetcher responses configured")
        return self._responses.pop(0)


def _settings() -> Settings:
    return Settings()


class TestOpenRouterCatalogService:
    async def test_normalizes_catalog_entries(self) -> None:
        fetcher = _SequenceFetcher(
            [_FetchResult(status_code=200, payload=_sample_catalog_payload())]
        )
        svc = OpenRouterCatalogService(_settings(), fetcher=fetcher, ttl_seconds=60)

        result = await svc.list_models()

        assert result.cached is False
        assert result.count == 2
        first = result.models[0]
        assert first.id == "openai/gpt-5.5"
        assert first.provider == "openai"
        assert first.vendor == "openai"
        assert first.context_length == 1050000
        assert first.max_completion_tokens == 128000
        assert first.moderated is True
        assert first.pricing.prompt == 0.000005
        assert first.pricing.completion == 0.00003
        assert first.pricing.cache_read == 0.0000005
        assert first.pricing.web_search == 0.01
        assert first.capabilities.supports_tools is True
        assert first.capabilities.supports_reasoning is True
        assert first.capabilities.supports_structured_outputs is True
        assert first.capabilities.supports_image_input is True
        assert first.capabilities.supports_file_input is True
        assert first.provider_limits == {"prompt_tokens": 1048576}
        assert first.details_path == "/api/v1/models/openai/gpt-5.5/endpoints"
        assert result.models[1].is_free is True

    async def test_missing_pricing_is_not_marked_free(self) -> None:
        fetcher = _SequenceFetcher(
            [
                _FetchResult(
                    status_code=200,
                    payload={
                        "data": [
                            {
                                "id": "meta/unknown-pricing",
                                "name": "Unknown Pricing",
                                "description": "Pricing fields are unavailable",
                                "pricing": {},
                                "top_provider": {
                                    "context_length": 8192,
                                    "max_completion_tokens": 1024,
                                    "is_moderated": False,
                                },
                            }
                        ]
                    },
                )
            ]
        )
        svc = OpenRouterCatalogService(_settings(), fetcher=fetcher, ttl_seconds=60)

        result = await svc.list_models()

        assert result.count == 1
        assert result.models[0].pricing.prompt is None
        assert result.models[0].pricing.completion is None
        assert result.models[0].is_free is False

    async def test_catalog_uses_ttl_cache(self) -> None:
        now = 100.0

        def clock() -> float:
            return now

        fetcher = _SequenceFetcher(
            [_FetchResult(status_code=200, payload=_sample_catalog_payload())]
        )
        svc = OpenRouterCatalogService(_settings(), fetcher=fetcher, ttl_seconds=60, clock=clock)

        first = await svc.list_models()
        second = await svc.list_models()

        assert first.cached is False
        assert second.cached is True
        assert len(fetcher.calls) == 1

    async def test_catalog_refreshes_after_ttl_expiry(self) -> None:
        now = 100.0

        def clock() -> float:
            return now

        fetcher = _SequenceFetcher(
            [
                _FetchResult(status_code=200, payload=_sample_catalog_payload()),
                _FetchResult(status_code=200, payload=_sample_catalog_payload()),
            ]
        )
        svc = OpenRouterCatalogService(_settings(), fetcher=fetcher, ttl_seconds=10, clock=clock)

        await svc.list_models()
        now = 111.0
        refreshed = await svc.list_models()

        assert refreshed.cached is False
        assert len(fetcher.calls) == 2

    async def test_raises_for_bad_catalog_response(self) -> None:
        fetcher = _SequenceFetcher([_FetchResult(status_code=503, detail="upstream unavailable")])
        svc = OpenRouterCatalogService(_settings(), fetcher=fetcher, ttl_seconds=60)

        try:
            await svc.list_models()
        except OpenRouterCatalogError as exc:
            assert "HTTP 503" in exc.detail
        else:
            raise AssertionError("Expected OpenRouterCatalogError")

    async def test_probe_reports_unconfigured_without_api_key(self) -> None:
        fetcher = _SequenceFetcher(
            [_FetchResult(status_code=200, payload=_sample_catalog_payload())]
        )
        svc = OpenRouterCatalogService(_settings(), fetcher=fetcher, ttl_seconds=60)

        result = await svc.probe()

        assert result.state == "unconfigured"
        assert result.configured is False
        assert result.catalog.status == "ok"
        assert result.authenticated.status == "unconfigured"
        assert len(fetcher.calls) == 1

    async def test_probe_reports_connected_with_valid_key(self) -> None:
        settings = _settings()
        object.__setattr__(settings, "openrouter_api_key", SecretStr("sk-or-test"))
        fetcher = _SequenceFetcher(
            [
                _FetchResult(status_code=200, payload=_sample_catalog_payload()),
                _FetchResult(status_code=200, payload=_sample_catalog_payload()),
            ]
        )
        svc = OpenRouterCatalogService(settings, fetcher=fetcher, ttl_seconds=60)

        result = await svc.probe()

        assert result.state == "connected"
        assert result.authenticated.status == "ok"
        assert "Authorization" in fetcher.calls[1][1]
        assert fetcher.calls[1][1]["Authorization"] == "Bearer sk-or-test"

    async def test_probe_reports_configured_when_authenticated_check_fails(self) -> None:
        settings = _settings()
        object.__setattr__(settings, "openrouter_api_key", SecretStr("sk-or-test"))
        fetcher = _SequenceFetcher(
            [
                _FetchResult(status_code=200, payload=_sample_catalog_payload()),
                _FetchResult(status_code=401, payload={"error": {"message": "Invalid API key"}}),
            ]
        )
        svc = OpenRouterCatalogService(settings, fetcher=fetcher, ttl_seconds=60)

        result = await svc.probe()

        assert result.state == "configured"
        assert result.catalog.status == "ok"
        assert result.authenticated.status == "error"
        assert result.authenticated.http_status == 401
        assert result.authenticated.detail == "Invalid API key"

    async def test_probe_uses_request_overrides_before_save(self) -> None:
        fetcher = _SequenceFetcher(
            [
                _FetchResult(status_code=200, payload=_sample_catalog_payload()),
                _FetchResult(status_code=200, payload=_sample_catalog_payload()),
            ]
        )
        svc = OpenRouterCatalogService(_settings(), fetcher=fetcher, ttl_seconds=60)

        result = await svc.probe(
            OpenRouterProbeRequest(
                openrouter_api_key="sk-or-draft",
                openrouter_base_url="https://openrouter.ai/api/v1",
                openrouter_site_url="https://draft.agent33.example",
                openrouter_app_name="Draft Console",
                openrouter_app_category="draft-ui",
            )
        )

        assert result.state == "connected"
        assert fetcher.calls[0][0] == "https://openrouter.ai/api/v1/models"
        assert fetcher.calls[0][1]["HTTP-Referer"] == "https://draft.agent33.example"
        assert fetcher.calls[1][1]["Authorization"] == "Bearer sk-or-draft"
        assert fetcher.calls[1][1]["X-OpenRouter-Title"] == "Draft Console"
