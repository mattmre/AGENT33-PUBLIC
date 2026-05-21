import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../lib/api";

type ResourceKind =
  | "pack"
  | "plugin"
  | "skill"
  | "workflow"
  | "prompt"
  | "policy"
  | "eval"
  | "dataset"
  | "environment";

interface ResourceManifest {
  id: string;
  name: string;
  version: string;
  kind: ResourceKind;
  description?: string;
  tags?: string[];
  permissions?: Array<{ scope: string; reason?: string; required?: boolean }>;
  trust?: { publisher?: string; verified?: boolean };
  rollback?: { supported?: boolean };
}

interface ResourceSearchResponse {
  items: ResourceManifest[];
  total: number;
}

interface ResourceCatalogPanelProps {
  token: string | null;
  apiKey: string | null;
}

const RESOURCE_KINDS: Array<ResourceKind | "all"> = [
  "all",
  "pack",
  "plugin",
  "skill",
  "workflow",
  "prompt",
  "policy",
  "eval",
  "dataset",
  "environment"
];

function isResourceSearchResponse(value: unknown): value is ResourceSearchResponse {
  const record = value as Partial<ResourceSearchResponse>;
  return Array.isArray(record?.items) && typeof record?.total === "number";
}

export function ResourceCatalogPanel({ token, apiKey }: ResourceCatalogPanelProps): JSX.Element {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<ResourceKind | "all">("all");
  const [resources, setResources] = useState<ResourceManifest[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const authReady = Boolean(token || apiKey);
  const filteredKinds = useMemo(
    () => RESOURCE_KINDS.map((item) => ({ id: item, label: item === "all" ? "All" : item })),
    []
  );

  async function loadResources(): Promise<void> {
    if (!authReady) {
      setResources([]);
      setTotal(0);
      return;
    }
    setLoading(true);
    setError("");
    const result = await apiRequest({
      method: "GET",
      path: "/v1/resources/search",
      token: token ?? undefined,
      apiKey: apiKey ?? undefined,
      query: {
        query,
        kind: kind === "all" ? "" : kind,
        limit: "50"
      }
    });
    setLoading(false);
    if (!result.ok || !isResourceSearchResponse(result.data)) {
      setError(`Resource API returned ${result.status}`);
      setResources([]);
      setTotal(0);
      return;
    }
    setResources(result.data.items);
    setTotal(result.data.total);
  }

  useEffect(() => {
    void loadResources();
  }, [token, apiKey]);

  return (
    <section className="resource-catalog-panel" aria-label="Unified resource catalog">
      <header className="resource-catalog-header">
        <div>
          <p className="eyebrow">Resource Catalog</p>
          <h3>Reusable capabilities across packs, plugins, skills, workflows, and policies</h3>
          <p>Search the unified manifest layer and inspect trust, permissions, rollback, and tags.</p>
        </div>
        <button type="button" onClick={() => void loadResources()} disabled={loading || !authReady}>
          {loading ? "Loading..." : "Refresh"}
        </button>
      </header>

      <div className="resource-catalog-controls">
        <label>
          <span>Search</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="ops, review, policy" />
        </label>
        <label>
          <span>Type</span>
          <select value={kind} onChange={(event) => setKind(event.target.value as ResourceKind | "all")}>
            {filteredKinds.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={() => void loadResources()} disabled={loading || !authReady}>
          Apply
        </button>
      </div>

      {!authReady ? <p className="resource-catalog-error">Connect with a session token or API key to load resources.</p> : null}
      {error ? <p className="resource-catalog-error" role="alert">{error}</p> : null}

      <div className="resource-catalog-count">{total} resources matched</div>
      <div className="resource-catalog-grid">
        {resources.map((resource) => (
          <article key={resource.id} className="resource-catalog-card">
            <div>
              <span>{resource.kind}</span>
              <strong>{resource.name}</strong>
            </div>
            <p>{resource.description || "No description provided."}</p>
            <dl>
              <div>
                <dt>Version</dt>
                <dd>{resource.version}</dd>
              </div>
              <div>
                <dt>Trust</dt>
                <dd>{resource.trust?.verified ? "Verified" : "Unverified"}</dd>
              </div>
              <div>
                <dt>Rollback</dt>
                <dd>{resource.rollback?.supported === false ? "No" : "Yes"}</dd>
              </div>
            </dl>
            <div className="resource-catalog-tags">
              {(resource.tags ?? []).map((tag) => (
                <span key={tag}>{tag}</span>
              ))}
              {(resource.permissions ?? []).map((permission) => (
                <span key={permission.scope}>{permission.scope}</span>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
