"""Tests for OpenRouter default-model runtime fallback hardening."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from agent33.llm.base import ChatMessage, LLMResponse
from agent33.llm.router import ModelRouter


def _provider_unavailable_error() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(
        503,
        request=request,
        json={"error": {"message": "No allowed providers are available for the selected model."}},
    )
    return httpx.HTTPStatusError("provider unavailable", request=request, response=response)


class _QueuedProvider:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[str] = []

    async def complete(self, messages, *, model, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(model)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def stream_complete(self, *args, **kwargs):  # pragma: no cover - not used here
        raise NotImplementedError


@pytest.mark.asyncio
async def test_model_router_falls_back_for_server_default_openrouter_model() -> None:
    openrouter_provider = _QueuedProvider([_provider_unavailable_error()])
    ollama_provider = _QueuedProvider(
        [
            LLMResponse(
                content="fallback ok",
                model="qwen3-coder",
                prompt_tokens=11,
                completion_tokens=7,
            )
        ]
    )
    router = ModelRouter(
        providers={"openrouter": openrouter_provider, "ollama": ollama_provider},
        default_provider="openrouter",
        prefix_map=[],
    )

    with (
        patch("agent33.config.settings.default_model", "openrouter/qwen/qwen3-coder-flash"),
        patch("agent33.config.settings.openrouter_default_fallback_models", "ollama/qwen3-coder"),
    ):
        response = await router.complete(
            [ChatMessage(role="user", content="hello")],
            model="openrouter/qwen/qwen3-coder-flash",
            allow_fallback=True,
        )

    assert openrouter_provider.calls == ["qwen/qwen3-coder-flash"]
    assert ollama_provider.calls == ["qwen3-coder"]
    assert response.content == "fallback ok"
    assert response.model == "qwen3-coder"


@pytest.mark.asyncio
async def test_model_router_does_not_fallback_without_opt_in() -> None:
    openrouter_provider = _QueuedProvider([_provider_unavailable_error()])
    router = ModelRouter(
        providers={"openrouter": openrouter_provider},
        default_provider="openrouter",
        prefix_map=[],
    )

    with (
        patch(
            "agent33.config.settings.default_model",
            "openrouter/qwen/qwen3-coder-flash",
        ),
        patch(
            "agent33.config.settings.openrouter_default_fallback_models",
            "ollama/qwen3-coder",
        ),
        pytest.raises(httpx.HTTPStatusError),
    ):
        await router.complete(
            [ChatMessage(role="user", content="hello")],
            model="openrouter/qwen/qwen3-coder-flash",
            allow_fallback=False,
        )

    assert openrouter_provider.calls == ["qwen/qwen3-coder-flash"]
