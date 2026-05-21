import { useCallback, useEffect, useMemo, useState } from "react";

import { formatTimestamp, getStatusClass, getStatusLabel } from "../operations-hub/helpers";
import { apiRequest } from "../../lib/api";
import type { ApiResult } from "../../types";
import {
  asToolApprovalList,
  asToolApprovalRequest,
  decideToolApproval,
  fetchToolApprovals
} from "./api";
import {
  TOOL_APPROVAL_STATUSES,
  type ToolApprovalDecision,
  type ToolApprovalRequest,
  type ToolApprovalStatus
} from "./types";
import {
  buildAttentionQueue,
  buildBulkDecisionGuidance,
  getPolicyPreset,
  getRecommendedTokenPreset,
  isBatchEligibleApproval,
  type ApprovalTokenPresetId
} from "./attentionQueue";

interface SafetyCenterPanelProps {
  token: string;
  apiKey: string;
  onOpenSetup: () => void;
  onResult: (label: string, result: ApiResult) => void;
}

type ApprovalFilter = ToolApprovalStatus | "all";

interface ApprovalTokenReceipt {
  approvalId: string;
  approvalToken: string;
  ttlSeconds: number | null;
  oneTime: boolean | null;
  tokenPreset: ApprovalTokenPresetId | null;
}

const APPROVAL_TOKEN_PRESET_OPTIONS: ReadonlyArray<{
  id: ApprovalTokenPresetId;
  label: string;
  summary: string;
}> = [
  { id: "single_use", label: "single_use", summary: "5 min, one-time" },
  { id: "session_15m", label: "session_15m", summary: "15 min, reusable" },
  { id: "session_1h", label: "session_1h", summary: "1 hour, reusable" },
  { id: "workday", label: "workday", summary: "8 hours, reusable" }
];

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function formatTokenPresetLabel(preset: ApprovalTokenPresetId): string {
  const option = APPROVAL_TOKEN_PRESET_OPTIONS.find((candidate) => candidate.id === preset);
  return option ? `${option.label} (${option.summary})` : preset;
}

function asApprovalTokenReceipt(value: unknown): ApprovalTokenReceipt | null {
  if (!isObject(value) || typeof value.approval_id !== "string" || typeof value.approval_token !== "string") {
    return null;
  }
  const ttlSeconds = typeof value.ttl_seconds === "number" ? value.ttl_seconds : null;
  const oneTime = typeof value.one_time === "boolean" ? value.one_time : null;
  return {
    approvalId: value.approval_id,
    approvalToken: value.approval_token,
    ttlSeconds,
    oneTime,
    tokenPreset: null
  };
}

function asBatchDecisionOutcome(value: unknown): {
  count: number;
  tokens: ApprovalTokenReceipt[];
} | null {
  if (!isObject(value) || typeof value.count !== "number" || !Array.isArray(value.results)) {
    return null;
  }
  const tokens = value.results
    .map((item) => asApprovalTokenReceipt(item))
    .filter((item): item is ApprovalTokenReceipt => item !== null);
  return {
    count: value.count,
    tokens
  };
}

function describeReason(reason: string): string {
  switch (reason) {
    case "supervised_destructive":
      return "Destructive or high-impact action";
    case "route_mutation":
      return "Sensitive route mutation";
    case "tool_policy_ask":
      return "Configured to ask before running";
    default:
      return getStatusLabel(reason);
  }
}

function formatRelativeRisk(request: ToolApprovalRequest): string {
  if (request.reason === "supervised_destructive" || request.reason === "route_mutation") {
    return "High risk";
  }
  if (request.command || request.operation) {
    return "Needs review";
  }
  return "Routine approval";
}

function getApprovalTitle(request: ToolApprovalRequest): string {
  if (request.operation) {
    return `${request.tool_name}: ${request.operation}`;
  }
  return request.tool_name;
}

export function SafetyCenterPanel({
  token,
  apiKey,
  onOpenSetup,
  onResult
}: SafetyCenterPanelProps): JSX.Element {
  const [approvals, setApprovals] = useState<ToolApprovalRequest[]>([]);
  const [selectedApprovalId, setSelectedApprovalId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<ApprovalFilter>("pending");
  const [textFilter, setTextFilter] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [batchReviewNote, setBatchReviewNote] = useState("");
  const [batchIssueTokens, setBatchIssueTokens] = useState(false);
  const [batchTokenPreset, setBatchTokenPreset] = useState<ApprovalTokenPresetId>("session_15m");
  const [detailTokenPreset, setDetailTokenPreset] = useState<ApprovalTokenPresetId>("single_use");
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionSuccess, setActionSuccess] = useState("");
  const [actionInFlight, setActionInFlight] = useState<ToolApprovalDecision | null>(null);
  const [batchInFlight, setBatchInFlight] = useState(false);
  const [tokenInFlight, setTokenInFlight] = useState(false);
  const [issuedTokens, setIssuedTokens] = useState<Record<string, ApprovalTokenReceipt>>({});

  const hasCredentials = token.trim() !== "" || apiKey.trim() !== "";

  const loadApprovals = useCallback(async (): Promise<ToolApprovalRequest[] | null> => {
    if (!hasCredentials) {
      return null;
    }
    setLoading(true);
    try {
      const result = await fetchToolApprovals(statusFilter, token, apiKey);
      onResult("Safety Center - Tool Approvals", result);
      const records = asToolApprovalList(result.data);
      if (!result.ok || records === null) {
        setLoadError(`Failed to load safety approvals (${result.status})`);
        return null;
      }
      setLoadError("");
      setApprovals(records);
      if (records.length === 0) {
        setSelectedApprovalId(null);
        return records;
      }
      setSelectedApprovalId((current) => {
        if (current !== null && records.some((approval) => approval.approval_id === current)) {
          return current;
        }
        return records[0].approval_id;
      });
      return records;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown safety approval error";
      setLoadError(message);
      return null;
    } finally {
      setLoading(false);
    }
  }, [apiKey, hasCredentials, onResult, statusFilter, token]);

  useEffect(() => {
    void loadApprovals();
    const interval = setInterval(() => {
      void loadApprovals();
    }, 5000);
    return () => clearInterval(interval);
  }, [loadApprovals]);

  const filteredApprovals = useMemo(() => {
    const normalizedText = textFilter.trim().toLowerCase();
    return approvals.filter((approval) => {
      if (normalizedText === "") {
        return true;
      }
      return (
        approval.approval_id.toLowerCase().includes(normalizedText) ||
        approval.tool_name.toLowerCase().includes(normalizedText) ||
        approval.operation.toLowerCase().includes(normalizedText) ||
        approval.command.toLowerCase().includes(normalizedText) ||
        approval.requested_by.toLowerCase().includes(normalizedText) ||
        approval.details.toLowerCase().includes(normalizedText)
      );
    });
  }, [approvals, textFilter]);

  const selectedApproval = useMemo(() => {
    if (selectedApprovalId === null) {
      return null;
    }
    return approvals.find((approval) => approval.approval_id === selectedApprovalId) ?? null;
  }, [approvals, selectedApprovalId]);

  useEffect(() => {
    if (selectedApproval !== null) {
      setDetailTokenPreset(getRecommendedTokenPreset(selectedApproval));
    }
  }, [selectedApproval]);

  const pendingCount = useMemo(() => {
    return approvals.filter((approval) => approval.status === "pending").length;
  }, [approvals]);
  const attentionQueue = useMemo(() => buildAttentionQueue(filteredApprovals), [filteredApprovals]);
  const bulkGuidance = useMemo(() => buildBulkDecisionGuidance(attentionQueue), [attentionQueue]);
  const batchEligibleApprovals = useMemo(() => {
    return filteredApprovals.filter((approval) => isBatchEligibleApproval(approval));
  }, [filteredApprovals]);
  const selectedApprovalToken = selectedApproval ? issuedTokens[selectedApproval.approval_id] ?? null : null;

  async function handleDecision(decision: ToolApprovalDecision): Promise<void> {
    if (selectedApproval === null) {
      return;
    }
    const trimmedNote = reviewNote.trim();
    if (trimmedNote === "") {
      setActionError("Add a short review note before approving or rejecting this action.");
      return;
    }
    setActionError("");
    setActionSuccess("");
    setActionInFlight(decision);
    try {
      const result = await decideToolApproval(
        selectedApproval.approval_id,
        decision,
        trimmedNote,
        token,
        apiKey
      );
      onResult(`Safety Center - ${decision}`, result);
      const updated = asToolApprovalRequest(result.data);
      if (!result.ok || updated === null) {
        setActionError(`${getStatusLabel(decision)} failed (${result.status})`);
        return;
      }
      setActionSuccess(
        decision === "approve"
          ? `${getApprovalTitle(selectedApproval)} approved. If follow-through is token-gated, issue a short-lived approval token next.`
          : `${getApprovalTitle(selectedApproval)} rejected. The governed action will remain blocked.`
      );
      setReviewNote("");
      await loadApprovals();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown approval decision error";
      setActionError(message);
    } finally {
      setActionInFlight(null);
    }
  }

  async function handleBatchApprove(): Promise<void> {
    if (batchEligibleApprovals.length === 0) {
      return;
    }
    const trimmedNote = batchReviewNote.trim();
    if (trimmedNote === "") {
      setActionError("Add a batch review note before approving low/medium-risk items together.");
      return;
    }
    setActionError("");
    setActionSuccess("");
    setBatchInFlight(true);
    try {
      const body: Record<string, unknown> = {
        approval_ids: batchEligibleApprovals.map((approval) => approval.approval_id),
        decision: "approve",
        review_note: trimmedNote,
        issue_tokens: batchIssueTokens
      };
      if (batchIssueTokens) {
        body.token_preset = batchTokenPreset;
      }
      const result = await apiRequest({
        method: "POST",
        path: "/v1/approvals/tools/batch-decision",
        token,
        apiKey,
        body: JSON.stringify(body)
      });
      onResult("Safety Center - batch approve", result);
      const outcome = asBatchDecisionOutcome(result.data);
      if (!result.ok || outcome === null) {
        setActionError(`Batch approval failed (${result.status})`);
        return;
      }
      if (outcome.tokens.length > 0) {
        setIssuedTokens((current) => {
          const next = { ...current };
          outcome.tokens.forEach((tokenReceipt) => {
            next[tokenReceipt.approvalId] = {
              ...tokenReceipt,
              tokenPreset: batchTokenPreset
            };
          });
          return next;
        });
      }
      setActionSuccess(
        batchIssueTokens
          ? `Approved ${outcome.count} low/medium-risk item${outcome.count === 1 ? "" : "s"} and issued ${outcome.tokens.length} ${formatTokenPresetLabel(batchTokenPreset)} token${outcome.tokens.length === 1 ? "" : "s"} for follow-through.`
          : `Approved ${outcome.count} low/medium-risk item${outcome.count === 1 ? "" : "s"} in one batch decision.`
      );
      setBatchReviewNote("");
      await loadApprovals();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown batch approval error";
      setActionError(message);
    } finally {
      setBatchInFlight(false);
    }
  }

  async function handleIssueApprovalToken(): Promise<void> {
    if (selectedApproval === null || selectedApproval.status !== "approved") {
      return;
    }
    setActionError("");
    setActionSuccess("");
    setTokenInFlight(true);
    try {
      const result = await apiRequest({
        method: "POST",
        path: "/v1/approvals/tools/{approval_id}/token",
        pathParams: { approval_id: selectedApproval.approval_id },
        token,
        apiKey,
        body: JSON.stringify({
          token_preset: detailTokenPreset
        })
      });
      onResult("Safety Center - issue approval token", result);
      const receipt = asApprovalTokenReceipt(result.data);
      if (!result.ok || receipt === null) {
        setActionError(`Approval token issuance failed (${result.status})`);
        return;
      }
      setIssuedTokens((current) => ({
        ...current,
        [receipt.approvalId]: {
          ...receipt,
          tokenPreset: detailTokenPreset
        }
      }));
      setActionSuccess(
        `Issued ${formatTokenPresetLabel(detailTokenPreset)} for ${getApprovalTitle(selectedApproval)}. Send it as X-Agent33-Approval-Token before it expires.`
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown approval token error";
      setActionError(message);
    } finally {
      setTokenInFlight(false);
    }
  }

  if (!hasCredentials) {
    return (
      <section className="safety-center-panel">
        <div className="onboarding-callout onboarding-callout-error">
          <h3>Connect to the engine first</h3>
          <p>
            Safety approvals are tenant-scoped. Add an API key or operator token before approving
            destructive tool actions, route mutations, or issuing approval tokens.
          </p>
          <button onClick={onOpenSetup}>Open integrations and API access</button>
        </div>
      </section>
    );
  }

  return (
    <section className="safety-center-panel">
      <header className="safety-center-hero">
        <div>
          <h2>Safety Center</h2>
          <p>
            Review governed tool calls and sensitive route mutations before they can run. Approved
            items can mint short-lived approval tokens for token-gated follow-through.
          </p>
        </div>
        <div className="safety-center-score" aria-label={`${pendingCount} pending approvals`}>
          <strong>{pendingCount}</strong>
          <span>pending approvals</span>
        </div>
      </header>

      <div className="review-panel-toolbar" aria-label="Safety approval filters">
        <label>
          Search approvals
          <input
            placeholder="Tool, route, command, requester, or id"
            value={textFilter}
            onChange={(event) => setTextFilter(event.target.value)}
          />
        </label>
        <label>
          Status
          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value as ApprovalFilter);
              setSelectedApprovalId(null);
            }}
          >
            <option value="all">All statuses</option>
            {TOOL_APPROVAL_STATUSES.map((status) => (
              <option key={status} value={status}>
                {getStatusLabel(status)}
              </option>
            ))}
          </select>
        </label>
        <button onClick={() => void loadApprovals()} disabled={loading}>
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      <section className="attention-queue-panel" aria-labelledby="attention-queue-title">
        <div>
          <p className="eyebrow">Attention queue</p>
          <h3 id="attention-queue-title">Decide the riskiest items first</h3>
          <p>{bulkGuidance}</p>
        </div>
        <div className="detail-section">
          <h4>Batch low/medium queue</h4>
          <p>
            {batchEligibleApprovals.length === 0
              ? "No visible low/medium-risk approvals are eligible for batch approval right now."
              : `${batchEligibleApprovals.length} visible low/medium-risk approval${batchEligibleApprovals.length === 1 ? "" : "s"} can be approved together. High-risk and route-mutation items still require individual review.`}
          </p>
          <div className="review-action-form">
            <label>
              Batch review note
              <textarea
                rows={2}
                value={batchReviewNote}
                onChange={(event) => setBatchReviewNote(event.target.value)}
                placeholder="Summarize why these low/medium-risk items are safe to approve together."
              />
            </label>
            <label>
              <input
                type="checkbox"
                checked={batchIssueTokens}
                onChange={(event) => setBatchIssueTokens(event.target.checked)}
              />
              Issue approval tokens for approved follow-through
            </label>
            {batchIssueTokens ? (
              <label>
                Time-bound preset
                <select
                  value={batchTokenPreset}
                  onChange={(event) =>
                    setBatchTokenPreset(event.target.value as ApprovalTokenPresetId)
                  }
                >
                  {APPROVAL_TOKEN_PRESET_OPTIONS.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label} - {option.summary}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <div className="review-action-buttons">
              <button
                type="button"
                onClick={() => void handleBatchApprove()}
                disabled={
                  batchEligibleApprovals.length === 0 ||
                  batchInFlight ||
                  actionInFlight !== null ||
                  tokenInFlight
                }
              >
                {batchInFlight ? "Approving batch..." : "Approve low/medium queue"}
              </button>
            </div>
          </div>
        </div>
        {attentionQueue.length === 0 ? (
          <p className="ops-hub-empty">No pending safety decisions need attention.</p>
        ) : (
          <div className="attention-queue-list">
            {attentionQueue.slice(0, 4).map((item) => (
              <article key={item.id} className={`attention-queue-item attention-queue-item--${item.priority}`}>
                <strong>{item.title}</strong>
                <span>{item.priority} priority</span>
                <p>{item.reason}</p>
                <small>{item.timeGuidance}</small>
                <small>Decision mode: {item.decisionMode}</small>
                <small>Token preset: {formatTokenPresetLabel(item.tokenPreset)}</small>
                <button type="button" onClick={() => setSelectedApprovalId(item.id)}>
                  Review this decision
                </button>
              </article>
            ))}
          </div>
        )}
      </section>

      <div className="safety-center-content">
        <div className="review-asset-list safety-approval-list">
          {loadError ? <p className="ops-hub-error" role="alert">{loadError}</p> : null}
          {loading && approvals.length === 0 ? (
            <p className="ops-hub-loading">Loading safety approvals...</p>
          ) : null}
          {approvals.length === 0 && !loading && !loadError ? (
            <p className="ops-hub-empty">No tool approvals match this status.</p>
          ) : null}
          {approvals.length > 0 && filteredApprovals.length === 0 ? (
            <p className="ops-hub-empty">No approvals match the current search.</p>
          ) : null}
          {filteredApprovals.map((approval) => (
            <article
              key={approval.approval_id}
              className={`ops-hub-process-item ${selectedApprovalId === approval.approval_id ? "selected" : ""}`}
              onClick={() => setSelectedApprovalId(approval.approval_id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  setSelectedApprovalId(approval.approval_id);
                }
              }}
              tabIndex={0}
              role="button"
              aria-pressed={selectedApprovalId === approval.approval_id}
            >
              <div className="process-item-header">
                <h4>{getApprovalTitle(approval)}</h4>
                <span className={`process-status ${getStatusClass(approval.status)}`}>
                  {getStatusLabel(approval.status)}
                </span>
              </div>
              <p className="process-item-id">{approval.approval_id}</p>
              <p className="process-item-time">
                {formatRelativeRisk(approval)} • {describeReason(approval.reason)}
              </p>
              <div className="review-asset-flags">
                {approval.requested_by ? (
                  <span className="review-asset-flag">Requested by {approval.requested_by}</span>
                ) : null}
                {approval.expires_at ? (
                  <span className="review-asset-flag">Expires {formatTimestamp(approval.expires_at)}</span>
                ) : null}
              </div>
            </article>
          ))}
        </div>

        <div className="ops-hub-detail safety-approval-detail">
          {selectedApproval === null ? (
            <p className="ops-hub-placeholder">Select an approval to inspect impact and decide.</p>
          ) : null}
          {actionError ? <p className="ops-hub-error" role="alert">{actionError}</p> : null}
          {actionSuccess ? <p className="review-action-success">{actionSuccess}</p> : null}
          {selectedApproval !== null ? (
            <div className="process-detail">
              <h3>{getApprovalTitle(selectedApproval)}</h3>
              <p className="safety-risk-summary">{describeReason(selectedApproval.reason)}</p>

              <div className="detail-field">
                <span className="detail-label">Approval ID</span>
                <span>{selectedApproval.approval_id}</span>
              </div>
              <div className="detail-field">
                <span className="detail-label">Status</span>
                <span className={`process-status ${getStatusClass(selectedApproval.status)}`}>
                  {getStatusLabel(selectedApproval.status)}
                </span>
              </div>
              <div className="detail-field">
                <span className="detail-label">Tool</span>
                <span>{selectedApproval.tool_name}</span>
              </div>
              <div className="detail-field">
                <span className="detail-label">Operation</span>
                <span>{selectedApproval.operation || "Not specified"}</span>
              </div>
              <div className="detail-field">
                <span className="detail-label">Requester</span>
                <span>{selectedApproval.requested_by || "Unknown"}</span>
              </div>
              <div className="detail-field">
                <span className="detail-label">Created</span>
                <span>{formatTimestamp(selectedApproval.created_at)}</span>
              </div>
              <div className="detail-field">
                <span className="detail-label">Expires</span>
                <span>{selectedApproval.expires_at ? formatTimestamp(selectedApproval.expires_at) : "No expiry"}</span>
              </div>

              {selectedApproval.command ? (
                <div className="detail-section">
                  <h4>Command preview</h4>
                  <pre className="safety-command-preview">{selectedApproval.command}</pre>
                </div>
              ) : null}

              {selectedApproval.details ? (
                <div className="detail-section">
                  <h4>Request details</h4>
                  <p>{selectedApproval.details}</p>
                </div>
              ) : null}

              <div className="detail-section">
                <h4>Decision guidance</h4>
                <p>{getPolicyPreset(selectedApproval)}</p>
              </div>

              {selectedApproval.status === "pending" ? (
                <div className="detail-section">
                  <h4>Operator decision</h4>
                  <div className="review-action-form">
                    <label>
                      Review note
                      <textarea
                        rows={3}
                        value={reviewNote}
                        onChange={(event) => setReviewNote(event.target.value)}
                        placeholder="Explain why this action is safe or why it should stay blocked."
                      />
                    </label>
                    <p>
                      High-risk and route-mutation approvals must be decided one by one. Only
                      visible low/medium-risk items can use batch approval.
                    </p>
                    <div className="review-action-buttons">
                      <button
                        className="danger"
                        onClick={() => void handleDecision("reject")}
                        disabled={actionInFlight !== null || batchInFlight || tokenInFlight}
                      >
                        {actionInFlight === "reject" ? "Rejecting..." : "Reject action"}
                      </button>
                      <button
                        onClick={() => void handleDecision("approve")}
                        disabled={actionInFlight !== null || batchInFlight || tokenInFlight}
                      >
                        {actionInFlight === "approve" ? "Approving..." : "Approve action"}
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="detail-section">
                  <h4>Audit trail</h4>
                  <p>
                    Reviewed by {selectedApproval.reviewed_by || "unknown operator"}
                    {selectedApproval.reviewed_at ? ` on ${formatTimestamp(selectedApproval.reviewed_at)}` : ""}.
                  </p>
                  {selectedApproval.review_note ? <p>{selectedApproval.review_note}</p> : null}
                </div>
              )}

              {selectedApproval.status === "approved" ? (
                <div className="detail-section">
                  <h4>Approval token</h4>
                  <p>
                    Sensitive follow-through routes now expect a short-lived
                    {" "}
                    <code>X-Agent33-Approval-Token</code>
                    {" "}
                    header. Mint the smallest preset that still fits the next step.
                  </p>
                  <div className="review-action-form">
                    <label>
                      Time-bound preset
                      <select
                        value={detailTokenPreset}
                        onChange={(event) =>
                          setDetailTokenPreset(event.target.value as ApprovalTokenPresetId)
                        }
                      >
                        {APPROVAL_TOKEN_PRESET_OPTIONS.map((option) => (
                          <option key={option.id} value={option.id}>
                            {option.label} - {option.summary}
                          </option>
                        ))}
                      </select>
                    </label>
                    <p>Recommended preset: {formatTokenPresetLabel(getRecommendedTokenPreset(selectedApproval))}</p>
                    <div className="review-action-buttons">
                      <button
                        type="button"
                        onClick={() => void handleIssueApprovalToken()}
                        disabled={tokenInFlight || actionInFlight !== null || batchInFlight}
                      >
                        {tokenInFlight ? "Issuing token..." : "Issue approval token"}
                      </button>
                    </div>
                  </div>
                  {selectedApprovalToken ? (
                    <div className="detail-section">
                      <h4>Issued token</h4>
                      <div className="detail-field">
                        <span className="detail-label">Preset</span>
                        <span>
                          {selectedApprovalToken.tokenPreset
                            ? formatTokenPresetLabel(selectedApprovalToken.tokenPreset)
                            : "Server default"}
                        </span>
                      </div>
                      <div className="detail-field">
                        <span className="detail-label">TTL</span>
                        <span>
                          {selectedApprovalToken.ttlSeconds !== null
                            ? `${selectedApprovalToken.ttlSeconds} seconds`
                            : "Server default"}
                        </span>
                      </div>
                      <div className="detail-field">
                        <span className="detail-label">One-time</span>
                        <span>
                          {selectedApprovalToken.oneTime === null
                            ? "Server default"
                            : selectedApprovalToken.oneTime
                              ? "Yes"
                              : "No"}
                        </span>
                      </div>
                      <label>
                        <span className="detail-label">Header value</span>
                        <textarea rows={4} readOnly value={selectedApprovalToken.approvalToken} />
                      </label>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
