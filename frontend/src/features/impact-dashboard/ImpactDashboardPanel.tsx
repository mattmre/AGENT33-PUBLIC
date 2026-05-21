import { useCallback, useEffect, useState } from "react";

import type { ApiResult } from "../../types";
import {
  asDashboardResponse,
  asPackImpactResponse,
  asROIResponse,
  fetchDashboard,
  fetchPackImpact,
  fetchROI,
} from "./api";
import type {
  DashboardResponse,
  PackImpactResponse,
  ROIResponse,
} from "./types";

interface Props {
  token: string;
  apiKey: string;
  onResult: (label: string, result: ApiResult) => void;
}

const POLL_INTERVAL_MS = 30_000;

function metricLabel(mt: string): string {
  switch (mt) {
    case "success_rate": return "Success Rate";
    case "quality_score": return "Quality Score";
    case "latency_ms": return "Latency (ms)";
    case "cost_usd": return "Cost (USD)";
    default: return mt;
  }
}

function pctColor(pct: number): string {
  if (pct > 5) return "#4ade80";
  if (pct < -5) return "#f87171";
  return "#a3a3a3";
}

function deltaColor(delta: number): string {
  if (delta > 0.01) return "#4ade80";
  if (delta < -0.01) return "#f87171";
  return "#a3a3a3";
}

export function ImpactDashboardPanel({ token, apiKey, onResult }: Props): JSX.Element {
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [packImpact, setPackImpact] = useState<PackImpactResponse | null>(null);
  const [roiResult, setRoiResult] = useState<ROIResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // ROI form state
  const [roiDomain, setRoiDomain] = useState("qa");
  const [roiHours, setRoiHours] = useState(0.5);
  const [roiCost, setRoiCost] = useState(150);
  const [roiWindow, setRoiWindow] = useState(30);
  const [roiLoading, setRoiLoading] = useState(false);

  const loadData = useCallback(async (): Promise<void> => {
    if (!token && !apiKey) return;
    setLoading(true);
    try {
      const [dashRes, packRes] = await Promise.all([
        fetchDashboard(token, apiKey),
        fetchPackImpact(token, apiKey),
      ]);
      onResult("Impact Dashboard", dashRes);
      onResult("Pack Impact", packRes);

      const parsedDash = asDashboardResponse(dashRes.data);
      if (dashRes.ok && parsedDash) {
        setDashboard(parsedDash);
        setError("");
      } else {
        setError(`Dashboard load failed (${dashRes.status})`);
      }

      const parsedPack = asPackImpactResponse(packRes.data);
      if (packRes.ok && parsedPack) {
        setPackImpact(parsedPack);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [token, apiKey, onResult]);

  useEffect(() => {
    loadData();
    const interval = setInterval(() => { void loadData(); }, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [loadData]);

  async function calculateROI(): Promise<void> {
    if (!token && !apiKey) return;
    setRoiLoading(true);
    try {
      const res = await fetchROI(token, apiKey, roiDomain, roiHours, roiCost, roiWindow);
      onResult("ROI Estimate", res);
      const parsed = asROIResponse(res.data);
      if (res.ok && parsed) {
        setRoiResult(parsed);
      }
    } catch {
      // swallow
    } finally {
      setRoiLoading(false);
    }
  }

  const summary = dashboard?.summary;
  const successCount = summary?.metric_counts?.success_rate ?? 0;
  const latencyCount = summary?.metric_counts?.latency_ms ?? 0;

  // Week-over-week: find success_rate and latency_ms entries
  const wowSuccess = dashboard?.week_over_week.find((w) => w.metric_type === "success_rate");
  const wowLatency = dashboard?.week_over_week.find((w) => w.metric_type === "latency_ms");

  return (
    <section className="impact-dashboard-panel" style={{ padding: "1.5rem", maxWidth: "1200px", margin: "0 auto" }}>
      <header style={{ marginBottom: "1.5rem" }}>
        <h2 style={{ margin: 0, fontSize: "1.5rem", color: "#e2e8f0" }}>Impact Dashboard</h2>
        <p style={{ margin: "0.25rem 0 0", color: "#94a3b8", fontSize: "0.875rem" }}>
          Week-over-week trends, ROI estimation, and pack impact analysis.
        </p>
        <button
          onClick={() => { void loadData(); }}
          disabled={loading}
          style={{
            marginTop: "0.75rem",
            background: "rgba(48, 213, 200, 0.15)",
            border: "1px solid rgba(48, 213, 200, 0.4)",
            borderRadius: "6px",
            color: "#30d5c8",
            padding: "0.4rem 1rem",
            cursor: loading ? "not-allowed" : "pointer",
            fontSize: "0.8rem",
          }}
        >
          {loading ? "Loading..." : "Refresh"}
        </button>
      </header>

      {error ? <p role="alert" style={{ color: "#f87171", fontSize: "0.875rem" }}>{error}</p> : null}

      {/* KPI Cards */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
        gap: "1rem",
        marginBottom: "1.5rem",
      }}>
        <div style={kpiCardStyle}>
          <span style={kpiLabelStyle}>Total Invocations (30d)</span>
          <span style={kpiValueStyle}>{successCount}</span>
        </div>
        <div style={kpiCardStyle}>
          <span style={kpiLabelStyle}>Success Rate</span>
          <span style={kpiValueStyle}>
            {wowSuccess ? `${(wowSuccess.current_week_avg * 100).toFixed(1)}%` : "N/A"}
          </span>
        </div>
        <div style={kpiCardStyle}>
          <span style={kpiLabelStyle}>Avg Latency (ms)</span>
          <span style={kpiValueStyle}>
            {wowLatency ? wowLatency.current_week_avg.toFixed(1) : latencyCount > 0 ? "-" : "N/A"}
          </span>
        </div>
      </div>

      {/* Week-over-Week */}
      {dashboard && dashboard.week_over_week.length > 0 ? (
        <section style={sectionStyle}>
          <h3 style={sectionHeadStyle}>Week-over-Week Change</h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "0.75rem" }}>
            {dashboard.week_over_week.map((stat) => (
              <div key={stat.metric_type} style={{
                background: "rgba(15, 23, 42, 0.6)",
                borderRadius: "8px",
                padding: "0.75rem 1rem",
                border: "1px solid rgba(148, 163, 184, 0.15)",
              }}>
                <div style={{ fontSize: "0.75rem", color: "#94a3b8", marginBottom: "0.5rem" }}>
                  {metricLabel(stat.metric_type)}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                  <span style={{ fontSize: "1.1rem", fontWeight: 600, color: pctColor(stat.pct_change) }}>
                    {stat.pct_change >= 0 ? "+" : ""}{stat.pct_change.toFixed(1)}%
                  </span>
                  <div style={{
                    flex: 1,
                    height: "6px",
                    background: "rgba(148, 163, 184, 0.15)",
                    borderRadius: "3px",
                    overflow: "hidden",
                  }}>
                    <div style={{
                      width: `${Math.min(Math.abs(stat.pct_change), 100)}%`,
                      height: "100%",
                      background: pctColor(stat.pct_change),
                      borderRadius: "3px",
                    }} />
                  </div>
                </div>
                <div style={{ fontSize: "0.7rem", color: "#64748b", marginTop: "0.35rem" }}>
                  prev: {stat.previous_week_avg.toFixed(3)} / curr: {stat.current_week_avg.toFixed(3)}
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {/* Top Failure Modes */}
      {dashboard && dashboard.top_failure_modes.length > 0 ? (
        <section style={sectionStyle}>
          <h3 style={sectionHeadStyle}>Top Failure Modes</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {dashboard.top_failure_modes.map((fm) => {
              const maxCount = dashboard.top_failure_modes[0]?.count ?? 1;
              return (
                <div key={fm.failure_class} style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.75rem",
                  background: "rgba(15, 23, 42, 0.6)",
                  borderRadius: "6px",
                  padding: "0.5rem 0.75rem",
                  border: "1px solid rgba(148, 163, 184, 0.1)",
                }}>
                  <span style={{ flex: "0 0 180px", fontSize: "0.8rem", color: "#e2e8f0" }}>
                    {fm.failure_class}
                  </span>
                  <div style={{
                    flex: 1,
                    height: "6px",
                    background: "rgba(148, 163, 184, 0.15)",
                    borderRadius: "3px",
                    overflow: "hidden",
                  }}>
                    <div style={{
                      width: `${(fm.count / maxCount) * 100}%`,
                      height: "100%",
                      background: "#f87171",
                      borderRadius: "3px",
                    }} />
                  </div>
                  <span style={{ flex: "0 0 40px", textAlign: "right", fontSize: "0.8rem", color: "#94a3b8" }}>
                    {fm.count}
                  </span>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      {/* ROI Estimator */}
      <section style={sectionStyle}>
        <h3 style={sectionHeadStyle}>ROI Estimator</h3>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "flex-end" }}>
          <label style={inputLabelStyle}>
            Domain
            <input
              value={roiDomain}
              onChange={(e) => setRoiDomain(e.target.value)}
              style={inputStyle}
            />
          </label>
          <label style={inputLabelStyle}>
            Hours saved / success
            <input
              type="number"
              step="0.1"
              min="0"
              value={roiHours}
              onChange={(e) => setRoiHours(Number(e.target.value) || 0)}
              style={inputStyle}
            />
          </label>
          <label style={inputLabelStyle}>
            Cost per hour (USD)
            <input
              type="number"
              step="10"
              min="0"
              value={roiCost}
              onChange={(e) => setRoiCost(Number(e.target.value) || 0)}
              style={inputStyle}
            />
          </label>
          <label style={inputLabelStyle}>
            Window (days)
            <input
              type="number"
              min="1"
              value={roiWindow}
              onChange={(e) => setRoiWindow(Number(e.target.value) || 30)}
              style={inputStyle}
            />
          </label>
          <button
            onClick={() => { void calculateROI(); }}
            disabled={roiLoading}
            style={{
              background: "rgba(48, 213, 200, 0.15)",
              border: "1px solid rgba(48, 213, 200, 0.4)",
              borderRadius: "6px",
              color: "#30d5c8",
              padding: "0.4rem 1.2rem",
              cursor: roiLoading ? "not-allowed" : "pointer",
              fontSize: "0.8rem",
              height: "fit-content",
            }}
          >
            {roiLoading ? "Calculating..." : "Calculate"}
          </button>
        </div>
        {roiResult ? (
          <div style={{
            marginTop: "1rem",
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
            gap: "0.75rem",
          }}>
            <div style={roiCardStyle}><span style={roiLabelStyle}>Invocations</span><span style={roiValStyle}>{roiResult.total_invocations}</span></div>
            <div style={roiCardStyle}><span style={roiLabelStyle}>Successes</span><span style={roiValStyle}>{roiResult.success_count}</span></div>
            <div style={roiCardStyle}><span style={roiLabelStyle}>Failures</span><span style={roiValStyle}>{roiResult.failure_count}</span></div>
            <div style={roiCardStyle}><span style={roiLabelStyle}>Hours Saved</span><span style={roiValStyle}>{roiResult.estimated_hours_saved}</span></div>
            <div style={roiCardStyle}><span style={roiLabelStyle}>Value (USD)</span><span style={{ ...roiValStyle, color: "#4ade80" }}>${roiResult.estimated_value_usd.toLocaleString()}</span></div>
            <div style={roiCardStyle}><span style={roiLabelStyle}>Success Rate</span><span style={roiValStyle}>{(roiResult.success_rate * 100).toFixed(1)}%</span></div>
            <div style={roiCardStyle}><span style={roiLabelStyle}>Avg Latency</span><span style={roiValStyle}>{roiResult.avg_latency_ms.toFixed(1)} ms</span></div>
          </div>
        ) : null}
      </section>

      {/* Pack Impact Table */}
      <section style={sectionStyle}>
        <h3 style={sectionHeadStyle}>Pack Impact</h3>
        {packImpact && packImpact.packs.length > 0 ? (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid rgba(148, 163, 184, 0.2)" }}>
                <th style={thStyle}>Pack Name</th>
                <th style={thStyle}>Sessions</th>
                <th style={thStyle}>With Pack</th>
                <th style={thStyle}>Without Pack</th>
                <th style={thStyle}>Delta</th>
              </tr>
            </thead>
            <tbody>
              {packImpact.packs.map((p) => (
                <tr key={p.pack_name} style={{ borderBottom: "1px solid rgba(148, 163, 184, 0.08)" }}>
                  <td style={tdStyle}>{p.pack_name}</td>
                  <td style={{ ...tdStyle, textAlign: "center" }}>{p.sessions_applied}</td>
                  <td style={{ ...tdStyle, textAlign: "center" }}>{(p.success_rate_with_pack * 100).toFixed(1)}%</td>
                  <td style={{ ...tdStyle, textAlign: "center" }}>{(p.success_rate_without_pack * 100).toFixed(1)}%</td>
                  <td style={{ ...tdStyle, textAlign: "center", color: deltaColor(p.delta), fontWeight: 600 }}>
                    {p.delta >= 0 ? "+" : ""}{(p.delta * 100).toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p style={{ color: "#64748b", fontSize: "0.8rem" }}>No pack impact data available.</p>
        )}
      </section>
    </section>
  );
}

// Inline styles (following existing pattern of inline styles in the project)
const kpiCardStyle: React.CSSProperties = {
  background: "rgba(11, 30, 39, 0.65)",
  border: "1px solid rgba(48, 213, 200, 0.25)",
  borderRadius: "10px",
  padding: "1rem 1.2rem",
  display: "flex",
  flexDirection: "column",
  gap: "0.35rem",
};
const kpiLabelStyle: React.CSSProperties = { fontSize: "0.75rem", color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.05em" };
const kpiValueStyle: React.CSSProperties = { fontSize: "1.6rem", fontWeight: 700, color: "#e2e8f0" };

const sectionStyle: React.CSSProperties = {
  marginBottom: "1.5rem",
  background: "rgba(11, 30, 39, 0.4)",
  border: "1px solid rgba(148, 163, 184, 0.1)",
  borderRadius: "10px",
  padding: "1rem 1.2rem",
};
const sectionHeadStyle: React.CSSProperties = { fontSize: "1rem", color: "#e2e8f0", margin: "0 0 0.75rem" };

const inputLabelStyle: React.CSSProperties = { display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "0.75rem", color: "#94a3b8" };
const inputStyle: React.CSSProperties = {
  background: "rgba(15, 23, 42, 0.8)",
  border: "1px solid rgba(148, 163, 184, 0.2)",
  borderRadius: "6px",
  color: "#e2e8f0",
  padding: "0.35rem 0.5rem",
  fontSize: "0.8rem",
  width: "120px",
};

const roiCardStyle: React.CSSProperties = {
  background: "rgba(15, 23, 42, 0.6)",
  borderRadius: "8px",
  padding: "0.5rem 0.75rem",
  border: "1px solid rgba(148, 163, 184, 0.1)",
  display: "flex",
  flexDirection: "column",
  gap: "0.2rem",
};
const roiLabelStyle: React.CSSProperties = { fontSize: "0.65rem", color: "#64748b", textTransform: "uppercase" };
const roiValStyle: React.CSSProperties = { fontSize: "1.1rem", fontWeight: 600, color: "#e2e8f0" };

const thStyle: React.CSSProperties = { textAlign: "left", padding: "0.5rem", color: "#94a3b8", fontWeight: 500 };
const tdStyle: React.CSSProperties = { padding: "0.5rem", color: "#e2e8f0" };
