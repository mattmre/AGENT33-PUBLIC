"""Provider catalog and auto-registration for LLM providers.

Defines 22+ known LLM providers and enables automatic registration
from environment variables.  All OpenAI-compatible providers use
:class:`OpenAIProvider` with the correct base URL and prefix mapping.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent33.llm.router import ModelRouter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderInfo:
    """Metadata about a known LLM provider."""

    name: str
    display_name: str
    base_url: str
    auth_type: str = "bearer"  # "bearer" | "api-key" | "none"
    model_prefixes: list[str] = field(default_factory=list)
    env_key_var: str = ""  # Name of the env var holding the API key
    openai_compatible: bool = True
    notes: str = ""


# ── Known Provider Catalog ───────────────────────────────────────────

PROVIDER_CATALOG: dict[str, ProviderInfo] = {
    "openai": ProviderInfo(
        name="openai",
        display_name="OpenAI",
        base_url="https://api.openai.com/v1",
        model_prefixes=["gpt-", "o1", "o3", "o4", "ft:gpt-", "dall-e-", "chatgpt-"],
        env_key_var="OPENAI_API_KEY",
    ),
    "anthropic": ProviderInfo(
        name="anthropic",
        display_name="Anthropic",
        base_url="https://api.anthropic.com/v1",
        model_prefixes=["claude-"],
        env_key_var="ANTHROPIC_API_KEY",
        notes="Requires OpenAI-compatible proxy or direct API adapter",
    ),
    "azure_openai": ProviderInfo(
        name="azure_openai",
        display_name="Azure OpenAI",
        base_url="",  # Deployment-specific
        model_prefixes=["azure/"],
        env_key_var="AZURE_OPENAI_API_KEY",
        notes="base_url is deployment-specific",
    ),
    "groq": ProviderInfo(
        name="groq",
        display_name="Groq",
        base_url="https://api.groq.com/openai/v1",
        model_prefixes=["llama-", "mixtral-", "gemma-", "llama3-"],
        env_key_var="GROQ_API_KEY",
    ),
    "together": ProviderInfo(
        name="together",
        display_name="Together AI",
        base_url="https://api.together.xyz/v1",
        model_prefixes=["together/", "meta-llama/", "mistralai/", "togethercomputer/"],
        env_key_var="TOGETHER_API_KEY",
    ),
    "mistral": ProviderInfo(
        name="mistral",
        display_name="Mistral AI",
        base_url="https://api.mistral.ai/v1",
        model_prefixes=["mistral-", "open-mistral-", "open-mixtral-", "codestral-"],
        env_key_var="MISTRAL_API_KEY",
    ),
    "fireworks": ProviderInfo(
        name="fireworks",
        display_name="Fireworks AI",
        base_url="https://api.fireworks.ai/inference/v1",
        model_prefixes=["fireworks/", "accounts/fireworks/"],
        env_key_var="FIREWORKS_API_KEY",
    ),
    "deepseek": ProviderInfo(
        name="deepseek",
        display_name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        model_prefixes=["deepseek-"],
        env_key_var="DEEPSEEK_API_KEY",
    ),
    "perplexity": ProviderInfo(
        name="perplexity",
        display_name="Perplexity AI",
        base_url="https://api.perplexity.ai",
        model_prefixes=["pplx-", "sonar-"],
        env_key_var="PERPLEXITY_API_KEY",
    ),
    "anyscale": ProviderInfo(
        name="anyscale",
        display_name="Anyscale",
        base_url="https://api.endpoints.anyscale.com/v1",
        model_prefixes=["anyscale/"],
        env_key_var="ANYSCALE_API_KEY",
    ),
    "cohere": ProviderInfo(
        name="cohere",
        display_name="Cohere",
        base_url="https://api.cohere.ai/v1",
        model_prefixes=["command-", "cohere/"],
        env_key_var="COHERE_API_KEY",
    ),
    "google": ProviderInfo(
        name="google",
        display_name="Google AI (Gemini)",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        model_prefixes=["gemini-", "models/gemini-"],
        env_key_var="GOOGLE_API_KEY",
    ),
    "xai": ProviderInfo(
        name="xai",
        display_name="xAI (Grok)",
        base_url="https://api.x.ai/v1",
        model_prefixes=["grok-"],
        env_key_var="XAI_API_KEY",
    ),
    "openrouter": ProviderInfo(
        name="openrouter",
        display_name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        model_prefixes=["openrouter/"],
        env_key_var="OPENROUTER_API_KEY",
    ),
    "replicate": ProviderInfo(
        name="replicate",
        display_name="Replicate",
        base_url="https://api.replicate.com/v1",
        model_prefixes=["replicate/"],
        env_key_var="REPLICATE_API_KEY",
        openai_compatible=False,
        notes="Uses Replicate HTTP API, not OpenAI-compatible",
    ),
    "huggingface": ProviderInfo(
        name="huggingface",
        display_name="Hugging Face Inference",
        base_url="https://api-inference.huggingface.co/models",
        model_prefixes=["hf/"],
        env_key_var="HUGGINGFACE_API_KEY",
        openai_compatible=False,
    ),
    "ollama": ProviderInfo(
        name="ollama",
        display_name="Ollama (Local)",
        base_url="http://localhost:11434",
        auth_type="none",
        model_prefixes=[],
        openai_compatible=False,
        notes="Default local provider; no API key needed",
    ),
    "lmstudio": ProviderInfo(
        name="lmstudio",
        display_name="LM Studio",
        base_url="http://localhost:1234/v1",
        auth_type="none",
        model_prefixes=["lmstudio/"],
        notes="Local OpenAI-compatible server",
    ),
    "vllm": ProviderInfo(
        name="vllm",
        display_name="vLLM",
        base_url="http://localhost:8000/v1",
        auth_type="none",
        model_prefixes=["vllm/"],
        notes="Self-hosted vLLM server",
    ),
    "llamacpp": ProviderInfo(
        name="llamacpp",
        display_name="llama.cpp Server",
        base_url="http://host.docker.internal:8033/v1",
        auth_type="none",
        model_prefixes=["llamacpp/"],
        notes="llama.cpp HTTP server with OpenAI-compatible endpoint",
    ),
    "bedrock": ProviderInfo(
        name="bedrock",
        display_name="AWS Bedrock",
        base_url="",
        model_prefixes=["bedrock/"],
        env_key_var="AWS_ACCESS_KEY_ID",
        openai_compatible=False,
        notes="Requires AWS SDK; base_url is region-specific",
    ),
    "vertex": ProviderInfo(
        name="vertex",
        display_name="Google Vertex AI",
        base_url="",
        model_prefixes=["vertex/"],
        env_key_var="GOOGLE_APPLICATION_CREDENTIALS",
        openai_compatible=False,
        notes="Requires Google Cloud SDK; base_url is project-specific",
    ),
    "cerebras": ProviderInfo(
        name="cerebras",
        display_name="Cerebras",
        base_url="https://api.cerebras.ai/v1",
        model_prefixes=["cerebras/"],
        env_key_var="CEREBRAS_API_KEY",
    ),
}


def get_provider_info(name: str) -> ProviderInfo | None:
    """Look up a provider by name from the catalog."""
    return PROVIDER_CATALOG.get(name)


def list_providers() -> list[ProviderInfo]:
    """Return all known providers sorted by name."""
    return sorted(PROVIDER_CATALOG.values(), key=lambda p: p.name)


def list_openai_compatible() -> list[ProviderInfo]:
    """Return only OpenAI-compatible providers."""
    return [p for p in list_providers() if p.openai_compatible]


def build_prefix_map(
    providers: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Build a model-prefix → provider-name map from the catalog.

    If *providers* is given, only include those providers.
    Otherwise includes all providers with defined prefixes.
    """
    prefix_map: list[tuple[str, str]] = []
    catalog = PROVIDER_CATALOG
    names = providers if providers else list(catalog.keys())
    for name in names:
        info = catalog.get(name)
        if info is None:
            continue
        for prefix in info.model_prefixes:
            prefix_map.append((prefix, name))
    return prefix_map


def auto_register(
    router: ModelRouter,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Auto-register OpenAI-compatible providers that have API keys set.

    Scans the catalog for providers whose ``env_key_var`` exists in
    *env* (defaults to ``os.environ``).  Creates an ``OpenAIProvider``
    for each and registers it on the router.

    Returns the list of registered provider names.
    """
    import os

    from agent33.llm.openai import OpenAIProvider

    env = env if env is not None else dict(os.environ)
    registered: list[str] = []

    for name, info in PROVIDER_CATALOG.items():
        if not info.openai_compatible:
            continue
        if not info.env_key_var:
            continue
        api_key = env.get(info.env_key_var, "")
        if not api_key:
            continue
        if not info.base_url:
            continue

        provider = OpenAIProvider(
            api_key=api_key,
            base_url=info.base_url,
        )
        router.register(name, provider)
        registered.append(name)
        logger.info(
            "Auto-registered provider '%s' (%s)",
            name,
            info.display_name,
        )

    # Update the router's prefix map with all registered providers.
    if registered:
        prefix_map = build_prefix_map(registered)
        for prefix, pname in prefix_map:
            router._prefix_map.append((prefix, pname))

    return registered
