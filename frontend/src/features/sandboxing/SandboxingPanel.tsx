import { useState } from "react";

import { apiRequest } from "../../lib/api";

interface ReviewDecision {
  review_id: string;
  agent_id: string;
  action: string;
  risk_score: number;
  decision: string;
  reason: string;
  created_at: string;
}

interface SandboxingPanelProps {
  token: string | null;
}

export function SandboxingPanel({ token }: SandboxingPanelProps): JSX.Element {
  const [reviews, setReviews] = useState<ReviewDecision[]>([]);
  const [agentId, setAgentId] = useState("");
  const [action, setAction] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submitReview() {
    if (!token || !agentId.trim() || !action.trim()) return;
    setIsLoading(true);
    setError(null);
    try {
      const result = await apiRequest({
        method: "POST",
        path: "/v1/sandboxing/review",
        token,
        body: JSON.stringify({ agent_id: agentId, proposed_action: action }),
      });
      if (result.ok) {
        setReviews((prev) => [result.data as ReviewDecision, ...prev]);
        setAgentId("");
        setAction("");
      } else {
        setError("Review request failed.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error submitting review.");
    } finally {
      setIsLoading(false);
    }
  }

  if (!token) {
    return (
      <section className="sandboxing-panel" aria-label="Sandboxing">
        <p style={{ padding: "1rem", color: "#f6d37b" }}>Sign in to access sandboxing controls.</p>
      </section>
    );
  }

  return (
    <section className="sandboxing-panel" aria-label="Sandboxing" style={{ padding: "1rem" }}>
      <div className="sandboxing-panel-head" style={{ marginBottom: "1rem" }}>
        <p className="eyebrow">Sandboxing</p>
        <h2 style={{ color: "#30d5c8", margin: "0 0 0.4rem" }}>Execution sandbox</h2>
        <p style={{ color: "#9dc3cf", fontSize: "0.85rem", margin: 0 }}>
          Submit a proposed agent action for sandbox review before it runs in a live workflow. The
          sandbox engine evaluates risk and returns an approval decision.
        </p>
      </div>

      {error && <p style={{ color: "#f87171" }}>{error}</p>}

      <div style={{ display: "grid", gap: "0.5rem", marginBottom: "1rem", maxWidth: "420px" }}>
        <input
          value={agentId}
          onChange={(e) => setAgentId(e.target.value)}
          placeholder="Agent ID"
          style={{
            padding: "0.4rem 0.6rem",
            borderRadius: "6px",
            border: "1px solid rgba(48, 213, 200, 0.4)",
            background: "rgba(22, 45, 58, 0.8)",
            color: "#d8f7f3",
            fontSize: "0.85rem",
          }}
        />
        <input
          value={action}
          onChange={(e) => setAction(e.target.value)}
          placeholder="Proposed action (e.g., write_file /tmp/output.txt)"
          style={{
            padding: "0.4rem 0.6rem",
            borderRadius: "6px",
            border: "1px solid rgba(48, 213, 200, 0.4)",
            background: "rgba(22, 45, 58, 0.8)",
            color: "#d8f7f3",
            fontSize: "0.85rem",
          }}
        />
        <button
          onClick={() => void submitReview()}
          disabled={isLoading || !agentId.trim() || !action.trim()}
          style={{
            background: "rgba(48, 213, 200, 0.1)",
            border: "1px solid rgba(48, 213, 200, 0.4)",
            color: "#30d5c8",
            borderRadius: "6px",
            padding: "0.4rem 0.8rem",
            cursor: isLoading || !agentId.trim() || !action.trim() ? "not-allowed" : "pointer",
          }}
        >
          {isLoading ? "Reviewing…" : "Submit for Review"}
        </button>
      </div>

      {reviews.length === 0 && (
        <p style={{ color: "#9dc3cf", fontSize: "0.85rem" }}>
          No reviews yet. Submit an agent action above to see sandbox review decisions.
        </p>
      )}

      {reviews.map((r) => (
        <div
          key={r.review_id}
          style={{
            background: "rgba(22, 45, 58, 0.8)",
            border: `1px solid ${r.decision === "approved" ? "rgba(52, 211, 153, 0.4)" : "rgba(248, 113, 113, 0.4)"}`,
            borderRadius: "8px",
            padding: "0.8rem",
            marginBottom: "0.6rem",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <strong
              style={{
                color: r.decision === "approved" ? "#34d399" : "#f87171",
                fontSize: "0.9rem",
              }}
            >
              {r.decision.toUpperCase()}
            </strong>
            <span style={{ fontSize: "0.75rem", color: "#9dc3cf" }}>
              Risk: {r.risk_score.toFixed(2)}
            </span>
          </div>
          <p style={{ fontSize: "0.78rem", color: "#9dc3cf", margin: "0.3rem 0 0" }}>
            Agent: {r.agent_id} · {r.action}
          </p>
          <p style={{ fontSize: "0.78rem", color: "#9dc3cf", margin: "0.2rem 0 0" }}>{r.reason}</p>
        </div>
      ))}
    </section>
  );
}
