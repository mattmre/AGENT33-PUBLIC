"""Tests for the per-model pricing catalog (Phase 49)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from agent33.llm.pricing import (
    CostResult,
    CostSource,
    CostStatus,
    PricingCatalog,
    PricingEntry,
    apply_pricing_overrides_json,
    estimate_cost,
    get_default_catalog,
)


class TestPricingCatalogLookup:
    """Verify the multi-tier lookup fallback chain."""

    def test_exact_provider_model_match(self) -> None:
        """Known (provider, model) returns the correct pricing entry."""
        catalog = get_default_catalog()
        entry = catalog.lookup("openai", "gpt-4.1")
        assert entry is not None
        assert entry.input_cost_per_million == Decimal("2")
        assert entry.output_cost_per_million == Decimal("8")
        assert entry.source == CostSource.OFFICIAL_DOCS

    def test_case_insensitive_lookup(self) -> None:
        """Lookup is case-insensitive for both provider and model."""
        catalog = get_default_catalog()
        entry = catalog.lookup("OpenAI", "GPT-4.1")
        assert entry is not None
        assert entry.input_cost_per_million == Decimal("2")

    def test_model_only_fallback(self) -> None:
        """When provider doesn't match but model does, fall back to model-only."""
        catalog = get_default_catalog()
        # gpt-4.1 exists under "openai" but not under "custom-proxy"
        entry = catalog.lookup("custom-proxy", "gpt-4.1")
        assert entry is not None
        assert entry.input_cost_per_million == Decimal("2")

    def test_ollama_wildcard_match(self) -> None:
        """Any model under "ollama" provider matches the wildcard at $0."""
        catalog = get_default_catalog()
        entry = catalog.lookup("ollama", "some-custom-model-7b")
        assert entry is not None
        assert entry.input_cost_per_million == Decimal("0")
        assert entry.output_cost_per_million == Decimal("0")

    def test_local_wildcard_match(self) -> None:
        """Any model under "local" provider matches the wildcard at $0."""
        catalog = get_default_catalog()
        entry = catalog.lookup("local", "anything")
        assert entry is not None
        assert entry.input_cost_per_million == Decimal("0")

    def test_airllm_wildcard_match(self) -> None:
        """Any model under "airllm" provider matches the wildcard at $0."""
        catalog = get_default_catalog()
        entry = catalog.lookup("airllm", "llama-70b-sharded")
        assert entry is not None
        assert entry.input_cost_per_million == Decimal("0")

    def test_unknown_provider_and_model_returns_none(self) -> None:
        """Completely unknown (provider, model) returns None."""
        catalog = get_default_catalog()
        entry = catalog.lookup("nonexistent-provider", "nonexistent-model-xyz")
        assert entry is None

    def test_user_override_takes_precedence(self) -> None:
        """User overrides are checked before the builtin table."""
        catalog = PricingCatalog()
        catalog.set_override(
            "openai",
            "gpt-4.1",
            PricingEntry(
                input_cost_per_million=Decimal("99"),
                output_cost_per_million=Decimal("199"),
                source=CostSource.USER_OVERRIDE,
            ),
        )
        entry = catalog.lookup("openai", "gpt-4.1")
        assert entry is not None
        assert entry.input_cost_per_million == Decimal("99")
        assert entry.source == CostSource.USER_OVERRIDE

    def test_remove_override(self) -> None:
        """Removing an override falls back to builtin pricing."""
        catalog = PricingCatalog()
        catalog.set_override(
            "openai",
            "gpt-4.1",
            PricingEntry(
                input_cost_per_million=Decimal("99"),
                output_cost_per_million=Decimal("199"),
                source=CostSource.USER_OVERRIDE,
            ),
        )
        catalog.remove_override("openai", "gpt-4.1")
        entry = catalog.lookup("openai", "gpt-4.1")
        assert entry is not None
        # Should be the builtin value now
        assert entry.input_cost_per_million == Decimal("2")

    def test_builtin_models_returns_populated_list(self) -> None:
        """The catalog has a non-empty set of builtin models."""
        catalog = get_default_catalog()
        models = catalog.builtin_models
        assert len(models) >= 25  # 18 original + 11 Phase 49 provider entries

    def test_effective_entries_include_user_override_and_builtin_entries(self) -> None:
        """Effective entry listing applies overrides without dropping builtin rows."""
        catalog = PricingCatalog()
        catalog.set_override(
            "custom",
            "my-model",
            PricingEntry(
                input_cost_per_million=Decimal("1"),
                output_cost_per_million=Decimal("2"),
                source=CostSource.USER_OVERRIDE,
            ),
        )

        entries = catalog.list_effective_entries()

        assert ("custom", "my-model", catalog.lookup("custom", "my-model")) in entries
        assert any(provider == "openai" and model == "gpt-4.1" for provider, model, _ in entries)

    def test_apply_pricing_overrides_json_registers_user_override(self) -> None:
        """Startup pricing overrides can be applied without code edits."""
        catalog = PricingCatalog()

        applied = apply_pricing_overrides_json(
            """
            [
              {
                "provider": "openai",
                "model": "gpt-4.1",
                "input_cost_per_million": "9",
                "output_cost_per_million": "19",
                "source_url": "https://example.test/pricing",
                "fetched_at": "2026-03-29T00:00:00+00:00"
              }
            ]
            """,
            catalog=catalog,
        )

        assert applied == 1
        entry = catalog.lookup("openai", "gpt-4.1")
        assert entry is not None
        assert entry.input_cost_per_million == Decimal("9")
        assert entry.output_cost_per_million == Decimal("19")
        assert entry.source == CostSource.USER_OVERRIDE
        assert entry.source_url == "https://example.test/pricing"
        assert entry.fetched_at == datetime(2026, 3, 29, tzinfo=UTC)

    def test_apply_pricing_overrides_json_requires_array(self) -> None:
        """Invalid override payloads fail fast during startup validation."""
        with pytest.raises(ValueError, match="pricing_catalog_overrides must be a JSON array"):
            apply_pricing_overrides_json('{"provider":"openai"}', catalog=PricingCatalog())

    def test_apply_pricing_overrides_json_requires_cost_fields(self) -> None:
        """Missing required cost fields raise a clear validation error."""
        with pytest.raises(
            ValueError,
            match="must include 'input_cost_per_million' and 'output_cost_per_million'",
        ):
            apply_pricing_overrides_json(
                '[{"provider":"openai","model":"gpt-4.1"}]',
                catalog=PricingCatalog(),
            )


class TestEstimateCost:
    """Verify end-to-end cost estimation arithmetic."""

    def test_known_model_cost_calculation(self) -> None:
        """gpt-4.1 at 1000 input + 500 output tokens."""
        result = estimate_cost("gpt-4.1", "openai", 1000, 500)
        assert isinstance(result, CostResult)
        assert result.status == CostStatus.ESTIMATED
        assert result.model == "gpt-4.1"
        assert result.provider == "openai"
        assert result.input_tokens == 1000
        assert result.output_tokens == 500
        # input: 2/1M * 1000 = 0.002, output: 8/1M * 500 = 0.004, total = 0.006
        assert result.amount_usd == Decimal("0.006000")

    def test_claude_sonnet_cost_calculation(self) -> None:
        """claude-sonnet-4 at 10000 input + 2000 output tokens."""
        result = estimate_cost("claude-sonnet-4", "openai", 10000, 2000)
        assert result.status == CostStatus.ESTIMATED
        # input: 3/1M * 10000 = 0.03, output: 15/1M * 2000 = 0.03, total = 0.06
        assert result.amount_usd == Decimal("0.060000")

    def test_ollama_model_is_free(self) -> None:
        """Any ollama model should cost $0."""
        result = estimate_cost("llama3.2", "ollama", 50000, 10000)
        assert result.status == CostStatus.ESTIMATED
        assert result.amount_usd == Decimal("0.000000")

    def test_unknown_model_returns_zero_with_unknown_status(self) -> None:
        """Completely unknown model returns $0 with UNKNOWN status."""
        result = estimate_cost("mystery-model", "mystery-provider", 1000, 500)
        assert result.status == CostStatus.UNKNOWN
        assert result.amount_usd == Decimal("0")
        assert result.model == "mystery-model"
        assert result.provider == "mystery-provider"

    def test_zero_tokens_returns_zero_cost(self) -> None:
        """Zero tokens means zero cost even for expensive models."""
        result = estimate_cost("claude-opus-4", "openai", 0, 0)
        assert result.status == CostStatus.ESTIMATED
        assert result.amount_usd == Decimal("0.000000")

    def test_large_token_count_cost(self) -> None:
        """Verify arithmetic at scale (1M tokens in + 1M tokens out)."""
        result = estimate_cost("gpt-4.1", "openai", 1_000_000, 1_000_000)
        assert result.status == CostStatus.ESTIMATED
        # input: 2/1M * 1M = 2, output: 8/1M * 1M = 8, total = 10
        assert result.amount_usd == Decimal("10.000000")

    def test_custom_catalog_override(self) -> None:
        """estimate_cost respects a custom catalog with overrides."""
        catalog = PricingCatalog()
        catalog.set_override(
            "custom",
            "my-model",
            PricingEntry(
                input_cost_per_million=Decimal("10"),
                output_cost_per_million=Decimal("20"),
                source=CostSource.USER_OVERRIDE,
            ),
        )
        result = estimate_cost("my-model", "custom", 1000, 500, catalog=catalog)
        assert result.status == CostStatus.ESTIMATED
        # input: 10/1M * 1000 = 0.01, output: 20/1M * 500 = 0.01, total = 0.02
        assert result.amount_usd == Decimal("0.020000")

    def test_gemini_pro_cost(self) -> None:
        """Verify Gemini 2.5 Pro pricing."""
        result = estimate_cost("gemini-2.5-pro", "google", 100_000, 10_000)
        assert result.status == CostStatus.ESTIMATED
        # input: 1.25/1M * 100K = 0.125, output: 10/1M * 10K = 0.1, total = 0.225
        assert result.amount_usd == Decimal("0.225000")

    def test_mistral_large_cost(self) -> None:
        """Verify Mistral Large pricing."""
        result = estimate_cost("mistral-large-latest", "mistral", 5000, 2000)
        assert result.status == CostStatus.ESTIMATED
        # input: 2/1M * 5K = 0.01, output: 6/1M * 2K = 0.012, total = 0.022
        assert result.amount_usd == Decimal("0.022000")


class TestPricingCatalogCoverage:
    """Ensure all expected models are present in the builtin table."""

    @pytest.mark.parametrize(
        ("provider", "model"),
        [
            ("openai", "claude-sonnet-4"),
            ("openai", "claude-opus-4"),
            ("openai", "gpt-4.1"),
            ("openai", "gpt-4.1-mini"),
            ("openai", "gpt-4.1-nano"),
            ("openai", "gpt-4o"),
            ("openai", "gpt-4o-mini"),
            ("openai", "o3"),
            ("openai", "o3-mini"),
            ("openai", "o4-mini"),
            ("google", "gemini-2.5-pro"),
            ("google", "gemini-2.5-flash"),
            ("google", "gemini-2.0-flash"),
            ("mistral", "mistral-large-latest"),
            ("mistral", "mistral-small-latest"),
            ("mistral", "codestral-latest"),
            ("ollama", "llama3.2"),
            ("ollama", "nomic-embed-text"),
            # Phase 49 new providers
            ("deepseek", "deepseek-chat"),
            ("deepseek", "deepseek-reasoner"),
            ("groq", "llama-3.3-70b-versatile"),
            ("groq", "mixtral-8x7b-32768"),
            ("xai", "grok-2"),
            ("xai", "grok-3-mini"),
            ("cerebras", "llama3.1-70b"),
            ("cohere", "command-r-plus"),
            ("cohere", "command-r"),
            ("perplexity", "sonar-pro"),
            ("perplexity", "sonar"),
        ],
    )
    def test_model_exists_in_builtin_table(self, provider: str, model: str) -> None:
        """Each expected model should be discoverable in the catalog."""
        catalog = get_default_catalog()
        entry = catalog.lookup(provider, model)
        assert entry is not None, f"Missing builtin pricing for ({provider}, {model})"
        assert entry.input_cost_per_million >= Decimal("0")
        assert entry.output_cost_per_million >= Decimal("0")


class TestNewProviderPricing:
    """Verify exact pricing values for the new Phase 49 provider entries."""

    def test_deepseek_chat_pricing(self) -> None:
        """DeepSeek Chat: $0.14 input, $0.28 output per million tokens."""
        result = estimate_cost("deepseek-chat", "deepseek", 1_000_000, 1_000_000)
        assert result.status == CostStatus.ESTIMATED
        # input: 0.14/1M * 1M = 0.14, output: 0.28/1M * 1M = 0.28, total = 0.42
        assert result.amount_usd == Decimal("0.420000")

    def test_deepseek_reasoner_pricing(self) -> None:
        """DeepSeek Reasoner: $0.55 input, $2.19 output per million tokens."""
        result = estimate_cost("deepseek-reasoner", "deepseek", 10_000, 5_000)
        assert result.status == CostStatus.ESTIMATED
        # input: 0.55/1M * 10K = 0.0055, output: 2.19/1M * 5K = 0.01095, total = 0.01645
        assert result.amount_usd == Decimal("0.016450")

    def test_groq_llama_pricing(self) -> None:
        """Groq LLaMA 3.3 70B: $0.59 input, $0.79 output per million tokens."""
        result = estimate_cost("llama-3.3-70b-versatile", "groq", 100_000, 50_000)
        assert result.status == CostStatus.ESTIMATED
        # input: 0.59/1M * 100K = 0.059, output: 0.79/1M * 50K = 0.0395, total = 0.0985
        assert result.amount_usd == Decimal("0.098500")

    def test_groq_mixtral_pricing(self) -> None:
        """Groq Mixtral: $0.24 input, $0.24 output per million tokens."""
        result = estimate_cost("mixtral-8x7b-32768", "groq", 100_000, 100_000)
        assert result.status == CostStatus.ESTIMATED
        # input: 0.24/1M * 100K = 0.024, output: 0.24/1M * 100K = 0.024, total = 0.048
        assert result.amount_usd == Decimal("0.048000")

    def test_xai_grok2_pricing(self) -> None:
        """xAI Grok-2: $2.00 input, $10.00 output per million tokens."""
        result = estimate_cost("grok-2", "xai", 10_000, 5_000)
        assert result.status == CostStatus.ESTIMATED
        # input: 2/1M * 10K = 0.02, output: 10/1M * 5K = 0.05, total = 0.07
        assert result.amount_usd == Decimal("0.070000")

    def test_xai_grok3_mini_pricing(self) -> None:
        """xAI Grok-3 Mini: $0.30 input, $0.50 output per million tokens."""
        result = estimate_cost("grok-3-mini", "xai", 50_000, 20_000)
        assert result.status == CostStatus.ESTIMATED
        # input: 0.30/1M * 50K = 0.015, output: 0.50/1M * 20K = 0.01, total = 0.025
        assert result.amount_usd == Decimal("0.025000")

    def test_cerebras_llama_free_tier(self) -> None:
        """Cerebras LLaMA 3.1 70B: free tier ($0/$0)."""
        result = estimate_cost("llama3.1-70b", "cerebras", 500_000, 200_000)
        assert result.status == CostStatus.ESTIMATED
        assert result.amount_usd == Decimal("0.000000")

    def test_cohere_command_r_plus_pricing(self) -> None:
        """Cohere Command R+: $2.50 input, $10.00 output per million tokens."""
        result = estimate_cost("command-r-plus", "cohere", 20_000, 10_000)
        assert result.status == CostStatus.ESTIMATED
        # input: 2.50/1M * 20K = 0.05, output: 10/1M * 10K = 0.1, total = 0.15
        assert result.amount_usd == Decimal("0.150000")

    def test_cohere_command_r_pricing(self) -> None:
        """Cohere Command R: $0.15 input, $0.60 output per million tokens."""
        result = estimate_cost("command-r", "cohere", 100_000, 50_000)
        assert result.status == CostStatus.ESTIMATED
        # input: 0.15/1M * 100K = 0.015, output: 0.60/1M * 50K = 0.03, total = 0.045
        assert result.amount_usd == Decimal("0.045000")

    def test_perplexity_sonar_pro_pricing(self) -> None:
        """Perplexity Sonar Pro: $3.00 input, $15.00 output per million tokens."""
        result = estimate_cost("sonar-pro", "perplexity", 10_000, 5_000)
        assert result.status == CostStatus.ESTIMATED
        # input: 3/1M * 10K = 0.03, output: 15/1M * 5K = 0.075, total = 0.105
        assert result.amount_usd == Decimal("0.105000")

    def test_perplexity_sonar_pricing(self) -> None:
        """Perplexity Sonar: $1.00 input, $1.00 output per million tokens."""
        result = estimate_cost("sonar", "perplexity", 100_000, 100_000)
        assert result.status == CostStatus.ESTIMATED
        # input: 1/1M * 100K = 0.1, output: 1/1M * 100K = 0.1, total = 0.2
        assert result.amount_usd == Decimal("0.200000")
