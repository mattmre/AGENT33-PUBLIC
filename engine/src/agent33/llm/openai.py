"""OpenAI-compatible LLM provider."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, cast

import httpx

from agent33.config import settings
from agent33.connectors.boundary import (
    build_connector_boundary_executor,
    map_connector_exception,
)
from agent33.connectors.models import ConnectorRequest
from agent33.llm._stream_utils import stream_lines_through_boundary
from agent33.llm.base import (
    AudioBlock,
    ChatMessage,
    ImageBlock,
    LLMResponse,
    LLMStreamChunk,
    TextBlock,
    ToolCall,
    ToolCallDelta,
    ToolCallFunction,
)
from agent33.llm.prompt_caching import apply_anthropic_cache_control, is_anthropic_model

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_MAX_ATTEMPTS = 3
_BACKOFF_BASE = 1.0
_DEFAULT_TIMEOUT = 120.0
_OPENROUTER_PROVIDER_UNAVAILABLE_MARKERS = (
    "no allowed providers are available",
    "no providers are available",
    "no providers available",
    "provider routing",
    "provider unavailable",
)


def _coerce_openrouter_error_detail(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("message", "detail", "error"):
            nested = value.get(key)
            if nested:
                detail = _coerce_openrouter_error_detail(nested)
                if detail:
                    return detail
    return ""


def extract_openrouter_error_detail(response: httpx.Response) -> str:
    """Return the most useful OpenRouter error detail from a response body."""
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        payload = None
    if payload is not None:
        detail = _coerce_openrouter_error_detail(payload)
        if detail:
            return detail
    return response.text


def is_openrouter_provider_unavailable_response(response: httpx.Response) -> bool:
    """Return True when the response matches OpenRouter provider-routing failures."""
    if response.status_code < 400:
        return False
    detail = extract_openrouter_error_detail(response).lower()
    return any(marker in detail for marker in _OPENROUTER_PROVIDER_UNAVAILABLE_MARKERS)


def is_openrouter_provider_unavailable_error(exc: Exception) -> bool:
    """Return True when *exc* represents an OpenRouter model-availability failure."""
    if isinstance(exc, httpx.HTTPStatusError):
        return is_openrouter_provider_unavailable_response(exc.response)
    return any(marker in str(exc).lower() for marker in _OPENROUTER_PROVIDER_UNAVAILABLE_MARKERS)


class OpenAIProvider:
    """LLM provider for OpenAI and OpenAI-compatible APIs."""

    supports_streaming: bool = True

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        default_model: str = "gpt-4o",
        timeout: float = _DEFAULT_TIMEOUT,
        max_connections: int = 20,
        max_keepalive_connections: int = 10,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout = timeout
        self._extra_headers = dict(extra_headers or {})
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

    @property
    def base_url(self) -> str:
        """Return the configured API base URL."""
        return self._base_url

    @property
    def request_headers(self) -> dict[str, str]:
        """Return headers used for upstream requests."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self._extra_headers)
        return headers

    def _headers(self) -> dict[str, str]:
        return self.request_headers

    # -- helpers ----------------------------------------------------------

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST with exponential-backoff retry."""
        connector = "llm:openai"
        operation = f"POST {path}"

        async def _perform_post() -> dict[str, Any]:
            response = await self._client.post(
                f"{self._base_url}{path}",
                json=payload,
                headers=self._headers(),
            )
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
                if isinstance(
                    exc, httpx.HTTPStatusError
                ) and is_openrouter_provider_unavailable_response(exc.response):
                    break
                if attempt < _MAX_ATTEMPTS - 1:
                    delay = _BACKOFF_BASE * (2**attempt)
                    logger.warning(
                        "openai request failed (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1,
                        _MAX_ATTEMPTS,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
            except Exception as exc:
                if self._boundary_executor is not None:
                    mapped = map_connector_exception(exc, connector, operation)
                    raise mapped from exc
                raise
        if last_exc is not None and is_openrouter_provider_unavailable_error(last_exc):
            raise last_exc
        failure = RuntimeError(f"OpenAI request to {path} failed after {_MAX_ATTEMPTS} attempts")
        if self._boundary_executor is not None and last_exc is not None:
            raise map_connector_exception(last_exc, connector, operation) from last_exc
        raise failure from last_exc

    async def _get(self, path: str) -> dict[str, Any]:
        """GET with exponential-backoff retry."""
        connector = "llm:openai"
        operation = f"GET {path}"

        async def _perform_get() -> dict[str, Any]:
            response = await self._client.get(
                f"{self._base_url}{path}",
                headers=self._headers(),
            )
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
                        "openai GET failed (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1,
                        _MAX_ATTEMPTS,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
            except Exception as exc:
                if self._boundary_executor is not None:
                    mapped = map_connector_exception(exc, connector, operation)
                    raise mapped from exc
                raise
        failure = RuntimeError(f"OpenAI GET {path} failed after {_MAX_ATTEMPTS} attempts")
        if self._boundary_executor is not None and last_exc is not None:
            raise map_connector_exception(last_exc, connector, operation) from last_exc
        raise failure from last_exc

    async def _stream_lines(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        """Yield streamed response lines through the connector boundary executor."""
        connector = "llm:openai"
        operation = f"POST {path}"
        async for line in stream_lines_through_boundary(
            client=self._client,
            url=f"{self._base_url}{path}",
            payload=payload,
            headers=self._headers(),
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
        """Serialize a ChatMessage to OpenAI's message format."""
        if isinstance(m.content, list):
            content: Any = []
            for part in m.content:
                if isinstance(part, TextBlock):
                    content.append({"type": "text", "text": part.text})
                elif isinstance(part, ImageBlock):
                    if part.base64_data:
                        url = f"data:{part.media_type};base64,{part.base64_data}"
                    else:
                        url = part.url or ""
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": url, "detail": part.detail},
                        }
                    )
                elif isinstance(part, AudioBlock):
                    content.append(
                        {
                            "type": "text",
                            "text": f"[Audio: {part.url or 'embedded'}]",
                        }
                    )
        else:
            content = m.content
        msg: dict[str, Any] = {"role": m.role, "content": content}
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
        # Include tool_call_id and name on tool result messages
        if m.tool_call_id:
            msg["tool_call_id"] = m.tool_call_id
        if m.name:
            msg["name"] = m.name
        return msg

    @staticmethod
    def _parse_tool_calls(raw_calls: list[dict[str, Any]]) -> list[ToolCall]:
        """Parse tool calls from an OpenAI response message."""
        result: list[ToolCall] = []
        for tc in raw_calls:
            func_data = tc.get("function", {})
            result.append(
                ToolCall(
                    id=tc.get("id", ""),
                    function=ToolCallFunction(
                        name=func_data.get("name", ""),
                        arguments=func_data.get("arguments", "{}"),
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
        """Generate a chat completion via the OpenAI API."""
        resolved_model = model or self._default_model
        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": [self._serialize_message(m) for m in messages],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools is not None:
            # Wrap each tool dict in the OpenAI function tool format
            payload["tools"] = [{"type": "function", "function": tool_def} for tool_def in tools]

        # Phase 51: inject Anthropic prompt-cache breakpoints
        if is_anthropic_model(resolved_model) and settings.prompt_cache_enabled:
            payload["messages"] = apply_anthropic_cache_control(payload["messages"])

        data = await self._post("/chat/completions", payload)

        # Log Anthropic cache usage when available
        usage_data = data.get("usage", {})
        if isinstance(usage_data, dict):
            cache_read = usage_data.get("cache_read_input_tokens")
            cache_creation = usage_data.get("cache_creation_input_tokens")
            if cache_read is not None or cache_creation is not None:
                logger.info(
                    "anthropic cache usage: read=%s creation=%s",
                    cache_read,
                    cache_creation,
                )

        choices = data.get("choices", [])
        usage = data.get("usage")
        response_model = data.get("model", resolved_model)
        usage_dict = cast("dict[str, Any] | None", usage if isinstance(usage, dict) else None)
        usage_available = (
            usage_dict is not None
            and isinstance(usage_dict.get("prompt_tokens"), int)
            and isinstance(usage_dict.get("completion_tokens"), int)
        )
        prompt_token_count = (
            cast("int", usage_dict["prompt_tokens"])
            if usage_available and usage_dict is not None
            else 0
        )
        completion_token_count = (
            cast("int", usage_dict["completion_tokens"])
            if usage_available and usage_dict is not None
            else 0
        )
        if not choices:
            return LLMResponse(
                content="",
                model=response_model,
                prompt_tokens=prompt_token_count,
                completion_tokens=completion_token_count,
                usage_available=usage_available,
            )

        choice = choices[0]
        message_data = choice.get("message", {})
        content = message_data.get("content") or ""
        finish = choice.get("finish_reason", "stop")

        # Parse tool calls from response if present
        raw_tool_calls = message_data.get("tool_calls")
        parsed_tool_calls: list[ToolCall] | None = None
        if raw_tool_calls:
            parsed_tool_calls = self._parse_tool_calls(raw_tool_calls)
            # OpenAI uses "tool_calls" as the finish_reason
            if finish in ("tool_calls", "function_call"):
                finish = "tool_calls"

        return LLMResponse(
            content=content,
            model=response_model,
            prompt_tokens=prompt_token_count,
            completion_tokens=completion_token_count,
            tool_calls=parsed_tool_calls,
            finish_reason=finish,
            usage_available=usage_available,
        )

    async def list_models(self) -> list[str]:
        """Return available model identifiers from the API."""
        data = await self._get("/models")
        models: list[dict[str, Any]] = data.get("data", [])
        return [m["id"] for m in models if "id" in m]

    async def stream_complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        """Stream completion chunks via SSE."""
        resolved_model = model or self._default_model
        body: dict[str, Any] = {
            "model": resolved_model,
            "messages": [self._serialize_message(m) for m in messages],
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if tools is not None:
            body["tools"] = [{"type": "function", "function": t} for t in tools]

        # Phase 51: inject Anthropic prompt-cache breakpoints
        if is_anthropic_model(resolved_model) and settings.prompt_cache_enabled:
            body["messages"] = apply_anthropic_cache_control(body["messages"])

        async for line in self._stream_lines("/chat/completions", body):
            line = line.strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data: "):
                line = line[6:]
            if line == "[DONE]":
                break
            try:
                chunk_data = json.loads(line)
            except json.JSONDecodeError:
                continue
            choices = chunk_data.get("choices") or []
            choice = choices[0] if choices else {}
            delta = choice.get("delta", {})
            chunk_model = chunk_data.get("model", resolved_model)
            finish_reason = choice.get("finish_reason")
            if finish_reason == "function_call":
                finish_reason = "tool_calls"
            usage = chunk_data.get("usage")
            usage_available = (
                isinstance(usage, dict)
                and isinstance(usage.get("prompt_tokens"), int)
                and isinstance(usage.get("completion_tokens"), int)
            )
            prompt_tokens = usage.get("prompt_tokens", 0) if usage_available else 0
            completion_tokens = usage.get("completion_tokens", 0) if usage_available else 0

            # Log Anthropic cache usage when available (mirrors complete())
            if usage_available and isinstance(usage, dict):
                cache_read = usage.get("cache_read_input_tokens")
                cache_creation = usage.get("cache_creation_input_tokens")
                if cache_read is not None or cache_creation is not None:
                    logger.info(
                        "anthropic cache usage: read=%s creation=%s",
                        cache_read,
                        cache_creation,
                    )

            content = delta.get("content", "") or ""
            if content or finish_reason is not None or usage_available:
                yield LLMStreamChunk(
                    delta_content=content,
                    finish_reason=finish_reason,
                    model=chunk_model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    usage_available=usage_available,
                )

            for raw_tool_call in delta.get("tool_calls", []) or []:
                function = raw_tool_call.get("function", {})
                yield LLMStreamChunk(
                    tool_call_delta=ToolCallDelta(
                        index=raw_tool_call.get("index", 0),
                        id=raw_tool_call.get("id", ""),
                        name=function.get("name", ""),
                        arguments_fragment=function.get("arguments", ""),
                    ),
                    finish_reason=finish_reason,
                    model=chunk_model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    usage_available=usage_available,
                )
