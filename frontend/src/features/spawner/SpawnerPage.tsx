/**
 * SpawnerPage: visual workflow builder for parent-child sub-agent delegation (P71).
 *
 * Layout:
 *  - Left panel: list of saved workflows (or "No workflows yet")
 *  - Center: workflow editor (parent agent, child configs, save/execute)
 *  - Bottom: execution tree visualization when running
 */

import { useCallback, useEffect, useState } from "react";

import { ExecutionTree } from "./ExecutionTree";
import {
  createWorkflow,
  deleteWorkflow,
  executeWorkflow,
  fetchAgentNames,
  fetchWorkflows,
} from "./api";
import type {
  ChildAgentConfig,
  ExecutionTreeData,
  IsolationMode,
  WorkflowDefinition,
} from "./types";

interface SpawnerPageProps {
  token: string | null;
  apiKey: string | null;
}

const ISOLATION_OPTIONS: { value: IsolationMode; label: string }[] = [
  { value: "local", label: "Local" },
  { value: "subprocess", label: "Subprocess" },
  { value: "docker", label: "Docker" },
];

const EMPTY_CHILD: ChildAgentConfig = {
  agent_name: "",
  system_prompt_override: null,
  tool_allowlist: [],
  autonomy_level: 1,
  isolation: "local",
  pack_names: [],
};

export function SpawnerPage({ token, apiKey }: SpawnerPageProps): JSX.Element {
  // Workflow list
  const [workflows, setWorkflows] = useState<WorkflowDefinition[]>([]);
  const [loadingList, setLoadingList] = useState(true);

  // Editor state
  const [workflowName, setWorkflowName] = useState("");
  const [workflowDesc, setWorkflowDesc] = useState("");
  const [parentAgent, setParentAgent] = useState("");
  const [children, setChildren] = useState<ChildAgentConfig[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Agent names from registry
  const [agentNames, setAgentNames] = useState<string[]>([]);

  // Execution state
  const [executionTree, setExecutionTree] = useState<ExecutionTreeData | null>(null);
  const [executingId, setExecutingId] = useState<string | null>(null);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);

  // Load workflows
  const loadWorkflows = useCallback(async () => {
    setLoadingList(true);
    try {
      const wfs = await fetchWorkflows(token, apiKey);
      setWorkflows(wfs);
    } catch {
      // Non-critical, list will be empty
    } finally {
      setLoadingList(false);
    }
  }, [token, apiKey]);

  // Load agent names
  const loadAgents = useCallback(async () => {
    try {
      const names = await fetchAgentNames(token, apiKey);
      setAgentNames(names);
    } catch {
      // Fall back to empty list
    }
  }, [token, apiKey]);

  useEffect(() => {
    void loadWorkflows();
    void loadAgents();
  }, [loadWorkflows, loadAgents]);

  // Add a child config row
  function addChild(): void {
    setChildren((prev) => [...prev, { ...EMPTY_CHILD }]);
  }

  // Remove a child config row
  function removeChild(index: number): void {
    setChildren((prev) => prev.filter((_, i) => i !== index));
  }

  // Update a single child config field
  function updateChild<K extends keyof ChildAgentConfig>(
    index: number,
    field: K,
    value: ChildAgentConfig[K]
  ): void {
    setChildren((prev) =>
      prev.map((child, i) => (i === index ? { ...child, [field]: value } : child))
    );
  }

  // Save workflow
  async function handleSave(): Promise<void> {
    if (!workflowName.trim() || !parentAgent.trim()) {
      setError("Workflow name and parent agent are required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createWorkflow(token, apiKey, {
        name: workflowName.trim(),
        description: workflowDesc.trim(),
        parent_agent: parentAgent.trim(),
        children,
      });
      // Reset editor
      setWorkflowName("");
      setWorkflowDesc("");
      setParentAgent("");
      setChildren([]);
      await loadWorkflows();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  // Execute workflow
  async function handleExecute(workflowId: string): Promise<void> {
    setExecutingId(workflowId);
    setError(null);
    try {
      const tree = await executeWorkflow(token, apiKey, workflowId);
      setExecutionTree(tree);
      setSelectedWorkflowId(workflowId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Execution failed");
    } finally {
      setExecutingId(null);
    }
  }

  // Delete workflow
  async function handleDelete(workflowId: string): Promise<void> {
    try {
      await deleteWorkflow(token, apiKey, workflowId);
      await loadWorkflows();
      if (selectedWorkflowId === workflowId) {
        setExecutionTree(null);
        setSelectedWorkflowId(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  // Select a workflow to view in editor
  function selectWorkflow(wf: WorkflowDefinition): void {
    setWorkflowName(wf.name);
    setWorkflowDesc(wf.description);
    setParentAgent(wf.parent_agent);
    setChildren(wf.children.map((c) => ({ ...c })));
    setSelectedWorkflowId(wf.id);
  }

  const cardStyle: React.CSSProperties = {
    background: "rgba(11, 30, 39, 0.65)",
    border: "1px solid rgba(48, 213, 200, 0.25)",
    borderRadius: 10,
    padding: 16,
  };

  const inputStyle: React.CSSProperties = {
    background: "rgba(11, 30, 39, 0.8)",
    border: "1px solid rgba(48, 213, 200, 0.3)",
    borderRadius: 6,
    color: "#d9edf4",
    padding: "8px 10px",
    fontSize: "0.88rem",
    width: "100%",
    boxSizing: "border-box",
  };

  const buttonStyle: React.CSSProperties = {
    background: "rgba(48, 213, 200, 0.2)",
    border: "1px solid rgba(48, 213, 200, 0.5)",
    borderRadius: 6,
    color: "#d9edf4",
    padding: "8px 16px",
    fontSize: "0.85rem",
    cursor: "pointer",
  };

  const dangerButtonStyle: React.CSSProperties = {
    ...buttonStyle,
    background: "rgba(239, 68, 68, 0.15)",
    border: "1px solid rgba(239, 68, 68, 0.5)",
    color: "#ef4444",
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: 16, padding: 16 }}>
      {/* Left Panel: Workflow List */}
      <div style={cardStyle}>
        <h2 style={{ color: "#d9edf4", fontSize: "1.05rem", marginTop: 0 }}>Saved Workflows</h2>
        {loadingList && <p style={{ color: "#6b7a8a" }}>Loading...</p>}
        {!loadingList && workflows.length === 0 && (
          <p style={{ color: "#6b7a8a" }}>No workflows yet. Create one in the editor.</p>
        )}
        {workflows.map((wf) => (
          <div
            key={wf.id}
            style={{
              background:
                selectedWorkflowId === wf.id
                  ? "rgba(48, 213, 200, 0.12)"
                  : "rgba(11, 30, 39, 0.4)",
              border:
                selectedWorkflowId === wf.id
                  ? "1px solid rgba(48, 213, 200, 0.5)"
                  : "1px solid rgba(48, 213, 200, 0.15)",
              borderRadius: 8,
              padding: "10px 12px",
              marginBottom: 8,
              cursor: "pointer",
            }}
            onClick={() => selectWorkflow(wf)}
          >
            <div style={{ color: "#d9edf4", fontWeight: 600, fontSize: "0.9rem" }}>{wf.name}</div>
            <div style={{ color: "#6b7a8a", fontSize: "0.78rem" }}>
              {wf.parent_agent} + {wf.children.length} children
            </div>
            <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
              <button
                style={{ ...buttonStyle, padding: "4px 10px", fontSize: "0.78rem" }}
                onClick={(e) => {
                  e.stopPropagation();
                  void handleExecute(wf.id);
                }}
                disabled={executingId === wf.id}
              >
                {executingId === wf.id ? "Starting..." : "Execute"}
              </button>
              <button
                style={{ ...dangerButtonStyle, padding: "4px 10px", fontSize: "0.78rem" }}
                onClick={(e) => {
                  e.stopPropagation();
                  void handleDelete(wf.id);
                }}
              >
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Center: Editor + Execution Tree */}
      <div>
        {/* Workflow Editor */}
        <div style={{ ...cardStyle, marginBottom: 16 }}>
          <h2 style={{ color: "#d9edf4", fontSize: "1.05rem", marginTop: 0 }}>Workflow Editor</h2>

          {error && (
            <div
              style={{
                background: "rgba(239, 68, 68, 0.1)",
                border: "1px solid rgba(239, 68, 68, 0.4)",
                borderRadius: 6,
                padding: "8px 12px",
                color: "#ef4444",
                fontSize: "0.85rem",
                marginBottom: 12,
              }}
            >
              {error}
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
            <div>
              <label style={{ color: "#8ba0b0", fontSize: "0.8rem", display: "block", marginBottom: 4 }}>
                Workflow Name
              </label>
              <input
                style={inputStyle}
                value={workflowName}
                onChange={(e) => setWorkflowName(e.target.value)}
                placeholder="my-research-pipeline"
              />
            </div>
            <div>
              <label style={{ color: "#8ba0b0", fontSize: "0.8rem", display: "block", marginBottom: 4 }}>
                Parent Agent
              </label>
              <select
                style={inputStyle}
                value={parentAgent}
                onChange={(e) => setParentAgent(e.target.value)}
              >
                <option value="">-- select --</option>
                {agentNames.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div style={{ marginBottom: 12 }}>
            <label style={{ color: "#8ba0b0", fontSize: "0.8rem", display: "block", marginBottom: 4 }}>
              Description
            </label>
            <input
              style={inputStyle}
              value={workflowDesc}
              onChange={(e) => setWorkflowDesc(e.target.value)}
              placeholder="Optional description"
            />
          </div>

          {/* Child Agents */}
          <div style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <h3 style={{ color: "#d9edf4", fontSize: "0.95rem", margin: 0 }}>
                Child Agents ({children.length})
              </h3>
              <button style={buttonStyle} onClick={addChild}>
                + Add Child
              </button>
            </div>

            {children.map((child, i) => (
              <div
                key={i}
                style={{
                  background: "rgba(11, 30, 39, 0.4)",
                  border: "1px solid rgba(48, 213, 200, 0.15)",
                  borderRadius: 8,
                  padding: 12,
                  marginBottom: 8,
                }}
              >
                <div style={{ display: "grid", gridTemplateColumns: "1fr 140px 100px auto", gap: 8, alignItems: "end" }}>
                  <div>
                    <label style={{ color: "#8ba0b0", fontSize: "0.75rem", display: "block", marginBottom: 2 }}>
                      Agent
                    </label>
                    <select
                      style={{ ...inputStyle, fontSize: "0.82rem" }}
                      value={child.agent_name}
                      onChange={(e) => updateChild(i, "agent_name", e.target.value)}
                    >
                      <option value="">-- select --</option>
                      {agentNames.map((name) => (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label style={{ color: "#8ba0b0", fontSize: "0.75rem", display: "block", marginBottom: 2 }}>
                      Isolation
                    </label>
                    <select
                      style={{ ...inputStyle, fontSize: "0.82rem" }}
                      value={child.isolation}
                      onChange={(e) => updateChild(i, "isolation", e.target.value as IsolationMode)}
                    >
                      {ISOLATION_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label style={{ color: "#8ba0b0", fontSize: "0.75rem", display: "block", marginBottom: 2 }}>
                      Autonomy ({child.autonomy_level})
                    </label>
                    <input
                      type="range"
                      min={0}
                      max={3}
                      value={child.autonomy_level}
                      onChange={(e) => updateChild(i, "autonomy_level", Number(e.target.value))}
                      style={{ width: "100%" }}
                    />
                  </div>
                  <button
                    style={{ ...dangerButtonStyle, padding: "6px 10px", fontSize: "0.78rem" }}
                    onClick={() => removeChild(i)}
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>

          <button
            style={{ ...buttonStyle, opacity: saving ? 0.5 : 1 }}
            onClick={() => void handleSave()}
            disabled={saving}
          >
            {saving ? "Saving..." : "Save Workflow"}
          </button>
        </div>

        {/* Execution Tree */}
        {executionTree && selectedWorkflowId && (
          <ExecutionTree
            workflowId={selectedWorkflowId}
            initialTree={executionTree}
            token={token}
            apiKey={apiKey}
          />
        )}
      </div>
    </div>
  );
}
