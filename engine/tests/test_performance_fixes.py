"""Tests for performance fixes: HTTP client pooling and embedding batching."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

if TYPE_CHECKING:
    from agent33.llm.ollama import OllamaProvider
    from agent33.llm.openai import OpenAIProvider
    from agent33.memory.embeddings import EmbeddingProvider
    from agent33.memory.jina_embeddings import JinaEmbeddingProvider


def _mock_client() -> MagicMock:
    """Create a mock that behaves like an httpx.AsyncClient without spec."""
    client = MagicMock()
    client.post = AsyncMock()
    client.get = AsyncMock()
    client.aclose = AsyncMock()
    return client


def _mock_response(data: dict) -> MagicMock:  # type: ignore[type-arg]
    """Create a mock httpx response with given JSON data."""
    resp = MagicMock()
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# EmbeddingProvider tests
# ---------------------------------------------------------------------------


class TestEmbeddingProvider:
    """Tests for the Ollama EmbeddingProvider with persistent client."""

    def _make_provider(self) -> "EmbeddingProvider":  # noqa: UP037
        from agent33.memory.embeddings import EmbeddingProvider

        return EmbeddingProvider(base_url="http://test:11434")

    @pytest.mark.asyncio
    async def test_embed_uses_persistent_client(self) -> None:
        """embed() should use self._client and normalize single-vector responses."""
        provider = self._make_provider()

        mock_resp = _mock_response({"embedding": [0.1, 0.2, 0.3]})
        mock = _mock_client()
        mock.post.return_value = mock_resp
        provider._client = mock

        result = await provider.embed("hello world")

        mock.post.assert_awaited_once_with(
            "http://test:11434/api/embed",
            json={"model": "nomic-embed-text", "input": ["hello world"]},
        )
        assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_embed_batch_accepts_legacy_single_embedding_shape(self) -> None:
        """embed_batch() should wrap a legacy single-vector payload for one text."""
        provider = self._make_provider()

        mock_resp = _mock_response({"embedding": [0.1, 0.2, 0.3]})
        mock = _mock_client()
        mock.post.return_value = mock_resp
        provider._client = mock

        result = await provider.embed_batch(["hello world"])

        mock.post.assert_awaited_once_with(
            "http://test:11434/api/embed",
            json={"model": "nomic-embed-text", "input": ["hello world"]},
        )
        assert result == [[0.1, 0.2, 0.3]]

    @pytest.mark.asyncio
    async def test_embed_batch_single_request(self) -> None:
        """embed_batch() should send ONE POST to /api/embed with list input."""
        provider = self._make_provider()

        mock_resp = _mock_response({"embeddings": [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]})
        mock = _mock_client()
        mock.post.return_value = mock_resp
        provider._client = mock

        texts = ["hello", "world", "test"]
        result = await provider.embed_batch(texts)

        # Verify exactly one POST call to the batch endpoint
        mock.post.assert_awaited_once_with(
            "http://test:11434/api/embed",
            json={"model": "nomic-embed-text", "input": ["hello", "world", "test"]},
        )
        assert result == [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]

    @pytest.mark.asyncio
    async def test_embed_batch_empty_list(self) -> None:
        """embed_batch([]) should return [] without making any HTTP call."""
        provider = self._make_provider()

        mock = _mock_client()
        provider._client = mock

        result = await provider.embed_batch([])

        assert result == []
        mock.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_embed_batch_preserves_order(self) -> None:
        """embed_batch() should return embeddings in input order."""
        provider = self._make_provider()

        ordered_embeddings = [[1.0, 1.1], [2.0, 2.1], [3.0, 3.1], [4.0, 4.1]]
        mock_resp = _mock_response({"embeddings": ordered_embeddings})
        mock = _mock_client()
        mock.post.return_value = mock_resp
        provider._client = mock

        result = await provider.embed_batch(["a", "b", "c", "d"])

        assert len(result) == 4
        assert result[0] == [1.0, 1.1]
        assert result[1] == [2.0, 2.1]
        assert result[2] == [3.0, 3.1]
        assert result[3] == [4.0, 4.1]

    @pytest.mark.asyncio
    async def test_embed_close(self) -> None:
        """close() should call aclose() on the underlying httpx client."""
        provider = self._make_provider()

        mock = _mock_client()
        provider._client = mock

        await provider.close()

        mock.aclose.assert_awaited_once()

    def test_provider_has_persistent_client_on_init(self) -> None:
        """The provider should create an httpx.AsyncClient in __init__."""
        provider = self._make_provider()

        assert isinstance(provider._client, httpx.AsyncClient)

    def test_provider_client_has_connection_limits(self) -> None:
        """The persistent client should have connection pool limits configured."""
        from agent33.memory.embeddings import EmbeddingProvider

        provider = EmbeddingProvider(
            base_url="http://test:11434",
            max_connections=30,
            max_keepalive_connections=15,
        )

        assert isinstance(provider._client, httpx.AsyncClient)


# ---------------------------------------------------------------------------
# OllamaProvider tests
# ---------------------------------------------------------------------------


class TestOllamaProviderPooling:
    """Tests for OllamaProvider HTTP client pooling."""

    def _make_provider(self) -> "OllamaProvider":  # noqa: UP037
        from agent33.llm.ollama import OllamaProvider

        return OllamaProvider(base_url="http://test:11434")

    def test_ollama_has_persistent_client_on_init(self) -> None:
        """OllamaProvider should create an httpx.AsyncClient in __init__."""
        provider = self._make_provider()

        assert isinstance(provider._client, httpx.AsyncClient)

    @pytest.mark.asyncio
    async def test_ollama_post_uses_persistent_client(self) -> None:
        """_post() should use self._client instead of creating a new client."""
        provider = self._make_provider()

        mock_resp = _mock_response({"result": "ok"})
        mock = _mock_client()
        mock.post.return_value = mock_resp
        provider._client = mock

        result = await provider._post("/api/chat", {"model": "test"})

        mock.post.assert_awaited_once_with("http://test:11434/api/chat", json={"model": "test"})
        assert result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_ollama_get_uses_persistent_client(self) -> None:
        """_get() should use self._client instead of creating a new client."""
        provider = self._make_provider()

        mock_resp = _mock_response({"models": []})
        mock = _mock_client()
        mock.get.return_value = mock_resp
        provider._client = mock

        result = await provider._get("/api/tags")

        mock.get.assert_awaited_once_with("http://test:11434/api/tags")
        assert result == {"models": []}

    @pytest.mark.asyncio
    async def test_ollama_close(self) -> None:
        """close() should call aclose() on the httpx client."""
        provider = self._make_provider()

        mock = _mock_client()
        provider._client = mock

        await provider.close()

        mock.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ollama_post_retries_on_transport_error(self) -> None:
        """_post() should retry on TransportError using the persistent client."""
        provider = self._make_provider()

        mock_success = _mock_response({"ok": True})
        mock = _mock_client()
        mock.post = AsyncMock(side_effect=[httpx.ConnectError("connection refused"), mock_success])
        provider._client = mock

        with patch("agent33.llm.ollama.asyncio.sleep", new_callable=AsyncMock):
            result = await provider._post("/api/chat", {"model": "test"})

        assert result == {"ok": True}
        assert mock.post.await_count == 2


# ---------------------------------------------------------------------------
# OpenAIProvider tests
# ---------------------------------------------------------------------------


class TestOpenAIProviderPooling:
    """Tests for OpenAIProvider HTTP client pooling."""

    def _make_provider(self) -> "OpenAIProvider":  # noqa: UP037
        from agent33.llm.openai import OpenAIProvider

        return OpenAIProvider(api_key="test-key", base_url="http://test:8080/v1")

    def test_openai_has_persistent_client_on_init(self) -> None:
        """OpenAIProvider should create an httpx.AsyncClient in __init__."""
        provider = self._make_provider()

        assert isinstance(provider._client, httpx.AsyncClient)

    @pytest.mark.asyncio
    async def test_openai_post_uses_persistent_client(self) -> None:
        """_post() should use self._client instead of creating a new client."""
        provider = self._make_provider()

        mock_resp = _mock_response(
            {
                "choices": [{"message": {"content": "hi"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            }
        )
        mock = _mock_client()
        mock.post.return_value = mock_resp
        provider._client = mock

        result = await provider._post("/chat/completions", {"model": "gpt-4o"})

        mock.post.assert_awaited_once_with(
            "http://test:8080/v1/chat/completions",
            json={"model": "gpt-4o"},
            headers=provider._headers(),
        )
        assert result["choices"][0]["message"]["content"] == "hi"

    @pytest.mark.asyncio
    async def test_openai_get_uses_persistent_client(self) -> None:
        """_get() should use self._client instead of creating a new client."""
        provider = self._make_provider()

        mock_resp = _mock_response({"data": [{"id": "gpt-4o"}]})
        mock = _mock_client()
        mock.get.return_value = mock_resp
        provider._client = mock

        result = await provider._get("/models")

        mock.get.assert_awaited_once_with(
            "http://test:8080/v1/models",
            headers=provider._headers(),
        )
        assert result == {"data": [{"id": "gpt-4o"}]}

    @pytest.mark.asyncio
    async def test_openai_close(self) -> None:
        """close() should call aclose() on the httpx client."""
        provider = self._make_provider()

        mock = _mock_client()
        provider._client = mock

        await provider.close()

        mock.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_openai_post_retries_on_transport_error(self) -> None:
        """_post() should retry on TransportError using the persistent client."""
        provider = self._make_provider()

        mock_success = _mock_response({"ok": True})
        mock = _mock_client()
        mock.post = AsyncMock(side_effect=[httpx.ConnectError("connection refused"), mock_success])
        provider._client = mock

        with patch("agent33.llm.openai.asyncio.sleep", new_callable=AsyncMock):
            result = await provider._post("/chat/completions", {"model": "gpt-4o"})

        assert result == {"ok": True}
        assert mock.post.await_count == 2


# ---------------------------------------------------------------------------
# JinaEmbeddingProvider tests
# ---------------------------------------------------------------------------


class TestJinaEmbeddingProviderPooling:
    """Tests for JinaEmbeddingProvider HTTP client pooling."""

    def _make_provider(self) -> "JinaEmbeddingProvider":  # noqa: UP037
        from agent33.memory.jina_embeddings import JinaEmbeddingProvider

        return JinaEmbeddingProvider(model="jina-embeddings-v3")

    def test_jina_has_persistent_client_on_init(self) -> None:
        """JinaEmbeddingProvider should create an httpx.AsyncClient in __init__."""
        provider = self._make_provider()

        assert isinstance(provider._client, httpx.AsyncClient)

    @pytest.mark.asyncio
    async def test_jina_embed_batch_uses_persistent_client(self) -> None:
        """embed_batch() should use self._client."""
        provider = self._make_provider()

        mock_resp = _mock_response(
            {
                "data": [
                    {"index": 0, "embedding": [0.1, 0.2]},
                    {"index": 1, "embedding": [0.3, 0.4]},
                ]
            }
        )
        mock = _mock_client()
        mock.post.return_value = mock_resp
        provider._client = mock

        result = await provider.embed_batch(["hello", "world"])

        mock.post.assert_awaited_once()
        assert result == [[0.1, 0.2], [0.3, 0.4]]

    @pytest.mark.asyncio
    async def test_jina_embed_batch_empty_list(self) -> None:
        """embed_batch([]) should return [] without making any HTTP call."""
        provider = self._make_provider()

        mock = _mock_client()
        provider._client = mock

        result = await provider.embed_batch([])

        assert result == []
        mock.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_jina_embed_delegates_to_embed_batch(self) -> None:
        """embed() should delegate to embed_batch() for a single text."""
        provider = self._make_provider()

        mock_resp = _mock_response({"data": [{"index": 0, "embedding": [0.5, 0.6]}]})
        mock = _mock_client()
        mock.post.return_value = mock_resp
        provider._client = mock

        result = await provider.embed("test text")

        assert result == [0.5, 0.6]
        # Only one HTTP call should have been made
        mock.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_jina_embed_batch_preserves_order(self) -> None:
        """embed_batch() should sort by index to preserve input order."""
        provider = self._make_provider()

        # Return in reverse index order to verify sorting
        mock_resp = _mock_response(
            {
                "data": [
                    {"index": 2, "embedding": [0.5, 0.6]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                    {"index": 1, "embedding": [0.3, 0.4]},
                ]
            }
        )
        mock = _mock_client()
        mock.post.return_value = mock_resp
        provider._client = mock

        result = await provider.embed_batch(["a", "b", "c"])

        assert result == [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]

    @pytest.mark.asyncio
    async def test_jina_close(self) -> None:
        """close() should call aclose() on the httpx client."""
        provider = self._make_provider()

        mock = _mock_client()
        provider._client = mock

        await provider.close()

        mock.aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestConfigHttpSettings:
    """Tests for HTTP client pool config settings."""

    def test_config_http_settings_defaults(self) -> None:
        """Settings should have correct defaults for HTTP pool config."""
        from agent33.config import Settings

        s = Settings()
        assert s.http_max_connections == 20
        assert s.http_max_keepalive == 10
        assert s.embedding_batch_size == 100

    def test_config_http_settings_override(self) -> None:
        """HTTP pool settings should be overridable via environment variables."""
        import os

        env = {
            "HTTP_MAX_CONNECTIONS": "50",
            "HTTP_MAX_KEEPALIVE": "25",
            "EMBEDDING_BATCH_SIZE": "200",
        }
        with patch.dict(os.environ, env):
            from agent33.config import Settings

            s = Settings()
            assert s.http_max_connections == 50
            assert s.http_max_keepalive == 25
            assert s.embedding_batch_size == 200
