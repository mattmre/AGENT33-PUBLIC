"""Tests for the LLM provider catalog and auto-registration.

Tests cover: catalog completeness, provider info correctness, prefix
map generation, auto-registration logic, and router integration.
"""

from __future__ import annotations

import pytest

from agent33.llm.providers import (
    PROVIDER_CATALOG,
    ProviderInfo,
    auto_register,
    build_prefix_map,
    get_provider_info,
    list_openai_compatible,
    list_providers,
)
from agent33.llm.router import ModelRouter

# ═══════════════════════════════════════════════════════════════════════
# Catalog Tests
# ═══════════════════════════════════════════════════════════════════════


class TestProviderCatalog:
    """Test the provider catalog contents."""

    def test_has_at_least_22_providers(self) -> None:
        assert len(PROVIDER_CATALOG) >= 22

    def test_all_entries_are_provider_info(self) -> None:
        for name, info in PROVIDER_CATALOG.items():
            assert isinstance(info, ProviderInfo)
            assert info.name == name

    def test_known_providers_present(self) -> None:
        expected = [
            "openai",
            "anthropic",
            "groq",
            "together",
            "mistral",
            "fireworks",
            "deepseek",
            "perplexity",
            "cohere",
            "google",
            "xai",
            "openrouter",
            "ollama",
        ]
        for name in expected:
            assert name in PROVIDER_CATALOG, f"Missing provider: {name}"

    def test_ollama_is_not_openai_compatible(self) -> None:
        info = PROVIDER_CATALOG["ollama"]
        assert not info.openai_compatible

    def test_openai_is_openai_compatible(self) -> None:
        info = PROVIDER_CATALOG["openai"]
        assert info.openai_compatible

    def test_all_openai_compatible_have_base_url(self) -> None:
        # Azure has a deployment-specific URL, skip it.
        skip = {"azure_openai"}
        for name, info in PROVIDER_CATALOG.items():
            if info.openai_compatible and info.env_key_var and name not in skip:
                assert info.base_url, f"OpenAI-compatible provider '{name}' missing base_url"

    def test_get_provider_info(self) -> None:
        info = get_provider_info("groq")
        assert info is not None
        assert info.display_name == "Groq"
        assert info.base_url == "https://api.groq.com/openai/v1"

    def test_get_unknown_provider(self) -> None:
        assert get_provider_info("nonexistent") is None

    def test_list_providers_sorted(self) -> None:
        providers = list_providers()
        names = [p.name for p in providers]
        assert names == sorted(names)

    def test_list_openai_compatible(self) -> None:
        compatible = list_openai_compatible()
        assert all(p.openai_compatible for p in compatible)
        assert not any(p.name == "ollama" for p in compatible)
        assert any(p.name == "openai" for p in compatible)


# ═══════════════════════════════════════════════════════════════════════
# Prefix Map Tests
# ═══════════════════════════════════════════════════════════════════════


class TestBuildPrefixMap:
    """Test prefix map generation from catalog."""

    def test_full_prefix_map(self) -> None:
        prefix_map = build_prefix_map()
        assert len(prefix_map) > 20
        # All entries are (str, str) tuples.
        for prefix, provider in prefix_map:
            assert isinstance(prefix, str)
            assert isinstance(provider, str)

    def test_filtered_prefix_map(self) -> None:
        prefix_map = build_prefix_map(["openai", "groq"])
        providers = {p for _, p in prefix_map}
        assert providers <= {"openai", "groq"}

    def test_gpt_maps_to_openai(self) -> None:
        prefix_map = build_prefix_map()
        openai_prefixes = [p for p, name in prefix_map if name == "openai"]
        assert "gpt-" in openai_prefixes

    def test_deepseek_prefix(self) -> None:
        prefix_map = build_prefix_map(["deepseek"])
        assert ("deepseek-", "deepseek") in prefix_map

    def test_unknown_provider_skipped(self) -> None:
        prefix_map = build_prefix_map(["nonexistent"])
        assert len(prefix_map) == 0

    def test_ollama_has_no_prefixes(self) -> None:
        """Ollama is the default fallback — no prefix matching needed."""
        prefix_map = build_prefix_map(["ollama"])
        assert len(prefix_map) == 0


# ═══════════════════════════════════════════════════════════════════════
# Auto-Registration Tests
# ═══════════════════════════════════════════════════════════════════════


class TestAutoRegister:
    """Test auto-registration of providers from environment."""

    def test_no_keys_no_registration(self) -> None:
        router = ModelRouter()
        registered = auto_register(router, env={})
        assert registered == []
        assert len(router.providers) == 0

    def test_openai_key_registers_openai(self) -> None:
        router = ModelRouter()
        registered = auto_register(router, env={"OPENAI_API_KEY": "sk-test"})
        assert "openai" in registered
        assert "openai" in router.providers

    def test_multiple_keys_register_multiple(self) -> None:
        router = ModelRouter()
        env = {
            "OPENAI_API_KEY": "sk-test",
            "GROQ_API_KEY": "gsk-test",
            "DEEPSEEK_API_KEY": "dsk-test",
        }
        registered = auto_register(router, env=env)
        assert "openai" in registered
        assert "groq" in registered
        assert "deepseek" in registered
        assert len(router.providers) == 3

    def test_non_openai_compatible_skipped(self) -> None:
        """Providers not OpenAI-compatible are not auto-registered."""
        router = ModelRouter()
        # Replicate and HuggingFace are not OpenAI-compatible.
        env = {
            "REPLICATE_API_KEY": "r8-test",
            "HUGGINGFACE_API_KEY": "hf-test",
        }
        registered = auto_register(router, env=env)
        assert "replicate" not in registered
        assert "huggingface" not in registered

    def test_prefix_map_updated(self) -> None:
        """Auto-registration adds provider's prefixes to the router."""
        router = ModelRouter(prefix_map=[])
        auto_register(router, env={"GROQ_API_KEY": "gsk-test"})
        # Router should now have Groq prefixes.
        groq_prefixes = [p for p, n in router._prefix_map if n == "groq"]
        assert "llama-" in groq_prefixes or "mixtral-" in groq_prefixes

    def test_router_routes_after_registration(self) -> None:
        """Registered provider is routable via model prefix."""
        router = ModelRouter(prefix_map=[])
        auto_register(router, env={"DEEPSEEK_API_KEY": "dsk-test"})
        provider = router.route("deepseek-coder")
        assert provider is not None

    def test_empty_key_skipped(self) -> None:
        router = ModelRouter()
        registered = auto_register(router, env={"OPENAI_API_KEY": ""})
        assert registered == []

    def test_azure_skipped_no_base_url(self) -> None:
        """Azure has no default base_url so auto-registration skips it."""
        router = ModelRouter()
        registered = auto_register(router, env={"AZURE_OPENAI_API_KEY": "test"})
        assert "azure_openai" not in registered


class _DummyProvider:
    async def complete(self, *args, **kwargs):  # pragma: no cover - not used in these tests
        raise NotImplementedError

    async def stream_complete(self, *args, **kwargs):  # pragma: no cover - not used here
        raise NotImplementedError


class TestExplicitProviderRefs:
    def test_explicit_openai_ref_strips_provider_prefix(self) -> None:
        router = ModelRouter(providers={"openai": _DummyProvider()}, prefix_map=[])
        resolved = router.resolve("openai/gpt-4o")
        assert resolved.provider_name == "openai"
        assert resolved.model_name == "gpt-4o"

    def test_explicit_openrouter_auto_preserves_special_model(self) -> None:
        router = ModelRouter(providers={"openrouter": _DummyProvider()}, prefix_map=[])
        resolved = router.resolve("openrouter/auto")
        assert resolved.provider_name == "openrouter"
        assert resolved.model_name == "openrouter/auto"

    def test_explicit_openrouter_concrete_model_strips_internal_prefix(self) -> None:
        router = ModelRouter(providers={"openrouter": _DummyProvider()}, prefix_map=[])
        resolved = router.resolve("openrouter/openai/gpt-5.2")
        assert resolved.provider_name == "openrouter"
        assert resolved.model_name == "openai/gpt-5.2"

    def test_unregistered_explicit_provider_ref_errors(self) -> None:
        router = ModelRouter(providers={"ollama": _DummyProvider()}, prefix_map=[])
        with pytest.raises(ValueError, match="explicitly targets provider 'openrouter'"):
            router.resolve("openrouter/auto")
