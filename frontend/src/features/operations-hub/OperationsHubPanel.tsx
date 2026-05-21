import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { ApiResult } from "../../types";
import {
  asOperationsHubDetail,
  asOperationsHubResponse,
  asRecoveryReplaySummary,
  asRecoverySessionSummaries,
  checkpointSession,
  controlProcess,
  fetchIncompleteSessions,
  fetchOperationsHub,
  fetchProcessDetail,
  fetchReplaySummary,
  resumeIncompleteSession
} from "./api";
import {
  buildOperationsTimeline,
  buildReviewableOutputPlan,
  canCancel,
  canPause,
  canResume,
  filterAndSortProcesses,
  formatTimestamp,
  getStatusClass,
  getStatusLabel,
  summarizeOperations
} from "./helpers";
import { IngestionReviewPanel } from "./IngestionReviewPanel";
import {
  OPERATIONS_RECOVERY_PANEL_ID,
  consumeOperationsRecoveryFocusRequest
} from "./recoveryNavigation";
import type {
  OperationsHubControlAction,
  OperationsHubProcessDetail,
  OperationsHubProcessSummary,
  RecoveryReplaySummary,
  RecoverySessionSummary
} from "./types";

interface OperationsHubPanelProps {
  token: string;
  apiKey: string;
  onResult: (label: string, result: ApiResult) => void;
}

function stringifyMetadata(value: unknown): string {
  if (value === undefined) {
    return "";
  }
  return JSON.stringify(value, null, 2);
}

function sortRecoverySessions(
  sessions: RecoverySessionSummary[]
): RecoverySessionSummary[] {
  return [...sessions].sort((left, right) => {
    return new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime();
  });
}

function formatDurationSeconds(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return "0s";
  }
  if (value < 60) {
    return `${Math.round(value)}s`;
  }
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;
}

function summarizeReplayTypes(byType: Record<string, number>): string {
  const entries = Object.entries(byType).sort((left, right) => right[1] - left[1]);
  if (entries.length === 0) {
    return "No replay events recorded yet.";
  }
  return entries
    .slice(0, 3)
    .map(([eventType, count]) => `${count} ${getStatusLabel(eventType).toLowerCase()}`)
    .join(" • ");
}

export function OperationsHubPanel({
  token,
  apiKey,
  onResult
}: OperationsHubPanelProps): JSX.Element {
  const recoveryPanelRef = useRef<HTMLElement | null>(null);
  const [processes, setProcesses] = useState<OperationsHubProcessSummary[]>([]);
  const [selectedProcessId, setSelectedProcessId] = useState<string | null>(null);
  const [selectedProcess, setSelectedProcess] = useState<OperationsHubProcessDetail | null>(null);
  const [hubTimestamp, setHubTimestamp] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [textFilter, setTextFilter] = useState("");
  const [loadingHub, setLoadingHub] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [controlInFlight, setControlInFlight] = useState<OperationsHubControlAction | null>(null);
  const [hubError, setHubError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [incompleteSessions, setIncompleteSessions] = useState<RecoverySessionSummary[]>([]);
  const [replaySummaries, setReplaySummaries] = useState<Record<string, RecoveryReplaySummary>>({});
  const [loadingRecovery, setLoadingRecovery] = useState(false);
  const [recoveryError, setRecoveryError] = useState("");
  const [recoveryActionId, setRecoveryActionId] = useState("");
  const [recoveryStatus, setRecoveryStatus] = useState("");
  const [shouldFocusRecoveryPanel] = useState(() => consumeOperationsRecoveryFocusRequest());

  const loadHub = useCallback(async (): Promise<void> => {
    if (!token && !apiKey) {
      return;
    }
    setLoadingHub(true);
    try {
      const result = await fetchOperationsHub(token, apiKey);
      onResult("Operations Hub - Poll", result);
      const hub = asOperationsHubResponse(result.data);
      if (!result.ok || hub === null) {
        setHubError(`Failed to load operations hub (${result.status})`);
        return;
      }
      setHubError("");
      setProcesses(hub.processes);
      setHubTimestamp(hub.timestamp);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown operations hub error";
      setHubError(message);
    } finally {
      setLoadingHub(false);
    }
  }, [apiKey, onResult, token]);

  const loadDetail = useCallback(
    async (processId: string): Promise<void> => {
      if (!token && !apiKey) {
        return;
      }
      setLoadingDetail(true);
      try {
        const result = await fetchProcessDetail(processId, token, apiKey);
        onResult(`Operations Hub - Detail ${processId}`, result);
        const detail = asOperationsHubDetail(result.data);
        if (!result.ok || detail === null) {
          setDetailError(`Failed to load process detail (${result.status})`);
          return;
        }
        setDetailError("");
        setSelectedProcess(detail);
      } catch (error) {
        const message = error instanceof Error ? error.message : "Unknown process detail error";
        setDetailError(message);
      } finally {
        setLoadingDetail(false);
      }
    },
    [apiKey, onResult, token]
  );

  const loadRecovery = useCallback(async (): Promise<void> => {
    if (!token && !apiKey) {
      return;
    }
    setLoadingRecovery(true);
    try {
      const result = await fetchIncompleteSessions(token, apiKey);
      onResult("Operations Hub - Incomplete Sessions", result);
      const sessions = asRecoverySessionSummaries(result.data);
      if (!result.ok || sessions === null) {
        setRecoveryError(`Failed to load recovery sessions (${result.status})`);
        return;
      }

      const orderedSessions = sortRecoverySessions(sessions);
      setIncompleteSessions(orderedSessions);
      setRecoveryError("");

      if (orderedSessions.length === 0) {
        setReplaySummaries({});
        return;
      }

      const summaryResults = await Promise.allSettled(
        orderedSessions.map(async (session) => {
          const replayResult = await fetchReplaySummary(session.session_id, token, apiKey);
          if (!replayResult.ok) {
            return [session.session_id, null] as const;
          }
          return [session.session_id, asRecoveryReplaySummary(replayResult.data)] as const;
        })
      );

      const nextSummaries: Record<string, RecoveryReplaySummary> = {};
      summaryResults.forEach((resultItem) => {
        if (resultItem.status !== "fulfilled") {
          return;
        }
        const [sessionId, summary] = resultItem.value;
        if (summary !== null) {
          nextSummaries[sessionId] = summary;
        }
      });
      setReplaySummaries(nextSummaries);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown session recovery error";
      setRecoveryError(message);
    } finally {
      setLoadingRecovery(false);
    }
  }, [apiKey, onResult, token]);

  useEffect(() => {
    loadHub();
    const interval = setInterval(() => {
      loadHub();
    }, 1500);
    return () => clearInterval(interval);
  }, [loadHub]);

  useEffect(() => {
    void loadRecovery();
  }, [loadRecovery]);

  useEffect(() => {
    if (!shouldFocusRecoveryPanel || recoveryPanelRef.current === null) {
      return;
    }
    recoveryPanelRef.current.scrollIntoView({ block: "start" });
    recoveryPanelRef.current.focus();
  }, [shouldFocusRecoveryPanel]);

  useEffect(() => {
    if (selectedProcessId === null) {
      setSelectedProcess(null);
      setDetailError("");
      return;
    }
    loadDetail(selectedProcessId);
  }, [loadDetail, selectedProcessId]);

  const filteredProcesses = useMemo(() => {
    return filterAndSortProcesses(processes, statusFilter, textFilter);
  }, [processes, statusFilter, textFilter]);

  const timelineSummary = useMemo(() => summarizeOperations(processes), [processes]);
  const timelineItems = useMemo(
    () => buildOperationsTimeline(filteredProcesses, selectedProcess),
    [filteredProcesses, selectedProcess]
  );
  const reviewableOutputPlan = useMemo(
    () => (selectedProcess === null ? null : buildReviewableOutputPlan(selectedProcess)),
    [selectedProcess]
  );

  const availableStatuses = useMemo(() => {
    const values = new Set<string>(["all"]);
    processes.forEach((process) => values.add(process.status.toLowerCase()));
    return [...values];
  }, [processes]);

  async function handleControl(action: OperationsHubControlAction): Promise<void> {
    if (selectedProcess === null) {
      return;
    }
    if (action === "cancel") {
      const confirmed = window.confirm(
        `Cancel process '${selectedProcess.name}' (${selectedProcess.id})?`
      );
      if (!confirmed) {
        return;
      }
    }

    setControlInFlight(action);
    try {
      const result = await controlProcess(selectedProcess.id, action, token, apiKey);
      onResult(`Operations Hub - ${action}`, result);
      if (!result.ok) {
        setDetailError(`Control '${action}' failed (${result.status})`);
        return;
      }
      await Promise.all([loadHub(), loadDetail(selectedProcess.id)]);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown control error";
      setDetailError(message);
    } finally {
      setControlInFlight(null);
    }
  }

  async function handleRecoveryAction(
    action: "resume" | "checkpoint",
    sessionId: string
  ): Promise<void> {
    setRecoveryError("");
    setRecoveryStatus("");
    setRecoveryActionId(`${action}:${sessionId}`);
    try {
      const result =
        action === "resume"
          ? await resumeIncompleteSession(sessionId, token, apiKey)
          : await checkpointSession(sessionId, token, apiKey);
      onResult(`Operations Hub - Session ${getStatusLabel(action)}`, result);
      if (!result.ok) {
        setRecoveryError(`Session ${action} failed (${result.status})`);
        return;
      }
      setRecoveryStatus(
        action === "resume"
          ? `Session ${sessionId} resumed. Watch the live run below.`
          : `Checkpoint saved for session ${sessionId}.`
      );
      await Promise.all([loadRecovery(), loadHub()]);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown recovery action error";
      setRecoveryError(message);
    } finally {
      setRecoveryActionId("");
    }
  }

  return (
    <section className="operations-hub-panel">
      <header className="ops-hub-head">
        <div>
          <p className="ops-hub-eyebrow">Run Timeline</p>
          <h2>See what the agents are doing right now</h2>
          <p>Plain-language progress, attention signals, and safe controls for active work.</p>
        </div>
        <div className="ops-hub-filters">
          <label>
            Status
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              {availableStatuses.map((status) => (
                <option key={status} value={status}>
                  {status === "all" ? "All" : getStatusLabel(status)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Search
            <input
              placeholder="Filter by name, id, or type"
              value={textFilter}
              onChange={(event) => setTextFilter(event.target.value)}
            />
          </label>
        </div>
      </header>
      <section className="ops-timeline-overview" aria-label="Run timeline overview">
        <div className="ops-timeline-summary-card">
          <span>Current state</span>
          <strong>{timelineSummary.primaryMessage}</strong>
          <p>{timelineSummary.nextAction}</p>
        </div>
        <div className="ops-timeline-stats" aria-label="Run counts">
          <div>
            <strong>{timelineSummary.total}</strong>
            <span>Total</span>
          </div>
          <div>
            <strong>{timelineSummary.active}</strong>
            <span>Working</span>
          </div>
          <div>
            <strong>{timelineSummary.attention}</strong>
            <span>Needs attention</span>
          </div>
          <div>
            <strong>{timelineSummary.done}</strong>
            <span>Done</span>
          </div>
        </div>
      </section>
      <section
        id={OPERATIONS_RECOVERY_PANEL_ID}
        ref={recoveryPanelRef}
        className="ops-recovery-panel"
        aria-label="Session recovery"
        tabIndex={-1}
      >
        <div className="ops-recovery-head">
          <div>
            <h3>Session recovery</h3>
            <p>Recover suspended or crashed sessions before starting another host-backed run.</p>
          </div>
          <button type="button" onClick={() => void loadRecovery()} disabled={loadingRecovery}>
            {loadingRecovery ? "Refreshing..." : "Refresh recovery"}
          </button>
        </div>
        {recoveryError ? <p className="ops-hub-error" role="alert">{recoveryError}</p> : null}
        {recoveryStatus ? <p className="review-action-success">{recoveryStatus}</p> : null}
        {loadingRecovery && incompleteSessions.length === 0 ? (
          <p className="ops-hub-loading">Loading recovery candidates...</p>
        ) : null}
        {incompleteSessions.length === 0 && !loadingRecovery ? (
          <p className="ops-hub-empty">No suspended or crashed sessions are waiting for recovery.</p>
        ) : null}
        {incompleteSessions.length > 0 ? (
          <div className="ops-recovery-grid">
            {incompleteSessions.map((session) => {
              const replaySummary = replaySummaries[session.session_id];
              const resumeActionId = `resume:${session.session_id}`;
              const checkpointActionId = `checkpoint:${session.session_id}`;
              const sessionLabel = session.purpose.trim() || session.session_id;
              return (
                <article key={session.session_id} className="ops-recovery-card">
                  <div className="ops-recovery-card-head">
                    <div>
                      <span>Recovery candidate</span>
                      <h4>{sessionLabel}</h4>
                    </div>
                    <span className={`process-status ${getStatusClass(session.status)}`}>
                      {getStatusLabel(session.status)}
                    </span>
                  </div>
                  <p>
                    Last updated {formatTimestamp(session.updated_at)}. {session.tasks_completed} of{" "}
                    {session.task_count} tracked tasks are complete.
                  </p>
                  <dl className="ops-recovery-meta">
                    <div>
                      <dt>Session ID</dt>
                      <dd>{session.session_id}</dd>
                    </div>
                    <div>
                      <dt>Event count</dt>
                      <dd>{session.event_count}</dd>
                    </div>
                    <div>
                      <dt>Started</dt>
                      <dd>{formatTimestamp(session.started_at)}</dd>
                    </div>
                    <div>
                      <dt>Tenant</dt>
                      <dd>{session.tenant_id || "global"}</dd>
                    </div>
                  </dl>
                  <div className="ops-recovery-replay">
                    <strong>Replay summary</strong>
                    {replaySummary ? (
                      <>
                        <p>
                          {replaySummary.total_events} events across {formatDurationSeconds(replaySummary.duration_seconds)}.
                        </p>
                        <p>{summarizeReplayTypes(replaySummary.by_type)}</p>
                        <small>Latest event {formatTimestamp(replaySummary.last_event_at)}</small>
                      </>
                    ) : (
                      <p>No replay summary is available yet for this recovery candidate.</p>
                    )}
                  </div>
                  <div className="ops-recovery-actions">
                    <button
                      type="button"
                      disabled={recoveryActionId !== "" || session.status.toLowerCase() === "active"}
                      onClick={() => void handleRecoveryAction("resume", session.session_id)}
                    >
                      {recoveryActionId === resumeActionId ? "Resuming..." : "Resume session"}
                    </button>
                    <button
                      type="button"
                      disabled={recoveryActionId !== ""}
                      onClick={() => void handleRecoveryAction("checkpoint", session.session_id)}
                    >
                      {recoveryActionId === checkpointActionId ? "Checkpointing..." : "Save checkpoint"}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        ) : null}
      </section>
      <section className="ops-timeline-panel" aria-label="Latest agent activity">
        <div className="ops-timeline-head">
          <div>
            <h3>Latest activity</h3>
            <p>Select a process below to add its step-by-step actions to this timeline.</p>
          </div>
          {hubTimestamp ? <span>Updated {formatTimestamp(hubTimestamp)}</span> : null}
        </div>
        {timelineItems.length === 0 && !loadingHub ? (
          <p className="ops-hub-empty">No agent activity yet.</p>
        ) : null}
        {timelineItems.length > 0 ? (
          <ol className="ops-timeline-list">
            {timelineItems.map((item) => (
              <li key={item.id} className={`ops-timeline-item ops-timeline-item--${item.tone}`}>
                <div className="ops-timeline-marker" aria-hidden="true" />
                <div>
                  <span className="ops-timeline-time">{formatTimestamp(item.timestamp)}</span>
                  <h4>{item.title}</h4>
                  <p>{item.description}</p>
                </div>
              </li>
            ))}
          </ol>
        ) : null}
      </section>
      <div className="ops-hub-content">
        <div className="ops-hub-list">
          {hubError ? <p className="ops-hub-error" role="alert">{hubError}</p> : null}
          {loadingHub && processes.length === 0 ? (
            <p className="ops-hub-loading">Loading processes...</p>
          ) : null}
          {filteredProcesses.length === 0 && !loadingHub ? (
            <p className="ops-hub-empty">No matching processes.</p>
          ) : null}
          {filteredProcesses.map((process) => (
            <article
              key={process.id}
              className={`ops-hub-process-item ${selectedProcessId === process.id ? "selected" : ""}`}
              onClick={() => setSelectedProcessId(process.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setSelectedProcessId(process.id);
                }
              }}
              tabIndex={0}
              role="button"
              aria-pressed={selectedProcessId === process.id}
            >
              <div className="process-item-header">
                <h3>{process.name}</h3>
                <span className={`process-status ${getStatusClass(process.status)}`}>
                  {getStatusLabel(process.status)}
                </span>
              </div>
              <p className="process-item-id">{process.id}</p>
              <p className="process-item-time">Type: {process.type}</p>
              <p className="process-item-time">Started: {formatTimestamp(process.started_at)}</p>
            </article>
          ))}
          {hubTimestamp ? (
            <p className="process-item-time">Last refresh: {formatTimestamp(hubTimestamp)}</p>
          ) : null}
        </div>
        <div className="ops-hub-detail">
          {selectedProcessId === null ? (
            <p className="ops-hub-placeholder">Select a process to view details.</p>
          ) : null}
          {loadingDetail ? <p className="ops-hub-loading">Loading detail...</p> : null}
          {detailError ? <p className="ops-hub-error" role="alert">{detailError}</p> : null}
          {selectedProcess !== null && !loadingDetail ? (
            <div className="process-detail">
              <h3>{selectedProcess.name}</h3>
              <div className="detail-field">
                <span className="detail-label">ID</span>
                <span>{selectedProcess.id}</span>
              </div>
              <div className="detail-field">
                <span className="detail-label">Type</span>
                <span>{selectedProcess.type}</span>
              </div>
              <div className="detail-field">
                <span className="detail-label">Status</span>
                <span className={`process-status ${getStatusClass(selectedProcess.status)}`}>
                  {getStatusLabel(selectedProcess.status)}
                </span>
              </div>
              <div className="detail-field">
                <span className="detail-label">Started</span>
                <span>{formatTimestamp(selectedProcess.started_at)}</span>
              </div>

              {selectedProcess.metadata ? (
                <div className="detail-section">
                  <h4>Metadata</h4>
                  <pre className="detail-metadata">{stringifyMetadata(selectedProcess.metadata)}</pre>
                </div>
              ) : null}

              {reviewableOutputPlan ? (
                <section className="detail-section ops-reviewable-output" aria-label="Reviewable output plan">
                  <h4>Reviewable output</h4>
                  <div className="ops-reviewable-output-summary">
                    <strong>{reviewableOutputPlan.statusLabel}</strong>
                    <p>{reviewableOutputPlan.primaryAction}</p>
                  </div>
                  <dl className="ops-reviewable-output-meta">
                    <div>
                      <dt>Fix path</dt>
                      <dd>{reviewableOutputPlan.fixAction}</dd>
                    </div>
                    <div>
                      <dt>Review gate</dt>
                      <dd>{reviewableOutputPlan.reviewGate}</dd>
                    </div>
                    <div>
                      <dt>Budget</dt>
                      <dd>{reviewableOutputPlan.budgetLabel}</dd>
                    </div>
                  </dl>
                  <ul className="ops-reviewable-output-artifacts">
                    {reviewableOutputPlan.artifacts.map((artifact) => (
                      <li key={artifact}>{artifact}</li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {selectedProcess.actions && selectedProcess.actions.length > 0 ? (
                <div className="detail-section">
                  <h4>Actions</h4>
                  <div className="detail-log">
                    {selectedProcess.actions.map((action) => (
                      <div key={action.step_id} className="log-entry log-info">
                        <span className="log-time">
                          {action.completed_at ? formatTimestamp(action.completed_at) : "In progress"}
                        </span>
                        <span className="log-message">
                          {action.step_id} ({action.action_count} actions)
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="process-controls">
                <h4>Controls</h4>
                <div className="control-buttons">
                  <button
                    disabled={!canPause(selectedProcess) || controlInFlight !== null}
                    onClick={() => handleControl("pause")}
                  >
                    Pause
                  </button>
                  <button
                    disabled={!canResume(selectedProcess) || controlInFlight !== null}
                    onClick={() => handleControl("resume")}
                  >
                    Resume
                  </button>
                  <button
                    className="control-danger"
                    disabled={!canCancel(selectedProcess) || controlInFlight !== null}
                    onClick={() => handleControl("cancel")}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </div>
      <IngestionReviewPanel token={token} apiKey={apiKey} onResult={onResult} />
    </section>
  );
}
