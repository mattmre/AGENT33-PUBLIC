import { describe, expect, it } from "vitest";

import {
  buildOperationsTimeline,
  buildReviewableOutputPlan,
  canCancel,
  canPause,
  canResume,
  filterAndSortProcesses,
  getTimelineTone,
  getStatusClass,
  getStatusLabel,
  summarizeOperations
} from "./helpers";
import type { OperationsHubProcessDetail, OperationsHubProcessSummary } from "./types";

describe("operations hub helpers", () => {
  it("maps status to css classes", () => {
    expect(getStatusClass("running")).toBe("status-running");
    expect(getStatusClass("suspended")).toBe("status-paused");
    expect(getStatusClass("expired")).toBe("status-cancelled");
    expect(getStatusClass("crashed")).toBe("status-error");
    expect(getStatusClass("success")).toBe("status-ok");
    expect(getStatusClass("failed")).toBe("status-error");
  });

  it("formats status labels", () => {
    expect(getStatusLabel("in_progress")).toBe("In Progress");
    expect(getStatusLabel("test-status")).toBe("Test Status");
    expect(getStatusLabel("")).toBe("Unknown");
  });

  it("filters and sorts process summaries", () => {
    const input: OperationsHubProcessSummary[] = [
      {
        id: "a",
        type: "trace",
        status: "running",
        started_at: "2026-02-18T10:00:00Z",
        name: "Trace A"
      },
      {
        id: "b",
        type: "autonomy_budget",
        status: "active",
        started_at: "2026-02-18T12:00:00Z",
        name: "Budget B"
      }
    ];

    const filtered = filterAndSortProcesses(input, "active", "");
    expect(filtered).toHaveLength(1);
    expect(filtered[0].id).toBe("b");

    const searched = filterAndSortProcesses(input, "all", "trace");
    expect(searched).toHaveLength(1);
    expect(searched[0].id).toBe("a");
  });

  it("enforces control availability by process type/status", () => {
    const activeBudget: OperationsHubProcessDetail = {
      id: "budget-1",
      type: "autonomy_budget",
      status: "active",
      started_at: "2026-02-18T11:00:00Z",
      name: "budget"
    };
    const suspendedBudget: OperationsHubProcessDetail = {
      ...activeBudget,
      status: "suspended"
    };
    const runningTrace: OperationsHubProcessDetail = {
      id: "trace-1",
      type: "trace",
      status: "running",
      started_at: "2026-02-18T12:00:00Z",
      name: "trace"
    };

    expect(canPause(activeBudget)).toBe(true);
    expect(canPause(suspendedBudget)).toBe(false);
    expect(canResume(suspendedBudget)).toBe(true);
    expect(canResume(activeBudget)).toBe(false);
    expect(canCancel(runningTrace)).toBe(true);
    expect(canCancel({ ...runningTrace, status: "completed" })).toBe(false);
  });

  it("summarizes process status in operator-friendly groups", () => {
    const input: OperationsHubProcessSummary[] = [
      {
        id: "running-1",
        type: "trace",
        status: "running",
        started_at: "2026-02-18T10:00:00Z",
        name: "Trace"
      },
      {
        id: "paused-1",
        type: "autonomy_budget",
        status: "suspended",
        started_at: "2026-02-18T11:00:00Z",
        name: "Budget"
      },
      {
        id: "done-1",
        type: "workflow",
        status: "completed",
        started_at: "2026-02-18T12:00:00Z",
        name: "Workflow"
      }
    ];

    expect(getTimelineTone("running")).toBe("active");
    expect(getTimelineTone("suspended")).toBe("attention");
    expect(getTimelineTone("completed")).toBe("done");

    const summary = summarizeOperations(input);
    expect(summary.total).toBe(3);
    expect(summary.active).toBe(1);
    expect(summary.attention).toBe(1);
    expect(summary.done).toBe(1);
    expect(summary.primaryMessage).toContain("need attention");
  });

  it("builds a latest-first timeline with selected process actions", () => {
    const processes: OperationsHubProcessSummary[] = [
      {
        id: "workflow-1",
        type: "workflow_run",
        status: "running",
        started_at: "2026-02-18T10:00:00Z",
        name: "Build a release brief"
      },
      {
        id: "trace-1",
        type: "trace",
        status: "completed",
        started_at: "2026-02-18T09:00:00Z",
        name: "Previous trace"
      }
    ];
    const selectedProcess: OperationsHubProcessDetail = {
      ...processes[0],
      actions: [
        {
          step_id: "research",
          action_count: 2,
          completed_at: "2026-02-18T10:15:00Z"
        }
      ]
    };

    const timeline = buildOperationsTimeline(processes, selectedProcess);

    expect(timeline[0]).toMatchObject({
      id: "workflow-1:research",
      title: "research completed",
      tone: "done"
    });
    expect(timeline.some((item) => item.title === "Build a release brief is running")).toBe(true);
  });

  it("builds reviewable output plans for recovery decisions", () => {
    const failedProcess: OperationsHubProcessDetail = {
      id: "failed-1",
      type: "workflow_run",
      status: "failed",
      started_at: "2026-02-18T10:00:00Z",
      name: "Failed workflow",
      actions: [
        {
          step_id: "build",
          action_count: 3,
          completed_at: null
        }
      ]
    };
    const runningProcess: OperationsHubProcessDetail = {
      ...failedProcess,
      id: "running-1",
      status: "running",
      name: "Running workflow"
    };

    const failedPlan = buildReviewableOutputPlan(failedProcess);
    expect(failedPlan.statusLabel).toContain("needs operator review");
    expect(failedPlan.primaryAction).toContain("Retry only after");
    expect(failedPlan.artifacts).toContain("Fix checklist");

    const runningPlan = buildReviewableOutputPlan(runningProcess);
    expect(runningPlan.statusLabel).toContain("producing reviewable output");
    expect(runningPlan.budgetLabel).toContain("3 recorded actions");
  });
});
