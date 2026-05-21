"""Per-model pricing catalog for LLM cost estimation.

Provides a static pricing table for popular LLM models and a ``estimate_cost``
function that the effort router uses to replace the flat
``cost_per_1k_tokens`` heuristic with model-aware cost estimates.

Pricing data is sourced from official documentation snapshots.  Operators can
override individual entries at startup via ``PricingCatalog.set_override()``.

Phase 49 — Hermes Adoption Roadmap.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum


class CostSource(StrEnum):
    """Origin of a pricing entry."""

    OFFICIAL_DOCS = "official_docs_snapshot"
    PROVIDER_API = "provider_api"
    USER_OVERRIDE = "user_override"
    NONE = "none"


class CostStatus(StrEnum):
    """Confidence level for the cost result."""

    ACTUAL = "actual"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PricingEntry:
    """Per-token pricing for a single model."""

    input_cost_per_million: Decimal
    output_cost_per_million: Decimal
    cache_read_cost_per_million: Decimal = Decimal("0")
    cache_write_cost_per_million: Decimal = Decimal("0")
    source: CostSource = CostSource.OFFICIAL_DOCS
    source_url: str = ""
    fetched_at: datetime | None = None


@dataclass(frozen=True)
class CostResult:
    """Computed cost for a single LLM invocation."""

    amount_usd: Decimal
    status: CostStatus
    model: str
    provider: str
    input_tokens: int
    output_tokens: int


# ---------------------------------------------------------------------------
# Static pricing table: (provider, model) -> PricingEntry
# Pricing as of 2026-03-25 official documentation snapshots.
# All values are Decimal to avoid floating-point rounding in cost math.
# ---------------------------------------------------------------------------

_FETCHED = datetime(2026, 3, 25, tzinfo=UTC)

_BUILTIN_PRICING: dict[tuple[str, str], PricingEntry] = {
    # -- Anthropic (via OpenAI-compat proxy) --------------------------------
    ("openai", "claude-sonnet-4"): PricingEntry(
        input_cost_per_million=Decimal("3"),
        output_cost_per_million=Decimal("15"),
        cache_read_cost_per_million=Decimal("0.30"),
        cache_write_cost_per_million=Decimal("3.75"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://docs.anthropic.com/en/docs/about-claude/models",
        fetched_at=_FETCHED,
    ),
    ("openai", "claude-opus-4"): PricingEntry(
        input_cost_per_million=Decimal("15"),
        output_cost_per_million=Decimal("75"),
        cache_read_cost_per_million=Decimal("1.50"),
        cache_write_cost_per_million=Decimal("18.75"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://docs.anthropic.com/en/docs/about-claude/models",
        fetched_at=_FETCHED,
    ),
    # -- OpenAI -------------------------------------------------------------
    ("openai", "gpt-4.1"): PricingEntry(
        input_cost_per_million=Decimal("2"),
        output_cost_per_million=Decimal("8"),
        cache_read_cost_per_million=Decimal("0.50"),
        cache_write_cost_per_million=Decimal("0"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://openai.com/api/pricing/",
        fetched_at=_FETCHED,
    ),
    ("openai", "gpt-4.1-mini"): PricingEntry(
        input_cost_per_million=Decimal("0.40"),
        output_cost_per_million=Decimal("1.60"),
        cache_read_cost_per_million=Decimal("0.10"),
        cache_write_cost_per_million=Decimal("0"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://openai.com/api/pricing/",
        fetched_at=_FETCHED,
    ),
    ("openai", "gpt-4.1-nano"): PricingEntry(
        input_cost_per_million=Decimal("0.10"),
        output_cost_per_million=Decimal("0.40"),
        cache_read_cost_per_million=Decimal("0.025"),
        cache_write_cost_per_million=Decimal("0"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://openai.com/api/pricing/",
        fetched_at=_FETCHED,
    ),
    ("openai", "gpt-4o"): PricingEntry(
        input_cost_per_million=Decimal("2.50"),
        output_cost_per_million=Decimal("10"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://openai.com/api/pricing/",
        fetched_at=_FETCHED,
    ),
    ("openai", "gpt-4o-mini"): PricingEntry(
        input_cost_per_million=Decimal("0.15"),
        output_cost_per_million=Decimal("0.60"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://openai.com/api/pricing/",
        fetched_at=_FETCHED,
    ),
    ("openai", "o3"): PricingEntry(
        input_cost_per_million=Decimal("2"),
        output_cost_per_million=Decimal("8"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://openai.com/api/pricing/",
        fetched_at=_FETCHED,
    ),
    ("openai", "o3-mini"): PricingEntry(
        input_cost_per_million=Decimal("1.10"),
        output_cost_per_million=Decimal("4.40"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://openai.com/api/pricing/",
        fetched_at=_FETCHED,
    ),
    ("openai", "o4-mini"): PricingEntry(
        input_cost_per_million=Decimal("1.10"),
        output_cost_per_million=Decimal("4.40"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://openai.com/api/pricing/",
        fetched_at=_FETCHED,
    ),
    # -- Google Gemini ------------------------------------------------------
    ("google", "gemini-2.5-pro"): PricingEntry(
        input_cost_per_million=Decimal("1.25"),
        output_cost_per_million=Decimal("10"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://ai.google.dev/gemini-api/docs/pricing",
        fetched_at=_FETCHED,
    ),
    ("google", "gemini-2.5-flash"): PricingEntry(
        input_cost_per_million=Decimal("0.15"),
        output_cost_per_million=Decimal("0.60"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://ai.google.dev/gemini-api/docs/pricing",
        fetched_at=_FETCHED,
    ),
    ("google", "gemini-2.0-flash"): PricingEntry(
        input_cost_per_million=Decimal("0.10"),
        output_cost_per_million=Decimal("0.40"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://ai.google.dev/gemini-api/docs/pricing",
        fetched_at=_FETCHED,
    ),
    # -- Mistral ------------------------------------------------------------
    ("mistral", "mistral-large-latest"): PricingEntry(
        input_cost_per_million=Decimal("2"),
        output_cost_per_million=Decimal("6"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://mistral.ai/technology/",
        fetched_at=_FETCHED,
    ),
    ("mistral", "mistral-small-latest"): PricingEntry(
        input_cost_per_million=Decimal("0.10"),
        output_cost_per_million=Decimal("0.30"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://mistral.ai/technology/",
        fetched_at=_FETCHED,
    ),
    ("mistral", "codestral-latest"): PricingEntry(
        input_cost_per_million=Decimal("0.30"),
        output_cost_per_million=Decimal("0.90"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://mistral.ai/technology/",
        fetched_at=_FETCHED,
    ),
    # -- Ollama (local, free) -----------------------------------------------
    ("ollama", "llama3.2"): PricingEntry(
        input_cost_per_million=Decimal("0"),
        output_cost_per_million=Decimal("0"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="",
        fetched_at=_FETCHED,
    ),
    ("ollama", "nomic-embed-text"): PricingEntry(
        input_cost_per_million=Decimal("0"),
        output_cost_per_million=Decimal("0"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="",
        fetched_at=_FETCHED,
    ),
    # -- DeepSeek ----------------------------------------------------------
    ("deepseek", "deepseek-chat"): PricingEntry(
        input_cost_per_million=Decimal("0.14"),
        output_cost_per_million=Decimal("0.28"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://api-docs.deepseek.com/quick_start/pricing",
        fetched_at=_FETCHED,
    ),
    ("deepseek", "deepseek-reasoner"): PricingEntry(
        input_cost_per_million=Decimal("0.55"),
        output_cost_per_million=Decimal("2.19"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://api-docs.deepseek.com/quick_start/pricing",
        fetched_at=_FETCHED,
    ),
    # -- Groq --------------------------------------------------------------
    ("groq", "llama-3.3-70b-versatile"): PricingEntry(
        input_cost_per_million=Decimal("0.59"),
        output_cost_per_million=Decimal("0.79"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://groq.com/pricing/",
        fetched_at=_FETCHED,
    ),
    ("groq", "mixtral-8x7b-32768"): PricingEntry(
        input_cost_per_million=Decimal("0.24"),
        output_cost_per_million=Decimal("0.24"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://groq.com/pricing/",
        fetched_at=_FETCHED,
    ),
    # -- xAI ---------------------------------------------------------------
    ("xai", "grok-2"): PricingEntry(
        input_cost_per_million=Decimal("2.00"),
        output_cost_per_million=Decimal("10.00"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://docs.x.ai/docs/models",
        fetched_at=_FETCHED,
    ),
    ("xai", "grok-3-mini"): PricingEntry(
        input_cost_per_million=Decimal("0.30"),
        output_cost_per_million=Decimal("0.50"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://docs.x.ai/docs/models",
        fetched_at=_FETCHED,
    ),
    # -- Cerebras ----------------------------------------------------------
    ("cerebras", "llama3.1-70b"): PricingEntry(
        input_cost_per_million=Decimal("0.00"),
        output_cost_per_million=Decimal("0.00"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://cerebras.ai/pricing",
        fetched_at=_FETCHED,
    ),
    # -- Cohere ------------------------------------------------------------
    ("cohere", "command-r-plus"): PricingEntry(
        input_cost_per_million=Decimal("2.50"),
        output_cost_per_million=Decimal("10.00"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://cohere.com/pricing",
        fetched_at=_FETCHED,
    ),
    ("cohere", "command-r"): PricingEntry(
        input_cost_per_million=Decimal("0.15"),
        output_cost_per_million=Decimal("0.60"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://cohere.com/pricing",
        fetched_at=_FETCHED,
    ),
    # -- Perplexity --------------------------------------------------------
    ("perplexity", "sonar-pro"): PricingEntry(
        input_cost_per_million=Decimal("3.00"),
        output_cost_per_million=Decimal("15.00"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://docs.perplexity.ai/guides/pricing",
        fetched_at=_FETCHED,
    ),
    ("perplexity", "sonar"): PricingEntry(
        input_cost_per_million=Decimal("1.00"),
        output_cost_per_million=Decimal("1.00"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="https://docs.perplexity.ai/guides/pricing",
        fetched_at=_FETCHED,
    ),
}

# Wildcard patterns: provider prefix -> PricingEntry (matched when no exact
# (provider, model) key exists).  The ``*`` in the key means "any model under
# this provider".
_WILDCARD_PRICING: dict[str, PricingEntry] = {
    "ollama": PricingEntry(
        input_cost_per_million=Decimal("0"),
        output_cost_per_million=Decimal("0"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="",
        fetched_at=_FETCHED,
    ),
    "local": PricingEntry(
        input_cost_per_million=Decimal("0"),
        output_cost_per_million=Decimal("0"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="",
        fetched_at=_FETCHED,
    ),
    "airllm": PricingEntry(
        input_cost_per_million=Decimal("0"),
        output_cost_per_million=Decimal("0"),
        source=CostSource.OFFICIAL_DOCS,
        source_url="",
        fetched_at=_FETCHED,
    ),
}


class PricingCatalog:
    """Thread-safe pricing catalog with lookup fallback chain.

    Resolution order:
    1. User overrides (exact provider+model match)
    2. Builtin table (exact provider+model match)
    3. Builtin table (model-only match, any provider)
    4. Wildcard patterns (provider prefix match)
    5. Unknown ($0, status=unknown)
    """

    def __init__(self) -> None:
        self._overrides: dict[tuple[str, str], PricingEntry] = {}

    def set_override(
        self,
        provider: str,
        model: str,
        entry: PricingEntry,
    ) -> None:
        """Register a user override for a specific provider+model pair."""
        self._overrides[(provider.lower(), model.lower())] = entry

    def remove_override(self, provider: str, model: str) -> None:
        """Remove a user override if present."""
        self._overrides.pop((provider.lower(), model.lower()), None)

    def lookup(self, provider: str, model: str) -> PricingEntry | None:
        """Look up pricing entry following the full fallback chain.

        Returns ``None`` if no match is found (caller should treat as unknown).
        """
        p = provider.lower()
        m = model.lower()

        # 1. User overrides (exact)
        entry = self._overrides.get((p, m))
        if entry is not None:
            return entry

        # 2. Builtin exact (provider, model)
        entry = _BUILTIN_PRICING.get((p, m))
        if entry is not None:
            return entry

        # 3. Model-only match (any provider in builtin table)
        for (_, builtin_model), builtin_entry in _BUILTIN_PRICING.items():
            if builtin_model == m:
                return builtin_entry

        # 4. Wildcard provider match
        wildcard = _WILDCARD_PRICING.get(p)
        if wildcard is not None:
            return wildcard

        return None

    def list_effective_entries(self) -> list[tuple[str, str, PricingEntry]]:
        """Return the effective catalog entries after applying overrides."""
        merged = dict(_BUILTIN_PRICING)
        merged.update(self._overrides)
        return [(provider, model, entry) for (provider, model), entry in sorted(merged.items())]

    @property
    def builtin_models(self) -> list[tuple[str, str]]:
        """Return list of (provider, model) keys in the builtin table."""
        return list(_BUILTIN_PRICING.keys())


# Module-level singleton for convenient import.
_default_catalog = PricingCatalog()


def get_default_catalog() -> PricingCatalog:
    """Return the module-level default pricing catalog."""
    return _default_catalog


def apply_pricing_overrides_json(
    raw: str,
    *,
    catalog: PricingCatalog | None = None,
) -> int:
    """Apply startup pricing overrides from a JSON array."""
    if not raw.strip():
        return 0

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("pricing_catalog_overrides must be valid JSON") from exc

    if not isinstance(data, list):
        raise ValueError("pricing_catalog_overrides must be a JSON array")

    target_catalog = catalog or _default_catalog
    applied = 0
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"pricing_catalog_overrides[{index}] must be an object")

        provider = str(item.get("provider", "")).strip().lower()
        model = str(item.get("model", "")).strip().lower()
        if not provider or not model:
            raise ValueError(
                f"pricing_catalog_overrides[{index}] must include non-empty provider and model"
            )
        if "input_cost_per_million" not in item or "output_cost_per_million" not in item:
            raise ValueError(
                "pricing_catalog_overrides"
                f"[{index}] must include 'input_cost_per_million' and "
                "'output_cost_per_million'"
            )

        fetched_at_raw = str(item.get("fetched_at", "")).strip()
        fetched_at = (
            datetime.fromisoformat(fetched_at_raw.replace("Z", "+00:00"))
            if fetched_at_raw
            else None
        )
        target_catalog.set_override(
            provider,
            model,
            PricingEntry(
                input_cost_per_million=Decimal(str(item["input_cost_per_million"])),
                output_cost_per_million=Decimal(str(item["output_cost_per_million"])),
                cache_read_cost_per_million=Decimal(
                    str(item.get("cache_read_cost_per_million", "0"))
                ),
                cache_write_cost_per_million=Decimal(
                    str(item.get("cache_write_cost_per_million", "0"))
                ),
                source=CostSource.USER_OVERRIDE,
                source_url=str(item.get("source_url", "")).strip(),
                fetched_at=fetched_at,
            ),
        )
        applied += 1
    return applied


def estimate_cost(
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    *,
    catalog: PricingCatalog | None = None,
) -> CostResult:
    """Estimate invocation cost using the pricing catalog.

    Parameters
    ----------
    model:
        The model identifier (e.g. ``"gpt-4.1"``).
    provider:
        The provider name (e.g. ``"openai"``, ``"ollama"``).
    input_tokens:
        Number of input/prompt tokens.
    output_tokens:
        Number of output/completion tokens.
    catalog:
        Optional custom catalog; defaults to the module singleton.

    Returns
    -------
    CostResult
        Contains the estimated cost in USD and metadata about the lookup.
    """
    cat = catalog or _default_catalog
    entry = cat.lookup(provider, model)

    if entry is None:
        return CostResult(
            amount_usd=Decimal("0"),
            status=CostStatus.UNKNOWN,
            model=model,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    input_cost = entry.input_cost_per_million * Decimal(input_tokens) / Decimal("1000000")
    output_cost = entry.output_cost_per_million * Decimal(output_tokens) / Decimal("1000000")
    total = input_cost + output_cost

    return CostResult(
        amount_usd=total.quantize(Decimal("0.000001")),
        status=CostStatus.ESTIMATED,
        model=model,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
