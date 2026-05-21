/**
 * ExecutionTree: renders a live execution tree of agent invocations.
 *
 * Displays a hierarchical tree of ExecutionNode objects as expandable cards.
 * Color coding: pending=gray, running=blue+pulse, completed=green, failed=red.
 * Polls GET /v1/spawner/workflows/{id}/status every 2 seconds while running.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { fetchWorkflowStatus } from "./api";
import type { ExecutionNode, ExecutionTreeData } from "./types";

interface ExecutionTreeProps {
  workflowId: string;
  initialTree: ExecutionTreeData;
  token: string | null;
  apiKey: string | null;
}

const STATUS_STYLES: Record<string, { bg: string; border: string; label: string }> = {
  pending: { bg: "rgba(120,120,140,0.15)", border: "rgba(120,120,140,0.5)", label: "Pending" },
  running: { bg: "rgba(59,130,246,0.15)", border: "rgba(59,130,246,0.7)", label: "Running" },
  completed: { bg: "rgba(34,197,94,0.15)", border: "rgba(34,197,94,0.7)", label: "Completed" },
  failed: { bg: "rgba(239,68,68,0.15)", border: "rgba(239,68,68,0.7)", label: "Failed" },
};

function NodeCard({ node, depth }: { node: ExecutionNode; depth: number }): JSX.Element {
  const style = STATUS_STYLES[node.status] ?? STATUS_STYLES.pending;
  const isRunning = node.status === "running";

  return (
    <div style={{ marginLeft: depth * 24, marginBottom: 8 }}>
      <div
        style={{
          background: style.bg,
          border: `1px solid ${style.border}`,
          borderRadius: 8,
          padding: "10px 14px",
          animation: isRunning ? "pulse 2s ease-in-out infinite" : undefined,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <strong style={{ color: "#e0e8ee", fontSize: "0.95rem" }}>{node.agent_name}</strong>
          <span
            style={{
              fontSize: "0.75rem",
              padding: "2px 8px",
              borderRadius: 4,
              background: style.border,
              color: "#fff",
            }}
          >
            {style.label}
          </span>
        </div>
        {node.result_summary && (
          <p style={{ color: "#a0b0c0", fontSize: "0.82rem", marginTop: 6, marginBottom: 0 }}>
            {node.result_summary}
          </p>
        )}
        {node.error && (
          <p style={{ color: "#ef4444", fontSize: "0.82rem", marginTop: 6, marginBottom: 0 }}>
            Error: {node.error}
          </p>
        )}
        {node.started_at && (
          <p style={{ color: "#6b7a8a", fontSize: "0.72rem", marginTop: 4, marginBottom: 0 }}>
            Started: {new Date(node.started_at).toLocaleTimeString()}
            {node.completed_at && <> | Completed: {new Date(node.completed_at).toLocaleTimeString()}</>}
          </p>
        )}
      </div>
      {node.children.map((child, i) => (
        <NodeCard key={`${child.agent_name}-${i}`} node={child} depth={depth + 1} />
      ))}
    </div>
  );
}

export function ExecutionTree({
  workflowId,
  initialTree,
  token,
  apiKey,
}: ExecutionTreeProps): JSX.Element {
  const [tree, setTree] = useState<ExecutionTreeData>(initialTree);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isRunning = tree.status === "pending" || tree.status === "running";

  const poll = useCallback(async () => {
    try {
      const updated = await fetchWorkflowStatus(token, apiKey, workflowId);
      setTree(updated);
    } catch {
      // Polling failure is non-critical; will retry on next tick
    }
  }, [token, apiKey, workflowId]);

  useEffect(() => {
    if (isRunning) {
      intervalRef.current = setInterval(() => void poll(), 2000);
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [isRunning, poll]);

  // Sync with new initialTree when parent provides one
  useEffect(() => {
    setTree(initialTree);
  }, [initialTree]);

  const overallStyle = STATUS_STYLES[tree.status] ?? STATUS_STYLES.pending;

  return (
    <div
      style={{
        background: "rgba(11, 30, 39, 0.55)",
        border: `1px solid ${overallStyle.border}`,
        borderRadius: 10,
        padding: 16,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
        <h3 style={{ color: "#d9edf4", margin: 0, fontSize: "1rem" }}>
          Execution: {tree.execution_id}
        </h3>
        <span
          style={{
            fontSize: "0.8rem",
            padding: "2px 10px",
            borderRadius: 4,
            background: overallStyle.border,
            color: "#fff",
          }}
        >
          {overallStyle.label}
        </span>
      </div>
      <NodeCard node={tree.root} depth={0} />
    </div>
  );
}
