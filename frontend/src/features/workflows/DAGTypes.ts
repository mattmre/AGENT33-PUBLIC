/**
 * TypeScript types matching the backend DAGLayout models from
 * `engine/src/agent33/workflows/dag_layout.py`.
 */

/** A positioned node in the DAG visualization. */
export interface DAGNode {
  id: string;
  label: string;
  /** Action type: invoke-agent, run-command, etc. */
  type: string;
  status: "pending" | "running" | "completed" | "failed" | "skipped" | "success" | "retrying";
  duration_ms: number | null;
  agent_id: string | null;
  x: number;
  y: number;
  level: number;
}

/** A directed edge between two DAG nodes. */
export interface DAGEdge {
  source: string;
  target: string;
  label: string;
}

/** Complete positioned DAG layout for visualization. */
export interface DAGLayout {
  nodes: DAGNode[];
  edges: DAGEdge[];
  width: number;
  height: number;
  run_id: string | null;
  generated_at: string;
}

/** Maps a DAG node status to a display color. */
export function dagStatusToColor(status: DAGNode["status"]): string {
  switch (status) {
    case "completed":
    case "success":
      return "#22c55e";
    case "failed":
      return "#ef4444";
    case "running":
      return "#3b82f6";
    case "retrying":
      return "#f59e0b";
    case "skipped":
      return "#a855f7";
    case "pending":
    default:
      return "#9ca3af";
  }
}

/** Human-readable label for a DAG node status. */
export function dagStatusLabel(status: DAGNode["status"]): string {
  switch (status) {
    case "completed":
    case "success":
      return "completed";
    case "failed":
      return "failed";
    case "running":
      return "running";
    case "retrying":
      return "retrying";
    case "skipped":
      return "skipped";
    case "pending":
    default:
      return "pending";
  }
}
