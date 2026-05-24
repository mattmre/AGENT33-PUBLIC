import { useState } from "react";

import { apiRequest } from "../../lib/api";

type SandboxRisk = "low" | "medium" | "high";

interface SandboxReviewSummary {
  surface: string;
  requires_review: boolean;
  risk: SandboxRisk;
  blockers: string[];
  safe_mounts_required: boolean;
  recommendation: string;
}

interface SandboxingPanelProps {
  token: string | null;
}

export function SandboxingPanel({ token }: SandboxingPanelProps): JSX.Element {
  const [reviews, setReviews] = useState<SandboxReviewSummary[]>([]);
  const [surface, setSurface] = useState("");
  const [risk, setRisk] = useState<SandboxRisk>("medium");
  const [recommendation, setRecommendation] = useState("");
  const [blockers, setBlockers] = useState("");
  const [safeMountsRequired, setSafeMountsRequired] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submitReview() {
    if (!token || !surface.trim() || !recommendation.trim()) return;
    setIsLoading(true);
    setError(null);
    try {
      const blockerList = blockers
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      const result = await apiRequest({
        method: "POST",
        path: "/v1/sandboxing/review",
        token,
        body: JSON.stringify({
          surface: surface.trim(),
          risk,
          recommendation: recommendation.trim(),
          blockers: blockerList,
          safe_mounts_required: safeMountsRequired
        }),
      });
      if (result.ok) {
        setReviews((prev) => [result.data as SandboxReviewSummary, ...prev]);
        setSurface("");
        setRisk("medium");
        setRecommendation("");
        setBlockers("");
        setSafeMountsRequired(true);
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
          value={surface}
          onChange={(e) => setSurface(e.target.value)}
          placeholder="Surface (e.g., code-interpreter)"
          style={{
            padding: "0.4rem 0.6rem",
            borderRadius: "6px",
            border: "1px solid rgba(48, 213, 200, 0.4)",
            background: "rgba(22, 45, 58, 0.8)",
            color: "#d8f7f3",
            fontSize: "0.85rem",
          }}
        />
        <select
          aria-label="Risk"
          value={risk}
          onChange={(e) => setRisk(e.target.value as SandboxRisk)}
          style={{
            padding: "0.4rem 0.6rem",
            borderRadius: "6px",
            border: "1px solid rgba(48, 213, 200, 0.4)",
            background: "rgba(22, 45, 58, 0.8)",
            color: "#d8f7f3",
            fontSize: "0.85rem",
          }}
        >
          <option value="low">Low risk</option>
          <option value="medium">Medium risk</option>
          <option value="high">High risk</option>
        </select>
        <input
          value={recommendation}
          onChange={(e) => setRecommendation(e.target.value)}
          placeholder="Recommendation"
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
          value={blockers}
          onChange={(e) => setBlockers(e.target.value)}
          placeholder="Blockers, comma separated"
          style={{
            padding: "0.4rem 0.6rem",
            borderRadius: "6px",
            border: "1px solid rgba(48, 213, 200, 0.4)",
            background: "rgba(22, 45, 58, 0.8)",
            color: "#d8f7f3",
            fontSize: "0.85rem",
          }}
        />
        <label style={{ color: "#9dc3cf", fontSize: "0.8rem" }}>
          <input
            checked={safeMountsRequired}
            onChange={(e) => setSafeMountsRequired(e.target.checked)}
            type="checkbox"
            style={{ marginRight: "0.4rem" }}
          />
          Safe mounts required
        </label>
        <button
          onClick={() => void submitReview()}
          disabled={isLoading || !surface.trim() || !recommendation.trim()}
          style={{
            background: "rgba(48, 213, 200, 0.1)",
            border: "1px solid rgba(48, 213, 200, 0.4)",
            color: "#30d5c8",
            borderRadius: "6px",
            padding: "0.4rem 0.8rem",
            cursor:
              isLoading || !surface.trim() || !recommendation.trim()
                ? "not-allowed"
                : "pointer",
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

      {reviews.map((r, index) => (
        <div
          key={`${r.surface}-${index}`}
          style={{
            background: "rgba(22, 45, 58, 0.8)",
            border: `1px solid ${r.requires_review ? "rgba(248, 113, 113, 0.4)" : "rgba(52, 211, 153, 0.4)"}`,
            borderRadius: "8px",
            padding: "0.8rem",
            marginBottom: "0.6rem",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <strong
              style={{
                color: r.requires_review ? "#f87171" : "#34d399",
                fontSize: "0.9rem",
              }}
            >
              {r.requires_review ? "REVIEW REQUIRED" : "ALLOW"}
            </strong>
            <span style={{ fontSize: "0.75rem", color: "#9dc3cf" }}>
              Risk: {r.risk}
            </span>
          </div>
          <p style={{ fontSize: "0.78rem", color: "#9dc3cf", margin: "0.3rem 0 0" }}>
            Surface: {r.surface}
          </p>
          <p style={{ fontSize: "0.78rem", color: "#9dc3cf", margin: "0.2rem 0 0" }}>
            {r.recommendation}
          </p>
          {r.blockers.length > 0 && (
            <p style={{ fontSize: "0.78rem", color: "#f6d37b", margin: "0.2rem 0 0" }}>
              Blockers: {r.blockers.join(", ")}
            </p>
          )}
        </div>
      ))}
    </section>
  );
}
