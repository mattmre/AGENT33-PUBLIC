/**
 * ToolCatalogPage: main browsing page with search, category filters,
 * and tool detail panel.
 */

import { useCallback, useEffect, useState } from "react";

import { fetchCatalogTools, fetchCategories } from "./api";
import { CategoryFilter } from "./CategoryFilter";
import { ToolDetailPanel } from "./ToolDetailPanel";
import type { CatalogEntry, CatalogPage, CategoryCount } from "./types";

interface ToolCatalogPageProps {
  token: string | null;
  apiKey: string | null;
}

export function ToolCatalogPage({ token, apiKey }: ToolCatalogPageProps): JSX.Element {
  const [catalog, setCatalog] = useState<CatalogPage | null>(null);
  const [categories, setCategories] = useState<CategoryCount[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedTool, setSelectedTool] = useState<CatalogEntry | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const pageSize = 20;

  const loadTools = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchCatalogTools(token, apiKey, {
        category: selectedCategory ?? undefined,
        search: searchQuery || undefined,
        limit: pageSize,
        offset: page * pageSize,
      });
      setCatalog(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tools");
    } finally {
      setLoading(false);
    }
  }, [apiKey, token, selectedCategory, searchQuery, page]);

  const loadCategories = useCallback(async () => {
    try {
      const cats = await fetchCategories(token, apiKey);
      setCategories(cats);
    } catch {
      // Categories are non-critical; silently degrade
    }
  }, [apiKey, token]);

  useEffect(() => {
    void loadTools();
  }, [loadTools]);

  useEffect(() => {
    void loadCategories();
  }, [loadCategories]);

  const handleCategorySelect = (cat: string | null) => {
    setSelectedCategory(cat);
    setPage(0);
  };

  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchQuery(e.target.value);
    setPage(0);
  };

  const totalPages = catalog ? Math.ceil(catalog.total / pageSize) : 0;

  return (
    <div className="tool-catalog-page">
      <header className="tool-catalog-header">
        <h1>Tool Catalog</h1>
        <p>Browse and inspect all available tools, skills, and plugin contributions.</p>
      </header>

      <div className="tool-catalog-layout">
        <aside className="tool-catalog-sidebar">
          <CategoryFilter
            categories={categories}
            selected={selectedCategory}
            onSelect={handleCategorySelect}
          />
        </aside>

        <main className="tool-catalog-main">
          <div className="tool-catalog-search">
            <input
              type="search"
              placeholder="Search tools by name, description, or tag..."
              value={searchQuery}
              onChange={handleSearch}
              aria-label="Search tools"
            />
          </div>

          {loading && <p className="tool-catalog-loading">Loading tools...</p>}
          {error && <p className="tool-catalog-error">{error}</p>}

          {!loading && !error && catalog && (
            <>
              <p className="tool-catalog-count">
                {catalog.total} tool{catalog.total !== 1 ? "s" : ""} found
              </p>

              <div className="tool-catalog-grid" role="list">
                {catalog.tools.map((tool) => (
                  <article
                    key={tool.name}
                    className={`tool-card ${!tool.enabled ? "disabled" : ""}`}
                    role="listitem"
                    onClick={() => setSelectedTool(tool)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setSelectedTool(tool);
                      }
                    }}
                    tabIndex={0}
                  >
                    <h3 className="tool-card-name">{tool.name}</h3>
                    <p className="tool-card-desc">
                      {tool.description || "No description"}
                    </p>
                    <div className="tool-card-meta">
                      <span className="tool-card-provider">{tool.provider}</span>
                      <span className="tool-card-category">{tool.category}</span>
                      {tool.has_schema && (
                        <span className="tool-card-schema-badge">Schema</span>
                      )}
                      {!tool.enabled && (
                        <span className="tool-card-disabled-badge">Disabled</span>
                      )}
                    </div>
                  </article>
                ))}
              </div>

              {totalPages > 1 && (
                <nav className="tool-catalog-pagination" aria-label="Pagination">
                  <button
                    disabled={page === 0}
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                  >
                    Previous
                  </button>
                  <span>
                    Page {page + 1} of {totalPages}
                  </span>
                  <button
                    disabled={page >= totalPages - 1}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Next
                  </button>
                </nav>
              )}
            </>
          )}
        </main>

        {selectedTool && (
          <ToolDetailPanel
            tool={selectedTool}
            onClose={() => setSelectedTool(null)}
          />
        )}
      </div>
    </div>
  );
}
