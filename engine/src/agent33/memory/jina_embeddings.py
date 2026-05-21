"""Jina Embeddings API provider."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from agent33.config import settings
from agent33.connectors.boundary import (
    build_connector_boundary_executor,
    map_connector_exception,
)
from agent33.connectors.models import ConnectorRequest

logger = logging.getLogger(__name__)

_JINA_EMBED_URL = "https://api.jina.ai/v1/embeddings"


class JinaEmbeddingProvider:
    """Generate embeddings via the Jina Embeddings API."""

    def __init__(
        self,
        model: str = "jina-embeddings-v3",
        timeout: float = 60.0,
        max_connections: int = 20,
        max_keepalive_connections: int = 10,
    ) -> None:
        self.model = model
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

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.jina_api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string."""
        result = await self.embed_batch([text])
        return result[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in a single API call."""
        if not texts:
            return []
        connector = "memory:jina_embeddings"
        operation = "POST /v1/embeddings"
        payload = {"model": self.model, "input": texts}

        async def _perform_embed_batch() -> list[list[float]]:
            resp = await self._client.post(
                _JINA_EMBED_URL,
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            # Sort by index to preserve order
            embeddings = sorted(data["data"], key=lambda x: x["index"])
            return [e["embedding"] for e in embeddings]

        async def _execute_embed_batch(_request: ConnectorRequest) -> list[list[float]]:
            return await _perform_embed_batch()

        if self._boundary_executor is None:
            return await _perform_embed_batch()

        request = ConnectorRequest(
            connector=connector,
            operation=operation,
            payload=payload,
            metadata={"url": _JINA_EMBED_URL},
        )
        try:
            result: list[list[float]] = await self._boundary_executor.execute(
                request, _execute_embed_batch
            )
            return result
        except Exception as exc:
            raise map_connector_exception(exc, connector, operation) from exc
