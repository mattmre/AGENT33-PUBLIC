"""Web search tool backed by the provider-aware research service.

Implements the ``SchemaAwareTool`` protocol for JSON Schema validation and
multi-provider search with trust labels.
"""

from __future__ import annotations

from typing import Any

from agent33.tools.base import ToolContext, ToolResult
from agent33.web_research.models import TrustLabel
from agent33.web_research.service import (
    SearchProviderRegistry,
    create_default_web_research_service,
)


class SearchTool:
    """Query multiple search providers and return formatted, trust-labeled results.

    When a ``SearchProviderRegistry`` is provided (via constructor injection
    from lifespan), queries are dispatched to registered providers. Otherwise,
    falls back to the legacy SearXNG-only service.

    Implements the ``SchemaAwareTool`` protocol.
    """

    def __init__(self, *, search_registry: SearchProviderRegistry | None = None) -> None:
        self._registry = search_registry

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web via multiple providers (DuckDuckGo, Tavily, Brave, "
            "SearXNG) and return trust-labeled, structured results with provider "
            "attribution."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (required).",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Maximum results to return (default 10).",
                    "default": 10,
                },
                "categories": {
                    "type": "string",
                    "description": "Category filter (default 'general').",
                    "default": "general",
                },
                "provider": {
                    "type": "string",
                    "description": (
                        "Specific provider ID (duckduckgo, tavily, brave, searxng). "
                        "If omitted, uses the default provider."
                    ),
                },
                "all_providers": {
                    "type": "boolean",
                    "description": (
                        "If true, query all available providers and aggregate results. "
                        "Overrides the 'provider' parameter."
                    ),
                    "default": False,
                },
            },
            "required": ["query"],
        }

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        """Run a web search.

        Parameters
        ----------
        params:
            query        : str  - Search query (required).
            num_results  : int  - Maximum results to return (default 10).
            categories   : str  - SearXNG category filter (default "general").
            provider     : str  - Specific provider ID (optional).
            all_providers: bool - Query all providers and aggregate (default False).
        """
        query: str = params.get("query", "").strip()
        if not query:
            return ToolResult.fail("No search query provided.")

        num_results: int = params.get("num_results", 10)
        categories: str = params.get("categories", "general")
        provider: str | None = params.get("provider")
        all_providers: bool = params.get("all_providers", False)

        try:
            if self._registry is not None:
                if all_providers:
                    results = await self._registry.search_all(
                        query, limit=num_results, categories=categories
                    )
                else:
                    results = await self._registry.search(
                        query,
                        provider_id=provider,
                        limit=num_results,
                        categories=categories,
                    )
            else:
                # Legacy fallback: use the default service
                service = create_default_web_research_service()
                response = await service.search(query, limit=num_results, categories=categories)
                results = response.results

        except ValueError as exc:
            return ToolResult.fail(str(exc))

        if not results:
            return ToolResult.ok("No results found.")

        lines: list[str] = []
        for item in results:
            trust_label_display = _format_trust_label(item.trust_label)
            lines.append(
                "\n".join(
                    [
                        f"{item.rank}. {item.title} [{trust_label_display}]",
                        f"   {item.url}",
                        f"   {item.snippet}",
                        f"   Provider: {item.provider_id}",
                        f"   Trust: {item.trust_label_reason or item.trust_reason}",
                    ]
                )
            )

        return ToolResult.ok("\n\n".join(lines))


def _format_trust_label(label: TrustLabel) -> str:
    """Format a trust label for display."""
    icons = {
        TrustLabel.VERIFIED: "VERIFIED",
        TrustLabel.COMMUNITY: "COMMUNITY",
        TrustLabel.UNKNOWN: "UNKNOWN",
        TrustLabel.SUSPICIOUS: "SUSPICIOUS",
    }
    return icons.get(label, label.value.upper())
