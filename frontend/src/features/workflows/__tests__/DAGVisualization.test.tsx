import { createElement } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DAGLayout, DAGNode } from "../DAGTypes";
import { dagStatusLabel, dagStatusToColor } from "../DAGTypes";
import { DAGVisualization } from "../DAGVisualization";

// ---------------------------------------------------------------------------
// Test data factories
// ---------------------------------------------------------------------------

function makeNode(overrides: Partial<DAGNode> & { id: string }): DAGNode {
  return {
    label: overrides.id,
    type: "run-command",
    status: "pending",
    duration_ms: null,
    agent_id: null,
    x: 0,
    y: 0,
    level: 0,
    ...overrides
  };
}

function makeLayout(overrides?: Partial<DAGLayout>): DAGLayout {
  return {
    nodes: [],
    edges: [],
    width: 500,
    height: 400,
    run_id: null,
    generated_at: "2026-03-15T00:00:00Z",
    ...overrides
  };
}

// ---------------------------------------------------------------------------
// dagStatusToColor
// ---------------------------------------------------------------------------

describe("dagStatusToColor", () => {
  it("returns green for completed", () => {
    expect(dagStatusToColor("completed")).toBe("#22c55e");
  });

  it("returns green for success", () => {
    expect(dagStatusToColor("success")).toBe("#22c55e");
  });

  it("returns red for failed", () => {
    expect(dagStatusToColor("failed")).toBe("#ef4444");
  });

  it("returns blue for running", () => {
    expect(dagStatusToColor("running")).toBe("#3b82f6");
  });

  it("returns purple for skipped", () => {
    expect(dagStatusToColor("skipped")).toBe("#a855f7");
  });

  it("returns gray for pending", () => {
    expect(dagStatusToColor("pending")).toBe("#9ca3af");
  });

  it("returns amber for retrying", () => {
    expect(dagStatusToColor("retrying")).toBe("#f59e0b");
  });
});

// ---------------------------------------------------------------------------
// dagStatusLabel
// ---------------------------------------------------------------------------

describe("dagStatusLabel", () => {
  it("returns completed for success status", () => {
    expect(dagStatusLabel("success")).toBe("completed");
  });

  it("returns completed for completed status", () => {
    expect(dagStatusLabel("completed")).toBe("completed");
  });

  it("returns running for running status", () => {
    expect(dagStatusLabel("running")).toBe("running");
  });

  it("returns pending for pending status", () => {
    expect(dagStatusLabel("pending")).toBe("pending");
  });

  it("returns failed for failed status", () => {
    expect(dagStatusLabel("failed")).toBe("failed");
  });

  it("returns skipped for skipped status", () => {
    expect(dagStatusLabel("skipped")).toBe("skipped");
  });

  it("returns retrying for retrying status", () => {
    expect(dagStatusLabel("retrying")).toBe("retrying");
  });
});

// ---------------------------------------------------------------------------
// DAGVisualization rendering
// ---------------------------------------------------------------------------

describe("DAGVisualization", () => {
  it("renders the visualization container", () => {
    const layout = makeLayout();
    render(createElement(DAGVisualization, { dagLayout: layout }));
    expect(screen.getByTestId("dag-visualization")).toBeInTheDocument();
  });

  it("renders nodes with correct labels", () => {
    const layout = makeLayout({
      nodes: [
        makeNode({ id: "step-a", label: "Step A", x: 40, y: 40 }),
        makeNode({ id: "step-b", label: "Step B", x: 320, y: 40, level: 1 })
      ]
    });

    render(createElement(DAGVisualization, { dagLayout: layout }));

    expect(screen.getByTestId("node-step-a")).toBeInTheDocument();
    expect(screen.getByTestId("node-step-b")).toBeInTheDocument();
  });

  it("renders edges between connected nodes", () => {
    const layout = makeLayout({
      nodes: [
        makeNode({ id: "a", x: 40, y: 40 }),
        makeNode({ id: "b", x: 320, y: 40, level: 1 })
      ],
      edges: [{ source: "a", target: "b", label: "" }]
    });

    render(createElement(DAGVisualization, { dagLayout: layout }));

    expect(screen.getByTestId("edge-a-b")).toBeInTheDocument();
  });

  it("applies correct aria-label with status to nodes", () => {
    const layout = makeLayout({
      nodes: [makeNode({ id: "s1", label: "Build", status: "running", x: 40, y: 40 })]
    });

    render(createElement(DAGVisualization, { dagLayout: layout }));

    const node = screen.getByTestId("node-s1");
    expect(node).toHaveAttribute("aria-label", "Build: running");
  });

  it("applies success aria-label for completed nodes", () => {
    const layout = makeLayout({
      nodes: [makeNode({ id: "s1", label: "Deploy", status: "completed", x: 40, y: 40 })]
    });

    render(createElement(DAGVisualization, { dagLayout: layout }));

    const node = screen.getByTestId("node-s1");
    expect(node).toHaveAttribute("aria-label", "Deploy: completed");
  });

  it("calls onNodeClick when a node is clicked", () => {
    const onClick = vi.fn();
    const layout = makeLayout({
      nodes: [makeNode({ id: "clickable", label: "Click Me", x: 40, y: 40 })]
    });

    render(createElement(DAGVisualization, { dagLayout: layout, onNodeClick: onClick }));

    fireEvent.click(screen.getByTestId("node-clickable"));
    expect(onClick).toHaveBeenCalledWith("clickable");
  });

  it("calls onNodeClick on Enter key press", () => {
    const onClick = vi.fn();
    const layout = makeLayout({
      nodes: [makeNode({ id: "key-node", label: "Key Node", x: 40, y: 40 })]
    });

    render(createElement(DAGVisualization, { dagLayout: layout, onNodeClick: onClick }));

    fireEvent.keyDown(screen.getByTestId("node-key-node"), { key: "Enter" });
    expect(onClick).toHaveBeenCalledWith("key-node");
  });

  it("renders zoom control buttons", () => {
    const layout = makeLayout();
    render(createElement(DAGVisualization, { dagLayout: layout }));

    expect(screen.getByTestId("dag-zoom-in")).toBeInTheDocument();
    expect(screen.getByTestId("dag-zoom-out")).toBeInTheDocument();
    expect(screen.getByTestId("dag-zoom-reset")).toBeInTheDocument();
  });

  it("zoom buttons have accessible labels", () => {
    const layout = makeLayout();
    render(createElement(DAGVisualization, { dagLayout: layout }));

    expect(screen.getByLabelText("Zoom in")).toBeInTheDocument();
    expect(screen.getByLabelText("Zoom out")).toBeInTheDocument();
    expect(screen.getByLabelText("Reset zoom")).toBeInTheDocument();
  });

  it("shows tooltip on mouse enter and hides on mouse leave", () => {
    const layout = makeLayout({
      nodes: [
        makeNode({
          id: "hover-node",
          label: "Hover Me",
          type: "invoke-agent",
          agent_id: "qa-agent",
          duration_ms: 123.4,
          status: "success",
          x: 40,
          y: 40
        })
      ]
    });

    render(createElement(DAGVisualization, { dagLayout: layout }));

    // Tooltip should not exist initially
    expect(screen.queryByTestId("dag-tooltip")).not.toBeInTheDocument();

    // Hover over node
    fireEvent.mouseEnter(screen.getByTestId("node-hover-node"), {
      clientX: 100,
      clientY: 100
    });

    const tooltip = screen.getByTestId("dag-tooltip");
    expect(tooltip).toBeInTheDocument();
    expect(tooltip).toHaveTextContent("Hover Me");
    expect(tooltip).toHaveTextContent("invoke-agent");
    expect(tooltip).toHaveTextContent("qa-agent");
    expect(tooltip).toHaveTextContent("123.4ms");

    // Leave node
    fireEvent.mouseLeave(screen.getByTestId("node-hover-node"));
    expect(screen.queryByTestId("dag-tooltip")).not.toBeInTheDocument();
  });

  it("applies retrying aria-label and animation for retrying nodes", () => {
    const layout = makeLayout({
      nodes: [makeNode({ id: "r1", label: "Retry Step", status: "retrying", x: 40, y: 40 })]
    });

    render(createElement(DAGVisualization, { dagLayout: layout }));

    const node = screen.getByTestId("node-r1");
    expect(node).toHaveAttribute("aria-label", "Retry Step: retrying");
  });

  it("renders empty graph without errors", () => {
    const layout = makeLayout({ nodes: [], edges: [] });
    render(createElement(DAGVisualization, { dagLayout: layout }));
    expect(screen.getByTestId("dag-visualization")).toBeInTheDocument();
  });

  it("renders multiple edges correctly", () => {
    const layout = makeLayout({
      nodes: [
        makeNode({ id: "a", x: 40, y: 40 }),
        makeNode({ id: "b", x: 320, y: 40 }),
        makeNode({ id: "c", x: 320, y: 180 })
      ],
      edges: [
        { source: "a", target: "b", label: "" },
        { source: "a", target: "c", label: "" }
      ]
    });

    render(createElement(DAGVisualization, { dagLayout: layout }));

    expect(screen.getByTestId("edge-a-b")).toBeInTheDocument();
    expect(screen.getByTestId("edge-a-c")).toBeInTheDocument();
  });

  it("truncates long node labels", () => {
    const longLabel = "This Is A Very Long Step Name That Should Be Truncated";
    const layout = makeLayout({
      nodes: [makeNode({ id: "long", label: longLabel, x: 40, y: 40 })]
    });

    render(createElement(DAGVisualization, { dagLayout: layout }));

    const node = screen.getByTestId("node-long");
    // The full label should be in aria-label for accessibility
    expect(node).toHaveAttribute(
      "aria-label",
      expect.stringContaining("This Is A Very Long")
    );
  });

  it("shows download artifacts button when onDownloadArtifacts and run_id are provided", () => {
    const onDownloadArtifacts = vi.fn();
    const layout = makeLayout({ run_id: "run-42" });
    render(
      createElement(DAGVisualization, { dagLayout: layout, onDownloadArtifacts })
    );
    expect(screen.getByLabelText("Download artifacts")).toBeInTheDocument();
  });

  it("calls onDownloadArtifacts with run_id when download button is clicked", () => {
    const onDownloadArtifacts = vi.fn();
    const layout = makeLayout({ run_id: "run-42" });
    render(
      createElement(DAGVisualization, { dagLayout: layout, onDownloadArtifacts })
    );
    fireEvent.click(screen.getByLabelText("Download artifacts"));
    expect(onDownloadArtifacts).toHaveBeenCalledWith("run-42");
  });

  it("omits download artifacts button when run_id is null", () => {
    const onDownloadArtifacts = vi.fn();
    const layout = makeLayout({ run_id: null });
    render(
      createElement(DAGVisualization, { dagLayout: layout, onDownloadArtifacts })
    );
    expect(screen.queryByLabelText("Download artifacts")).not.toBeInTheDocument();
  });

  it("shows retry step button in tooltip for failed nodes when onRetryStep provided", () => {
    const onRetryStep = vi.fn();
    const layout = makeLayout({
      run_id: "run-99",
      nodes: [makeNode({ id: "bad-step", label: "Bad Step", status: "failed", x: 40, y: 40 })]
    });
    render(
      createElement(DAGVisualization, { dagLayout: layout, onRetryStep })
    );
    fireEvent.mouseEnter(screen.getByTestId("node-bad-step"), { clientX: 100, clientY: 100 });
    const retryBtn = screen.getByTestId("retry-step-bad-step");
    expect(retryBtn).toBeInTheDocument();
    fireEvent.click(retryBtn);
    expect(onRetryStep).toHaveBeenCalledWith("run-99", "bad-step");
  });

  it("does not show retry step button for non-failed nodes", () => {
    const onRetryStep = vi.fn();
    const layout = makeLayout({
      run_id: "run-99",
      nodes: [makeNode({ id: "ok-step", label: "OK Step", status: "success", x: 40, y: 40 })]
    });
    render(
      createElement(DAGVisualization, { dagLayout: layout, onRetryStep })
    );
    fireEvent.mouseEnter(screen.getByTestId("node-ok-step"), { clientX: 100, clientY: 100 });
    expect(screen.queryByTestId("retry-step-ok-step")).not.toBeInTheDocument();
  });
});
