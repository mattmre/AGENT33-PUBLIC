import { useCallback, useEffect, useState } from "react";
import { getRuntimeConfig } from "../../lib/api";

import { CitationList } from "./CitationList";
import type { WebResearchResult } from "./CitationTypes";
import { ProviderStatus } from "./ProviderStatus";
import type { ProviderStatusEntry } from "./ProviderStatus";
import { SearchHistory } from "./SearchHistory";
import type { SearchHistoryEntry } from "./SearchHistory";

interface SearchResult {
    content: string;
    level: string;
    citations: string[];
    token_estimate: number;
}

type ActiveTab = "memory" | "web" | "providers";

export function ResearchDashboard({ token }: { token: string | null }) {
    const [activeTab, setActiveTab] = useState<ActiveTab>("memory");
    const [query, setQuery] = useState("");
    const [results, setResults] = useState<SearchResult[]>([]);
    const [webResults, setWebResults] = useState<WebResearchResult[]>([]);
    const [loading, setLoading] = useState(false);
    const [webError, setWebError] = useState("");
    const [searchHistory, setSearchHistory] = useState<SearchHistoryEntry[]>([]);
    const [headerProviders, setHeaderProviders] = useState<
        ProviderStatusEntry[]
    >([]);
    const { API_BASE_URL } = getRuntimeConfig();

    // Fetch provider status for header indicators on mount
    const fetchHeaderProviders = useCallback(async () => {
        if (!token) return;
        try {
            const res = await fetch(
                `${API_BASE_URL}/v1/research/providers/status`,
                {
                    headers: { Authorization: `Bearer ${token}` },
                },
            );
            if (res.ok) {
                const data: ProviderStatusEntry[] = await res.json();
                setHeaderProviders(data);
            }
        } catch {
            // Silently ignore header indicator fetch failures
        }
    }, [token, API_BASE_URL]);

    useEffect(() => {
        void fetchHeaderProviders();
    }, [fetchHeaderProviders]);

    const searchMemory = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!token || !query.trim()) return;

        setLoading(true);
        try {
            const res = await fetch(`${API_BASE_URL}/v1/memory/search`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify({ query, level: "full", top_k: 5 }),
            });
            const data = await res.json();
            setResults(data.results || []);
        } catch (err) {
            console.error("Failed to search memory:", err);
        } finally {
            setLoading(false);
        }
    };

    const doWebSearch = useCallback(
        async (searchQuery: string) => {
            if (!token || !searchQuery.trim()) return;

            setLoading(true);
            setWebError("");
            try {
                const res = await fetch(
                    `${API_BASE_URL}/v1/research/search`,
                    {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                            Authorization: `Bearer ${token}`,
                        },
                        body: JSON.stringify({
                            query: searchQuery,
                            limit: 10,
                        }),
                    },
                );
                if (!res.ok) {
                    const errData = await res.json();
                    setWebError(errData.detail || "Web search failed");
                    setWebResults([]);
                } else {
                    const data = await res.json();
                    const resultList: WebResearchResult[] =
                        data.results || [];
                    setWebResults(resultList);

                    // Record in search history
                    const entry: SearchHistoryEntry = {
                        query: searchQuery,
                        timestamp: new Date().toISOString(),
                        resultCount: resultList.length,
                        provider: data.provider_id || "unknown",
                    };
                    setSearchHistory((prev) => [entry, ...prev].slice(0, 20));
                }
            } catch (err) {
                setWebError(
                    err instanceof Error
                        ? err.message
                        : "Web search failed",
                );
            } finally {
                setLoading(false);
            }
        },
        [token, API_BASE_URL],
    );

    const searchWeb = async (e: React.FormEvent) => {
        e.preventDefault();
        await doWebSearch(query);
    };

    const handleRerunSearch = (rerunQuery: string) => {
        setQuery(rerunQuery);
        setActiveTab("web");
        void doWebSearch(rerunQuery);
    };

    return (
        <div className="research-dashboard">
            {/* Header with provider health indicators */}
            <div
                style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                }}
            >
                <div>
                    <h3 style={{ margin: "0 0 4px" }}>
                        Research & RAG Knowledge Base
                    </h3>
                    <p style={{ margin: "0 0 12px", color: "#666" }}>
                        Search semantic memory vectors or run grounded web
                        research queries.
                    </p>
                </div>
                {headerProviders.length > 0 && (
                    <div
                        data-testid="provider-health-indicators"
                        style={{
                            display: "flex",
                            gap: "8px",
                            alignItems: "center",
                        }}
                    >
                        {headerProviders.map((p) => (
                            <span
                                key={p.name}
                                data-testid="header-provider-dot"
                                title={`${p.name}: ${p.status}`}
                                style={{
                                    display: "inline-flex",
                                    alignItems: "center",
                                    gap: "4px",
                                    fontSize: "0.75em",
                                    color: "#666",
                                }}
                            >
                                <span
                                    aria-hidden="true"
                                    style={{
                                        display: "inline-block",
                                        width: "8px",
                                        height: "8px",
                                        borderRadius: "50%",
                                        backgroundColor: p.enabled
                                            ? "#4caf50"
                                            : "#9e9e9e",
                                    }}
                                />
                                {p.name}
                            </span>
                        ))}
                    </div>
                )}
            </div>

            {/* Tab switcher */}
            <div
                className="research-tabs"
                role="tablist"
                style={{
                    display: "flex",
                    gap: "8px",
                    marginBottom: "12px",
                }}
            >
                <button
                    role="tab"
                    aria-selected={activeTab === "memory"}
                    onClick={() => setActiveTab("memory")}
                    style={{
                        padding: "6px 14px",
                        fontWeight: activeTab === "memory" ? 700 : 400,
                        borderBottom:
                            activeTab === "memory"
                                ? "2px solid #1a73e8"
                                : "2px solid transparent",
                        background: "none",
                        border: "none",
                        cursor: "pointer",
                    }}
                >
                    Memory Search
                </button>
                <button
                    role="tab"
                    aria-selected={activeTab === "web"}
                    onClick={() => setActiveTab("web")}
                    style={{
                        padding: "6px 14px",
                        fontWeight: activeTab === "web" ? 700 : 400,
                        borderBottom:
                            activeTab === "web"
                                ? "2px solid #1a73e8"
                                : "2px solid transparent",
                        background: "none",
                        border: "none",
                        cursor: "pointer",
                    }}
                >
                    Web Research
                </button>
                <button
                    role="tab"
                    aria-selected={activeTab === "providers"}
                    onClick={() => setActiveTab("providers")}
                    style={{
                        padding: "6px 14px",
                        fontWeight: activeTab === "providers" ? 700 : 400,
                        borderBottom:
                            activeTab === "providers"
                                ? "2px solid #1a73e8"
                                : "2px solid transparent",
                        background: "none",
                        border: "none",
                        cursor: "pointer",
                    }}
                >
                    Providers
                </button>
            </div>

            {/* Memory search tab */}
            {activeTab === "memory" && (
                <>
                    <form onSubmit={searchMemory} className="search-form">
                        <input
                            type="text"
                            placeholder="E.g. What did we learn about upstream agent OS?"
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            style={{
                                padding: "8px",
                                width: "400px",
                                marginRight: "10px",
                            }}
                        />
                        <button type="submit" disabled={loading}>
                            {loading ? "Searching..." : "Semantic Search"}
                        </button>
                    </form>

                    <div
                        className="results-list"
                        style={{ marginTop: "20px" }}
                    >
                        {results.length === 0 && !loading && (
                            <p>No results yet.</p>
                        )}
                        {results.map((r, i) => (
                            <div
                                key={i}
                                className="card"
                                style={{
                                    marginBottom: "15px",
                                    padding: "15px",
                                    border: "1px solid #ddd",
                                    borderRadius: "5px",
                                }}
                            >
                                <span
                                    className="badge"
                                    style={{
                                        background: "#4caf50",
                                        color: "white",
                                        padding: "3px 8px",
                                        borderRadius: "12px",
                                        float: "right",
                                    }}
                                >
                                    {r.level}
                                </span>
                                <p>{r.content}</p>
                                {r.citations && r.citations.length > 0 && (
                                    <div
                                        className="citations"
                                        style={{
                                            fontSize: "0.8em",
                                            color: "#666",
                                        }}
                                    >
                                        <strong>Citations:</strong>{" "}
                                        {r.citations.join(", ")}
                                    </div>
                                )}
                                <div
                                    style={{
                                        fontSize: "0.7em",
                                        color: "#999",
                                        marginTop: "5px",
                                    }}
                                >
                                    Tokens: {r.token_estimate}
                                </div>
                            </div>
                        ))}
                    </div>
                </>
            )}

            {/* Web research tab */}
            {activeTab === "web" && (
                <>
                    <form onSubmit={searchWeb} className="search-form">
                        <input
                            type="text"
                            placeholder="E.g. FastAPI dependency injection patterns"
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            style={{
                                padding: "8px",
                                width: "400px",
                                marginRight: "10px",
                            }}
                        />
                        <button type="submit" disabled={loading}>
                            {loading ? "Searching..." : "Web Search"}
                        </button>
                    </form>

                    {webError && (
                        <div
                            className="error-box"
                            style={{
                                color: "#c62828",
                                marginTop: "10px",
                            }}
                        >
                            {webError}
                        </div>
                    )}

                    <div style={{ marginTop: "20px" }}>
                        <CitationList citations={webResults} />
                    </div>

                    {/* Search history panel */}
                    <SearchHistory
                        entries={searchHistory}
                        onRerun={handleRerunSearch}
                    />
                </>
            )}

            {/* Providers tab */}
            {activeTab === "providers" && <ProviderStatus token={token} />}
        </div>
    );
}
