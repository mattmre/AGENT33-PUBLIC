"""Chat endpoint tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

from agent33.llm.openai import OpenAIProvider
from agent33.llm.router import ModelRouter


def test_chat_completions_returns_openai_format(client: TestClient) -> None:
    upstream_payload = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello!"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }

    mock_request = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.content = json.dumps(upstream_payload).encode("utf-8")
    mock_response.aread = AsyncMock(return_value=mock_response.content)

    with patch("agent33.api.routes.chat.httpx.AsyncClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.build_request.return_value = mock_request
        mock_client.send = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = mock_client

        r = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )

    assert r.status_code == 200
    assert r.json() == upstream_payload
    mock_client.build_request.assert_called_once()
    mock_client.send.assert_awaited_once_with(mock_request, stream=True)


def test_chat_completions_ollama_unavailable(client: TestClient) -> None:
    import httpx as _httpx

    with patch("agent33.api.routes.chat.httpx.AsyncClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.build_request.return_value = MagicMock()
        mock_client.send = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = mock_client

        r = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )

    assert r.status_code == 503


def test_chat_completions_boundary_governance_blocked_returns_503(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr("agent33.config.settings.connector_boundary_enabled", True)
    monkeypatch.setattr(
        "agent33.config.settings.connector_governance_blocked_connectors",
        "api:chat_proxy",
    )

    with patch("agent33.api.routes.chat.httpx.AsyncClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.build_request.return_value = MagicMock()
        mock_client.send = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = mock_client

        r = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )

    assert r.status_code == 503
    mock_client.send.assert_not_awaited()


def test_chat_completions_boundary_disabled_passes_through_when_connector_blocked(
    client: TestClient,
    monkeypatch,
) -> None:
    upstream_payload = {"choices": [{"message": {"role": "assistant", "content": "Hello!"}}]}
    mock_request = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.content = json.dumps(upstream_payload).encode("utf-8")
    mock_response.aread = AsyncMock(return_value=mock_response.content)

    monkeypatch.setattr("agent33.config.settings.connector_boundary_enabled", False)
    monkeypatch.setattr(
        "agent33.config.settings.connector_governance_blocked_connectors",
        "api:chat_proxy",
    )

    with patch("agent33.api.routes.chat.httpx.AsyncClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.build_request.return_value = mock_request
        mock_client.send = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = mock_client

        r = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )

    assert r.status_code == 200
    assert r.json() == upstream_payload
    mock_client.send.assert_awaited_once_with(mock_request, stream=True)


def test_chat_completions_openrouter_ref_uses_openrouter_proxy_settings(
    client: TestClient,
    monkeypatch,
) -> None:
    upstream_payload = {
        "choices": [{"message": {"role": "assistant", "content": "Hello from OR"}}]
    }
    mock_request = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.content = json.dumps(upstream_payload).encode("utf-8")
    mock_response.aread = AsyncMock(return_value=mock_response.content)

    model_router = ModelRouter(default_provider="openrouter")
    model_router.register(
        "openrouter",
        OpenAIProvider(
            api_key="sk-or-test",
            base_url="https://openrouter.ai/api/v1",
            default_model="openrouter/auto",
            extra_headers={
                "HTTP-Referer": "http://localhost",
                "X-OpenRouter-Title": "AGENT-33",
            },
        ),
    )
    monkeypatch.setattr(client.app.state, "model_router", model_router, raising=False)

    with patch("agent33.api.routes.chat.httpx.AsyncClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.build_request.return_value = mock_request
        mock_client.send = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = mock_client

        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "openrouter/openai/gpt-5.2",
                "messages": [{"role": "user", "content": "Hi"}],
            },
        )

    assert r.status_code == 200
    assert r.json() == upstream_payload
    build_call = mock_client.build_request.call_args
    assert build_call.args[:2] == ("POST", "https://openrouter.ai/api/v1/chat/completions")
    assert build_call.kwargs["json"]["model"] == "openai/gpt-5.2"
    assert build_call.kwargs["headers"]["Authorization"] == "Bearer sk-or-test"
    assert build_call.kwargs["headers"]["HTTP-Referer"] == "http://localhost"
    assert build_call.kwargs["headers"]["X-OpenRouter-Title"] == "AGENT-33"


def test_chat_completions_server_default_openrouter_falls_back(
    client: TestClient,
    monkeypatch,
) -> None:
    upstream_error = MagicMock()
    upstream_error.status_code = 503
    upstream_error.headers = {"content-type": "application/json"}
    upstream_error.content = json.dumps(
        {"error": {"message": "No allowed providers are available for the selected model."}}
    ).encode("utf-8")
    upstream_error.json.return_value = {
        "error": {"message": "No allowed providers are available for the selected model."}
    }
    upstream_error.text = upstream_error.content.decode("utf-8")
    upstream_error.aread = AsyncMock(return_value=upstream_error.content)

    fallback_payload = {
        "id": "chatcmpl-fallback",
        "object": "chat.completion",
        "created": 1700000001,
        "model": "qwen3-coder",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Fallback hello!"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
    }
    fallback_response = MagicMock()
    fallback_response.status_code = 200
    fallback_response.headers = {"content-type": "application/json"}
    fallback_response.content = json.dumps(fallback_payload).encode("utf-8")
    fallback_response.aread = AsyncMock(return_value=fallback_response.content)

    model_router = ModelRouter(default_provider="openrouter")
    model_router.register(
        "openrouter",
        OpenAIProvider(
            api_key="sk-or-test",
            base_url="https://openrouter.ai/api/v1",
            default_model="openrouter/auto",
        ),
    )
    model_router.register("ollama", MagicMock())
    monkeypatch.setattr(client.app.state, "model_router", model_router, raising=False)
    monkeypatch.setattr(
        "agent33.config.settings.default_model",
        "openrouter/qwen/qwen3-coder-flash",
    )
    monkeypatch.setattr(
        "agent33.config.settings.openrouter_default_fallback_models",
        "ollama/qwen3-coder",
    )
    monkeypatch.setattr("agent33.config.settings.ollama_base_url", "http://ollama.test:11434")

    with patch("agent33.api.routes.chat.httpx.AsyncClient") as mock_cls:
        mock_client = MagicMock()
        captured_requests: list[tuple[str, str, dict[str, object]]] = []

        def _build_request(method: str, url: str, *, json: dict[str, object], headers):  # type: ignore[no-untyped-def]
            captured_requests.append((method, url, dict(json)))
            return MagicMock()

        mock_client.build_request.side_effect = _build_request
        mock_client.send = AsyncMock(side_effect=[upstream_error, fallback_response])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = mock_client

        r = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )

    assert r.status_code == 200
    assert r.json() == fallback_payload
    assert mock_client.send.await_count == 2
    assert captured_requests[0][0:2] == ("POST", "https://openrouter.ai/api/v1/chat/completions")
    assert captured_requests[0][2]["model"] == "qwen/qwen3-coder-flash"
    assert captured_requests[1][0:2] == ("POST", "http://ollama.test:11434/v1/chat/completions")
    assert captured_requests[1][2]["model"] == "qwen3-coder"
    assert r.headers["x-agent33-resolved-provider"] == "ollama"
    assert r.headers["x-agent33-resolved-model"] == "ollama/qwen3-coder"
    assert r.headers["x-agent33-fallback-from"] == "openrouter/qwen/qwen3-coder-flash"


def test_chat_completions_explicit_openrouter_model_does_not_fallback(
    client: TestClient,
    monkeypatch,
) -> None:
    upstream_error = MagicMock()
    upstream_error.status_code = 503
    upstream_error.headers = {"content-type": "application/json"}
    upstream_error.content = json.dumps(
        {"error": {"message": "No allowed providers are available for the selected model."}}
    ).encode("utf-8")
    upstream_error.json.return_value = {
        "error": {"message": "No allowed providers are available for the selected model."}
    }
    upstream_error.text = upstream_error.content.decode("utf-8")
    upstream_error.aread = AsyncMock(return_value=upstream_error.content)

    model_router = ModelRouter(default_provider="openrouter")
    model_router.register(
        "openrouter",
        OpenAIProvider(
            api_key="sk-or-test",
            base_url="https://openrouter.ai/api/v1",
            default_model="openrouter/auto",
        ),
    )
    model_router.register("ollama", MagicMock())
    monkeypatch.setattr(client.app.state, "model_router", model_router, raising=False)
    monkeypatch.setattr(
        "agent33.config.settings.default_model",
        "openrouter/qwen/qwen3-coder-flash",
    )
    monkeypatch.setattr(
        "agent33.config.settings.openrouter_default_fallback_models",
        "ollama/qwen3-coder",
    )

    with patch("agent33.api.routes.chat.httpx.AsyncClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.build_request.return_value = MagicMock()
        mock_client.send = AsyncMock(return_value=upstream_error)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = mock_client

        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "openrouter/qwen/qwen3-coder-flash",
                "messages": [{"role": "user", "content": "Hi"}],
            },
        )

    assert r.status_code == 503
    assert mock_client.send.await_count == 1
    assert (
        r.json()["error"]["message"]
        == "No allowed providers are available for the selected model."
    )


def test_chat_completions_rebuilds_invalid_state_model_router(
    client: TestClient,
    monkeypatch,
) -> None:
    upstream_payload = {
        "id": "chatcmpl-rebuilt-router",
        "object": "chat.completion",
        "created": 1700000002,
        "model": "qwen3-coder",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Recovered router"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 6, "completion_tokens": 3, "total_tokens": 9},
    }
    mock_request = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.content = json.dumps(upstream_payload).encode("utf-8")
    mock_response.aread = AsyncMock(return_value=mock_response.content)

    rebuilt_router = ModelRouter(default_provider="openai")
    rebuilt_router.register(
        "openai",
        OpenAIProvider(
            api_key="sk-test",
            base_url="https://fallback.test/v1",
            default_model="gpt-4o-mini",
        ),
    )
    monkeypatch.setattr(client.app.state, "model_router", "mock-router", raising=False)

    with (
        patch(
            "agent33.api.routes.chat.build_model_router",
            return_value=rebuilt_router,
        ) as mock_build_router,
        patch("agent33.api.routes.chat.httpx.AsyncClient") as mock_cls,
    ):
        mock_client = MagicMock()
        mock_client.build_request.return_value = mock_request
        mock_client.send = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = mock_client

        r = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )

    assert r.status_code == 200
    assert r.json() == upstream_payload
    mock_build_router.assert_called_once()
    build_call = mock_client.build_request.call_args
    assert build_call.args[:2] == ("POST", "https://fallback.test/v1/chat/completions")
