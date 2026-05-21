"""Helpers for resolving runtime default models and fallback chains."""

from __future__ import annotations

from agent33.config import settings

_LOCAL_ORCHESTRATION_ENGINES = {
    "llama.cpp",
    "llamacpp",
    "llama-cpp",
    "vllm",
    "v-llm",
    "tgi",
    "text-generation-inference",
    "textgenerationinference",
    "openai-compatible",
    "openai_compatible",
    "local-openai",
}


def llamacpp_enabled() -> bool:
    """Return True when local orchestration should back the default runtime."""
    return settings.local_orchestration_engine.strip().lower() in _LOCAL_ORCHESTRATION_ENGINES


def resolve_default_model() -> str:
    """Return the configured default chat/agent model."""
    configured = settings.default_model.strip()
    if configured:
        return configured
    if llamacpp_enabled():
        return settings.local_orchestration_model
    return settings.ollama_default_model


def resolve_local_fallback_model_ref() -> str:
    """Return the explicit local fallback model reference."""
    if llamacpp_enabled():
        model = settings.local_orchestration_model.strip()
        return f"llamacpp/{model}" if model else ""

    model = settings.ollama_default_model.strip()
    return f"ollama/{model}" if model else ""


def resolve_openrouter_default_fallback_models(
    requested_model: str,
    *,
    explicit_model: bool,
) -> list[str]:
    """Return fallback models for the configured OpenRouter runtime default."""
    configured_default = resolve_default_model().strip()
    requested = requested_model.strip()
    if explicit_model or not requested or requested != configured_default:
        return []
    if not requested.startswith("openrouter/"):
        return []

    configured_fallbacks = [
        item.strip()
        for item in settings.openrouter_default_fallback_models.split(",")
        if item.strip()
    ]
    if not configured_fallbacks:
        local_fallback = resolve_local_fallback_model_ref()
        configured_fallbacks = [local_fallback] if local_fallback else []

    deduped: list[str] = []
    seen: set[str] = {requested}
    for candidate in configured_fallbacks:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped
