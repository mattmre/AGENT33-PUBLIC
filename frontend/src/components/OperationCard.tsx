import { useEffect, useMemo, useRef, useState } from "react";

import {
  buildWorkflowCreatePresetBody,
  buildWorkflowExecutePreset,
  getImprovementCyclePresetById
} from "../features/improvement-cycle/presets";
import { apiRequest } from "../lib/api";
import {
  connectWorkflowLiveTransport,
  isWorkflowTerminalEvent,
  shouldRefreshWorkflowGraph
} from "../lib/workflowLiveTransport";
import type { WorkflowLiveTransportConnection } from "../types";
import type {
  ApiResult,
  OperationConfig,
  WorkflowExecutionMode,
  WorkflowPresetDefinition
} from "../types";
import { ExplanationView, type ExplanationData } from "./ExplanationView";
import { WorkflowGraph, WorkflowGraphData } from "./WorkflowGraph";

interface OperationCardProps {
  operation: OperationConfig;
  token: string;
  apiKey: string;
  onResult: (label: string, result: ApiResult) => void;
}

function normalizeJsonText(input: string): string {
  if (input.trim() === "") {
    return "{}";
  }
  return input;
}

function parseJsonValue(text: string, emptyFallback: unknown = {}): unknown {
  if (text.trim() === "") {
    return emptyFallback;
  }
  return JSON.parse(text);
}

function parseObjectJson(text: string): Record<string, string> {
  const parsed = JSON.parse(normalizeJsonText(text));
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("Expected a JSON object");
  }
  const result: Record<string, string> = {};
  Object.entries(parsed).forEach(([key, value]) => {
    result[key] = String(value);
  });
  return result;
}

export function OperationCard({
  operation,
  token,
  apiKey,
  onResult
}: OperationCardProps): JSX.Element {
  const initialPathParamsText = useMemo(
    () => JSON.stringify(operation.defaultPathParams ?? {}, null, 2),
    [operation.defaultPathParams]
  );
  const initialQueryText = useMemo(
    () => JSON.stringify(operation.defaultQuery ?? {}, null, 2),
    [operation.defaultQuery]
  );
  const initialHeadersText = useMemo(
    () => JSON.stringify(operation.defaultHeaders ?? {}, null, 2),
    [operation.defaultHeaders]
  );
  const initialBodyText = useMemo(() => operation.defaultBody ?? "", [operation.defaultBody]);

  const isWorkflowExecute = operation.uxHint === "workflow-execute";
  const isWorkflowSchedule = operation.uxHint === "workflow-schedule";
  const isAgentIterative = operation.uxHint === "agent-iterative";
  const isWorkflowGraph = operation.uxHint === "workflow-graph";
  const isHealth = operation.uxHint === "health";
  const isHealthChannels = operation.uxHint === "health-channels";
  const isExplanationHtml = operation.uxHint === "explanation-html";

  const [pathParamsText, setPathParamsText] = useState(
    initialPathParamsText
  );
  const [queryText, setQueryText] = useState(initialQueryText);
  const [headersText, setHeadersText] = useState(initialHeadersText);
  const [bodyText, setBodyText] = useState(initialBodyText);
  const [error, setError] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [result, setResult] = useState<ApiResult | null>(null);
  const availableWorkflowPresets = useMemo(
    () =>
      (operation.presetBinding?.presetIds ?? [])
        .map((presetId) => getImprovementCyclePresetById(presetId))
        .filter((preset): preset is WorkflowPresetDefinition => preset !== undefined),
    [operation.presetBinding]
  );
  const [selectedWorkflowPresetId, setSelectedWorkflowPresetId] = useState("");
  const [executionMode, setExecutionMode] = useState<WorkflowExecutionMode>("single");
  const [repeatCount, setRepeatCount] = useState(3);
  const [repeatIntervalSeconds, setRepeatIntervalSeconds] = useState(0);
  const [scheduleMode, setScheduleMode] = useState<"interval" | "cron">("interval");
  const [scheduleIntervalSeconds, setScheduleIntervalSeconds] = useState(900);
  const [scheduleCronExpr, setScheduleCronExpr] = useState("0 */6 * * *");
  const [iterativePreset, setIterativePreset] = useState<"quick" | "balanced" | "deep">("balanced");
  const [workflowGraphData, setWorkflowGraphData] = useState<WorkflowGraphData | null>(null);
  const [workflowGraphError, setWorkflowGraphError] = useState("");
  const liveTransportRef = useRef<WorkflowLiveTransportConnection | null>(null);

  // UX Overhaul: Hide raw technical inputs by default if this operation has friendly text.
  const [showAdvanced, setShowAdvanced] = useState(!operation.instructionalText);

  useEffect(() => {
    return () => {
      liveTransportRef.current?.close();
      liveTransportRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (availableWorkflowPresets.length === 0) {
      setSelectedWorkflowPresetId("");
      return;
    }

    const presetIds = availableWorkflowPresets.map((preset) => preset.id);
    setSelectedWorkflowPresetId((current) =>
      presetIds.includes(current) ? current : availableWorkflowPresets[0].id
    );
  }, [availableWorkflowPresets]);

  const hasBody = useMemo(
    () => operation.method !== "GET" && operation.method !== "DELETE",
    [operation.method]
  );
  const hasHeaderInputs = useMemo(
    () =>
      Object.keys(operation.defaultHeaders ?? {}).length > 0 ||
      (operation.schemaInfo?.headers?.length ?? 0) > 0,
    [operation.defaultHeaders, operation.schemaInfo?.headers]
  );

  const responseSummary = useMemo(() => {
    if (!result || typeof result.data !== "object" || result.data === null) {
      return "";
    }
    const payload = result.data as Record<string, unknown>;
    if (isAgentIterative && typeof payload.iterations === "number") {
      const toolCalls = typeof payload.tool_calls_made === "number" ? payload.tool_calls_made : 0;
      return `Iterative run completed in ${payload.iterations} iterations with ${toolCalls} tool calls.`;
    }
    if (isWorkflowExecute && typeof payload.executions === "number") {
      return `Workflow autonomous run executed ${payload.executions} iterations.`;
    }
    if (isWorkflowSchedule && typeof payload.job_id === "string") {
      return `Schedule created: ${payload.job_id}`;
    }
    if (isWorkflowGraph && typeof payload.workflow_id === "string") {
      const nodeCount = Array.isArray(payload.nodes) ? payload.nodes.length : 0;
      const edgeCount = Array.isArray(payload.edges) ? payload.edges.length : 0;
      return `Graph loaded: ${nodeCount} nodes, ${edgeCount} edges`;
    }
    return "";
  }, [isAgentIterative, isWorkflowExecute, isWorkflowSchedule, isWorkflowGraph, result]);

  function formatObjectEditor(value: string, setter: (text: string) => void, label: string): void {
    try {
      setter(JSON.stringify(parseObjectJson(value), null, 2));
      setError("");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Invalid JSON object";
      setError(`${label}: ${message}`);
    }
  }

  function formatBodyEditor(): void {
    try {
      const parsed = parseJsonValue(bodyText, {});
      setBodyText(JSON.stringify(parsed, null, 2));
      setError("");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Invalid JSON";
      setError(`Request Body: ${message}`);
    }
  }

  function applyWorkflowPreset(): void {
    if (!selectedWorkflowPresetId) {
      return;
    }

    if (operation.id === "workflows-create") {
      setBodyText(buildWorkflowCreatePresetBody(selectedWorkflowPresetId));
      setError("");
      return;
    }

    if (operation.id === "workflows-execute") {
      const preset = buildWorkflowExecutePreset(selectedWorkflowPresetId);
      setPathParamsText(JSON.stringify(preset.pathParams, null, 2));
      setBodyText(JSON.stringify(preset.body, null, 2));
      setExecutionMode(preset.executionMode ?? "single");
      setError("");
    }
  }

  function prepareGuidedBody(): string {
    const parsed = parseJsonValue(bodyText, {});
    if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
      throw new Error("Guided mode requires a JSON object body.");
    }
    const nextBody = { ...(parsed as Record<string, unknown>) };

    if (isWorkflowExecute) {
      delete nextBody.repeat_count;
      delete nextBody.repeat_interval_seconds;
      delete nextBody.autonomous;
      if (executionMode !== "single") {
        nextBody.repeat_count = repeatCount;
        if (repeatIntervalSeconds > 0) {
          nextBody.repeat_interval_seconds = repeatIntervalSeconds;
        }
        nextBody.autonomous = executionMode === "autonomous";
      }
    }

    if (isWorkflowSchedule) {
      if (scheduleMode === "cron") {
        nextBody.cron_expr = scheduleCronExpr;
        delete nextBody.interval_seconds;
      } else {
        nextBody.interval_seconds = scheduleIntervalSeconds;
        delete nextBody.cron_expr;
      }
      if (
        typeof nextBody.inputs !== "object" ||
        nextBody.inputs === null ||
        Array.isArray(nextBody.inputs)
      ) {
        nextBody.inputs = {};
      }
    }

    if (isAgentIterative) {
      const preset =
        iterativePreset === "quick"
          ? { max_iterations: 4, max_tool_calls_per_iteration: 2, enable_double_confirmation: false }
          : iterativePreset === "deep"
            ? { max_iterations: 16, max_tool_calls_per_iteration: 6, enable_double_confirmation: true }
            : { max_iterations: 8, max_tool_calls_per_iteration: 4, enable_double_confirmation: true };
      Object.assign(nextBody, preset);
    }

    return JSON.stringify(nextBody, null, 2);
  }

  function renderGuidedControls(): JSX.Element | null {
    const selectedWorkflowPreset = selectedWorkflowPresetId
      ? getImprovementCyclePresetById(selectedWorkflowPresetId)
      : undefined;

    if (!hasBody && !selectedWorkflowPreset) {
      return null;
    }
    if (selectedWorkflowPreset) {
      return (
        <>
          <section className="helper-panel">
            <h4>Workflow Preset</h4>
            {operation.presetBinding?.helpText ? <p>{operation.presetBinding.helpText}</p> : null}
            <div className="helper-grid">
              <label>
                Preset
                <select
                  aria-label="Workflow Preset"
                  value={selectedWorkflowPresetId}
                  onChange={(e) => setSelectedWorkflowPresetId(e.target.value)}
                >
                  {availableWorkflowPresets.map((preset) => (
                    <option key={preset.id} value={preset.id}>
                      {preset.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Workflow Name
                <input value={selectedWorkflowPreset.workflowName} readOnly />
              </label>
            </div>
            <p>{selectedWorkflowPreset.description}</p>
            <p className="operation-note">
              Source of truth: <code>{selectedWorkflowPreset.sourcePath}</code>
            </p>
            <button type="button" onClick={applyWorkflowPreset}>
              {operation.presetBinding?.applyLabel ?? "Apply preset"}
            </button>
          </section>
          {hasBody ? renderExecutionStrategyControls() : null}
        </>
      );
    }
    return renderExecutionStrategyControls();
  }

  function renderExecutionStrategyControls(): JSX.Element | null {
    if (!hasBody) {
      return null;
    }
    if (isWorkflowExecute) {
      return (
        <section className="helper-panel">
          <h4>Execution Controls</h4>
          <div className="helper-grid">
            <label>
              Mode
              <select
                value={executionMode}
                onChange={(e) => setExecutionMode(e.target.value as WorkflowExecutionMode)}
              >
                <option value="single">Single</option>
                <option value="repeat">Repeat</option>
                <option value="autonomous">Autonomous</option>
              </select>
            </label>
            <label>
              Repeat Count
              <input
                type="number"
                min={1}
                max={100}
                value={repeatCount}
                onChange={(e) => setRepeatCount(Math.max(1, Number(e.target.value) || 1))}
              />
            </label>
            <label>
              Repeat Interval (seconds)
              <input
                type="number"
                min={0}
                max={3600}
                value={repeatIntervalSeconds}
                onChange={(e) =>
                  setRepeatIntervalSeconds(Math.max(0, Number(e.target.value) || 0))
                }
              />
            </label>
          </div>
        </section>
      );
    }
    if (isWorkflowSchedule) {
      return (
        <section className="helper-panel">
          <h4>Schedule Controls</h4>
          <div className="helper-grid">
            <label>
              Schedule Type
              <select
                value={scheduleMode}
                onChange={(e) => setScheduleMode(e.target.value as "interval" | "cron")}
              >
                <option value="interval">Interval</option>
                <option value="cron">Cron</option>
              </select>
            </label>
            {scheduleMode === "interval" ? (
              <label>
                Interval (seconds)
                <input
                  type="number"
                  min={1}
                  max={86400}
                  value={scheduleIntervalSeconds}
                  onChange={(e) =>
                    setScheduleIntervalSeconds(Math.max(1, Number(e.target.value) || 1))
                  }
                />
              </label>
            ) : (
              <label>
                Cron (minute hour day month weekday)
                <input
                  value={scheduleCronExpr}
                  onChange={(e) => setScheduleCronExpr(e.target.value)}
                  placeholder="0 */6 * * *"
                />
              </label>
            )}
          </div>
        </section>
      );
    }
    if (isAgentIterative) {
      return (
        <section className="helper-panel">
          <h4>Iterative Strategy</h4>
          <div className="helper-grid">
            <label>
              Preset
              <select
                value={iterativePreset}
                onChange={(e) =>
                  setIterativePreset(e.target.value as "quick" | "balanced" | "deep")
                }
              >
                <option value="quick">Quick</option>
                <option value="balanced">Balanced</option>
                <option value="deep">Deep</option>
              </select>
            </label>
          </div>
        </section>
      );
    }
    return null;
  }

  function renderHealthResults(): JSX.Element | null {
    if (!result || !result.ok || !result.data) return null;

    if (isHealth) {
      const payload = result.data as Record<string, unknown>;
      if (!payload.services) return null;
      return (
        <ul className="health-checklist">
          {Object.entries(payload.services as Record<string, string>).map(([service, status]) => (
            <li key={service} className={`health-item status-${String(status).toLowerCase()}`}>
              <span className="health-indicator" aria-hidden="true">
                {status === "ok" || status === "configured" ? "🟢" : status === "degraded" ? "🟡" : "🔴"}
              </span>
              <span className="health-name">{service}</span>
              <span className="health-state">{String(status).toUpperCase()}</span>
            </li>
          ))}
        </ul>
      );
    }

    if (isHealthChannels) {
      const payload = result.data as Record<string, unknown>;
      if (!payload.channels) return null;
      return (
        <ul className="health-checklist">
          {Object.entries(payload.channels as Record<string, Record<string, string>>).map(([platform, data]) => (
            <li key={platform} className={`health-item status-${data.status?.toLowerCase()}`}>
              <span className="health-indicator" aria-hidden="true">
                {data.status === "ok" ? "🟢" : "🔴"}
              </span>
              <span className="health-name">{platform}</span>
              <span className="health-state">{data.status?.toUpperCase() || "UNKNOWN"}</span>
            </li>
          ))}
        </ul>
      );
    }
    return null;
  }

  function stopWorkflowLiveTransport(): void {
    liveTransportRef.current?.close();
    liveTransportRef.current = null;
  }

  async function loadWorkflowGraph(workflowId: string, runId: string): Promise<void> {
    const graphResponse = await apiRequest({
      method: "GET",
      path: "/v1/visualizations/workflows/{workflow_id}/graph",
      token,
      apiKey,
      pathParams: { workflow_id: workflowId },
      query: { run_id: runId }
    });

    if (!graphResponse.ok || typeof graphResponse.data !== "object" || graphResponse.data === null) {
      throw new Error("Failed to load workflow graph");
    }

    setWorkflowGraphData(graphResponse.data as WorkflowGraphData);
    setWorkflowGraphError("");
  }

  async function runOperation(): Promise<void> {
    setError("");
    setWorkflowGraphError("");
    setIsRunning(true);
    try {
      const pathParams = parseObjectJson(pathParamsText);
      const query = parseObjectJson(queryText);
      const requestHeaders = parseObjectJson(headersText);
      let requestBody = bodyText;
      const shouldUseWorkflowLive = isWorkflowExecute && executionMode === "single";
      const workflowName = shouldUseWorkflowLive ? pathParams.name : undefined;
      const clientRunId =
        shouldUseWorkflowLive && typeof workflowName === "string" && workflowName.trim() !== ""
          ? createClientRunId()
          : null;
      if (isWorkflowExecute) {
        stopWorkflowLiveTransport();
        if (shouldUseWorkflowLive) {
          setWorkflowGraphData(null);
        }
      }
      if (hasBody) {
        const guidedBody = operation.uxHint ? prepareGuidedBody() : requestBody;
        requestBody = guidedBody;
        const parsedBody =
          requestBody.trim() === ""
            ? {}
            : (JSON.parse(requestBody) as Record<string, unknown>);
        if (clientRunId) {
          parsedBody.run_id = clientRunId;
        }
        requestBody = requestBody.trim() === "" && clientRunId === null
          ? requestBody
          : JSON.stringify(parsedBody);
        if (operation.uxHint) {
          setBodyText(guidedBody);
        }
      }
      if (!shouldUseWorkflowLive) {
        setWorkflowGraphData(null);
      }
      const res = await apiRequest({
        method: operation.method,
        path: operation.path,
        token,
        apiKey,
        pathParams,
        query,
        headers: requestHeaders,
        body: hasBody ? requestBody : undefined
      });
      setResult(res);
      onResult(operation.title, res);
      if (shouldUseWorkflowLive && res.ok && clientRunId && typeof workflowName === "string") {
        const responsePayload =
          typeof res.data === "object" && res.data !== null
            ? (res.data as Record<string, unknown>)
            : null;
        const liveRunId =
          responsePayload && typeof responsePayload.run_id === "string"
            ? responsePayload.run_id
            : clientRunId;

        await loadWorkflowGraph(workflowName, liveRunId);
        liveTransportRef.current = connectWorkflowLiveTransport({
          runId: liveRunId,
          token,
          apiKey,
          onEvent: async (event) => {
            if (!shouldRefreshWorkflowGraph(event)) {
              return;
            }
            try {
              await loadWorkflowGraph(workflowName, liveRunId);
            } catch (graphError) {
              const message =
                graphError instanceof Error ? graphError.message : "Failed to refresh workflow graph";
              setWorkflowGraphError(message);
            } finally {
              if (isWorkflowTerminalEvent(event)) {
                stopWorkflowLiveTransport();
              }
            }
          },
          onError: (transportError) => {
            setWorkflowGraphError(transportError.message);
          }
        });
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Unknown error while running operation";
      setError(message);
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <article className="operation-card">
      <header className="operation-head">
        <span className={`method-badge method-${operation.method.toLowerCase()}`}>
          {operation.method}
        </span>
        <div style={{ flex: 1 }}>
          <h3>{operation.title}</h3>
          <p>{operation.description}</p>
        </div>
        {operation.instructionalText && (
          <button
            className={`advanced-toggle-btn ${showAdvanced ? "active" : ""}`}
            onClick={() => setShowAdvanced(!showAdvanced)}
            title="Toggle Raw JSON Editor"
          >
            {showAdvanced ? "Hide Advanced" : "Advanced"}
          </button>
        )}
      </header>

      {operation.instructionalText && (
        <div className="instructional-text">
          <p>{operation.instructionalText}</p>
        </div>
      )}

      {showAdvanced ? (
        <div className="raw-operation-warning" role="status">
          <strong>Raw endpoint mode</strong>
          <span>
            Review path params, query params, and JSON body before running. Prefer guided screens for
            routine workflows and settings changes.
          </span>
        </div>
      ) : null}

      {showAdvanced && operation.schemaInfo && (
        <section className="schema-info-panel">
          <h4>Operation Schema</h4>
          {operation.schemaInfo.parameters && (
            <div className="schema-table-container">
              <table className="schema-table">
                <thead>
                  <tr>
                    <th>Parameter</th>
                    <th>Type</th>
                    <th>Required</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {operation.schemaInfo.parameters.map((p) => (
                    <tr key={p.name}>
                      <td><code>{p.name}</code></td>
                      <td><span className="schema-type">{p.type}</span></td>
                      <td>{p.required ? <span className="req-badge req-true">Yes</span> : <span className="req-badge req-false">No</span>}</td>
                      <td>{p.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {operation.schemaInfo.headers && (
            <div className="schema-table-container">
              <h5>Headers</h5>
              <table className="schema-table">
                <thead>
                  <tr>
                    <th>Header</th>
                    <th>Type</th>
                    <th>Required</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {operation.schemaInfo.headers.map((header) => (
                    <tr key={header.name}>
                      <td><code>{header.name}</code></td>
                      <td><span className="schema-type">{header.type}</span></td>
                      <td>{header.required ? <span className="req-badge req-true">Yes</span> : <span className="req-badge req-false">No</span>}</td>
                      <td>{header.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {operation.schemaInfo.body && (
            <div className="schema-body-info">
              <h5>Body Payload</h5>
              <p>{operation.schemaInfo.body.description}</p>
              <h6>Expected Format:</h6>
              <pre><code>{operation.schemaInfo.body.example}</code></pre>
            </div>
          )}
        </section>
      )}

      {showAdvanced && (
        <p className="operation-path">{operation.path}</p>
      )}

      {showAdvanced && (
        <div className="operation-grid">
          <label>
            Path Params (JSON)
            <textarea
              value={pathParamsText}
              onChange={(e) => setPathParamsText(e.target.value)}
              rows={4}
            />
            <div className="json-tools">
              <button type="button" onClick={() => formatObjectEditor(pathParamsText, setPathParamsText, "Path Params")}>
                Format
              </button>
              <button type="button" onClick={() => setPathParamsText(initialPathParamsText)}>
                Reset
              </button>
            </div>
          </label>
          <label>
            Query Params (JSON)
            <textarea value={queryText} onChange={(e) => setQueryText(e.target.value)} rows={4} />
            <div className="json-tools">
              <button type="button" onClick={() => formatObjectEditor(queryText, setQueryText, "Query Params")}>
                Format
              </button>
              <button type="button" onClick={() => setQueryText(initialQueryText)}>
                Reset
              </button>
            </div>
          </label>
          {hasHeaderInputs ? (
            <label>
              Headers (JSON)
              <textarea
                value={headersText}
                onChange={(e) => setHeadersText(e.target.value)}
                rows={4}
              />
              <div className="json-tools">
                <button
                  type="button"
                  onClick={() => formatObjectEditor(headersText, setHeadersText, "Headers")}
                >
                  Format
                </button>
                <button type="button" onClick={() => setHeadersText(initialHeadersText)}>
                  Reset
                </button>
              </div>
            </label>
          ) : null}
        </div>
      )}

      {renderGuidedControls()}

      {hasBody && showAdvanced ? (
        <label>
          Request Body (JSON)
          <textarea value={bodyText} onChange={(e) => setBodyText(e.target.value)} rows={8} />
          <div className="json-tools">
            <button type="button" onClick={formatBodyEditor}>
              Format
            </button>
            <button type="button" onClick={() => setBodyText(initialBodyText)}>
              Reset
            </button>
          </div>
        </label>
      ) : null}
      <div className="operation-actions">
        <button onClick={runOperation} disabled={isRunning} aria-label={`Run ${operation.title}`}>
          {isRunning ? "Running..." : "Run"}
        </button>
        {result ? (
          <span className={result.ok ? "status-ok" : "status-error"}>
            <span className="sr-only">{result.ok ? "Success" : "Error"}:</span>
            {result.status} in {result.durationMs}ms
          </span>
        ) : null}
      </div>
      {responseSummary ? <p className="operation-note">{responseSummary}</p> : null}
      {error ? <pre className="error-box" role="alert">{error}</pre> : null}
      {workflowGraphError ? <pre className="error-box" role="alert">{workflowGraphError}</pre> : null}
      {((isWorkflowGraph && result && result.ok) || (isWorkflowExecute && workflowGraphData)) ? (
        <WorkflowGraph
          data={
            (isWorkflowGraph && result?.ok
              ? (result.data as WorkflowGraphData)
              : workflowGraphData) as WorkflowGraphData
          }
        />
      ) : null}
      {(isHealth || isHealthChannels) && result ? (
        renderHealthResults()
      ) : null}
      {isExplanationHtml && result && result.ok ? (
        <ExplanationView explanation={result.data as ExplanationData} />
      ) : null}
      {result && !isWorkflowGraph && !isHealth && !isHealthChannels && !isExplanationHtml ? (
        <pre className="response-box">{JSON.stringify(result.data, null, 2)}</pre>
      ) : null}
    </article>
  );
}

function createClientRunId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `workflow-run-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
