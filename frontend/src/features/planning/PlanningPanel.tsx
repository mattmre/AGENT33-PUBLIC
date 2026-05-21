import { useEffect, useState } from "react";

import { apiRequest } from "../../lib/api";

interface PlanStep {
  step_id: string;
  description: string;
  status: string;
}

interface Plan {
  plan_id: string;
  goal: string;
  status: string;
  steps: PlanStep[];
  created_at: string;
  updated_at: string;
}

interface PlanningPanelProps {
  token: string | null;
}

export function PlanningPanel({ token }: PlanningPanelProps): JSX.Element {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replanningId, setReplanningId] = useState<string | null>(null);

  async function loadPlans() {
    if (!token) return;
    setIsLoading(true);
    setError(null);
    try {
      const result = await apiRequest({ method: "GET", path: "/v1/planning/plans", token });
      if (result.ok) {
        const data = result.data as { plans?: Plan[] } | Plan[];
        setPlans(Array.isArray(data) ? data : ((data as { plans?: Plan[] }).plans ?? []));
      } else {
        setError("Failed to load plans.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error loading plans.");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadPlans();
  }, [token]);

  async function triggerReplan(planId: string) {
    if (!token) return;
    setReplanningId(planId);
    try {
      const result = await apiRequest({
        method: "POST",
        path: "/v1/planning/replan",
        token,
        body: JSON.stringify({ plan_id: planId }),
      });
      if (result.ok) void loadPlans();
      else setError("Replan request failed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Replan error.");
    } finally {
      setReplanningId(null);
    }
  }

  if (!token) {
    return (
      <section className="planning-panel" aria-label="Planning">
        <p style={{ padding: "1rem", color: "#f6d37b" }}>Sign in to view planning data.</p>
      </section>
    );
  }

  return (
    <section className="planning-panel" aria-label="Planning" style={{ padding: "1rem" }}>
      <div className="planning-panel-head" style={{ marginBottom: "1rem" }}>
        <p className="eyebrow">Planning</p>
        <h2 style={{ color: "#30d5c8", margin: "0 0 0.4rem" }}>Agent planning surface</h2>
        <p style={{ color: "#9dc3cf", fontSize: "0.85rem", margin: 0 }}>
          Compose multi-step plans, break down goals into agent-executable tasks, and trigger
          replanning when conditions change.
        </p>
      </div>

      {isLoading && <p style={{ color: "#9dc3cf" }}>Loading plans…</p>}
      {error && <p style={{ color: "#f87171" }}>{error}</p>}
      {!isLoading && plans.length === 0 && !error && (
        <p style={{ color: "#9dc3cf" }}>
          No plans found. Plans are created by the orchestrator when goals are submitted.
        </p>
      )}

      {plans.map((plan) => (
        <div
          key={plan.plan_id}
          style={{
            background: "rgba(22, 45, 58, 0.8)",
            border: "1px solid rgba(48, 213, 200, 0.3)",
            borderRadius: "8px",
            padding: "0.8rem",
            marginBottom: "0.6rem",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <strong style={{ color: "#d8f7f3", fontSize: "0.9rem" }}>{plan.goal}</strong>
            <span
              style={{
                fontSize: "0.75rem",
                color: plan.status === "active" ? "#34d399" : "#9dc3cf",
              }}
            >
              {plan.status}
            </span>
          </div>
          <p style={{ fontSize: "0.75rem", color: "#9dc3cf", margin: "0.3rem 0" }}>
            {plan.steps.length} step{plan.steps.length !== 1 ? "s" : ""} · Updated{" "}
            {new Date(plan.updated_at).toLocaleString()}
          </p>
          <button
            onClick={() => void triggerReplan(plan.plan_id)}
            disabled={replanningId === plan.plan_id}
            style={{
              fontSize: "0.75rem",
              background: "rgba(48, 213, 200, 0.1)",
              border: "1px solid rgba(48, 213, 200, 0.4)",
              color: "#30d5c8",
              borderRadius: "6px",
              padding: "0.25rem 0.6rem",
              cursor: replanningId === plan.plan_id ? "wait" : "pointer",
            }}
          >
            {replanningId === plan.plan_id ? "Replanning…" : "Trigger Replan"}
          </button>
        </div>
      ))}
    </section>
  );
}
