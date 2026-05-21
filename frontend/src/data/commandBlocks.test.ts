import { describe, expect, it } from "vitest";

import {
  buildCommandBlocksFromTasks,
  createCockpitCommandBlock,
  formatCommandDuration,
  getCommandBlocksByArtifactId,
  getCommandBlocksByTaskId,
  getCommandBlocksForWorkspace
} from "./commandBlocks";

describe("cockpit command blocks", () => {
  it("formats command durations without inventing missing timing", () => {
    expect(formatCommandDuration(undefined)).toBe("Duration not recorded");
    expect(formatCommandDuration(250)).toBe("250 ms");
    expect(formatCommandDuration(1500)).toBe("1.5 s");
    expect(formatCommandDuration(2000)).toBe("2 s");
  });

  it("throws for invalid duration values", () => {
    expect(() => formatCommandDuration(-1)).toThrow(/durationMs must be zero or greater/);
  });

  it("creates explicit success and failure records", () => {
    const success = createCockpitCommandBlock({
      id: "shipyard-command-success",
      workspaceId: "shipyard",
      commandLabel: "npm run lint",
      sourceRole: "Builder",
      status: "success",
      exitCode: 0,
      timestampLabel: "Just now",
      durationMs: 2000,
      traceId: "trace-lint-1",
      redactionState: "not-required",
      outputSummary: "TypeScript completed without errors.",
      relatedArtifactId: "shipyard-command",
      relatedTaskId: "shipyard-build"
    });
    const failure = createCockpitCommandBlock({
      id: "shipyard-command-failure",
      workspaceId: "shipyard",
      commandLabel: "npm test",
      sourceRole: "Reviewer",
      status: "failed",
      exitCode: 1,
      timestampLabel: "Just now",
      traceId: "trace-test-1",
      redactionState: "redacted",
      failureSummary: "One test assertion failed",
      outputSummary: "One test failed; full output was redacted for review.",
      relatedArtifactId: "shipyard-command",
      relatedTaskId: "shipyard-review"
    });

    expect(success).toMatchObject({
      exitLabel: "Exit 0",
      durationLabel: "2 s",
      traceId: "trace-lint-1",
      nextActionLabel: "Review the linked artifact"
    });
    expect(failure).toMatchObject({
      exitLabel: "Exit 1",
      durationLabel: "Duration not recorded",
      redactionState: "redacted",
      traceId: "trace-test-1",
      failureSummary: "One test assertion failed",
      nextActionLabel: "Investigate failure: One test assertion failed"
    });
  });

  it("maps running workspace tasks into template command blocks linked to the command artifact", () => {
    const blocks = getCommandBlocksForWorkspace("shipyard");

    expect(blocks.map((block) => block.relatedTaskId)).toEqual(["shipyard-scout", "shipyard-build"]);
    expect(blocks.every((block) => block.relatedArtifactId === "shipyard-command")).toBe(true);
    expect(blocks.every((block) => block.timestampLabel === "Template")).toBe(true);
    expect(blocks.map((block) => block.sourceRole)).toEqual(["Scout", "Builder"]);
    expect(blocks.every((block) => block.status === "running")).toBe(true);
    expect(blocks.every((block) => block.redactionState === "not-required")).toBe(true);
    expect(blocks.map((block) => block.traceId)).toEqual([
      "shipyard-trace-shipyard-scout",
      "shipyard-trace-shipyard-build"
    ]);
  });

  it("maps blocked tasks into blocked command review records", () => {
    const blocks = getCommandBlocksForWorkspace("test-review");

    expect(blocks.find((block) => block.relatedTaskId === "quality-merge")).toMatchObject({
      status: "blocked",
      redactionState: "review-required",
      traceId: "test-review-trace-quality-merge",
      failureSummary: "Prepare merge handoff is blocked before command evidence can complete.",
      nextActionLabel: "Resolve the blocker before rerunning"
    });
  });

  it("filters command blocks by linked artifact and task ids", () => {
    const blocks = getCommandBlocksForWorkspace("shipyard");

    expect(getCommandBlocksByArtifactId(blocks, "shipyard-command")).toHaveLength(2);
    expect(getCommandBlocksByTaskId(blocks, "shipyard-build")).toMatchObject([
      {
        id: "shipyard-command-shipyard-build",
        relatedArtifactId: "shipyard-command"
      }
    ]);
    expect(getCommandBlocksByTaskId(blocks, "shipyard-review")).toHaveLength(0);
  });

  it("returns an explicit not-run block when no task has execution evidence", () => {
    const [block] = buildCommandBlocksFromTasks({
      workspaceId: "solo-builder",
      relatedArtifactId: "solo-builder-command",
      timestampLabel: "Default workspace",
      tasks: [
        {
          id: "completed-build",
          title: "Completed build",
          outcome: "Completed work should not become a running command block.",
          status: "complete",
          ownerRole: "Builder"
        }
      ]
    });

    expect(block).toMatchObject({
      id: "solo-builder-command-empty",
      status: "not-run",
      exitLabel: "No exit code yet",
      timestampLabel: "Default workspace",
      nextActionLabel: "Start a workflow to create command evidence"
    });
  });

  it("throws an actionable error for unknown workspaces", () => {
    expect(() => getCommandBlocksForWorkspace("missing-workspace")).toThrow(
      /Cannot build command blocks for unknown workspaceId "missing-workspace"/
    );
  });
});
