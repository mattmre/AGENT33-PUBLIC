"""Provider/runtime error taxonomy and fallback decisions."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class ProviderErrorClass(StrEnum):
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    CONTEXT_LENGTH = "context_length"
    MODEL_UNAVAILABLE = "model_unavailable"
    TOOL_FAILURE = "tool_failure"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    NETWORK = "network"
    UNKNOWN = "unknown"


class ProviderErrorRecord(BaseModel):
    provider: str = ""
    model: str = ""
    message: str
    status_code: int = 0
    error_class: ProviderErrorClass = ProviderErrorClass.UNKNOWN


class FallbackDecision(BaseModel):
    error_class: ProviderErrorClass
    retryable: bool
    fallback_recommended: bool
    circuit_breaker_recommended: bool
    reason: str


def classify_provider_error(message: str, *, status_code: int = 0) -> ProviderErrorClass:
    text = message.lower()
    if status_code in {401, 403} or "api key" in text or "unauthorized" in text:
        return ProviderErrorClass.AUTH
    if status_code == 429 or "rate limit" in text or "quota" in text:
        return ProviderErrorClass.RATE_LIMIT
    if "context" in text and ("length" in text or "window" in text):
        return ProviderErrorClass.CONTEXT_LENGTH
    if status_code == 404 or "model not found" in text or "model unavailable" in text:
        return ProviderErrorClass.MODEL_UNAVAILABLE
    if "tool" in text and ("failed" in text or "error" in text):
        return ProviderErrorClass.TOOL_FAILURE
    if "ollama" in text or "runtime" in text or "connection refused" in text:
        return ProviderErrorClass.RUNTIME_UNAVAILABLE
    if status_code >= 500 or "timeout" in text or "network" in text:
        return ProviderErrorClass.NETWORK
    return ProviderErrorClass.UNKNOWN


def fallback_decision(error_class: ProviderErrorClass) -> FallbackDecision:
    if error_class in {ProviderErrorClass.RATE_LIMIT, ProviderErrorClass.NETWORK}:
        return FallbackDecision(
            error_class=error_class,
            retryable=True,
            fallback_recommended=True,
            circuit_breaker_recommended=True,
            reason="Transient provider failure; retry briefly then route to a healthy provider.",
        )
    if error_class in {ProviderErrorClass.CONTEXT_LENGTH, ProviderErrorClass.MODEL_UNAVAILABLE}:
        return FallbackDecision(
            error_class=error_class,
            retryable=False,
            fallback_recommended=True,
            circuit_breaker_recommended=False,
            reason="Select a compatible model before retrying the task.",
        )
    if error_class == ProviderErrorClass.AUTH:
        return FallbackDecision(
            error_class=error_class,
            retryable=False,
            fallback_recommended=False,
            circuit_breaker_recommended=True,
            reason="Credentials or provider access must be fixed before retry.",
        )
    return FallbackDecision(
        error_class=error_class,
        retryable=False,
        fallback_recommended=False,
        circuit_breaker_recommended=False,
        reason="Manual inspection required before automated fallback.",
    )
