import { useState } from "react";

import { apiRequest } from "../../lib/api";

interface DiagnosticFinding {
  id: string;
  category: string;
  severity: string;
  message: string;
}

interface DiagnosticReport {
  generated_at: string;
  findings: DiagnosticFinding[];
  overall: string;
}

interface BundleManifest {
  bundle_id: string;
  sections: string[];
  created_at: string;
}

interface SupportPanelProps {
  token: string | null;
}

export function SupportPanel({ token }: SupportPanelProps): JSX.Element {
  const [diagnostic, setDiagnostic] = useState<DiagnosticReport | null>(null);
  const [bundle, setBundle] = useState<BundleManifest | null>(null);
  const [isRunningDiag, setIsRunningDiag] = useState(false);
  const [isCreatingBundle, setIsCreatingBundle] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runDiagnostics() {
    if (!token) return;
    setIsRunningDiag(true);
    setError(null);
    try {
      const result = await apiRequest({
        method: "POST",
        path: "/v1/support/diagnostics",
        token,
        body: JSON.stringify({}),
      });
      if (result.ok) setDiagnostic(result.data as DiagnosticReport);
      else setError("Diagnostics request failed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error running diagnostics.");
    } finally {
      setIsRunningDiag(false);
    }
  }

  async function createBundle() {
    if (!token) return;
    setIsCreatingBundle(true);
    setError(null);
    try {
      const result = await apiRequest({
        method: "POST",
        path: "/v1/support/bundles",
        token,
        body: JSON.stringify({}),
      });
      if (result.ok) setBundle(result.data as BundleManifest);
      else setError("Bundle creation failed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error creating bundle.");
    } finally {
      setIsCreatingBundle(false);
    }
  }

  if (!token) {
    return (
      <section className="support-panel" aria-label="Support">
        <p style={{ padding: "1rem", color: "#f6d37b" }}>Sign in to access support tools.</p>
      </section>
    );
  }

  return (
    <section className="support-panel" aria-label="Support" style={{ padding: "1rem" }}>
      <div className="support-panel-head" style={{ marginBottom: "1rem" }}>
        <p className="eyebrow">Support</p>
        <h2 style={{ color: "#30d5c8", margin: "0 0 0.4rem" }}>Operator support center</h2>
        <p style={{ color: "#9dc3cf", fontSize: "0.85rem", margin: 0 }}>
          Run diagnostics to surface configuration and health issues, or create a support bundle for
          escalation.
        </p>
      </div>

      {error && <p style={{ color: "#f87171" }}>{error}</p>}

      <div style={{ display: "flex", gap: "0.8rem", marginBottom: "1.2rem" }}>
        <button
          onClick={() => void runDiagnostics()}
          disabled={isRunningDiag}
          style={{
            background: "rgba(48, 213, 200, 0.1)",
            border: "1px solid rgba(48, 213, 200, 0.4)",
            color: "#30d5c8",
            borderRadius: "6px",
            padding: "0.4rem 0.8rem",
            cursor: isRunningDiag ? "wait" : "pointer",
          }}
        >
          {isRunningDiag ? "Running…" : "Run Diagnostics"}
        </button>
        <button
          onClick={() => void createBundle()}
          disabled={isCreatingBundle}
          style={{
            background: "rgba(48, 213, 200, 0.1)",
            border: "1px solid rgba(48, 213, 200, 0.4)",
            color: "#30d5c8",
            borderRadius: "6px",
            padding: "0.4rem 0.8rem",
            cursor: isCreatingBundle ? "wait" : "pointer",
          }}
        >
          {isCreatingBundle ? "Creating…" : "Create Support Bundle"}
        </button>
      </div>

      {diagnostic && (
        <div
          style={{
            background: "rgba(22, 45, 58, 0.8)",
            border: "1px solid rgba(48, 213, 200, 0.3)",
            borderRadius: "8px",
            padding: "0.8rem",
            marginBottom: "0.8rem",
          }}
        >
          <strong style={{ color: "#d8f7f3" }}>
            Diagnostic Report — {diagnostic.overall.toUpperCase()}
          </strong>
          <p style={{ fontSize: "0.75rem", color: "#9dc3cf", margin: "0.3rem 0" }}>
            Generated {new Date(diagnostic.generated_at).toLocaleString()} ·{" "}
            {diagnostic.findings.length} finding{diagnostic.findings.length !== 1 ? "s" : ""}
          </p>
          {diagnostic.findings.map((f) => (
            <div
              key={f.id}
              style={{
                fontSize: "0.78rem",
                color:
                  f.severity === "critical"
                    ? "#f87171"
                    : f.severity === "warning"
                      ? "#f6d37b"
                      : "#9dc3cf",
                marginTop: "0.3rem",
              }}
            >
              [{f.severity.toUpperCase()}] {f.category}: {f.message}
            </div>
          ))}
        </div>
      )}

      {bundle && (
        <div
          style={{
            background: "rgba(22, 45, 58, 0.8)",
            border: "1px solid rgba(48, 213, 200, 0.3)",
            borderRadius: "8px",
            padding: "0.8rem",
          }}
        >
          <strong style={{ color: "#d8f7f3" }}>Support Bundle Created</strong>
          <p style={{ fontSize: "0.75rem", color: "#9dc3cf", margin: "0.3rem 0" }}>
            ID: {bundle.bundle_id} · Sections: {bundle.sections.join(", ")} · Created{" "}
            {new Date(bundle.created_at).toLocaleString()}
          </p>
        </div>
      )}
    </section>
  );
}
