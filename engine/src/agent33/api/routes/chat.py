"""Chat completions proxy to Ollama."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from agent33.config import settings
from agent33.connectors.boundary import (
    build_connector_boundary_executor,
    map_connector_exception,
)
from agent33.connectors.models import ConnectorRequest
from agent33.llm.default_models import resolve_openrouter_default_fallback_models
from agent33.llm.openai import (
    OpenAIProvider,
    is_openrouter_provider_unavailable_response,
)
from agent33.llm.runtime_config import build_model_router, resolve_default_model
from agent33.security.injection import scan_input

if TYPE_CHECKING:
    from agent33.llm.router import ModelRouter

router = APIRouter(prefix="/v1", tags=["chat"])
logger = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    temperature: float = 0.7
    max_tokens: int | None = None
    stream: bool = False


def _resolve_model_router(request: Request) -> ModelRouter:
    """Return the app router when it exposes the required route API."""
    model_router = getattr(request.app.state, "model_router", None)
    if callable(getattr(model_router, "resolve", None)):
        return cast("ModelRouter", model_router)
    return build_model_router()


@router.post("/chat/completions")
async def chat_completions(request: Request) -> Response:
    """Proxy chat completions to the locally configured orchestration engine."""
    payload = await request.json()
    explicit_model = bool(payload.get("model"))
    model = payload.get("model") or resolve_default_model()

    # Scan for prompt injection
    for msg in payload.get("messages", []):
        content = msg.get("content", "")
        if content:
            scan = scan_input(content)
            if not scan.is_safe:
                raise HTTPException(
                    status_code=400,
                    detail=f"Input rejected: {', '.join(scan.threats)}",
                )

    model_router = _resolve_model_router(request)

    try:
        resolution = model_router.resolve(model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    attempt_models = [model]
    attempt_models.extend(
        resolve_openrouter_default_fallback_models(model, explicit_model=explicit_model)
    )

    def _response_headers(provider_name: str, model_name: str) -> dict[str, str]:
        headers = {
            "X-Agent33-Requested-Model": model,
            "X-Agent33-Resolved-Provider": provider_name,
            "X-Agent33-Resolved-Model": model_name,
        }
        if model_name != model:
            headers["X-Agent33-Fallback-From"] = model
        return headers

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            boundary_executor = build_connector_boundary_executor(
                default_timeout_seconds=120.0,
                retry_attempts=1,
            )
            attempted_models: list[str] = []
            for index, attempted_model in enumerate(attempt_models):
                try:
                    resolution = model_router.resolve(attempted_model)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                payload["model"] = resolution.model_name
                attempted_models.append(attempted_model)

                if isinstance(resolution.provider, OpenAIProvider):
                    base_url = resolution.provider.base_url
                    headers = resolution.provider.request_headers
                elif resolution.provider_name == "ollama":
                    base_url = f"{settings.runtime_ollama_base_url.rstrip('/')}/v1"
                    headers = {}
                else:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"Chat completions are not available for provider "
                            f"'{resolution.provider_name}' via the OpenAI-compatible endpoint"
                        ),
                    )

                req = client.build_request(
                    "POST",
                    f"{base_url.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                connector = "api:chat_proxy"
                operation = "POST /chat/completions"

                async def _send_request(
                    _request: ConnectorRequest,
                    request_to_send: httpx.Request = req,
                ) -> httpx.Response:
                    return await client.send(request_to_send, stream=True)

                if boundary_executor is None:
                    r = await client.send(req, stream=True)
                else:
                    boundary_request = ConnectorRequest(
                        connector=connector,
                        operation=operation,
                        payload={"model": attempted_model},
                        metadata={"base_url": base_url},
                    )
                    try:
                        r = await boundary_executor.execute(boundary_request, _send_request)
                    except Exception as exc:
                        raise map_connector_exception(exc, connector, operation) from exc

                await r.aread()
                should_fallback = (
                    r.status_code >= 400
                    and index < len(attempt_models) - 1
                    and resolution.provider_name == "openrouter"
                    and is_openrouter_provider_unavailable_response(r)
                )
                if should_fallback:
                    logger.warning(
                        "chat proxy fallback from %s to %s after upstream OpenRouter failure",
                        attempted_model,
                        attempt_models[index + 1],
                    )
                    continue

                return Response(
                    content=r.content,
                    status_code=r.status_code,
                    media_type=r.headers.get("content-type", "application/json"),
                    headers=_response_headers(resolution.provider_name, attempted_model),
                )

        attempted = ", ".join(attempted_models) if attempted_models else model
        raise HTTPException(
            status_code=503,
            detail=(f"{resolution.provider_name} unavailable after attempts [{attempted}]"),
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        attempted = ", ".join(attempted_models) if "attempted_models" in locals() else model
        detail = (
            f"{resolution.provider_name} unavailable after attempts [{attempted}]: "
            f"{type(e).__name__} - {e}"
        )
        raise HTTPException(status_code=503, detail=detail) from e
