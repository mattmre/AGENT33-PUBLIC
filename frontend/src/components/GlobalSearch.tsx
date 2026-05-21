import { useState } from "react";
import { getRuntimeConfig } from "../lib/api";

export function GlobalSearch({ token }: { token: string | null }) {
    const [query, setQuery] = useState("");
    const [results, setResults] = useState<any[]>([]);
    const [isOpen, setIsOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const canSearch = Boolean(token);
    const { API_BASE_URL } = getRuntimeConfig();

    const searchMemory = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!query.trim()) return;
        if (!token) {
            setResults([]);
            setIsOpen(true);
            return;
        }

        setLoading(true);
        setIsOpen(true);
        try {
            const res = await fetch(`${API_BASE_URL}/v1/memory/search`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`
                },
                body: JSON.stringify({ query, level: "full", top_k: 3 })
            });
            const data = await res.json();
            setResults(data.results || []);
        } catch (e) {
            console.error("Failed to search globally:", e);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="global-search" role="search">
            <form onSubmit={searchMemory} className="global-search-form">
                <input
                    type="search"
                    aria-label="Search semantic memory"
                    placeholder={canSearch ? "Search semantic memory, workflows, and notes..." : "Sign in to use memory search"}
                    value={query}
                    onChange={e => setQuery(e.target.value)}
                    disabled={!canSearch}
                    className="global-search-input"
                />
            </form>

            {isOpen && (
                <div
                    role="region"
                    aria-label="Search results"
                    aria-live="polite"
                    className="global-search-results"
                >
                    <div className="global-search-results-head">
                        <strong>{loading ? "Searching..." : "Memory Results"}</strong>
                        <button
                            type="button"
                            onClick={() => setIsOpen(false)}
                            aria-label="Close search results"
                            className="global-search-close"
                        >
                            Close
                        </button>
                    </div>
                    {!canSearch ? <div className="global-search-empty">Add a token in Integrations to enable search.</div> : null}
                    {results.length === 0 && !loading ? <div className="global-search-empty">No results found.</div> : null}
                    {results.map((r, i) => (
                        <div key={i} className="global-search-result">
                            <div className="global-search-result-copy">{r.content.substring(0, 150)}...</div>
                            <div className="global-search-result-meta">Tokens: {r.token_estimate} | Match: {r.level}</div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
