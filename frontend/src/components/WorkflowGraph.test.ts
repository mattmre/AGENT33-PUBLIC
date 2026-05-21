import { createElement } from "react";
import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("reactflow", async () => {
  const React = await import("react");
  return {
    __esModule: true,
    default: ({
      nodes,
      edges,
      onNodeClick,
      children
    }: {
      nodes: Array<{ id: string; data: Record<string, unknown> }>;
      edges: Array<{ id: string }>;
      onNodeClick?: (event: unknown, node: { id: string; data: Record<string, unknown> }) => void;
      children?: ReactNode;
    }) =>
      createElement(
        "div",
        { "data-testid": "reactflow-mock" },
        createElement("div", { "data-testid": "mock-edge-count" }, String(edges.length)),
        ...nodes.map((node) =>
          createElement(
            "button",
            {
              key: node.id,
              onClick: () => onNodeClick?.({}, node)
            },
            String(node.data.label)
          )
        ),
        children
      ),
    Background: () => createElement("div"),
    Controls: () => createElement("div"),
    Panel: ({ children }: { children?: ReactNode }) => createElement("div", null, children),
    ReactFlowProvider: ({ children }: { children?: ReactNode }) =>
      createElement("div", null, children),
    useNodesState: <T,>(initialNodes: T[]) => {
      const [nodes, setNodes] = React.useState(initialNodes);
      return [nodes, setNodes, () => undefined] as const;
    },
    useEdgesState: <T,>(initialEdges: T[]) => {
      const [edges, setEdges] = React.useState(initialEdges);
      return [edges, setEdges, () => undefined] as const;
    }
  };
});

import {
  WorkflowGraph,
  getRunningNodeIds,
  hasActiveNodes,
  mapWorkflowEdgesToReactFlow,
  mapWorkflowNodesToReactFlow,
  type WorkflowEdge,
  type WorkflowNode
} from "./WorkflowGraph";

import { normalizeWorkflowStepStatus, statusToColor } from "./WorkflowStatusNode";

afterEach(() => {
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// mapWorkflowNodesToReactFlow
// ---------------------------------------------------------------------------
describe("mapWorkflowNodesToReactFlow", () => {
  it("maps nodes with position field", () => {
    const nodes: WorkflowNode[] = [
      {
        id: "node-1",
        name: "Start Node",
        action: "start",
        position: { x: 100, y: 200 },
        status: "active"
      }
    ];

    const result = mapWorkflowNodesToReactFlow(nodes);

    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("node-1");
    expect(result[0].position).toEqual({ x: 100, y: 200 });
    expect(result[0].data.label).toBe("Start Node");
    expect(result[0].data.action).toBe("start");
    expect(result[0].data.status).toBe("active");
  });

  it("maps nodes with x/y fields", () => {
    const nodes: WorkflowNode[] = [
      {
        id: "node-2",
        name: "Transform",
        action: "transform",
        x: 300,
        y: 400
      }
    ];

    const result = mapWorkflowNodesToReactFlow(nodes);

    expect(result).toHaveLength(1);
    expect(result[0].position).toEqual({ x: 300, y: 400 });
  });

  it("defaults to zero position when no coordinates provided", () => {
    const nodes: WorkflowNode[] = [
      {
        id: "node-3",
        name: "End Node",
        action: "end"
      }
    ];

    const result = mapWorkflowNodesToReactFlow(nodes);

    expect(result[0].position).toEqual({ x: 0, y: 0 });
  });

  it("uses name as label, falls back to id", () => {
    const nodes: WorkflowNode[] = [
      {
        id: "node-4",
        name: "Custom Name",
        action: "custom"
      },
      {
        id: "node-5",
        name: "",
        action: "test"
      }
    ];

    const result = mapWorkflowNodesToReactFlow(nodes);

    expect(result[0].data.label).toBe("Custom Name");
    expect(result[1].data.label).toBe("node-5");
  });

  it("includes metadata in node data", () => {
    const nodes: WorkflowNode[] = [
      {
        id: "node-6",
        name: "With Meta",
        action: "process",
        metadata: { timeout: 30, retries: 3 }
      }
    ];

    const result = mapWorkflowNodesToReactFlow(nodes);

    expect(result[0].data.metadata).toEqual({ timeout: 30, retries: 3 });
  });

  it("sets node type to workflowStatus for all nodes", () => {
    const nodes: WorkflowNode[] = [
      { id: "a", name: "A", action: "run", status: "success" },
      { id: "b", name: "B", action: "run", status: "pending" }
    ];

    const result = mapWorkflowNodesToReactFlow(nodes);

    for (const node of result) {
      expect(node.type).toBe("workflowStatus");
    }
  });
});

// ---------------------------------------------------------------------------
// statusToColor — node status → border color mapping
// ---------------------------------------------------------------------------
describe("statusToColor", () => {
  it("returns green for success", () => {
    expect(statusToColor("success")).toBe("#22c55e");
  });

  it("returns red for failed", () => {
    expect(statusToColor("failed")).toBe("#ef4444");
  });

  it("returns blue for running", () => {
    expect(statusToColor("running")).toBe("#3b82f6");
  });

  it("returns amber for retrying", () => {
    expect(statusToColor("retrying")).toBe("#f59e0b");
  });

  it("returns gray for pending", () => {
    expect(statusToColor("pending")).toBe("#9ca3af");
  });

  it("returns gray for skipped", () => {
    expect(statusToColor("skipped")).toBe("#9ca3af");
  });

  it("returns gray for undefined (default)", () => {
    expect(statusToColor(undefined)).toBe("#9ca3af");
  });

  it("returns gray for unknown status strings", () => {
    expect(statusToColor("cancelled")).toBe("#9ca3af");
    expect(statusToColor("")).toBe("#9ca3af");
  });
});

describe("normalizeWorkflowStepStatus", () => {
  it("keeps supported retrying and skipped statuses explicit", () => {
    expect(normalizeWorkflowStepStatus("retrying")).toBe("retrying");
    expect(normalizeWorkflowStepStatus("skipped")).toBe("skipped");
  });

  it("falls back to pending for unknown statuses", () => {
    expect(normalizeWorkflowStepStatus("cancelled")).toBe("pending");
    expect(normalizeWorkflowStepStatus(undefined)).toBe("pending");
  });
});

// ---------------------------------------------------------------------------
// mapWorkflowEdgesToReactFlow — edge animation detection
// ---------------------------------------------------------------------------
describe("mapWorkflowEdgesToReactFlow", () => {
  const edges: WorkflowEdge[] = [
    { id: "e1", source: "a", target: "b" },
    { id: "e2", source: "b", target: "c" },
    { id: "e3", source: "c", target: "d" }
  ];

  it("maps edges with type smoothstep", () => {
    const result = mapWorkflowEdgesToReactFlow(edges);

    expect(result).toHaveLength(3);
    expect(result[0].type).toBe("smoothstep");
  });

  it("sets animated=false when no running node ids provided", () => {
    const result = mapWorkflowEdgesToReactFlow(edges);

    for (const edge of result) {
      expect(edge.animated).toBe(false);
    }
  });

  it("sets animated=true on edges whose source is a running node", () => {
    const running = new Set(["b"]);
    const result = mapWorkflowEdgesToReactFlow(edges, running);

    // e1: source=a, target=b → animated (target is running)
    expect(result[0].animated).toBe(true);
    // e2: source=b → animated (source is running)
    expect(result[1].animated).toBe(true);
    // e3: source=c, target=d → NOT animated
    expect(result[2].animated).toBe(false);
  });

  it("sets animated=true on edges whose target is a running node", () => {
    const running = new Set(["c"]);
    const result = mapWorkflowEdgesToReactFlow(edges, running);

    // e2: target=c → animated
    expect(result[1].animated).toBe(true);
    // e3: source=c → animated
    expect(result[2].animated).toBe(true);
    // e1: neither → not animated
    expect(result[0].animated).toBe(false);
  });

  it("handles empty edge list", () => {
    const result = mapWorkflowEdgesToReactFlow([]);

    expect(result).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// hasActiveNodes — polling activation detection
// ---------------------------------------------------------------------------
describe("hasActiveNodes", () => {
  it("returns true when any node has status running", () => {
    const nodes: WorkflowNode[] = [
      { id: "a", name: "A", action: "run", status: "success" },
      { id: "b", name: "B", action: "run", status: "running" }
    ];
    expect(hasActiveNodes(nodes)).toBe(true);
  });

  it("returns true when any node has status pending", () => {
    const nodes: WorkflowNode[] = [
      { id: "a", name: "A", action: "run", status: "success" },
      { id: "b", name: "B", action: "run", status: "pending" }
    ];
    expect(hasActiveNodes(nodes)).toBe(true);
  });

  it("returns true when any node has status retrying", () => {
    const nodes: WorkflowNode[] = [
      { id: "a", name: "A", action: "run", status: "success" },
      { id: "b", name: "B", action: "run", status: "retrying" }
    ];
    expect(hasActiveNodes(nodes)).toBe(true);
  });

  it("returns false when all nodes are terminal (success/failed)", () => {
    const nodes: WorkflowNode[] = [
      { id: "a", name: "A", action: "run", status: "success" },
      { id: "b", name: "B", action: "run", status: "failed" }
    ];
    expect(hasActiveNodes(nodes)).toBe(false);
  });

  it("returns false when nodes are only skipped", () => {
    const nodes: WorkflowNode[] = [{ id: "a", name: "A", action: "run", status: "skipped" }];
    expect(hasActiveNodes(nodes)).toBe(false);
  });

  it("returns false when nodes have no status", () => {
    const nodes: WorkflowNode[] = [{ id: "a", name: "A", action: "run" }];
    expect(hasActiveNodes(nodes)).toBe(false);
  });

  it("returns false for empty node list", () => {
    expect(hasActiveNodes([])).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// getRunningNodeIds — helper for edge animation
// ---------------------------------------------------------------------------
describe("getRunningNodeIds", () => {
  it("collects running and retrying node IDs used for active edge animation", () => {
    const nodes: WorkflowNode[] = [
      { id: "a", name: "A", action: "run", status: "running" },
      { id: "b", name: "B", action: "run", status: "success" },
      { id: "c", name: "C", action: "run", status: "retrying" }
    ];

    const ids = getRunningNodeIds(nodes);

    expect(ids.size).toBe(2);
    expect(ids.has("a")).toBe(true);
    expect(ids.has("c")).toBe(true);
    expect(ids.has("b")).toBe(false);
  });

  it("returns empty set when no nodes are running", () => {
    const nodes: WorkflowNode[] = [
      { id: "a", name: "A", action: "run", status: "success" },
      { id: "b", name: "B", action: "run", status: "pending" }
    ];

    const ids = getRunningNodeIds(nodes);

    expect(ids.size).toBe(0);
  });
});

describe("WorkflowGraph", () => {
  it("updates rendered nodes and selected-node details when props change", () => {
    const { rerender } = render(
      createElement(WorkflowGraph, {
        data: {
          workflow_id: "hello-flow",
          nodes: [
            {
              id: "step-a",
              name: "Step A",
              action: "transform",
              status: "pending",
              metadata: { attempt: 1 }
            }
          ],
          edges: []
        }
      })
    );

    fireEvent.click(screen.getByRole("button", { name: "Step A" }));
    expect(screen.getByText("pending")).toBeInTheDocument();
    expect(screen.getByText(/"attempt": 1/)).toBeInTheDocument();

    rerender(
      createElement(WorkflowGraph, {
        data: {
          workflow_id: "hello-flow",
          nodes: [
            {
              id: "step-a",
              name: "Step A Updated",
              action: "transform",
              status: "success",
              metadata: { attempt: 2 }
            },
            {
              id: "step-b",
              name: "Step B",
              action: "notify",
              status: "pending"
            }
          ],
          edges: [{ id: "edge-a-b", source: "step-a", target: "step-b" }]
        }
      })
    );

    expect(screen.getByRole("button", { name: "Step A Updated" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Step B" })).toBeInTheDocument();
    expect(screen.getByText("success")).toBeInTheDocument();
    expect(screen.getByText(/"attempt": 2/)).toBeInTheDocument();
    expect(screen.getByText("2 nodes · 1 edges")).toBeInTheDocument();
  });

  it("keeps polling while a node is retrying", () => {
    vi.useFakeTimers();
    const onRefresh = vi.fn();

    render(
      createElement(WorkflowGraph, {
        onRefresh,
        pollIntervalMs: 500,
        data: {
          workflow_id: "retry-flow",
          nodes: [{ id: "step-a", name: "Step A", action: "transform", status: "retrying" }],
          edges: []
        }
      })
    );

    vi.advanceTimersByTime(1_000);

    expect(onRefresh).toHaveBeenCalledTimes(2);
  });

  it("does not poll when nodes are only skipped", () => {
    vi.useFakeTimers();
    const onRefresh = vi.fn();

    render(
      createElement(WorkflowGraph, {
        onRefresh,
        pollIntervalMs: 500,
        data: {
          workflow_id: "skipped-flow",
          nodes: [{ id: "step-a", name: "Step A", action: "transform", status: "skipped" }],
          edges: []
        }
      })
    );

    vi.advanceTimersByTime(1_000);

    expect(onRefresh).not.toHaveBeenCalled();
  });
});
