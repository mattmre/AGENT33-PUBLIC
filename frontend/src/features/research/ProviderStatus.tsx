/**
 * ProviderStatus: displays the health/status of each configured research
 * provider, fetched from GET /v1/research/providers/status.
 */

import { useCallback, useEffect, useState } from "react";

import { getRuntimeConfig } from "../../lib/api";

/** Shape returned by GET /v1/research/providers/status. */
export interface ProviderStatusEntry {
  name: string;
  enabled: boolean;
  status: string;
  last_check: string | null;
  total_calls: number;
  success_rate: number;
}

const STATUS_COLORS: Record<string, string> = {
  ok: "#4caf50",
  unconfigured: "#ff9800",
  error: "#f44336",
};

function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? "#607d8b";
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return "Never";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso ?? "Never";
  }
}

function formatRate(rate: number): string {
  return `${(rate * 100).toFixed(0)}%`;
}

export function ProviderStatus({
  token,
}: {
  token: string | null;
}): JSX.Element {
  const [providers, setProviders] = useState<ProviderStatusEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const fetchStatus = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError("");
    const { API_BASE_URL } = getRuntimeConfig();
    try {
      const res = await fetch(`${API_BASE_URL}/v1/research/providers/status`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({ detail: res.statusText }));
        setError(errData.detail || "Failed to fetch provider status");
        return;
      }
      const data: ProviderStatusEntry[] = await res.json();
      setProviders(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch provider status");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  return (
    <div className="provider-status" data-testid="provider-status">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "12px",
        }}
      >
        <h4 style={{ margin: 0 }}>Provider Health</h4>
        <button
          data-testid="refresh-status"
          onClick={() => void fetchStatus()}
          disabled={loading}
          style={{
            padding: "4px 10px",
            fontSize: "0.85em",
            cursor: "pointer",
          }}
        >
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {error && (
        <div
          data-testid="provider-status-error"
          style={{ color: "#c62828", marginBottom: "10px" }}
        >
          {error}
        </div>
      )}

      {providers.length === 0 && !loading && !error && (
        <p style={{ color: "#888", fontStyle: "italic" }}>
          No providers configured.
        </p>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        {providers.map((p) => (
          <div
            key={p.name}
            className="provider-status-card"
            data-testid="provider-status-card"
            style={{
              display: "flex",
              alignItems: "center",
              gap: "12px",
              padding: "10px 14px",
              border: "1px solid #ddd",
              borderRadius: "5px",
              backgroundColor: "#fff",
            }}
          >
            {/* Status indicator dot */}
            <span
              data-testid="status-indicator"
              aria-label={`Status: ${p.status}`}
              style={{
                display: "inline-block",
                width: "10px",
                height: "10px",
                borderRadius: "50%",
                backgroundColor: statusColor(p.status),
                flexShrink: 0,
              }}
            />

            {/* Provider name */}
            <span
              data-testid="provider-name"
              style={{ fontWeight: 600, minWidth: "140px" }}
            >
              {p.name}
            </span>

            {/* Enabled badge */}
            <span
              data-testid="enabled-badge"
              style={{
                padding: "2px 8px",
                borderRadius: "12px",
                fontSize: "0.75em",
                fontWeight: 600,
                color: "#fff",
                backgroundColor: p.enabled ? "#4caf50" : "#9e9e9e",
              }}
            >
              {p.enabled ? "Connected" : "Disconnected"}
            </span>

            {/* Metrics */}
            <span
              data-testid="call-count"
              style={{ fontSize: "0.85em", color: "#666" }}
            >
              {p.total_calls} calls
            </span>
            <span
              data-testid="success-rate"
              style={{ fontSize: "0.85em", color: "#666" }}
            >
              {formatRate(p.success_rate)} success
            </span>

            {/* Last check */}
            <span
              data-testid="last-check"
              style={{ fontSize: "0.8em", color: "#999", marginLeft: "auto" }}
            >
              Last check: {formatTimestamp(p.last_check)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
