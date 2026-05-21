import { useCallback, useEffect, useRef, useState } from "react";
import type { WorkflowLiveEvent, WorkflowLiveTransportConnection } from "../../../types";
import {
  connectWorkflowLiveTransport,
  isWorkflowTerminalEvent,
  shouldRefreshWorkflowGraph
} from "../../../lib/workflowLiveTransport";
import { EventLog } from "../EventLog";

export interface WorkflowRunState {
  runId: string;
  workflowName: string;
  status: "pending" | "running" | "completed" | "failed";
  startedAt: number;
  completedAt?: number;
  durationMs?: number;
  stepStatuses: Record<string, string>;
  events: WorkflowLiveEvent[];
  result?: Record<string, unknown>;
  error?: string;
}

interface ExecuteTrackStepProps {
  runState: WorkflowRunState | null;
  token: string;
  apiKey: string;
  onRunStateChange: (state: WorkflowRunState) => void;
  onComplete: () => void;
}

export function ExecuteTrackStep({
  runState,
  token,
  apiKey,
  onRunStateChange,
  onComplete
}: ExecuteTrackStepProps): JSX.Element {
  const connectionRef = useRef<WorkflowLiveTransportConnection | null>(null);
  const [connectionError, setConnectionError] = useState<string>("");

  const handleEvent = useCallback(
    (event: WorkflowLiveEvent) => {
      if (!runState) return;

      const updatedEvents = [...runState.events, event];
      const updatedStepStatuses = { ...runState.stepStatuses };

      if (event.step_id && event.data?.status) {
        updatedStepStatuses[event.step_id] = String(event.data.status);
      }

      if (event.type === "sync" && event.data) {
        const syncStatuses = event.data.step_statuses;
        if (typeof syncStatuses === "object" && syncStatuses !== null) {
          Object.assign(updatedStepStatuses, syncStatuses);
        }
      }

      let newStatus = runState.status;
      let completedAt = runState.completedAt;
      let durationMs = runState.durationMs;
      let result = runState.result;
      let error = runState.error;

      if (event.type === "step_started" && newStatus === "pending") {
        newStatus = "running";
      }
      if (event.type === "workflow_completed") {
        newStatus = "completed";
        completedAt = Date.now();
        durationMs = completedAt - runState.startedAt;
        result = (event.data as Record<string, unknown>) ?? undefined;
      }
      if (event.type === "workflow_failed") {
        newStatus = "failed";
        completedAt = Date.now();
        durationMs = completedAt - runState.startedAt;
        error = event.data?.error ? String(event.data.error) : "Workflow failed";
      }

      const updated: WorkflowRunState = {
        ...runState,
        status: newStatus,
        stepStatuses: updatedStepStatuses,
        events: updatedEvents,
        completedAt,
        durationMs,
        result,
        error
      };

      onRunStateChange(updated);

      if (isWorkflowTerminalEvent(event)) {
        connectionRef.current?.close();
        connectionRef.current = null;
        onComplete();
      }
    },
    [runState, onRunStateChange, onComplete]
  );

  useEffect(() => {
    if (!runState || runState.status === "completed" || runState.status === "failed") {
      return;
    }

    if (connectionRef.current) return;

    const conn = connectWorkflowLiveTransport({
      runId: runState.runId,
      token: token || undefined,
      apiKey: apiKey || undefined,
      onEvent: handleEvent,
      onError: (err) => setConnectionError(err.message)
    });
    connectionRef.current = conn;

    return () => {
      conn.close();
      connectionRef.current = null;
    };
  }, [runState?.runId]);

  const handleClose = useCallback(() => {
    connectionRef.current?.close();
    connectionRef.current = null;
  }, []);

  if (!runState) {
    return (
      <section className="wizard-step-content">
        <h3>Execute and Track</h3>
        <p className="wizard-muted">No workflow execution in progress.</p>
      </section>
    );
  }

  const elapsed = runState.durationMs ?? (Date.now() - runState.startedAt);
  const elapsedSeconds = Math.round(elapsed / 1000);

  return (
    <section className="wizard-step-content">
      <h3>Execute and Track</h3>

      <div className="wizard-execution-header">
        <span>
          Run: <strong>{runState.runId}</strong>
        </span>
        <span>
          Workflow: <strong>{runState.workflowName}</strong>
        </span>
        <span>
          Status: <strong data-testid="run-status">{runState.status}</strong>
        </span>
        <span>
          Elapsed: <strong>{elapsedSeconds}s</strong>
        </span>
      </div>

      {connectionError && (
        <p className="wizard-error">Connection error: {connectionError}</p>
      )}

      <div className="wizard-step-statuses">
        <h4>Step Progress</h4>
        {Object.keys(runState.stepStatuses).length === 0 ? (
          <p className="wizard-muted">Waiting for step events...</p>
        ) : (
          <table className="wizard-table">
            <thead>
              <tr>
                <th>Step</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(runState.stepStatuses).map(([stepId, status]) => (
                <tr key={stepId}>
                  <td>{stepId}</td>
                  <td>{status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {runState.error && (
        <div className="wizard-error-detail">
          <h4>Error</h4>
          <pre>{runState.error}</pre>
        </div>
      )}

      <EventLog events={runState.events} />

      <div className="wizard-actions">
        <button onClick={handleClose}>
          {runState.status === "completed" || runState.status === "failed"
            ? "Close"
            : "Disconnect"}
        </button>
      </div>
    </section>
  );
}
