import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";

/** Valid workflow step statuses */
export type WorkflowStepStatus =
  | "success"
  | "failed"
  | "running"
  | "pending"
  | "retrying"
  | "skipped";

const KNOWN_WORKFLOW_STEP_STATUSES = new Set<WorkflowStepStatus>([
  "success",
  "failed",
  "running",
  "pending",
  "retrying",
  "skipped"
]);

export interface WorkflowStatusNodeData {
  label: string;
  action?: string;
  status?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Normalize workflow statuses for display, falling back to `pending`.
 */
export function normalizeWorkflowStepStatus(status: string | undefined): WorkflowStepStatus {
  if (status && KNOWN_WORKFLOW_STEP_STATUSES.has(status as WorkflowStepStatus)) {
    return status as WorkflowStepStatus;
  }
  return "pending";
}

/**
 * Maps a workflow step status string to a display color.
 *
 * Exported for direct unit-testing without rendering.
 */
export function statusToColor(status: string | undefined): string {
  switch (normalizeWorkflowStepStatus(status)) {
    case "success":
      return "#22c55e";
    case "failed":
      return "#ef4444";
    case "running":
      return "#3b82f6";
    case "retrying":
      return "#f59e0b";
    case "skipped":
    case "pending":
    default:
      return "#9ca3af";
  }
}

const nodeBaseStyle: React.CSSProperties = {
  padding: "10px 16px",
  borderRadius: 10,
  background: "linear-gradient(170deg, rgba(22, 45, 58, 0.95), rgba(10, 27, 36, 0.95))",
  color: "#e2e8f0",
  fontFamily: "'Space Grotesk', 'Segoe UI', sans-serif",
  fontSize: "0.85rem",
  minWidth: 140,
  textAlign: "center" as const
};

const statusBadgeBase: React.CSSProperties = {
  display: "inline-block",
  marginTop: 6,
  padding: "2px 8px",
  borderRadius: 6,
  fontSize: "0.72rem",
  fontWeight: 600,
  textTransform: "uppercase" as const,
  letterSpacing: "0.04em"
};

/**
 * Custom ReactFlow node that color-codes its border by workflow step status.
 *
 * When the status is `"running"`, the border uses a CSS pulsing animation
 * defined in `styles.css` (class `.wf-node-running`).
 */
function WorkflowStatusNodeRaw({ data }: NodeProps<WorkflowStatusNodeData>): JSX.Element {
  const normalizedStatus = normalizeWorkflowStepStatus(data.status);
  const color = statusToColor(normalizedStatus);
  const isRunning = normalizedStatus === "running";

  const borderStyle: React.CSSProperties = {
    border: `2px solid ${color}`,
    boxShadow: `0 0 8px ${color}40`
  };

  return (
    <div
      className={isRunning ? "wf-node-running" : undefined}
      style={{ ...nodeBaseStyle, ...borderStyle }}
      role="group"
      aria-label={`${data.label}: ${normalizedStatus}`}
    >
      <Handle type="target" position={Position.Top} style={{ background: color }} />

      <div style={{ fontWeight: 600 }}>{data.label}</div>

      <span
        style={{
          ...statusBadgeBase,
          color,
          background: `${color}18`
        }}
        role="status"
      >
        {normalizedStatus}
      </span>

      <Handle type="source" position={Position.Bottom} style={{ background: color }} />
    </div>
  );
}

/**
 * Memoised version — ReactFlow re-renders nodes on every viewport change,
 * so we memoise to avoid unnecessary DOM work.
 */
export const WorkflowStatusNode = memo(WorkflowStatusNodeRaw);
