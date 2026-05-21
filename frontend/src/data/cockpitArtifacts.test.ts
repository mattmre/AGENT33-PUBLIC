import { describe, expect, it } from "vitest";

import { ARTIFACT_DRAWER_SECTION_IDS } from "./artifactDrawerSections";
import {
  COCKPIT_ARTIFACT_KINDS,
  buildCockpitArtifacts,
  detectOutcomeCompletion,
  getCockpitArtifactsByKind,
  getCockpitArtifactsForWorkspace
} from "./cockpitArtifacts";
import { WORKSPACE_SESSIONS, getWorkspaceSession } from "./workspaces";

describe("cockpit artifact view models", () => {
  it("creates one artifact for every drawer-backed artifact kind", () => {
    for (const workspace of WORKSPACE_SESSIONS) {
      const artifacts = getCockpitArtifactsForWorkspace(workspace.id);

      expect(artifacts.map((artifact) => artifact.kind)).toEqual(COCKPIT_ARTIFACT_KINDS);
      expect(new Set(artifacts.map((artifact) => artifact.id)).size).toBe(artifacts.length);
      expect(artifacts.every((artifact) => artifact.workspaceId === workspace.id)).toBe(true);
      expect(artifacts.every((artifact) => ARTIFACT_DRAWER_SECTION_IDS.includes(artifact.sectionId))).toBe(true);
    }
  });

  it("keeps required review metadata on every artifact", () => {
    const artifacts = getCockpitArtifactsForWorkspace("shipyard");

    for (const artifact of artifacts) {
      expect(artifact.id).toMatch(/^shipyard-/);
      expect(artifact.title.length).toBeGreaterThan(0);
      expect(artifact.summary.length).toBeGreaterThan(0);
      expect(artifact.sourceLabel.length).toBeGreaterThan(0);
      expect(artifact.timestampLabel.length).toBeGreaterThan(0);
      expect(artifact.nextActionLabel.length).toBeGreaterThan(0);
    }
  });

  it("uses explicit empty artifacts instead of fake success states", () => {
    const artifactsByKind = getCockpitArtifactsByKind("solo-builder");

    expect(artifactsByKind.risk).toMatchObject({
      evidenceState: "empty",
      status: "not-available",
      reviewState: "not-required",
      title: "No active blocker is attached"
    });
    expect(artifactsByKind.outcome).toMatchObject({
      evidenceState: "empty",
      status: "not-available",
      reviewState: "not-started",
      title: "No PR or artifact package linked"
    });
  });

  it("does not turn a non-planning task into a running plan artifact", () => {
    const workspace = getWorkspaceSession("solo-builder");
    const [artifact] = buildCockpitArtifacts({
      workspace,
      board: {
        workspaceId: workspace.id,
        agents: [],
        tasks: [
          {
            id: "completed-build",
            title: "Completed build",
            outcome: "A finished task should not be treated as an active plan.",
            status: "complete",
            ownerRole: "Builder"
          }
        ]
      }
    });

    expect(artifact).toMatchObject({
      kind: "plan",
      evidenceState: "empty",
      status: "not-available",
      reviewState: "not-started",
      relatedTaskIds: []
    });
  });

  it("marks blocked command artifacts as blocked instead of unavailable", () => {
    const workspace = getWorkspaceSession("solo-builder");
    const [, commandArtifact] = buildCockpitArtifacts({
      workspace,
      board: {
        workspaceId: workspace.id,
        agents: [],
        tasks: [
          {
            id: "blocked-command",
            title: "Command waiting on approval",
            outcome: "The command cannot collect evidence until the operator approves it.",
            status: "blocked",
            ownerRole: "Coordinator"
          }
        ]
      }
    });

    expect(commandArtifact).toMatchObject({
      kind: "command",
      status: "blocked",
      reviewState: "blocked",
      relatedTaskIds: ["blocked-command"]
    });
  });

  it("keeps command artifact priority deterministic when several tasks can produce command evidence", () => {
    const workspace = getWorkspaceSession("shipyard");
    const [, commandArtifact] = buildCockpitArtifacts({
      workspace,
      board: {
        workspaceId: workspace.id,
        agents: [],
        tasks: [
          {
            id: "first-running",
            title: "First running task",
            outcome: "This task should own the primary command artifact.",
            status: "running",
            ownerRole: "Scout"
          },
          {
            id: "blocked-second",
            title: "Blocked second task",
            outcome: "Blocked command evidence should not outrank active running work.",
            status: "blocked",
            ownerRole: "Builder"
          },
          {
            id: "running-third",
            title: "Running third task",
            outcome: "Later running work remains visible through command blocks and logs.",
            status: "running",
            ownerRole: "Builder"
          }
        ]
      }
    });

    expect(commandArtifact).toMatchObject({
      title: "First running task",
      status: "running",
      relatedTaskIds: ["first-running"]
    });
  });

  it("maps blocked work into risk, approval, and outcome artifacts", () => {
    const artifactsByKind = getCockpitArtifactsByKind("test-review");

    expect(artifactsByKind.risk).toMatchObject({
      status: "blocked",
      reviewState: "blocked",
      relatedTaskIds: ["quality-merge"]
    });
    expect(artifactsByKind.approval).toMatchObject({
      status: "blocked",
      reviewState: "blocked",
      nextActionLabel: "Review the requested approval"
    });
    expect(artifactsByKind.outcome).toMatchObject({
      title: "Blocked with required action",
      status: "blocked",
      relatedTaskIds: ["quality-merge"]
    });
  });

  it("detects PR-ready completion from completed task context", () => {
    const workspace = getWorkspaceSession("shipyard");
    const outcome = detectOutcomeCompletion({
      workspaceId: workspace.id,
      agents: [],
      tasks: [
        {
          id: "feature-pr",
          title: "Prepare PR handoff",
          outcome: "PR-ready implementation with tests and reviewer notes.",
          status: "complete",
          ownerRole: "Builder"
        }
      ]
    });

    expect(outcome).toMatchObject({
      state: "pr-ready",
      title: "PR ready",
      status: "done",
      reviewState: "approved",
      nextActionLabel: "Open the PR-ready handoff"
    });
  });

  it("prioritizes PR-ready completion across all completed tasks", () => {
    const workspace = getWorkspaceSession("shipyard");
    const outcome = detectOutcomeCompletion({
      workspaceId: workspace.id,
      agents: [],
      tasks: [
        {
          id: "package-first",
          title: "Collect artifacts",
          outcome: "Implementation notes and validation logs collected.",
          status: "complete",
          ownerRole: "Reviewer"
        },
        {
          id: "pr-second",
          title: "Prepare pull request",
          outcome: "Pull request is ready with tests and reviewer notes.",
          status: "complete",
          ownerRole: "Builder"
        }
      ]
    });

    expect(outcome).toMatchObject({
      state: "pr-ready",
      title: "PR ready",
      task: expect.objectContaining({ id: "pr-second" })
    });
  });

  it("prefers explicit PR-ready completed tasks before generic pull request mentions", () => {
    const workspace = getWorkspaceSession("shipyard");
    const outcome = detectOutcomeCompletion({
      workspaceId: workspace.id,
      agents: [],
      tasks: [
        {
          id: "generic-pr-note",
          title: "Collect pull request notes",
          outcome: "Implementation notes mention the pull request but do not mark it ready.",
          status: "complete",
          ownerRole: "Reviewer"
        },
        {
          id: "ready-pr-note",
          title: "Prepare release handoff",
          outcome: "PR ready with tests and reviewer notes.",
          status: "complete",
          ownerRole: "Builder"
        }
      ]
    });

    expect(outcome).toMatchObject({
      state: "pr-ready",
      task: expect.objectContaining({ id: "ready-pr-note" })
    });
  });


  it("detects package-ready completion when no PR signal exists", () => {
    const workspace = getWorkspaceSession("research-build");
    const outcome = detectOutcomeCompletion({
      workspaceId: workspace.id,
      agents: [],
      tasks: [
        {
          id: "research-package",
          title: "Review research handoff",
          outcome: "Approved direction for the next build slice.",
          status: "complete",
          ownerRole: "Reviewer"
        }
      ]
    });

    expect(outcome).toMatchObject({
      state: "package-ready",
      title: "Artifact package ready",
      status: "done",
      reviewState: "approved",
      nextActionLabel: "Review the completed handoff"
    });
  });

  it("prioritizes blocked outcomes over completed work", () => {
    const workspace = getWorkspaceSession("test-review");
    const outcome = detectOutcomeCompletion({
      workspaceId: workspace.id,
      agents: [],
      tasks: [
        {
          id: "complete-package",
          title: "Package artifacts",
          outcome: "Artifact package collected.",
          status: "complete",
          ownerRole: "Builder"
        },
        {
          id: "blocked-merge",
          title: "Prepare merge handoff",
          outcome: "Merge-safe summary and final status.",
          status: "blocked",
          ownerRole: "Coordinator"
        }
      ]
    });

    expect(outcome).toMatchObject({
      state: "blocked",
      title: "Blocked with required action",
      status: "blocked",
      task: expect.objectContaining({ id: "blocked-merge" })
    });
  });

  it("keeps not-run outcomes explicit when no task is complete", () => {
    const workspace = getWorkspaceSession("solo-builder");
    const outcome = detectOutcomeCompletion({
      workspaceId: workspace.id,
      agents: [],
      tasks: [
        {
          id: "draft-plan",
          title: "Draft the first workflow",
          outcome: "Recommended starter plan with safe next action.",
          status: "running",
          ownerRole: "Builder"
        }
      ]
    });

    expect(outcome).toMatchObject({
      state: "not-run",
      title: "No PR or artifact package linked",
      status: "not-available",
      reviewState: "not-started"
    });
  });

  it("maps active work into command, log, activity, and validation artifacts", () => {
    const artifactsByKind = getCockpitArtifactsByKind("shipyard");

    expect(artifactsByKind.command).toMatchObject({
      status: "running",
      reviewState: "in-progress",
      relatedTaskIds: ["shipyard-scout"]
    });
    expect(artifactsByKind.log.relatedTaskIds).toEqual(["shipyard-scout", "shipyard-build"]);
    expect(artifactsByKind.activity.status).toBe("running");
    expect(artifactsByKind.test).toMatchObject({
      status: "needs-review",
      reviewState: "needs-review",
      ownerRole: "Reviewer"
    });
  });

  it("prioritizes active review work over a completed reviewer-owned task", () => {
    const artifactsByKind = getCockpitArtifactsByKind("research-build");

    expect(artifactsByKind.test).toMatchObject({
      status: "needs-review",
      reviewState: "needs-review",
      relatedTaskIds: ["research-convert"],
      validationItems: [
        expect.objectContaining({ name: "Scope checks", status: "pass" }),
        expect.objectContaining({ name: "Automated validation", status: "skipped" }),
        expect.objectContaining({ name: "Reviewer decision", status: "skipped" })
      ]
    });
  });

  it("prefers reviewer-owned review tasks when several tasks are in review", () => {
    const workspace = getWorkspaceSession("test-review");
    const artifacts = buildCockpitArtifacts({
      workspace,
      board: {
        workspaceId: workspace.id,
        agents: [],
        tasks: [
          {
            id: "builder-review",
            title: "Builder review",
            outcome: "Builder-owned review should remain secondary validation evidence.",
            status: "review",
            ownerRole: "Builder"
          },
          {
            id: "reviewer-review",
            title: "Reviewer review",
            outcome: "Reviewer-owned review should become the primary test artifact.",
            status: "review",
            ownerRole: "Reviewer"
          },
          {
            id: "reviewer-complete",
            title: "Completed reviewer handoff",
            outcome: "Completed reviewer-owned task should not outrank active review work.",
            status: "complete",
            ownerRole: "Reviewer"
          }
        ]
      }
    });
    const testArtifact = artifacts.find((artifact) => artifact.kind === "test");

    expect(testArtifact).toMatchObject({
      title: "Reviewer review",
      relatedTaskIds: ["reviewer-review"],
      validationItems: [
        expect.objectContaining({ name: "Scope checks", status: "pass" }),
        expect.objectContaining({ name: "Automated validation", status: "skipped" }),
        expect.objectContaining({ name: "Reviewer decision", status: "skipped" })
      ]
    });
  });

  it("adds validation details and outcome handoff state for completed work", () => {
    const artifactsByKind = getCockpitArtifactsByKind("shipyard");

    expect(artifactsByKind.test.validationItems).toEqual([
      expect.objectContaining({ name: "Scope checks", status: "pass" }),
      expect.objectContaining({ name: "Automated validation", status: "skipped" }),
      expect.objectContaining({ name: "Reviewer decision", status: "skipped" })
    ]);
    expect(artifactsByKind.outcome).toMatchObject({
      outcomeState: "package-ready",
      handoffState: "confirmed"
    });
  });

  it("throws an actionable error for an unknown workspace id", () => {
    expect(() => getCockpitArtifactsForWorkspace("missing-workspace")).toThrow(
      /Cannot build cockpit artifacts for unknown workspaceId "missing-workspace"/
    );
  });
});
