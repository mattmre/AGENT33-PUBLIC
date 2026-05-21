"""Connector boundary coverage for LLM and memory providers."""

from __future__ import annotations

from typing import Any

import pytest

from agent33.llm.base import ChatMessage
from agent33.llm.ollama import OllamaProvider
from agent33.llm.openai import OpenAIProvider
from agent33.memory.embeddings import EmbeddingProvider
from agent33.memory.jina_embeddings import JinaEmbeddingProvider


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _NeverCalledClient:
    async def post(self, *args: Any, **kwargs: Any) -> _Response:  # noqa: ARG002
        raise AssertionError("HTTP client should not be called when governance denies")

    async def get(self, *args: Any, **kwargs: Any) -> _Response:  # noqa: ARG002
        raise AssertionError("HTTP client should not be called when governance denies")

    async def aclose(self) -> None:
        return None


class _OpenAISuccessClient:
    async def post(self, url: str, **kwargs: Any) -> _Response:  # noqa: ARG002
        assert url.endswith("/chat/completions")
        return _Response(
            {
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }
        )

    async def get(self, url: str, **kwargs: Any) -> _Response:  # noqa: ARG002
        assert url.endswith("/models")
        return _Response({"data": [{"id": "gpt-4o-mini"}]})

    async def aclose(self) -> None:
        return None


class _OllamaSuccessClient:
    async def post(self, url: str, **kwargs: Any) -> _Response:  # noqa: ARG002
        assert url.endswith("/api/chat")
        return _Response({"message": {"content": "ok"}, "prompt_eval_count": 1, "eval_count": 1})

    async def get(self, url: str, **kwargs: Any) -> _Response:  # noqa: ARG002
        assert url.endswith("/api/tags")
        return _Response({"models": [{"name": "llama3.2"}]})

    async def aclose(self) -> None:
        return None


class _EmbeddingSuccessClient:
    async def post(self, url: str, **kwargs: Any) -> _Response:
        if url.endswith("/api/embeddings"):
            return _Response({"embedding": [0.1, 0.2]})
        if url.endswith("/api/embed"):
            return _Response({"embeddings": [[0.1, 0.2], [0.3, 0.4]]})
        raise AssertionError(f"Unexpected URL: {url}")

    async def aclose(self) -> None:
        return None


class _JinaSuccessClient:
    async def post(self, url: str, **kwargs: Any) -> _Response:  # noqa: ARG002
        assert url.endswith("/v1/embeddings")
        return _Response(
            {
                "data": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ]
            }
        )

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_llm_memory_boundary_governance_blocks_without_http_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent33.config.settings.connector_boundary_enabled", True)
    monkeypatch.setattr(
        "agent33.config.settings.connector_governance_blocked_connectors",
        "llm:openai,llm:ollama,memory:ollama_embeddings,memory:jina_embeddings",
    )
    monkeypatch.setattr("agent33.config.settings.connector_governance_blocked_operations", "")

    msg = [ChatMessage(role="user", content="hello")]

    openai = OpenAIProvider(api_key="test-key", base_url="http://example.com/v1")
    openai._client = _NeverCalledClient()  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="Connector governance blocked"):
        await openai.complete(msg)
    await openai.close()

    ollama = OllamaProvider(base_url="http://localhost:11434")
    ollama._client = _NeverCalledClient()  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="Connector governance blocked"):
        await ollama.list_models()
    await ollama.close()

    embeddings = EmbeddingProvider(base_url="http://localhost:11434")
    embeddings._client = _NeverCalledClient()  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="Connector governance blocked"):
        await embeddings.embed("hello")
    await embeddings.close()

    jina = JinaEmbeddingProvider(model="jina-embeddings-v3")
    jina._client = _NeverCalledClient()  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="Connector governance blocked"):
        await jina.embed_batch(["hello"])
    await jina.close()


@pytest.mark.asyncio
async def test_llm_memory_boundary_disabled_passes_through_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent33.config.settings.connector_boundary_enabled", False)
    monkeypatch.setattr(
        "agent33.config.settings.connector_governance_blocked_connectors",
        "llm:openai,llm:ollama,memory:ollama_embeddings,memory:jina_embeddings",
    )
    monkeypatch.setattr("agent33.config.settings.connector_governance_blocked_operations", "")

    msg = [ChatMessage(role="user", content="hello")]

    openai = OpenAIProvider(api_key="test-key", base_url="http://example.com/v1")
    openai._client = _OpenAISuccessClient()  # type: ignore[assignment]
    openai_result = await openai.complete(msg)
    openai_models = await openai.list_models()
    assert openai_result.content == "ok"
    assert openai_models == ["gpt-4o-mini"]
    await openai.close()

    ollama = OllamaProvider(base_url="http://localhost:11434")
    ollama._client = _OllamaSuccessClient()  # type: ignore[assignment]
    ollama_result = await ollama.complete(msg)
    ollama_models = await ollama.list_models()
    assert ollama_result.content == "ok"
    assert ollama_models == ["llama3.2"]
    await ollama.close()

    embeddings = EmbeddingProvider(base_url="http://localhost:11434")
    embeddings._client = _EmbeddingSuccessClient()  # type: ignore[assignment]
    single_vector = await embeddings.embed("hello")
    batch_vectors = await embeddings.embed_batch(["hello", "world"])
    assert single_vector == [0.1, 0.2]
    assert batch_vectors == [[0.1, 0.2], [0.3, 0.4]]
    await embeddings.close()

    jina = JinaEmbeddingProvider(model="jina-embeddings-v3")
    jina._client = _JinaSuccessClient()  # type: ignore[assignment]
    jina_vectors = await jina.embed_batch(["a", "b"])
    assert jina_vectors == [[0.1, 0.2], [0.3, 0.4]]
    await jina.close()
