/**
 * AgentBuilderPage: visual agent definition builder with capability toggles,
 * live system-prompt preview, inline testing, and JSON export.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { getRuntimeConfig } from "../../lib/api";
import type { AgentBuilderState, AgentDefinitionExport } from "../../types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const AGENT_ROLES = [
  "orchestrator",
  "director",
  "implementer",
  "qa",
  "reviewer",
  "researcher",
  "documentation",
  "security",
  "architect",
  "test-engineer",
] as const;

interface CapabilityToggle {
  key: keyof Pick<
    AgentBuilderState,
    "canReadFiles" | "canWriteFiles" | "canSearchWeb" | "canRunCode" | "canCallAPIs"
  >;
  label: string;
  capability: string;
}

interface AgentTemplate {
  id: string;
  title: string;
  audience: string;
  description: string;
  name: string;
  role: (typeof AGENT_ROLES)[number];
  capabilities: Array<CapabilityToggle["key"]>;
  providerHint: string;
  recommendedSkills: string[];
  recommendedTools: string[];
}

const CAPABILITY_TOGGLES: CapabilityToggle[] = [
  { key: "canReadFiles", label: "Can it read your files?", capability: "file-read" },
  { key: "canWriteFiles", label: "Can it write to your files?", capability: "file-write" },
  { key: "canSearchWeb", label: "Can it search the web?", capability: "web-search" },
  { key: "canRunCode", label: "Can it run code?", capability: "code-execution" },
  { key: "canCallAPIs", label: "Can it connect to external services?", capability: "api-calls" },
];

const AGENT_TEMPLATES: AgentTemplate[] = [
  {
    id: "research-analyst",
    title: "Research analyst",
    audience: "Founder or product owner",
    description: "Finds sources, compares options, and returns a cited decision brief.",
    name: "research-analyst",
    role: "researcher",
    capabilities: ["canReadFiles", "canSearchWeb"],
    providerHint: "Use a long-context cloud model or a strong local research model.",
    recommendedSkills: ["web research", "source synthesis", "competitive analysis"],
    recommendedTools: ["web search", "document reader", "citation tracker"]
  },
  {
    id: "safe-implementer",
    title: "Safe implementer",
    audience: "Developer or operator",
    description: "Makes scoped code changes with review gates before saving work.",
    name: "safe-implementer",
    role: "implementer",
    capabilities: ["canReadFiles", "canWriteFiles", "canRunCode"],
    providerHint: "Bind to your coding model after Models shows a successful connection.",
    recommendedSkills: ["repo analysis", "test planning", "patch authoring"],
    recommendedTools: ["file read", "file edit", "test runner"]
  },
  {
    id: "qa-reviewer",
    title: "QA reviewer",
    audience: "QA lead or maintainer",
    description: "Reviews features, proposes test coverage, and checks release risk.",
    name: "qa-reviewer",
    role: "qa",
    capabilities: ["canReadFiles", "canRunCode"],
    providerHint: "Use a coding model with reliable test reasoning.",
    recommendedSkills: ["test generation", "regression review", "release readiness"],
    recommendedTools: ["file read", "test runner", "artifact viewer"]
  }
];

const NAME_PATTERN = /^[a-z][a-z0-9-]*$/;
const APPROVAL_SENSITIVE_KEYS: Array<
  keyof Pick<
    AgentBuilderState,
    | "name"
    | "description"
    | "role"
    | "version"
    | "canReadFiles"
    | "canWriteFiles"
    | "canSearchWeb"
    | "canRunCode"
    | "canCallAPIs"
  >
> = [
  "name",
  "description",
  "role",
  "version",
  "canReadFiles",
  "canWriteFiles",
  "canSearchWeb",
  "canRunCode",
  "canCallAPIs",
];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface AgentBuilderPageProps {
  apiUrl?: string;
  token: string | null;
  apiKey?: string | null;
}

interface RouteApprovalRequirement {
  approvalId: string;
  approvalHeader: string;
  actionLabel: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildCapabilities(state: AgentBuilderState): string[] {
  const caps: string[] = [];
  for (const toggle of CAPABILITY_TOGGLES) {
    if (state[toggle.key]) {
      caps.push(toggle.capability);
    }
  }
  return caps;
}

function buildGovernance(state: AgentBuilderState) {
  const network = state.canCallAPIs
    ? "external"
    : state.canSearchWeb
      ? "external-read"
      : "none";
  const approvalRequired = [
    state.canWriteFiles ? "file-write" : null,
    state.canRunCode ? "code-execution" : null,
    state.canCallAPIs ? "api-calls" : null,
  ].filter((value): value is string => value !== null);
  return {
    scope: "workspace",
    network,
    approval_required: approvalRequired,
    tool_policies: Object.fromEntries(
      approvalRequired.map((capability) => [capability, "review-required"]),
    ) as Record<string, string>,
  };
}

function buildDefinitionPayload(state: AgentBuilderState) {
  return {
    name: state.name,
    version: state.version || "1.0.0",
    role: state.role,
    description: state.description,
    capabilities: buildCapabilities(state),
    inputs: {},
    outputs: {},
    governance: buildGovernance(state),
    autonomy_level:
      state.canWriteFiles || state.canRunCode ? "supervised" : "read-only",
  };
}

function buildExport(state: AgentBuilderState): AgentDefinitionExport {
  return {
    name: state.name,
    version: state.version || "1.0.0",
    role: state.role,
    description: state.description,
    capabilities: buildCapabilities(state),
    governance: buildGovernance(state),
    autonomy_level:
      state.canWriteFiles || state.canRunCode ? "supervised" : "read-only",
  };
}

function authHeaders(
  token: string | null,
  apiKey: string | null | undefined,
  approvalToken?: string | null,
): Record<string, string> {
  const h: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (token) h.Authorization = `Bearer ${token}`;
  if (apiKey) h["X-API-Key"] = apiKey;
  if (approvalToken?.trim()) {
    h["X-Agent33-Approval-Token"] = approvalToken.trim();
  }
  return h;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function asRouteApprovalRequirement(
  value: unknown,
  actionLabel: string,
): RouteApprovalRequirement | null {
  if (!isObject(value) || typeof value.approval_id !== "string") {
    return null;
  }
  const approvalHeader =
    typeof value.approval_header === "string" && value.approval_header.trim() !== ""
      ? value.approval_header
      : "X-Agent33-Approval-Token";
  return {
    approvalId: value.approval_id,
    approvalHeader,
    actionLabel,
  };
}

function formatResponseDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim() !== "") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        isObject(item) && typeof item.msg === "string" ? item.msg : JSON.stringify(item),
      )
      .join("; ");
  }
  if (detail !== null && detail !== undefined) {
    return JSON.stringify(detail);
  }
  return fallback;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const INITIAL_STATE: AgentBuilderState = {
  name: "",
  description: "",
  role: "implementer",
  version: "1.0.0",
  canReadFiles: false,
  canWriteFiles: false,
  canSearchWeb: false,
  canRunCode: false,
  canCallAPIs: false,
  systemPromptPreview: "",
  isPreviewLoading: false,
  testMessage: "",
  testResponse: "",
  isTestLoading: false,
};

export default function AgentBuilderPage({
  token,
  apiKey,
}: AgentBuilderPageProps): JSX.Element {
  const [state, setState] = useState<AgentBuilderState>({ ...INITIAL_STATE });
  const [nameError, setNameError] = useState("");
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [saveMessage, setSaveMessage] = useState("");
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [approvalToken, setApprovalToken] = useState("");
  const [pendingRouteApproval, setPendingRouteApproval] = useState<RouteApprovalRequirement | null>(null);

  const previewTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { API_BASE_URL } = getRuntimeConfig();

  // -- Name validation -------------------------------------------------------

  const validateName = useCallback((name: string) => {
    if (!name) {
      setNameError("");
      return;
    }
    if (!NAME_PATTERN.test(name)) {
      setNameError("Must start with a lowercase letter, only a-z, 0-9, and hyphens");
    } else if (name.length < 2) {
      setNameError("Must be at least 2 characters");
    } else {
      setNameError("");
    }
  }, []);

  // -- Live prompt preview (debounced) ----------------------------------------

  const fetchPreview = useCallback(
    async (currentState: AgentBuilderState) => {
      if (!currentState.name || !NAME_PATTERN.test(currentState.name)) return;

      setState((s) => ({ ...s, isPreviewLoading: true }));
      try {
        const payload = buildDefinitionPayload(currentState);
        const resp = await fetch(`${API_BASE_URL}/v1/agents/preview-prompt`, {
          method: "POST",
          headers: authHeaders(token, apiKey),
          body: JSON.stringify(payload),
        });
        if (resp.ok) {
          const data = await resp.json();
          setState((s) => ({
            ...s,
            systemPromptPreview: data.system_prompt ?? "",
            isPreviewLoading: false,
          }));
        } else {
          setState((s) => ({ ...s, isPreviewLoading: false }));
        }
      } catch {
        setState((s) => ({ ...s, isPreviewLoading: false }));
      }
    },
    [API_BASE_URL, token, apiKey],
  );

  useEffect(() => {
    if (previewTimerRef.current) clearTimeout(previewTimerRef.current);
    previewTimerRef.current = setTimeout(() => {
      void fetchPreview(state);
    }, 500);
    return () => {
      if (previewTimerRef.current) clearTimeout(previewTimerRef.current);
    };
  }, [
    state.name,
    state.description,
    state.role,
    state.canReadFiles,
    state.canWriteFiles,
    state.canSearchWeb,
    state.canRunCode,
    state.canCallAPIs,
    fetchPreview,
  ]);

  // -- State updaters --------------------------------------------------------

  function updateField<K extends keyof AgentBuilderState>(
    key: K,
    value: AgentBuilderState[K],
  ) {
    setState((prev) => ({ ...prev, [key]: value }));
    if (key === "name") validateName(value as string);
    if (APPROVAL_SENSITIVE_KEYS.includes(key as (typeof APPROVAL_SENSITIVE_KEYS)[number])) {
      setApprovalToken("");
      setPendingRouteApproval(null);
    }
  }

  function applyTemplate(template: AgentTemplate) {
    const nextState: AgentBuilderState = {
      ...state,
      name: template.name,
      description: template.description,
      role: template.role,
      canReadFiles: template.capabilities.includes("canReadFiles"),
      canWriteFiles: template.capabilities.includes("canWriteFiles"),
      canSearchWeb: template.capabilities.includes("canSearchWeb"),
      canRunCode: template.capabilities.includes("canRunCode"),
      canCallAPIs: template.capabilities.includes("canCallAPIs"),
    };
    setSelectedTemplateId(template.id);
    setState(nextState);
    validateName(nextState.name);
  }

  // -- Save agent ------------------------------------------------------------

  async function handleSave() {
    if (!state.name || nameError) return;
    setSaveStatus("saving");
    setSaveMessage("");
    setValidationErrors([]);

    const payload = buildDefinitionPayload(state);
    const mutationHeaders = authHeaders(token, apiKey, approvalToken);
    const lookupHeaders = authHeaders(token, apiKey);
    const agentPath = `${API_BASE_URL}/v1/agents/${encodeURIComponent(state.name)}`;

    async function submitMutation(options: {
      actionLabel: string;
      method: "POST" | "PUT";
      successMessage: string;
      url: string;
    }): Promise<void> {
      const resp = await fetch(options.url, {
        method: options.method,
        headers: mutationHeaders,
        body: JSON.stringify(payload),
      });
      const errData = await resp.json().catch(() => null);
      const detail = isObject(errData) ? errData.detail : null;

      if (resp.ok) {
        setSaveStatus("saved");
        setSaveMessage(options.successMessage);
        setValidationErrors([]);
        setApprovalToken("");
        setPendingRouteApproval(null);
        return;
      }

      if (resp.status === 428) {
        const requirement = asRouteApprovalRequirement(detail, options.actionLabel);
        if (requirement !== null) {
          setPendingRouteApproval(requirement);
          setSaveStatus("error");
          setSaveMessage(
            `Approval required before ${options.actionLabel}. Approve ${requirement.approvalId} in Safety Center, issue a short-lived token, paste it below, then save again.`,
          );
          return;
        }
      }

      if (resp.status === 422) {
        if (Array.isArray(detail)) {
          setValidationErrors(
            detail.map((item) =>
              isObject(item) && typeof item.msg === "string" ? item.msg : JSON.stringify(item),
            ),
          );
        } else {
          setValidationErrors([formatResponseDetail(detail, "Validation failed.")]);
        }
        setSaveStatus("error");
        setSaveMessage("Validation failed.");
        return;
      }

      setSaveStatus("error");
      setSaveMessage(formatResponseDetail(detail, `Error ${resp.status}`));
    }

    try {
      const lookupResp = await fetch(agentPath, {
        method: "GET",
        headers: lookupHeaders,
      });

      if (lookupResp.ok) {
        await submitMutation({
          actionLabel: "updating this agent",
          method: "PUT",
          successMessage: "Agent updated successfully.",
          url: agentPath,
        });
        return;
      }

      if (lookupResp.status === 404) {
        await submitMutation({
          actionLabel: "creating this agent",
          method: "POST",
          successMessage: "Agent created successfully.",
          url: `${API_BASE_URL}/v1/agents/`,
        });
        return;
      }

      const lookupData = await lookupResp.json().catch(() => null);
      const lookupDetail = isObject(lookupData) ? lookupData.detail : null;
      setSaveStatus("error");
      setSaveMessage(formatResponseDetail(lookupDetail, `Error ${lookupResp.status}`));
    } catch (err) {
      setSaveStatus("error");
      setSaveMessage(err instanceof Error ? err.message : "Network error");
    }
  }

  // -- Export JSON ------------------------------------------------------------

  function handleExport() {
    const exportData = buildExport(state);
    const blob = new Blob([JSON.stringify(exportData, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${state.name || "agent"}-definition.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // -- Inline test -----------------------------------------------------------

  async function handleTest() {
    if (!state.name || !state.testMessage.trim()) return;
    setState((s) => ({ ...s, isTestLoading: true, testResponse: "" }));

    try {
      const resp = await fetch(
        `${API_BASE_URL}/v1/agents/${encodeURIComponent(state.name)}/invoke`,
        {
          method: "POST",
          headers: authHeaders(token, apiKey),
          body: JSON.stringify({
            inputs: { task: state.testMessage },
            temperature: 0.4,
          }),
        },
      );
      if (resp.ok) {
        const data = await resp.json();
        const output = data.output?.response ?? data.output?.text ?? JSON.stringify(data.output);
        setState((s) => ({ ...s, testResponse: output, isTestLoading: false }));
      } else {
        const errData = await resp.json().catch(() => null);
        setState((s) => ({
          ...s,
          testResponse: `Error ${resp.status}: ${errData?.detail ?? "Request failed"}`,
          isTestLoading: false,
        }));
      }
    } catch (err) {
      setState((s) => ({
        ...s,
        testResponse: err instanceof Error ? err.message : "Network error",
        isTestLoading: false,
      }));
    }
  }

  // -- Render ----------------------------------------------------------------

  const nameValid = state.name.length >= 2 && NAME_PATTERN.test(state.name) && !nameError;
  const selectedTemplate = AGENT_TEMPLATES.find((template) => template.id === selectedTemplateId) ?? null;
  const governance = buildGovernance(state);
  const enabledCapabilityLabels = CAPABILITY_TOGGLES.filter((toggle) => state[toggle.key]).map(
    (toggle) => toggle.capability,
  );

  return (
    <div className="agent-builder-page">
      <header className="agent-builder-header">
        <h1>Agent Builder</h1>
        <p>Design and deploy custom agents with a visual interface.</p>
      </header>

      <div className="agent-builder-layout">
        {/* Left column: form */}
        <div className="agent-builder-form">
          <section className="builder-section">
            <h2>Start with a template</h2>
            <p className="section-subtitle">
              Pick a safe default, then edit the name, role, and capabilities before saving.
            </p>
            <div className="agent-template-grid" role="group" aria-label="Agent templates">
              {AGENT_TEMPLATES.map((template) => (
                <button
                  type="button"
                  key={template.id}
                  className={`agent-template-card ${selectedTemplateId === template.id ? "active" : ""}`}
                  aria-pressed={selectedTemplateId === template.id}
                  onClick={() => applyTemplate(template)}
                >
                  <strong>{template.title}</strong>
                  <span>{template.audience}</span>
                  <small>{template.description}</small>
                </button>
              ))}
            </div>
          </section>

          {/* Basic Info */}
          <section className="builder-section">
            <h2>Basic Info</h2>

            <label>
              Name
              <input
                type="text"
                placeholder="my-agent"
                value={state.name}
                onChange={(e) => updateField("name", e.target.value)}
                aria-invalid={!!nameError}
                aria-describedby={nameError ? "name-error" : undefined}
              />
              {nameError && (
                <span id="name-error" className="field-error" role="alert">
                  {nameError}
                </span>
              )}
            </label>

            <label>
              Description
              <textarea
                placeholder="What does this agent do?"
                value={state.description}
                onChange={(e) => updateField("description", e.target.value)}
                rows={3}
              />
            </label>

            <label>
              Role
              <select
                value={state.role}
                onChange={(e) => updateField("role", e.target.value)}
              >
                {AGENT_ROLES.map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Version
              <input
                type="text"
                placeholder="1.0.0"
                value={state.version}
                onChange={(e) => updateField("version", e.target.value)}
              />
            </label>
          </section>

          {/* Capability Toggles */}
          <section className="builder-section">
            <h2>Capabilities</h2>
            <p className="section-subtitle">
              Enable the tools and permissions this agent needs.
            </p>

            <div className="capability-toggles">
              {CAPABILITY_TOGGLES.map((toggle) => (
                <label key={toggle.key} className="toggle-row">
                  <span className="toggle-label">{toggle.label}</span>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={state[toggle.key] as boolean}
                    className={`toggle-switch ${state[toggle.key] ? "active" : ""}`}
                    onClick={() =>
                      updateField(toggle.key, !state[toggle.key])
                    }
                  >
                    <span className="toggle-knob" />
                  </button>
                </label>
              ))}
            </div>
          </section>

          <section className="builder-section">
            <h2>Recommended setup</h2>
            <p className="section-subtitle">
              Use these as plain-language hints before saving this agent definition.
            </p>
            <div className="agent-recommendation-list">
              <article>
                <strong>Provider binding</strong>
                <span>
                  {selectedTemplate?.providerHint ??
                    "Choose a template to see the model/provider fit before saving."}
                </span>
              </article>
              <article>
                <strong>Suggested skills</strong>
                <span>{selectedTemplate?.recommendedSkills.join(", ") ?? "Choose a template first."}</span>
              </article>
              <article>
                <strong>Suggested tools</strong>
                <span>{selectedTemplate?.recommendedTools.join(", ") ?? "Choose a template first."}</span>
              </article>
            </div>
          </section>

          {/* Inline Test */}
          <section className="builder-section">
            <h2>Test Agent</h2>
            <p className="section-subtitle">
              Send a message to the saved agent and see its response.
            </p>
            <div className="test-area">
              <input
                type="text"
                placeholder="Type a test message..."
                value={state.testMessage}
                onChange={(e) => updateField("testMessage", e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void handleTest();
                }}
              />
              <button
                type="button"
                onClick={() => void handleTest()}
                disabled={!nameValid || !state.testMessage.trim() || state.isTestLoading}
              >
                {state.isTestLoading ? "Testing..." : "Test"}
              </button>
            </div>
            {state.testResponse && (
              <pre className="test-response">{state.testResponse}</pre>
            )}
          </section>

          {/* Actions */}
          <div className="builder-actions">
            <button
              type="button"
              className="action-primary"
              onClick={() => void handleSave()}
              disabled={!nameValid || saveStatus === "saving"}
            >
              {saveStatus === "saving" ? "Saving..." : "Save Agent"}
            </button>
            <button
              type="button"
              onClick={handleExport}
              disabled={!nameValid}
            >
              Export JSON
            </button>
          </div>

          {(pendingRouteApproval !== null || approvalToken.trim() !== "") && (
            <section className="approval-token-panel" aria-label="Route approval token">
              <h3>Route approval token</h3>
              <p>
                Save requests are approval-gated. Approve the pending Safety Center item, issue a
                short-lived token, then retry save with{" "}
                <code>{pendingRouteApproval?.approvalHeader ?? "X-Agent33-Approval-Token"}</code>.
              </p>
              {pendingRouteApproval !== null && (
                <p className="approval-token-meta">
                  Pending approval: <strong>{pendingRouteApproval.approvalId}</strong> for{" "}
                  {pendingRouteApproval.actionLabel}.
                </p>
              )}
              <label>
                Approval token
                <input
                  type="text"
                  value={approvalToken}
                  onChange={(event) => setApprovalToken(event.target.value)}
                  placeholder="Paste short-lived approval token from Safety Center"
                />
              </label>
            </section>
          )}

          {saveMessage && (
            <p
              className={`save-feedback ${saveStatus === "error" ? "error" : "success"}`}
              role="status"
            >
              {saveMessage}
            </p>
          )}

          {validationErrors.length > 0 && (
            <ul className="validation-errors" role="alert">
              {validationErrors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          )}
        </div>

        {/* Right column: live preview */}
        <div className="agent-builder-preview">
          <section className="agent-builder-review" aria-labelledby="agent-builder-review-title">
            <h2 id="agent-builder-review-title">Review before save</h2>
            <dl>
              <div>
                <dt>Template</dt>
                <dd>{selectedTemplate?.title ?? "Custom agent"}</dd>
              </div>
              <div>
                <dt>Autonomy</dt>
                <dd>{state.canWriteFiles || state.canRunCode ? "Supervised" : "Read-only"}</dd>
              </div>
              <div>
                <dt>Network</dt>
                <dd>{governance.network}</dd>
              </div>
              <div>
                <dt>Capabilities</dt>
                <dd>{enabledCapabilityLabels.length > 0 ? enabledCapabilityLabels.join(", ") : "None enabled"}</dd>
              </div>
            </dl>
            {governance.approval_required.length > 0 ? (
              <p className="agent-review-warning">
                Review required for {governance.approval_required.join(", ")}.
              </p>
            ) : (
              <p className="agent-review-safe">This agent is read-only unless you enable more tools.</p>
            )}
          </section>

          <h2>System Prompt Preview</h2>
          {state.isPreviewLoading && (
            <p className="preview-loading">Generating preview...</p>
          )}
          {state.systemPromptPreview ? (
            <pre className="prompt-preview">{state.systemPromptPreview}</pre>
          ) : (
            !state.isPreviewLoading && (
              <p className="preview-placeholder">
                Fill in the agent details to see a live preview of the system prompt.
              </p>
            )
          )}
        </div>
      </div>
    </div>
  );
}
