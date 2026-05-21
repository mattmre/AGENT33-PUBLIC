"""Internal helpers for provider streaming."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any, cast

from agent33.connectors.models import ConnectorRequest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    import httpx

_STREAM_LINE_QUEUE_MAXSIZE = 1


async def stream_lines_through_boundary(
    *,
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None,
    timeout: float,
    connector: str,
    operation: str,
    metadata: dict[str, Any],
    boundary_executor: Any,
    map_exception: Callable[[Exception, str, str], Exception],
) -> AsyncGenerator[str, None]:
    """Yield streamed response lines with bounded buffering and cancellation safety."""
    done = object()
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=_STREAM_LINE_QUEUE_MAXSIZE)

    async def _perform_stream() -> None:
        async with client.stream(
            "POST",
            url,
            json=payload,
            headers=headers,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                await queue.put(line)

    async def _execute_stream(_request: ConnectorRequest) -> None:
        await _perform_stream()

    async def _produce() -> None:
        try:
            if boundary_executor is None:
                await _perform_stream()
            else:
                request = ConnectorRequest(
                    connector=connector,
                    operation=operation,
                    payload=payload,
                    metadata=metadata,
                )
                await boundary_executor.execute(request, _execute_stream)
        except Exception as exc:
            if boundary_executor is not None:
                exc = map_exception(exc, connector, operation)
            await queue.put(exc)
        finally:
            await queue.put(done)

    producer = asyncio.create_task(_produce())
    try:
        while True:
            item = await queue.get()
            if item is done:
                break
            if isinstance(item, Exception):
                raise item
            yield cast("str", item)
    finally:
        producer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await producer
