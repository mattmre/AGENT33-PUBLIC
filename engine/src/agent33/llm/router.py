"""Model router that dispatches to the correct LLM provider."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agent33.llm.default_models import resolve_openrouter_default_fallback_models
from agent33.llm.openai import is_openrouter_provider_unavailable_error

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from agent33.llm.base import ChatMessage, LLMProvider, LLMResponse, LLMStreamChunk

from agent33.llm.base import StreamingNotSupportedError

logger = logging.getLogger(__name__)

# Maps model-name prefixes to provider names. Checked in order; first match wins.
_DEFAULT_PREFIX_MAP: list[tuple[str, str]] = [
    ("gpt-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("claude-", "openai"),  # Anthropic via OpenAI-compat proxy
    ("ft:gpt-", "openai"),
    ("airllm-", "airllm"),
]

_DEFAULT_PROVIDER = "ollama"


@dataclass(frozen=True, slots=True)
class RouteResolution:
    """Resolved provider + model name for an LLM request."""

    provider_name: str
    provider: LLMProvider
    model_name: str


class ModelRouter:
    """Routes completion requests to the appropriate LLM provider."""

    def __init__(
        self,
        providers: dict[str, Any] | None = None,
        prefix_map: list[tuple[str, str]] | None = None,
        default_provider: str = _DEFAULT_PROVIDER,
    ) -> None:
        self._providers: dict[str, LLMProvider] = dict(providers or {})
        self._prefix_map = prefix_map if prefix_map is not None else list(_DEFAULT_PREFIX_MAP)
        self._default_provider = default_provider

    # -- provider management ----------------------------------------------

    def register(self, name: str, provider: LLMProvider) -> None:
        """Register a provider under the given name."""
        self._providers[name] = provider
        logger.info("registered llm provider %s", name)

    def unregister(self, name: str) -> None:
        """Remove a registered provider."""
        self._providers.pop(name, None)

    @property
    def providers(self) -> dict[str, LLMProvider]:
        """Read-only view of registered providers."""
        return dict(self._providers)

    # -- routing ----------------------------------------------------------

    def _known_provider_names(self) -> set[str]:
        from agent33.llm.providers import PROVIDER_CATALOG

        names = {self._default_provider}
        names.update(PROVIDER_CATALOG.keys())
        names.update(self._providers.keys())
        names.update(provider_name for _, provider_name in self._prefix_map)
        return names

    @staticmethod
    def _normalize_explicit_model(provider_name: str, model_name: str) -> str:
        """Normalize explicit ``provider/model`` refs for provider APIs."""
        if provider_name == "openrouter":
            return "openrouter/auto" if model_name == "auto" else model_name
        return model_name

    def resolve(self, model_name: str) -> RouteResolution:
        """Resolve the provider and provider-native model name."""
        if "/" in model_name:
            provider_name, explicit_model = model_name.split("/", 1)
            if provider_name in self._known_provider_names():
                if provider_name not in self._providers:
                    raise ValueError(
                        f"Model '{model_name}' explicitly targets provider '{provider_name}' "
                        "which is not registered"
                    )
                return RouteResolution(
                    provider_name=provider_name,
                    provider=self._providers[provider_name],
                    model_name=self._normalize_explicit_model(provider_name, explicit_model),
                )

        for prefix, provider_name in self._prefix_map:
            if model_name.startswith(prefix):
                if provider_name in self._providers:
                    return RouteResolution(
                        provider_name=provider_name,
                        provider=self._providers[provider_name],
                        model_name=model_name,
                    )
                raise ValueError(
                    f"Model '{model_name}' maps to provider '{provider_name}' "
                    f"which is not registered"
                )

        if self._default_provider in self._providers:
            return RouteResolution(
                provider_name=self._default_provider,
                provider=self._providers[self._default_provider],
                model_name=model_name,
            )

        raise ValueError(
            f"No provider found for model '{model_name}' and default provider "
            f"'{self._default_provider}' is not registered"
        )

    def route(self, model_name: str) -> LLMProvider:
        """Pick the right provider for *model_name* based on prefix rules."""
        return self.resolve(model_name).provider

    # -- convenience ------------------------------------------------------

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        allow_fallback: bool = False,
    ) -> LLMResponse:
        """Route to the correct provider and generate a completion."""
        attempts = [model]
        if allow_fallback:
            attempts.extend(
                resolve_openrouter_default_fallback_models(model, explicit_model=False)
            )

        attempted_models: list[str] = []
        last_exc: Exception | None = None
        for index, candidate in enumerate(attempts):
            resolved = self.resolve(candidate)
            attempted_models.append(candidate)
            try:
                response = await resolved.provider.complete(
                    messages,
                    model=resolved.model_name,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                )
                if index > 0:
                    logger.warning(
                        "llm fallback succeeded requested=%s actual=%s provider=%s",
                        model,
                        response.model,
                        resolved.provider_name,
                    )
                return response
            except Exception as exc:
                last_exc = exc
                should_fallback = (
                    index < len(attempts) - 1
                    and resolved.provider_name == "openrouter"
                    and is_openrouter_provider_unavailable_error(exc)
                )
                if should_fallback:
                    logger.warning(
                        "openrouter default unavailable; trying fallback %s after %s: %s",
                        attempts[index + 1],
                        candidate,
                        exc,
                    )
                    continue
                if index > 0:
                    attempted = ", ".join(attempted_models)
                    raise RuntimeError(
                        f"LLM fallback chain exhausted for {model}: attempted {attempted}; "
                        f"last error: {exc}"
                    ) from exc
                raise

        if last_exc is not None:
            attempted = ", ".join(attempted_models)
            raise RuntimeError(
                f"LLM fallback chain exhausted for {model}: attempted {attempted}; "
                f"last error: {last_exc}"
            ) from last_exc
        raise RuntimeError(f"LLM request failed before any provider call for model {model}")

    async def stream_complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        allow_fallback: bool = False,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        """Stream completion via the routed provider."""
        attempts = [model]
        if allow_fallback:
            attempts.extend(
                resolve_openrouter_default_fallback_models(model, explicit_model=False)
            )

        attempted_models: list[str] = []
        last_exc: Exception | None = None
        no_streaming_candidates: list[str] = []
        for index, candidate in enumerate(attempts):
            resolved = self.resolve(candidate)
            attempted_models.append(candidate)
            if not getattr(resolved.provider, "supports_streaming", False):
                # This candidate's provider doesn't support streaming — skip it
                # and try the next fallback instead of aborting the whole chain.
                no_streaming_candidates.append(candidate)
                continue
            yielded_chunks = False
            try:
                async for chunk in resolved.provider.stream_complete(
                    messages,
                    model=resolved.model_name,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                ):
                    yielded_chunks = True
                    yield chunk
                return
            except Exception as exc:
                last_exc = exc
                should_fallback = (
                    not yielded_chunks
                    and index < len(attempts) - 1
                    and resolved.provider_name == "openrouter"
                    and is_openrouter_provider_unavailable_error(exc)
                )
                if should_fallback:
                    logger.warning(
                        "openrouter default stream unavailable; trying fallback %s after %s: %s",
                        attempts[index + 1],
                        candidate,
                        exc,
                    )
                    continue
                if index > 0:
                    attempted = ", ".join(attempted_models)
                    raise RuntimeError(
                        f"LLM fallback chain exhausted for {model}: attempted {attempted}; "
                        f"last error: {exc}"
                    ) from exc
                raise

        if last_exc is not None:
            attempted = ", ".join(attempted_models)
            raise RuntimeError(
                f"LLM fallback chain exhausted for {model}: attempted {attempted}; "
                f"last error: {last_exc}"
            ) from last_exc
        if no_streaming_candidates and not attempted_models:
            raise StreamingNotSupportedError(
                f"No streaming-capable provider found for model '{model}'; "
                f"checked: {', '.join(no_streaming_candidates)}"
            )
        raise RuntimeError(f"LLM stream failed before any provider call for model {model}")
