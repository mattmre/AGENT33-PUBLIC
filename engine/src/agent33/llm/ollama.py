"""Ollama LLM provider."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, cast

import httpx

from agent33.connectors.boundary import (
    build_connector_boundary_executor,
    map_connector_exception,
)
from agent33.connectors.models import ConnectorRequest
from agent33.llm._stream_utils import stream_lines_through_boundary
from agent33.llm.base import (
    ChatMessage,
    ImageBlock,
    LLMResponse,
    LLMStreamChunk,
    TextBlock,
    ToolCall,
    ToolCallDelta,
    ToolCallFunction,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:11434"
_MAX_ATTEMPTS = 3
_BACKOFF_BASE = 1.0
_DEFAULT_TIMEOUT = 120.0


class OllamaProvider:
    """LLM provider that talks to a local or remote Ollama instance."""

    supports_streaming: bool = True

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        default_model: str = "llama3.2",
        timeout: float = _DEFAULT_TIMEOUT,
        max_connections: int = 20,
        max_keepalive_connections: int = 10,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
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

    # -- helpers ----------------------------------------------------------

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST with exponential-backoff retry."""
        connector = "llm:ollama"
        operation = f"POST {path}"

        async def _perform_post() -> dict[str, Any]:
            response = await self._client.post(f"{self._base_url}{path}", json=payload)
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

        async def _execute_post(_request: ConnectorRequest) -> dict[str, Any]:
            return await _perform_post()

        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                if self._boundary_executor is None:
                    return await _perform_post()
                request = ConnectorRequest(
                    connector=connector,
                    operation=operation,
                    payload=payload,
                    metadata={"base_url": self._base_url},
                )
                result = await self._boundary_executor.execute(request, _execute_post)
                return cast("dict[str, Any]", result)
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                if attempt < _MAX_ATTEMPTS - 1:
                    delay = _BACKOFF_BASE * (2**attempt)
                    logger.warning(
                        "ollama request failed (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1,
                        _MAX_ATTEMPTS,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
            except Exception as exc:
                if self._boundary_executor is not None:
                    raise map_connector_exception(exc, connector, operation) from exc
                raise
        failure = RuntimeError(f"Ollama request to {path} failed after {_MAX_ATTEMPTS} attempts")
        if self._boundary_executor is not None and last_exc is not None:
            raise map_connector_exception(last_exc, connector, operation) from last_exc
        raise failure from last_exc

    async def _get(self, path: str) -> dict[str, Any]:
        """GET with exponential-backoff retry."""
        connector = "llm:ollama"
        operation = f"GET {path}"

        async def _perform_get() -> dict[str, Any]:
            response = await self._client.get(f"{self._base_url}{path}")
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

        async def _execute_get(_request: ConnectorRequest) -> dict[str, Any]:
            return await _perform_get()

        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                if self._boundary_executor is None:
                    return await _perform_get()
                request = ConnectorRequest(
                    connector=connector,
                    operation=operation,
                    metadata={"base_url": self._base_url},
                )
                result = await self._boundary_executor.execute(request, _execute_get)
                return cast("dict[str, Any]", result)
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                if attempt < _MAX_ATTEMPTS - 1:
                    delay = _BACKOFF_BASE * (2**attempt)
                    logger.warning(
                        "ollama GET failed (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1,
                        _MAX_ATTEMPTS,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
            except Exception as exc:
                if self._boundary_executor is not None:
                    raise map_connector_exception(exc, connector, operation) from exc
                raise
        failure = RuntimeError(f"Ollama GET {path} failed after {_MAX_ATTEMPTS} attempts")
        if self._boundary_executor is not None and last_exc is not None:
            raise map_connector_exception(last_exc, connector, operation) from last_exc
        raise failure from last_exc

    async def _stream_lines(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        """Yield streamed response lines through the connector boundary executor."""
        connector = "llm:ollama"
        operation = f"POST {path}"
        async for line in stream_lines_through_boundary(
            client=self._client,
            url=f"{self._base_url}{path}",
            payload=payload,
            headers=None,
            timeout=self._timeout,
            connector=connector,
            operation=operation,
            metadata={"base_url": self._base_url},
            boundary_executor=self._boundary_executor,
            map_exception=map_connector_exception,
        ):
            yield line

    # -- public API -------------------------------------------------------

    @staticmethod
    def _serialize_message(m: ChatMessage) -> dict[str, Any]:
        """Serialize a ChatMessage to Ollama's message format."""
        if isinstance(m.content, list):
            text_parts: list[str] = []
            images: list[str] = []
            for part in m.content:
                if isinstance(part, TextBlock):
                    text_parts.append(part.text)
                elif isinstance(part, ImageBlock) and part.base64_data:
                    images.append(part.base64_data)
            msg: dict[str, Any] = {"role": m.role, "content": " ".join(text_parts)}
            if images:
                msg["images"] = images
        else:
            msg = {"role": m.role, "content": m.content}
        # Include tool_calls on assistant messages when present
        if m.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in m.tool_calls
            ]
        # Include tool_call_id on tool result messages
        if m.tool_call_id:
            msg["tool_call_id"] = m.tool_call_id
        if m.name:
            msg["name"] = m.name
        return msg

    @staticmethod
    def _parse_tool_calls(raw_calls: list[dict[str, Any]]) -> list[ToolCall]:
        """Parse tool calls from an Ollama response message."""
        result: list[ToolCall] = []
        for i, tc in enumerate(raw_calls):
            func_data = tc.get("function", {})
            # Ollama may return arguments as dict or string
            args = func_data.get("arguments", "{}")
            if isinstance(args, dict):
                import json

                args = json.dumps(args)
            result.append(
                ToolCall(
                    id=tc.get("id", f"call_{i}"),
                    function=ToolCallFunction(
                        name=func_data.get("name", ""),
                        arguments=args,
                    ),
                )
            )
        return result

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Generate a chat completion via Ollama."""
        resolved_model = model or self._default_model
        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": [self._serialize_message(m) for m in messages],
            "stream": False,
            "options": {"temperature": temperature},
        }
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens
        if tools is not None:
            # Wrap raw function defs in OpenAI-style tool objects for
            # consistency with the OpenAI provider format.
            payload["tools"] = [
                t if "type" in t else {"type": "function", "function": t} for t in tools
            ]

        data = await self._post("/api/chat", payload)

        message_data = data.get("message", {})
        content = message_data.get("content", "")
        response_model = data.get("model", resolved_model)

        # Parse tool calls from response if present
        raw_tool_calls = message_data.get("tool_calls")
        parsed_tool_calls: list[ToolCall] | None = None
        if raw_tool_calls:
            parsed_tool_calls = self._parse_tool_calls(raw_tool_calls)

        finish_reason = "tool_calls" if parsed_tool_calls else "stop"
        usage_available = isinstance(data.get("prompt_eval_count"), int) and isinstance(
            data.get("eval_count"), int
        )

        return LLMResponse(
            content=content,
            model=response_model,
            prompt_tokens=data.get("prompt_eval_count", 0) if usage_available else 0,
            completion_tokens=data.get("eval_count", 0) if usage_available else 0,
            tool_calls=parsed_tool_calls,
            finish_reason=finish_reason,
            usage_available=usage_available,
        )

    async def list_models(self) -> list[str]:
        """Return model names available on the Ollama instance."""
        data = await self._get("/api/tags")
        models: list[dict[str, Any]] = data.get("models", [])
        return [m["name"] for m in models if "name" in m]

    async def stream_complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        """Stream completion chunks via NDJSON."""
        resolved_model = model or self._default_model
        body: dict[str, Any] = {
            "model": resolved_model,
            "messages": [self._serialize_message(m) for m in messages],
            "stream": True,
            "options": {"temperature": temperature},
        }
        if max_tokens is not None:
            body["options"]["num_predict"] = max_tokens
        if tools is not None:
            body["tools"] = [
                t if "type" in t else {"type": "function", "function": t} for t in tools
            ]

        async for line in self._stream_lines("/api/chat", body):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = data.get("message", {})
            chunk_model = data.get("model", resolved_model)
            raw_tool_calls = msg.get("tool_calls") or []
            finish_reason = data.get("done_reason")
            if finish_reason is None and data.get("done"):
                finish_reason = "tool_calls" if raw_tool_calls else "stop"
            content = msg.get("content", "") or ""
            usage_available = isinstance(data.get("prompt_eval_count"), int) and isinstance(
                data.get("eval_count"), int
            )
            prompt_tokens = data.get("prompt_eval_count", 0) if usage_available else 0
            completion_tokens = data.get("eval_count", 0) if usage_available else 0
            if content or finish_reason is not None or usage_available:
                yield LLMStreamChunk(
                    delta_content=content,
                    finish_reason=finish_reason,
                    model=chunk_model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    usage_available=usage_available,
                )
            if raw_tool_calls:
                parsed_tool_calls = self._parse_tool_calls(raw_tool_calls)
                for index, tool_call in enumerate(parsed_tool_calls):
                    yield LLMStreamChunk(
                        tool_call_delta=ToolCallDelta(
                            index=index,
                            id=tool_call.id,
                            name=tool_call.function.name,
                            arguments_fragment=tool_call.function.arguments,
                        ),
                        finish_reason="tool_calls" if data.get("done") else finish_reason,
                        model=chunk_model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        usage_available=usage_available,
                    )
