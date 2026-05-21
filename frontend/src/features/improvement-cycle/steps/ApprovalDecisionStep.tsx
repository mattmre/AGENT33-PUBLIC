import { useState } from "react";
import type { ApiResult } from "../../../types";
import { apiRequest } from "../../../lib/api";

type ApprovalDecisionType = "approved" | "changes_requested" | "escalated" | "deferred";

interface ApprovalDecisionStepProps {
  reviewId: string | null;
  reviewState: string;
  token: string;
  apiKey: string;
  onResult: (label: string, result: ApiResult) => void;
  onDecisionComplete: (decision: ApprovalDecisionType, newState: string) => void;
}

const DECISION_OPTIONS: { value: ApprovalDecisionType; label: string }[] = [
  { value: "approved", label: "Approved" },
  { value: "changes_requested", label: "Changes Requested" },
  { value: "escalated", label: "Escalated" },
  { value: "deferred", label: "Deferred" }
];

export function ApprovalDecisionStep({
  reviewId,
  reviewState,
  token,
  apiKey,
  onResult,
  onDecisionComplete
}: ApprovalDecisionStepProps): JSX.Element {
  const [decision, setDecision] = useState<ApprovalDecisionType>("approved");
  const [rationale, setRationale] = useState("");
  const [modificationSummary, setModificationSummary] = useState("");
  const [conditions, setConditions] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const isEnabled = reviewId !== null && reviewState === "approved";
  const rationaleRequired = decision !== "approved";

  async function handleSubmit(): Promise<void> {
    if (!reviewId) return;
    if (rationaleRequired && rationale.trim() === "") {
      setError("Rationale is required for non-approved decisions.");
      return;
    }

    setIsBusy(true);
    setError("");
    setSuccess("");
    try {
      const result = await apiRequest({
        method: "POST",
        path: "/v1/reviews/{review_id}/approve-with-rationale",
        pathParams: { review_id: reviewId },
        token,
        apiKey,
        body: JSON.stringify({
          decision,
          rationale,
          modification_summary: modificationSummary,
          conditions: conditions
            .split(",")
            .map((c) => c.trim())
            .filter(Boolean)
        })
      });
      onResult("Improvement Cycle - Approval Decision", result);

      if (!result.ok) {
        const detail =
          typeof result.data === "object" && result.data !== null
            ? (result.data as Record<string, unknown>).detail
            : undefined;
        throw new Error(
          typeof detail === "string" ? detail : `Request failed (${result.status})`
        );
      }

      const body = result.data as Record<string, unknown>;
      const newState = typeof body.state === "string" ? body.state : reviewState;
      setSuccess(`Decision recorded: ${decision}`);
      onDecisionComplete(decision, newState);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit decision.");
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <section className="wizard-step-content">
      <h3>Approval Decision</h3>
      <p>
        Record a structured approval decision with rationale. The review must be in APPROVED
        state.
      </p>

      {!isEnabled && (
        <p className="wizard-warning" role="alert">
          {reviewId === null
            ? "Create and complete a review before recording an approval decision."
            : `Review is in "${reviewState}" state. It must be "approved" to record a decision.`}
        </p>
      )}

      {error && <p className="wizard-error">{error}</p>}
      {success && <p className="wizard-notice">{success}</p>}

      <div className="wizard-form-grid">
        <label>
          Decision
          <select
            aria-label="Approval decision"
            value={decision}
            disabled={!isEnabled}
            onChange={(e) => setDecision(e.target.value as ApprovalDecisionType)}
          >
            {DECISION_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <p className="wizard-help-text">
        The approval identity is derived from the authenticated user.
      </p>

      <label className="wizard-textarea">
        Rationale {rationaleRequired && <span className="wizard-required">*</span>}
        <textarea
          aria-label="Rationale"
          rows={4}
          value={rationale}
          disabled={!isEnabled}
          onChange={(e) => setRationale(e.target.value)}
          placeholder={
            rationaleRequired
              ? "Explain why this decision was made (required)."
              : "Optional rationale for approval."
          }
        />
      </label>

      {decision === "changes_requested" && (
        <label className="wizard-textarea">
          Modification summary
          <textarea
            aria-label="Modification summary"
            rows={3}
            value={modificationSummary}
            disabled={!isEnabled}
            onChange={(e) => setModificationSummary(e.target.value)}
            placeholder="Describe the changes requested."
          />
        </label>
      )}

      <label>
        Conditions (comma-separated)
        <input
          aria-label="Conditions"
          value={conditions}
          disabled={!isEnabled}
          onChange={(e) => setConditions(e.target.value)}
          placeholder="Optional conditions for approval"
        />
      </label>

      <div className="wizard-actions">
        <button disabled={isBusy || !isEnabled} onClick={() => void handleSubmit()}>
          {isBusy ? "Submitting..." : "Submit Decision"}
        </button>
      </div>
    </section>
  );
}
