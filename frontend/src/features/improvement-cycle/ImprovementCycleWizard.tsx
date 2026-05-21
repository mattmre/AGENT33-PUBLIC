import { useState } from "react";

import { apiRequest } from "../../lib/api";
import type { ApiResult } from "../../types";
import {
  buildWorkflowCreatePresetBody,
  improvementCycleWorkflowPresets
} from "./presets";

interface ImprovementCycleWizardProps {
  token: string;
  apiKey: string;
  onResult: (label: string, result: ApiResult) => void;
}

type ArtifactMode = "plan_review" | "diff_review";
type ReviewDecision = "approved" | "changes_requested" | "escalated";

interface ExplanationArtifact {
  id: string;
  entity_type: string;
  entity_id: string;
  content: string;
  mode: string;
  fact_check_status: string;
}

interface ReviewArtifactLink {
  kind: string;
  artifact_id: string;
  label: string;
  mode: string;
}

interface ReviewDetail {
  id: string;
  task_id: string;
  branch: string;
  state: string;
  artifacts: ReviewArtifactLink[];
  risk_assessment: {
    risk_level: string;
    triggers_identified: string[];
    l1_required: boolean;
    l2_required: boolean;
  };
  l1_review: {
    reviewer_id: string;
    reviewer_role: string;
    decision: string;
    comments: string;
    issues_found: string[];
  };
  l2_review: {
    reviewer_id: string;
    reviewer_role: string;
    decision: string;
    comments: string;
    issues_found: string[];
  };
  final_signoff: {
    approved_by: string;
    approval_type: string;
    conditions: string[];
  };
}

interface ToolApprovalRecord {
  approval_id: string;
  status: string;
  reason: string;
  tool_name: string;
  operation: string;
  command: string;
  requested_by: string;
  details: string;
  created_at: string;
  expires_at: string;
  review_note: string;
}

const RISK_TRIGGER_OPTIONS = [
  "documentation",
  "config",
  "code-isolated",
  "api-internal",
  "api-public",
  "security",
  "schema",
  "infrastructure",
  "prompt-agent",
  "secrets",
  "production-data",
  "prompt-injection",
  "sandbox-escape",
  "supply-chain"
] as const;

const DEFAULT_ENTITY_TYPE = "workflow";
const DEFAULT_ENTITY_ID = "improvement-cycle-session58";
const DEFAULT_TASK_ID = "session58-phase26-review";
const DEFAULT_BRANCH = "codex/session58-phase26-wizard";

function asObject(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function formatLabel(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function getResultError(result: ApiResult): string {
  const payload = asObject(result.data);
  if (payload) {
    const detail = payload.detail;
    if (typeof detail === "string" && detail !== "") {
      return detail;
    }
  }
  return `Request failed (${result.status})`;
}

function parseExplanationArtifact(data: unknown): ExplanationArtifact | null {
  const payload = asObject(data);
  if (!payload) {
    return null;
  }
  return {
    id: asString(payload.id),
    entity_type: asString(payload.entity_type),
    entity_id: asString(payload.entity_id),
    content: asString(payload.content),
    mode: asString(payload.mode),
    fact_check_status: asString(payload.fact_check_status)
  };
}

function parseReviewDetail(data: unknown): ReviewDetail | null {
  const payload = asObject(data);
  if (!payload) {
    return null;
  }

  const riskAssessment = asObject(payload.risk_assessment);
  const l1Review = asObject(payload.l1_review);
  const l2Review = asObject(payload.l2_review);
  const finalSignoff = asObject(payload.final_signoff);
  const artifacts = Array.isArray(payload.artifacts) ? payload.artifacts : [];

  return {
    id: asString(payload.id),
    task_id: asString(payload.task_id),
    branch: asString(payload.branch),
    state: asString(payload.state),
    artifacts: artifacts
      .map((artifact) => {
        const item = asObject(artifact);
        if (!item) {
          return null;
        }
        return {
          kind: asString(item.kind),
          artifact_id: asString(item.artifact_id),
          label: asString(item.label),
          mode: asString(item.mode)
        };
      })
      .filter((artifact): artifact is ReviewArtifactLink => artifact !== null),
    risk_assessment: {
      risk_level: asString(riskAssessment?.risk_level),
      triggers_identified: asStringArray(riskAssessment?.triggers_identified),
      l1_required: riskAssessment?.l1_required === true,
      l2_required: riskAssessment?.l2_required === true
    },
    l1_review: {
      reviewer_id: asString(l1Review?.reviewer_id),
      reviewer_role: asString(l1Review?.reviewer_role),
      decision: asString(l1Review?.decision),
      comments: asString(l1Review?.comments),
      issues_found: asStringArray(l1Review?.issues_found)
    },
    l2_review: {
      reviewer_id: asString(l2Review?.reviewer_id),
      reviewer_role: asString(l2Review?.reviewer_role),
      decision: asString(l2Review?.decision),
      comments: asString(l2Review?.comments),
      issues_found: asStringArray(l2Review?.issues_found)
    },
    final_signoff: {
      approved_by: asString(finalSignoff?.approved_by),
      approval_type: asString(finalSignoff?.approval_type),
      conditions: asStringArray(finalSignoff?.conditions)
    }
  };
}

function parseToolApprovals(data: unknown): ToolApprovalRecord[] {
  if (!Array.isArray(data)) {
    return [];
  }
  return data
    .map((entry) => {
      const item = asObject(entry);
      if (!item) {
        return null;
      }
      return {
        approval_id: asString(item.approval_id),
        status: asString(item.status),
        reason: asString(item.reason),
        tool_name: asString(item.tool_name),
        operation: asString(item.operation),
        command: asString(item.command),
        requested_by: asString(item.requested_by),
        details: asString(item.details),
        created_at: asString(item.created_at),
        expires_at: asString(item.expires_at),
        review_note: asString(item.review_note)
      };
    })
    .filter((item): item is ToolApprovalRecord => item !== null);
}

function buildReviewArtifactLink(artifact: ExplanationArtifact): ReviewArtifactLink {
  return {
    kind: "explanation",
    artifact_id: artifact.id,
    label: artifact.mode.replaceAll("_", "-"),
    mode: artifact.mode
  };
}

export function ImprovementCycleWizard({
  token,
  apiKey,
  onResult
}: ImprovementCycleWizardProps): JSX.Element {
  const [artifactMode, setArtifactMode] = useState<ArtifactMode>("plan_review");
  const [selectedPresetId, setSelectedPresetId] = useState(improvementCycleWorkflowPresets[0]?.id ?? "");
  const [entityType, setEntityType] = useState(DEFAULT_ENTITY_TYPE);
  const [entityId, setEntityId] = useState(DEFAULT_ENTITY_ID);
  const [artifactText, setArtifactText] = useState(`## Improvement Cycle Review

1. Confirm the workflow preset matches the intended scope.
2. Generate a review artifact before opening signoff.
3. Record the signoff path and any required approvals.`);
  const [taskId, setTaskId] = useState(DEFAULT_TASK_ID);
  const [branch, setBranch] = useState(DEFAULT_BRANCH);
  const [approvalNote, setApprovalNote] = useState("");
  const [selectedTriggers, setSelectedTriggers] = useState<string[]>([]);
  const [l1Decision, setL1Decision] = useState<ReviewDecision>("approved");
  const [l2Decision, setL2Decision] = useState<ReviewDecision>("approved");
  const [artifact, setArtifact] = useState<ExplanationArtifact | null>(null);
  const [review, setReview] = useState<ReviewDetail | null>(null);
  const [toolApprovals, setToolApprovals] = useState<ToolApprovalRecord[]>([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busyAction, setBusyAction] = useState("");

  async function runRequest(
    label: string,
    args: Parameters<typeof apiRequest>[0]
  ): Promise<ApiResult> {
    setBusyAction(label);
    setError("");
    try {
      const result = await apiRequest(args);
      onResult(label, result);
      if (!result.ok) {
        throw new Error(getResultError(result));
      }
      return result;
    } finally {
      setBusyAction("");
    }
  }

  async function loadReview(reviewId: string): Promise<void> {
    const result = await runRequest("Improvement Cycle - Review Detail", {
      method: "GET",
      path: "/v1/reviews/{review_id}",
      pathParams: { review_id: reviewId },
      token,
      apiKey
    });
    const detail = parseReviewDetail(result.data);
    if (detail === null) {
      throw new Error("Review detail response was not valid JSON.");
    }
    setReview(detail);
  }

  async function handleApplyPreset(): Promise<void> {
    try {
      const result = await runRequest("Improvement Cycle - Create Preset", {
        method: "POST",
        path: "/v1/workflows/",
        token,
        apiKey,
        body: buildWorkflowCreatePresetBody(selectedPresetId)
      });
      const payload = asObject(result.data);
      setNotice(
        `Preset workflow ready: ${asString(payload?.name, selectedPresetId)}`
      );
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Failed to apply preset.");
    }
  }

  async function handleGenerateArtifact(): Promise<void> {
    try {
      const isPlanReview = artifactMode === "plan_review";
      const result = await runRequest("Improvement Cycle - Generate Artifact", {
        method: "POST",
        path: isPlanReview ? "/v1/explanations/plan-review" : "/v1/explanations/diff-review",
        token,
        apiKey,
        body: JSON.stringify(
          isPlanReview
            ? {
                entity_type: entityType,
                entity_id: entityId,
                plan_text: artifactText,
                metadata: {
                  branch,
                  preset_id: selectedPresetId
                },
                claims: []
              }
            : {
                entity_type: entityType,
                entity_id: entityId,
                diff_text: artifactText,
                metadata: {
                  branch,
                  preset_id: selectedPresetId
                },
                claims: []
              }
        )
      });
      const nextArtifact = parseExplanationArtifact(result.data);
      if (nextArtifact === null || nextArtifact.id === "") {
        throw new Error("Artifact response was missing an explanation id.");
      }
      setArtifact(nextArtifact);
      setNotice(`Artifact ready: ${nextArtifact.id}`);
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "Failed to generate artifact."
      );
    }
  }

  async function handleCreateReview(): Promise<void> {
    if (artifact === null) {
      setError("Generate an artifact before creating a review.");
      return;
    }
    try {
      const result = await runRequest("Improvement Cycle - Create Review", {
        method: "POST",
        path: "/v1/reviews/",
        token,
        apiKey,
        body: JSON.stringify({
          task_id: taskId,
          branch,
          artifacts: [buildReviewArtifactLink(artifact)]
        })
      });
      const payload = asObject(result.data);
      const reviewId = asString(payload?.id);
      if (reviewId === "") {
        throw new Error("Review response was missing an id.");
      }
      await loadReview(reviewId);
      setNotice(`Linked review created: ${reviewId}`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Failed to create review.");
    }
  }

  async function handleAssessRisk(): Promise<void> {
    if (review === null) {
      setError("Create a review before assessing risk.");
      return;
    }
    try {
      await runRequest("Improvement Cycle - Assess Risk", {
        method: "POST",
        path: "/v1/reviews/{review_id}/assess",
        pathParams: { review_id: review.id },
        token,
        apiKey,
        body: JSON.stringify({ triggers: selectedTriggers })
      });
      await loadReview(review.id);
      setNotice("Risk assessment updated.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Failed to assess risk.");
    }
  }

  async function handleReviewAction(
    label: string,
    path: string,
    payload?: Record<string, unknown>
  ): Promise<void> {
    if (review === null) {
      setError("Create a review before advancing signoff.");
      return;
    }
    try {
      await runRequest(label, {
        method: "POST",
        path,
        pathParams: { review_id: review.id },
        token,
        apiKey,
        body: payload ? JSON.stringify(payload) : undefined
      });
      await loadReview(review.id);
      setNotice(`${label} completed.`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : `${label} failed.`);
    }
  }

  async function handleRefreshToolApprovals(): Promise<void> {
    try {
      const result = await runRequest("Improvement Cycle - Pending Tool Approvals", {
        method: "GET",
        path: "/v1/approvals/tools",
        query: { status: "pending" },
        token,
        apiKey
      });
      setToolApprovals(parseToolApprovals(result.data));
      setNotice("Tool approvals refreshed.");
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "Failed to load tool approvals."
      );
    }
  }

  async function handleToolDecision(
    approvalId: string,
    decision: "approve" | "reject"
  ): Promise<void> {
    try {
      await runRequest(`Improvement Cycle - ${formatLabel(decision)} Tool Approval`, {
        method: "POST",
        path: "/v1/approvals/tools/{approval_id}/decision",
        pathParams: { approval_id: approvalId },
        token,
        apiKey,
        body: JSON.stringify({
          decision,
          review_note: approvalNote
        })
      });
      setToolApprovals((current) =>
        current.filter((record) => record.approval_id !== approvalId)
      );
      setNotice(`Tool approval ${approvalId} marked ${decision}.`);
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "Failed to update tool approval."
      );
    }
  }

  function toggleTrigger(trigger: string): void {
    setSelectedTriggers((current) =>
      current.includes(trigger)
        ? current.filter((entry) => entry !== trigger)
        : [...current, trigger]
    );
  }

  const isBusy = busyAction !== "";

  return (
    <section className="improvement-cycle-wizard">
      <header className="wizard-head">
        <div>
          <h2>Improvement Cycle Wizard</h2>
          <p>
            Guided artifact, signoff, and approval flow for workflow review operations.
          </p>
        </div>
        <div className="wizard-status">
          <span>{artifact ? `Artifact ${artifact.id}` : "No artifact yet"}</span>
          <span>{review ? `Review ${review.id}` : "No review yet"}</span>
        </div>
      </header>

      {!token && !apiKey ? (
        <p className="wizard-warning">
          Provide a bearer token or API key before using the review wizard.
        </p>
      ) : null}

      {notice ? <p className="wizard-notice">{notice}</p> : null}
      {error ? <p className="wizard-error">{error}</p> : null}

      <div className="wizard-grid">
        <section className="wizard-card">
          <header>
            <h3>1. Artifact</h3>
            <p>Generate a plan or diff review artifact and preview it inline.</p>
          </header>
          <div className="wizard-form-grid">
            <label>
              Review mode
              <select
                aria-label="Review mode"
                value={artifactMode}
                onChange={(event) => setArtifactMode(event.target.value as ArtifactMode)}
              >
                <option value="plan_review">Plan review</option>
                <option value="diff_review">Diff review</option>
              </select>
            </label>
            <label>
              Improvement preset
              <select
                aria-label="Improvement preset"
                value={selectedPresetId}
                onChange={(event) => setSelectedPresetId(event.target.value)}
              >
                {improvementCycleWorkflowPresets.map((preset) => (
                  <option key={preset.id} value={preset.id}>
                    {preset.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Entity type
              <input value={entityType} onChange={(event) => setEntityType(event.target.value)} />
            </label>
            <label>
              Entity ID
              <input value={entityId} onChange={(event) => setEntityId(event.target.value)} />
            </label>
          </div>
          <label className="wizard-textarea">
            Artifact content
            <textarea
              aria-label="Artifact content"
              rows={8}
              value={artifactText}
              onChange={(event) => setArtifactText(event.target.value)}
            />
          </label>
          <div className="wizard-actions">
            <button disabled={isBusy} onClick={() => void handleApplyPreset()}>
              Create preset workflow
            </button>
            <button disabled={isBusy} onClick={() => void handleGenerateArtifact()}>
              Generate artifact
            </button>
          </div>
          {artifact ? (
            <div className="wizard-preview">
              <div className="wizard-meta">
                <span>
                  Artifact ID: <strong>{artifact.id}</strong>
                </span>
                <span>
                  Fact-check: <strong>{formatLabel(artifact.fact_check_status)}</strong>
                </span>
              </div>
              <iframe
                className="wizard-preview-frame"
                title="Artifact preview"
                srcDoc={artifact.content}
              />
            </div>
          ) : null}
        </section>

        <section className="wizard-card">
          <header>
            <h3>2. Review Draft</h3>
            <p>Create a linked review and assess risk with explicit trigger selection.</p>
          </header>
          <div className="wizard-form-grid">
            <label>
              Task ID
              <input value={taskId} onChange={(event) => setTaskId(event.target.value)} />
            </label>
            <label>
              Branch
              <input value={branch} onChange={(event) => setBranch(event.target.value)} />
            </label>
          </div>
          <div className="wizard-actions">
            <button disabled={isBusy || artifact === null} onClick={() => void handleCreateReview()}>
              Create linked review
            </button>
            <button disabled={isBusy || review === null} onClick={() => void handleAssessRisk()}>
              Assess selected risk triggers
            </button>
          </div>
          <div className="wizard-trigger-grid">
            {RISK_TRIGGER_OPTIONS.map((trigger) => (
              <label key={trigger} className="wizard-check">
                <input
                  type="checkbox"
                  checked={selectedTriggers.includes(trigger)}
                  onChange={() => toggleTrigger(trigger)}
                />
                {formatLabel(trigger)}
              </label>
            ))}
          </div>
          {review ? (
            <div className="wizard-review-summary">
              <p>
                Review ID: <strong>{review.id}</strong>
              </p>
              <p>
                State: <strong>{formatLabel(review.state)}</strong>
              </p>
              <p>
                Risk: <strong>{formatLabel(review.risk_assessment.risk_level || "none")}</strong>
              </p>
              <p>
                L1 required: <strong>{review.risk_assessment.l1_required ? "Yes" : "No"}</strong>
              </p>
              <p>
                L2 required: <strong>{review.risk_assessment.l2_required ? "Yes" : "No"}</strong>
              </p>
            </div>
          ) : null}
        </section>

        <section className="wizard-card">
          <header>
            <h3>3. Signoff</h3>
            <p>Advance the review through ready, L1, optional L2, approval, and merge.</p>
          </header>
          <div className="wizard-actions wizard-actions-wrap">
            <button disabled={isBusy || review === null} onClick={() => void handleReviewAction("Improvement Cycle - Mark Ready", "/v1/reviews/{review_id}/ready")}>
              Mark ready
            </button>
            <button disabled={isBusy || review === null} onClick={() => void handleReviewAction("Improvement Cycle - Assign L1", "/v1/reviews/{review_id}/assign-l1")}>
              Assign L1 reviewer
            </button>
            <button
              disabled={isBusy || review === null}
              onClick={() =>
                void handleReviewAction("Improvement Cycle - Submit L1", "/v1/reviews/{review_id}/l1", {
                  decision: l1Decision,
                  checklist: {
                    code_quality: "pass",
                    correctness: "pass",
                    testing: "pass",
                    scope: "pass"
                  },
                  issues: [],
                  comments: "Submitted from the improvement-cycle wizard."
                })
              }
            >
              Submit L1
            </button>
            <button
              disabled={isBusy || review === null || !review.risk_assessment.l2_required}
              onClick={() => void handleReviewAction("Improvement Cycle - Assign L2", "/v1/reviews/{review_id}/assign-l2")}
            >
              Assign L2 reviewer
            </button>
            <button
              disabled={isBusy || review === null || !review.risk_assessment.l2_required}
              onClick={() =>
                void handleReviewAction("Improvement Cycle - Submit L2", "/v1/reviews/{review_id}/l2", {
                  decision: l2Decision,
                  checklist: {
                    architecture: "pass",
                    security: "pass",
                    compliance: "pass",
                    impact: "pass"
                  },
                  issues: [],
                  comments: "Submitted from the improvement-cycle wizard."
                })
              }
            >
              Submit L2
            </button>
            <button
              disabled={isBusy || review === null}
              onClick={() =>
                void handleReviewAction(
                  "Improvement Cycle - Approve Review",
                  "/v1/reviews/{review_id}/approve",
                  { conditions: [] }
                )
              }
            >
              Final approval
            </button>
            <button disabled={isBusy || review === null} onClick={() => void handleReviewAction("Improvement Cycle - Merge Review", "/v1/reviews/{review_id}/merge")}>
              Mark merged
            </button>
          </div>
          <div className="wizard-form-grid">
            <label>
              L1 decision
              <select
                aria-label="L1 decision"
                value={l1Decision}
                onChange={(event) => setL1Decision(event.target.value as ReviewDecision)}
              >
                <option value="approved">Approved</option>
                <option value="changes_requested">Changes requested</option>
                <option value="escalated">Escalated</option>
              </select>
            </label>
            <label>
              L2 decision
              <select
                aria-label="L2 decision"
                value={l2Decision}
                onChange={(event) => setL2Decision(event.target.value as ReviewDecision)}
              >
                <option value="approved">Approved</option>
                <option value="changes_requested">Changes requested</option>
                <option value="escalated">Escalated</option>
              </select>
            </label>
          </div>
          <p className="wizard-help-text">
            Final approval is recorded for the authenticated user automatically.
          </p>
          {review ? (
            <div className="wizard-signoff-state">
              <p>
                Current state: <strong>{formatLabel(review.state)}</strong>
              </p>
              <p>
                L1 decision: <strong>{formatLabel(review.l1_review.decision || "pending")}</strong>
              </p>
              <p>
                L2 decision: <strong>{formatLabel(review.l2_review.decision || "pending")}</strong>
              </p>
              <p>
                Approved by: <strong>{review.final_signoff.approved_by || "Pending"}</strong>
              </p>
            </div>
          ) : null}
        </section>

        <section className="wizard-card">
          <header>
            <h3>4. Tool Approvals</h3>
            <p>Review pending tool approvals without leaving the workflow domain.</p>
          </header>
          <label className="wizard-textarea">
            Review note
            <textarea
              aria-label="Tool approval note"
              rows={3}
              value={approvalNote}
              onChange={(event) => setApprovalNote(event.target.value)}
            />
          </label>
          <div className="wizard-actions">
            <button disabled={isBusy} onClick={() => void handleRefreshToolApprovals()}>
              Refresh pending approvals
            </button>
          </div>
          <div className="wizard-approval-list">
            {toolApprovals.length === 0 ? (
              <p className="wizard-muted">No pending tool approvals loaded.</p>
            ) : (
              toolApprovals.map((approval) => (
                <article key={approval.approval_id} className="wizard-approval-card">
                  <div className="wizard-meta">
                    <span>
                      Approval ID: <strong>{approval.approval_id}</strong>
                    </span>
                    <span>
                      Status: <strong>{formatLabel(approval.status)}</strong>
                    </span>
                  </div>
                  <p>
                    <strong>{approval.tool_name}</strong>
                    {approval.operation ? ` · ${approval.operation}` : ""}
                  </p>
                  {approval.command ? <pre>{approval.command}</pre> : null}
                  {approval.details ? <p>{approval.details}</p> : null}
                  <div className="wizard-actions">
                    <button
                      disabled={isBusy}
                      onClick={() => void handleToolDecision(approval.approval_id, "approve")}
                    >
                      Approve
                    </button>
                    <button
                      className="wizard-danger"
                      disabled={isBusy}
                      onClick={() => void handleToolDecision(approval.approval_id, "reject")}
                    >
                      Reject
                    </button>
                  </div>
                </article>
              ))
            )}
          </div>
        </section>
      </div>
    </section>
  );
}
