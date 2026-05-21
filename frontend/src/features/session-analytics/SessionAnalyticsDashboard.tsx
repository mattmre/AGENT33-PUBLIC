import { useCallback, useEffect, useMemo, useState } from "react";

import type { ApiResult } from "../../types";
import { asInsightsReport, fetchInsights } from "./api";
import { buildSparklinePoints, formatCost, formatDuration, formatTokens } from "./helpers";
import type { InsightsReport } from "./types";

interface SessionAnalyticsDashboardProps {
  token: string;
  apiKey: string;
  onResult: (label: string, result: ApiResult) => void;
}

const PERIOD_OPTIONS = [7, 14, 30, 90] as const;

const cardStyle: React.CSSProperties = {
  background: "rgba(11, 30, 39, 0.65)",
  border: "1px solid rgba(48, 213, 200, 0.35)",
  borderRadius: "10px",
  padding: "1rem 1.25rem",
  textAlign: "center" as const,
};

const cardLabelStyle: React.CSSProperties = {
  fontSize: "0.78rem",
  color: "#8ab4c4",
  marginBottom: "0.35rem",
};

const cardValueStyle: React.CSSProperties = {
  fontSize: "1.5rem",
  fontWeight: 700,
  color: "#d9edf4",
};

const tableStyle: React.CSSProperties = {
  width: "100%",
  borderCollapse: "collapse" as const,
  fontSize: "0.88rem",
};

const thStyle: React.CSSProperties = {
  textAlign: "left" as const,
  padding: "0.5rem 0.75rem",
  borderBottom: "1px solid rgba(48, 213, 200, 0.25)",
  color: "#8ab4c4",
  fontWeight: 600,
};

const tdStyle: React.CSSProperties = {
  padding: "0.5rem 0.75rem",
  borderBottom: "1px solid rgba(48, 213, 200, 0.1)",
  color: "#d9edf4",
};

const btnBase: React.CSSProperties = {
  background: "rgba(11, 30, 39, 0.65)",
  border: "1px solid rgba(48, 213, 200, 0.35)",
  borderRadius: "6px",
  color: "#d9edf4",
  padding: "0.4rem 0.85rem",
  fontSize: "0.84rem",
  cursor: "pointer",
};

const btnActive: React.CSSProperties = {
  ...btnBase,
  background: "rgba(48, 213, 200, 0.25)",
  border: "1px solid rgba(48, 213, 200, 0.7)",
};

function ActivitySparkline({ points }: { points: string }): JSX.Element {
  if (points === "") {
    return <span style={{ color: "#8ab4c4" }}>Not enough data</span>;
  }
  return (
    <svg
      viewBox="0 0 200 60"
      preserveAspectRatio="none"
      role="img"
      aria-label="Daily activity sparkline chart"
      style={{ width: "100%", height: "60px" }}
    >
      <polyline
        points={points}
        fill="none"
        stroke="rgba(48, 213, 200, 0.8)"
        strokeWidth="2"
      />
    </svg>
  );
}

export function SessionAnalyticsDashboard({
  token,
  apiKey,
  onResult,
}: SessionAnalyticsDashboardProps): JSX.Element {
  const [periodDays, setPeriodDays] = useState<number>(30);
  const [report, setReport] = useState<InsightsReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadInsights = useCallback(async (): Promise<void> => {
    if (!token && !apiKey) {
      return;
    }
    setLoading(true);
    try {
      const result = await fetchInsights(token, apiKey, periodDays);
      onResult("Session Insights", result);
      const parsed = asInsightsReport(result.data);
      if (!result.ok || parsed === null) {
        setError(`Unable to load insights (${result.status})`);
        return;
      }
      setError("");
      setReport(parsed);
    } catch (loadError) {
      const message =
        loadError instanceof Error ? loadError.message : "Unknown insights error";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [apiKey, onResult, periodDays, token]);

  useEffect(() => {
    loadInsights();
  }, [loadInsights]);

  const sparklinePoints = useMemo(() => {
    if (!report || report.daily_activity.length < 2) {
      return "";
    }
    return buildSparklinePoints(report.daily_activity, 200, 56);
  }, [report]);

  const sortedModels = useMemo(() => {
    if (!report) {
      return [];
    }
    return Object.entries(report.model_usage).sort(
      ([, a], [, b]) => b.invocations - a.invocations
    );
  }, [report]);

  const sortedTools = useMemo(() => {
    if (!report) {
      return [];
    }
    return Object.entries(report.tool_usage).sort(([, a], [, b]) => b - a);
  }, [report]);

  return (
    <section style={{ maxWidth: "960px", margin: "0 auto" }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "0.75rem",
          marginBottom: "1.25rem",
        }}
      >
        <div>
          <h2 style={{ margin: 0, color: "#d9edf4" }}>Session Analytics</h2>
          <p style={{ margin: "0.25rem 0 0", color: "#8ab4c4", fontSize: "0.88rem" }}>
            Usage insights, model costs, and daily activity trends.
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
          {PERIOD_OPTIONS.map((days) => (
            <button
              key={days}
              style={periodDays === days ? btnActive : btnBase}
              onClick={() => setPeriodDays(days)}
              aria-pressed={periodDays === days}
            >
              {days}d
            </button>
          ))}
          <button
            style={{ ...btnBase, marginLeft: "0.5rem" }}
            onClick={() => loadInsights()}
            disabled={loading}
          >
            {loading ? "Loading..." : "Refresh"}
          </button>
        </div>
      </header>

      {error ? (
        <p role="alert" style={{ color: "#f87171", marginBottom: "1rem" }}>
          {error}
        </p>
      ) : null}

      {loading && !report ? (
        <p style={{ color: "#8ab4c4" }}>Loading insights...</p>
      ) : null}

      {report ? (
        <>
          {/* Summary Cards */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
              gap: "0.75rem",
              marginBottom: "1.5rem",
            }}
          >
            <div style={cardStyle}>
              <div style={cardLabelStyle}>Total Sessions</div>
              <div style={cardValueStyle} data-testid="card-sessions">
                {report.total_sessions}
              </div>
            </div>
            <div style={cardStyle}>
              <div style={cardLabelStyle}>Total Tokens</div>
              <div style={cardValueStyle} data-testid="card-tokens">
                {formatTokens(report.total_tokens)}
              </div>
            </div>
            <div style={cardStyle}>
              <div style={cardLabelStyle}>Total Cost</div>
              <div style={cardValueStyle} data-testid="card-cost">
                {formatCost(report.total_cost_usd)}
              </div>
            </div>
            <div style={cardStyle}>
              <div style={cardLabelStyle}>Avg Duration</div>
              <div style={cardValueStyle} data-testid="card-duration">
                {formatDuration(report.avg_session_duration_seconds)}
              </div>
            </div>
          </div>

          {/* Daily Activity Sparkline */}
          <section
            style={{
              ...cardStyle,
              textAlign: "left" as const,
              marginBottom: "1.5rem",
            }}
          >
            <h3 style={{ margin: "0 0 0.5rem", color: "#d9edf4", fontSize: "0.95rem" }}>
              Daily Activity (Tokens)
            </h3>
            <ActivitySparkline points={sparklinePoints} />
          </section>

          {/* Model Usage Table */}
          {sortedModels.length > 0 ? (
            <section
              style={{
                ...cardStyle,
                textAlign: "left" as const,
                marginBottom: "1.5rem",
                padding: "1rem",
              }}
            >
              <h3 style={{ margin: "0 0 0.75rem", color: "#d9edf4", fontSize: "0.95rem" }}>
                Model Usage
              </h3>
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <th style={thStyle}>Model</th>
                    <th style={thStyle}>Invocations</th>
                    <th style={thStyle}>Input Tokens</th>
                    <th style={thStyle}>Output Tokens</th>
                    <th style={thStyle}>Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedModels.map(([name, usage]) => (
                    <tr key={name}>
                      <td style={tdStyle}>{name}</td>
                      <td style={tdStyle}>{usage.invocations}</td>
                      <td style={tdStyle}>{formatTokens(usage.input_tokens)}</td>
                      <td style={tdStyle}>{formatTokens(usage.output_tokens)}</td>
                      <td style={tdStyle}>{formatCost(usage.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ) : null}

          {/* Tool Usage Table */}
          {sortedTools.length > 0 ? (
            <section
              style={{
                ...cardStyle,
                textAlign: "left" as const,
                marginBottom: "1.5rem",
                padding: "1rem",
              }}
            >
              <h3 style={{ margin: "0 0 0.75rem", color: "#d9edf4", fontSize: "0.95rem" }}>
                Tool Usage
              </h3>
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <th style={thStyle}>Tool</th>
                    <th style={thStyle}>Calls</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedTools.map(([name, count]) => (
                    <tr key={name}>
                      <td style={tdStyle}>{name}</td>
                      <td style={tdStyle}>{count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
