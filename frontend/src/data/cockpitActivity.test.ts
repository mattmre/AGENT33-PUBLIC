import { describe, expect, it } from "vitest";

import { getCockpitArtifactsForWorkspace } from "./cockpitArtifacts";
import {
  buildActivityEventsFromTasks,
  createCockpitActivityEvent,
  getActivityEventsByArtifactId,
  getActivityEventsByTaskId,
  getActivityEventsByType,
  getActivityEventsForWorkspace
} from "./cockpitActivity";
import { getCommandBlocksForWorkspace } from "./commandBlocks";
import { getWorkspaceBoard } from "./workspaceBoard";

describe("cockpit activity events", () => {
  it("creates structured approval events without transcript-shaped fields", () => {
    const event = createCockpitActivityEvent({
      id: "test-review-activity-approval-quality-merge",
      workspaceId: "test-review",
      type: "approval",
      severity: "attention",
      senderRole: "Coordinator",
      recipientRole: "Operator",
      title: "Approval needed: Prepare merge handoff",
      summary: "Merge-safe summary and final status.",
      timestampLabel: "Template",
      createdAtLabel: "Requested 15 min ago",
      expiresAtLabel: "Expires in 45 min",
      relatedTaskId: "quality-merge",
      relatedArtifactId: "test-review-approval",
      nextActionLabel: "Approve, reject, or ask for a safer route"
    });

    expect(event).toMatchObject({
      decisionState: "pending",
      recipientRole: "Operator",
      relatedTaskId: "quality-merge",
      createdAtLabel: "Requested 15 min ago",
      expiresAtLabel: "Expires in 45 min"
    });
    expect(Object.keys(event)).not.toContain("message");
    expect(Object.keys(event)).not.toContain("transcript");
  });

  it("maps workspace tasks into decision, handoff, review, blocker, approval, and validation events", () => {
    const eventTypes = getActivityEventsForWorkspace("test-review").map((event) => event.type);
    const researchEventTypes = getActivityEventsForWorkspace("research-build").map((event) => event.type);

    expect(eventTypes).toEqual(["decision", "handoff", "review-comment", "blocker"]);
    expect(researchEventTypes).toContain("approval");
    expect(researchEventTypes).toContain("validation");
  });

  it("links blocked activity to blocker artifacts without implying approval", () => {
    const events = getActivityEventsForWorkspace("test-review");

    expect(getActivityEventsByTaskId(events, "quality-merge")).toEqual([
      expect.objectContaining({
        type: "blocker",
        severity: "blocked",
        decisionState: "blocked",
        relatedArtifactId: "test-review-risk",
        nextActionLabel: "Resolve this blocker before approval can proceed"
      })
    ]);
  });

  it("links approval events to review gates instead of blocked tasks", () => {
    const events = getActivityEventsForWorkspace("research-build");

    expect(getActivityEventsByType(events, "approval")).toEqual([
      expect.objectContaining({
        relatedTaskId: "research-convert",
        relatedArtifactId: "research-build-approval",
        decisionState: "pending"
      })
    ]);
  });

  it("links running handoffs to command blocks and command artifacts", () => {
    const events = getActivityEventsForWorkspace("shipyard");
    const handoffs = getActivityEventsByType(events, "handoff");

    expect(handoffs.map((event) => event.relatedTaskId)).toEqual(["shipyard-scout", "shipyard-build"]);
    expect(handoffs.every((event) => event.relatedArtifactId === "shipyard-command")).toBe(true);
    expect(handoffs.map((event) => event.relatedCommandBlockId)).toEqual([
      "shipyard-command-shipyard-scout",
      "shipyard-command-shipyard-build"
    ]);
    expect(handoffs.map((event) => event.sequenceIndex)).toEqual([2, 3]);
    expect(handoffs.every((event) => event.isInterAgentHandoff)).toBe(true);
  });

  it("filters events by artifact id for drawer sections", () => {
    const events = getActivityEventsForWorkspace("shipyard");

    expect(getActivityEventsByArtifactId(events, "shipyard-command").map((event) => event.type)).toEqual([
      "handoff",
      "handoff"
    ]);
  });

  it("builds events from a synthetic task snapshot", () => {
    const workspaceId = "solo-builder";
    const events = buildActivityEventsFromTasks({
      workspaceId,
      timestampLabel: "Default workspace",
      tasks: getWorkspaceBoard(workspaceId).tasks,
      artifacts: getCockpitArtifactsForWorkspace(workspaceId),
      commandBlocks: getCommandBlocksForWorkspace(workspaceId)
    });

    expect(events[0]).toMatchObject({
      type: "decision",
      relatedArtifactId: "solo-builder-plan",
      decisionState: "pending"
    });
  });

  it("keeps completed validation handoffs pending operator review", () => {
    const event = getActivityEventsByTaskId(getActivityEventsForWorkspace("shipyard"), "shipyard-log")[0];

    expect(event).toMatchObject({
      type: "validation",
      severity: "success",
      decisionState: "pending",
      relatedArtifactId: "shipyard-outcome",
      validationDetails: [
        expect.objectContaining({ name: "Implementation evidence", status: "pass" }),
        expect.objectContaining({ name: "Validation commands", status: "pass" }),
        expect.objectContaining({ name: "Reviewer handoff", status: "pass" })
      ]
    });
  });

  it("throws an actionable error for unknown workspaces", () => {
    expect(() => getActivityEventsForWorkspace("missing-workspace")).toThrow(
      /Cannot build activity events for unknown workspaceId "missing-workspace"/
    );
  });
});
