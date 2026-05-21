import { useCallback, useEffect, useState } from "react";
import { getRuntimeConfig } from "../../lib/api";
import { ScanRunCard } from "./ScanRunCard";
import { FindingsTable } from "./FindingsTable";

export interface SecurityRun {
  id: string;
  status: string;
  profile: string;
  target: { repository_path: string; commit_ref: string; branch: string };
  findings_count: number;
  findings_summary: {
    critical: number;
    high: number;
    medium: number;
    low: number;
    info: number;
  };
  created_at: string;
  completed_at: string | null;
  error_message: string;
  metadata: { tools_executed: string[]; tool_warnings: string[] };
}

export interface SecurityFinding {
  id: string;
  run_id: string;
  severity: string;
  category: string;
  title: string;
  description: string;
  tool: string;
  file_path: string;
  line_number: number | null;
  remediation: string;
  cwe_id: string;
}

export function SecurityDashboard({ token }: { token: string | null }) {
  const [runs, setRuns] = useState<SecurityRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [findings, setFindings] = useState<SecurityFinding[]>([]);
  const [loading, setLoading] = useState(false);
  const [scanLoading, setScanLoading] = useState(false);
  const [error, setError] = useState("");
  const { API_BASE_URL } = getRuntimeConfig();

  const fetchRuns = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/v1/component-security/runs?limit=20`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setRuns(data);
      }
    } catch (e) {
      console.error("Failed to fetch security runs:", e);
    } finally {
      setLoading(false);
    }
  }, [token, API_BASE_URL]);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  const fetchFindings = async (runId: string) => {
    if (!token) return;
    setSelectedRunId(runId);
    try {
      const res = await fetch(
        `${API_BASE_URL}/v1/component-security/runs/${runId}/findings`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (res.ok) {
        const data = await res.json();
        setFindings(data.findings || []);
      }
    } catch (e) {
      console.error("Failed to fetch findings:", e);
    }
  };

  const triggerQuickScan = async () => {
    if (!token) return;
    setScanLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE_URL}/v1/component-security/runs`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          target: { repository_path: ".", branch: "main" },
          profile: "quick",
          execute_now: true,
        }),
      });
      if (res.ok) {
        await fetchRuns();
      } else {
        const data = await res.json();
        setError(data.detail || "Scan failed");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scan failed");
    } finally {
      setScanLoading(false);
    }
  };

  const downloadSarif = async (runId: string) => {
    if (!token) return;
    try {
      const res = await fetch(
        `${API_BASE_URL}/v1/component-security/runs/${runId}/sarif`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (res.ok) {
        const data = await res.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `security-scan-${runId}.sarif.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }
    } catch (e) {
      console.error("Failed to download SARIF:", e);
    }
  };

  const summaryTotals = runs.reduce(
    (acc, run) => {
      if (run.status === "completed" && run.findings_summary) {
        acc.critical += run.findings_summary.critical;
        acc.high += run.findings_summary.high;
        acc.medium += run.findings_summary.medium;
        acc.low += run.findings_summary.low;
        acc.info += run.findings_summary.info;
      }
      return acc;
    },
    { critical: 0, high: 0, medium: 0, low: 0, info: 0 }
  );

  return (
    <div className="security-dashboard">
      <div className="security-header">
        <h3>Security Scanning Dashboard</h3>
        <button onClick={triggerQuickScan} disabled={scanLoading}>
          {scanLoading ? "Scanning..." : "Quick Scan"}
        </button>
      </div>

      {error && <div className="error-box" role="alert">{error}</div>}

      <div className="severity-summary">
        <span className="severity-badge severity-critical">
          Critical: {summaryTotals.critical}
        </span>
        <span className="severity-badge severity-high">
          High: {summaryTotals.high}
        </span>
        <span className="severity-badge severity-medium">
          Medium: {summaryTotals.medium}
        </span>
        <span className="severity-badge severity-low">
          Low: {summaryTotals.low}
        </span>
        <span className="severity-badge severity-info">
          Info: {summaryTotals.info}
        </span>
      </div>

      {loading && <p>Loading scan history...</p>}

      <div className="scan-runs-list">
        {runs.map((run) => (
          <ScanRunCard
            key={run.id}
            run={run}
            isSelected={run.id === selectedRunId}
            onSelect={() => fetchFindings(run.id)}
            onDownloadSarif={() => downloadSarif(run.id)}
          />
        ))}
        {!loading && runs.length === 0 && (
          <p>No scan runs yet. Click &quot;Quick Scan&quot; to start.</p>
        )}
      </div>

      {selectedRunId && findings.length > 0 && (
        <FindingsTable findings={findings} />
      )}

      {selectedRunId && findings.length === 0 && (
        <p className="no-findings">No findings for this run.</p>
      )}
    </div>
  );
}
