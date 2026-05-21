"""Embedding provider using Ollama's batched embedding API."""

from __future__ import annotations

from typing import cast

import httpx

from agent33.connectors.boundary import (
    build_connector_boundary_executor,
    map_connector_exception,
)
from agent33.connectors.models import ConnectorRequest

_DEFAULT_BASE_URL = "http://localhost:11434"
_DEFAULT_MODEL = "nomic-embed-text"
_DEFAULT_TIMEOUT = 60.0


def _normalize_embed_response(data: object, expected_count: int) -> list[list[float]]:
    """Support both batched and legacy single-embedding response shapes."""
    if isinstance(data, dict):
        embeddings = data.get("embeddings")
        if isinstance(embeddings, list):
            return cast("list[list[float]]", embeddings)

        embedding = data.get("embedding")
        if expected_count == 1 and isinstance(embedding, list):
            return [cast("list[float]", embedding)]

    raise KeyError("embeddings")


class EmbeddingProvider:
    """Generates text embeddings via Ollama."""

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        model: str = _DEFAULT_MODEL,
        timeout: float = _DEFAULT_TIMEOUT,
        max_connections: int = 20,
        max_keepalive_connections: int = 10,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive_connections,
            ),
        )
        self._boundary_executor = build_connector_boundary_executor(
            default_timeout_seconds=timeout,
            retry_attempts=1,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for a single text."""
        embeddings = await self.embed_batch([text])
        return embeddings[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts in a single batched request."""
        if not texts:
            return []
        connector = "memory:ollama_embeddings"
        operation = "POST /api/embed"
        payload = {"model": self._model, "input": texts}

        async def _perform_embed_batch() -> list[list[float]]:
            response = await self._client.post(
                f"{self._base_url}/api/embed",
                json=payload,
            )
            response.raise_for_status()
            return _normalize_embed_response(response.json(), len(texts))

        async def _execute_embed_batch(_request: ConnectorRequest) -> list[list[float]]:
            return await _perform_embed_batch()

        if self._boundary_executor is None:
            return await _perform_embed_batch()

        request = ConnectorRequest(
            connector=connector,
            operation=operation,
            payload=payload,
            metadata={"base_url": self._base_url},
        )
        try:
            return cast(
                "list[list[float]]",
                await self._boundary_executor.execute(request, _execute_embed_batch),
            )
        except Exception as exc:
            raise map_connector_exception(exc, connector, operation) from exc
