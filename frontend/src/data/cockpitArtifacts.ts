import type { ArtifactDrawerSectionId } from "./artifactDrawerSections";
import type { WorkspaceAgentRole, WorkspaceBoard, WorkspaceTaskCard } from "./workspaceBoard";
import { getWorkspaceBoard } from "./workspaceBoard";
import type { WorkspaceSessionId, WorkspaceSessionSummary } from "./workspaces";
import { WORKSPACE_SESSION_IDS, getWorkspaceSession, isWorkspaceSessionId } from "./workspaces";

export const DEMO_MODE = (import.meta.env.VITE_DEMO_MODE ?? "false") === "true";

export const COCKPIT_ARTIFACT_KINDS = [
  "plan",
  "command",
  "log",
  "test",
  "risk",
  "approval",
  "activity",
  "outcome"
] as const;

export type CockpitArtifactKind = (typeof COCKPIT_ARTIFACT_KINDS)[number];
export type CockpitArtifactStatus = "ready" | "running" | "needs-review" | "blocked" | "done" | "not-available";
export type CockpitArtifactReviewState =
  | "not-started"
  | "in-progress"
  | "needs-review"
  | "approved"
  | "blocked"
  | "not-required";
export type CockpitArtifactEvidenceState = "template" | "adapted" | "empty";
export type CockpitArtifactOwnerRole = WorkspaceAgentRole | "Operator";
export type OutcomeCompletionState = "pr-ready" | "package-ready" | "blocked" | "not-run";
export type OutcomeHandoffState = "not-started" | "in-progress" | "confirmed";
export type CockpitValidationItemStatus = "pass" | "fail" | "skipped";

export interface CockpitValidationItem {
  readonly name: string;
  readonly status: CockpitValidationItemStatus;
  readonly summary: string;
  readonly durationLabel?: string;
}

export interface OutcomeCompletion {
  readonly state: OutcomeCompletionState;
  readonly handoffState: OutcomeHandoffState;
  readonly task?: WorkspaceTaskCard;
  readonly title: string;
  readonly summary: string;
  readonly status: CockpitArtifactStatus;
  readonly reviewState: CockpitArtifactReviewState;
  readonly evidenceState: CockpitArtifactEvidenceState;
  readonly nextActionLabel: string;
}

export interface CockpitArtifact {
  readonly id: string;
  readonly kind: CockpitArtifactKind;
  readonly sectionId: ArtifactDrawerSectionId;
  readonly workspaceId: WorkspaceSessionId;
  readonly title: string;
  readonly summary: string;
  readonly status: CockpitArtifactStatus;
  readonly reviewState: CockpitArtifactReviewState;
  readonly ownerRole: CockpitArtifactOwnerRole;
  readonly sourceLabel: string;
  readonly timestampLabel: string;
  readonly evidenceState: CockpitArtifactEvidenceState;
  readonly nextActionLabel: string;
  readonly relatedTaskIds: ReadonlyArray<string>;
  readonly validationItems?: ReadonlyArray<CockpitValidationItem>;
  readonly outcomeState?: OutcomeCompletionState;
  readonly handoffState?: OutcomeHandoffState;
}

export interface CockpitArtifactSnapshot {
  readonly workspace: WorkspaceSessionSummary;
  readonly board: WorkspaceBoard;
}

const ARTIFACT_SECTION_BY_KIND: Record<CockpitArtifactKind, ArtifactDrawerSectionId> = {
  plan: "plan",
  command: "commands",
  log: "logs",
  test: "tests",
  risk: "risks",
  approval: "approval",
  activity: "activity",
  outcome: "outcome"
};

function createArtifact(
  snapshot: CockpitArtifactSnapshot,
  kind: CockpitArtifactKind,
  artifact: Omit<CockpitArtifact, "id" | "kind" | "sectionId" | "workspaceId" | "sourceLabel" | "timestampLabel">
): CockpitArtifact {
  return {
    id: `${snapshot.workspace.id}-${kind}`,
    kind,
    sectionId: ARTIFACT_SECTION_BY_KIND[kind],
    workspaceId: snapshot.workspace.id,
    sourceLabel: "Workspace template adapter",
    timestampLabel: snapshot.workspace.updatedLabel,
    ...artifact
  };
}

function getFirstTaskByStatus(board: WorkspaceBoard, status: WorkspaceTaskCard["status"]): WorkspaceTaskCard | undefined {
  return board.tasks.find((task) => task.status === status);
}

function getTasksByStatus(board: WorkspaceBoard, status: WorkspaceTaskCard["status"]): ReadonlyArray<WorkspaceTaskCard> {
  return board.tasks.filter((task) => task.status === status);
}

// Frontend adapters use stable board order until backend run metadata can mark the primary artifact task explicitly.
function getPrimaryCommandTask(board: WorkspaceBoard): WorkspaceTaskCard | undefined {
  return getFirstTaskByStatus(board, "running") ?? getFirstTaskByStatus(board, "blocked");
}

function getPrimaryValidationTask(board: WorkspaceBoard): WorkspaceTaskCard | undefined {
  const reviewTasks = getTasksByStatus(board, "review");
  const reviewerOwnedReviewTask = reviewTasks.find((task) => task.ownerRole === "Reviewer");
  return reviewerOwnedReviewTask ?? reviewTasks[0] ?? getFirstTaskByStatus(board, "complete");
}

function taskMentionsPullRequest(task: WorkspaceTaskCard): boolean {
  const searchableText = `${task.title} ${task.outcome}`.toLowerCase();
  return /\b(pr|pull request)\b/.test(searchableText);
}

function taskMentionsPullRequestReady(task: WorkspaceTaskCard): boolean {
  const searchableText = `${task.title} ${task.outcome}`.toLowerCase();
  return /\b(pr|pull request)[\s-]*ready\b/.test(searchableText) || /\bready\b.*\b(pr|pull request)\b/.test(searchableText);
}

export function detectOutcomeCompletion(board: WorkspaceBoard): OutcomeCompletion {
  const blockedTask = getFirstTaskByStatus(board, "blocked");
  if (blockedTask) {
    return {
      state: "blocked",
      task: blockedTask,
      title: "Blocked with required action",
      summary: `${blockedTask.title}: ${blockedTask.outcome}`,
      status: "blocked",
      reviewState: "blocked",
      evidenceState: "template",
      handoffState: "in-progress",
      nextActionLabel: "Resolve blocker before marking work done"
    };
  }

  const completeTasks = getTasksByStatus(board, "complete");
  const prReadyTask =
    completeTasks.find((task) => taskMentionsPullRequestReady(task)) ??
    completeTasks.find((task) => taskMentionsPullRequest(task));
  const completeTask = prReadyTask ?? completeTasks[0];
  if (!completeTask) {
    return {
      state: "not-run",
      title: "No PR or artifact package linked",
      summary: "Completed sessions should end as PR ready, artifact package ready, or blocked with a clear action.",
      status: "not-available",
      reviewState: "not-started",
      evidenceState: "empty",
      handoffState: "not-started",
      nextActionLabel: "Run a task to produce an outcome"
    };
  }

  if (prReadyTask) {
    return {
      state: "pr-ready",
      task: completeTask,
      title: "PR ready",
      summary: completeTask.outcome,
      status: "done",
      reviewState: "approved",
      evidenceState: "template",
      handoffState: "confirmed",
      nextActionLabel: "Open the PR-ready handoff"
    };
  }

  return {
    state: "package-ready",
    task: completeTask,
    title: "Artifact package ready",
    summary: completeTask.outcome,
    status: "done",
    reviewState: "approved",
    evidenceState: "template",
    handoffState: "confirmed",
    nextActionLabel: "Review the completed handoff"
  };
}

export function getValidationItemsForTask(task: WorkspaceTaskCard): ReadonlyArray<CockpitValidationItem> {
  if (task.status === "complete") {
    return [
      {
        name: "Implementation evidence",
        status: "pass",
        summary: "Completed task produced a reviewable handoff.",
        durationLabel: "Captured"
      },
      {
        name: "Validation commands",
        status: "pass",
        summary: "Validation evidence is ready for the operator to review.",
        durationLabel: "Recorded"
      },
      {
        name: "Reviewer handoff",
        status: "pass",
        summary: task.outcome,
        durationLabel: "Confirmed"
      }
    ];
  }

  if (task.status === "review") {
    return [
      {
        name: "Scope checks",
        status: "pass",
        summary: "The task has reached a review gate with a clear owner.",
        durationLabel: "Ready"
      },
      {
        name: "Automated validation",
        status: "skipped",
        summary: "Attach test, lint, or build output before marking the handoff complete.",
        durationLabel: "Waiting"
      },
      {
        name: "Reviewer decision",
        status: "skipped",
        summary: "Reviewer approval has not been recorded yet.",
        durationLabel: "Waiting"
      }
    ];
  }

  return [];
}

function createPlanArtifact(snapshot: CockpitArtifactSnapshot): CockpitArtifact {
  const task = getFirstTaskByStatus(snapshot.board, "todo");

  if (!task) {
    return createArtifact(snapshot, "plan", {
      title: "No plan has been generated yet",
      summary: "Choose a workspace template or guided workflow before AGENT33 can collect assumptions and validation steps.",
      status: "not-available",
      reviewState: "not-started",
      ownerRole: "Coordinator",
      evidenceState: "empty",
      nextActionLabel: "Choose a guided workflow",
      relatedTaskIds: []
    });
  }

  return createArtifact(snapshot, "plan", {
    title: task.title,
    summary: task.outcome,
    status: "ready",
    reviewState: "not-started",
    ownerRole: task.ownerRole,
    evidenceState: "template",
    nextActionLabel: "Review scope and assumptions",
    relatedTaskIds: [task.id]
  });
}

function createCommandArtifact(snapshot: CockpitArtifactSnapshot): CockpitArtifact {
  const task = getPrimaryCommandTask(snapshot.board);

  if (!task) {
    return createArtifact(snapshot, "command", {
      title: "No commands have run yet",
      summary: "Command blocks will appear after a task starts running through a workflow or agent lane.",
      status: "not-available",
      reviewState: "not-required",
      ownerRole: "Builder",
      evidenceState: "empty",
      nextActionLabel: "Start a workflow to create command evidence",
      relatedTaskIds: []
    });
  }

  return createArtifact(snapshot, "command", {
    title: task.title,
    summary: `${task.ownerRole} lane is expected to produce command/tool evidence: ${task.outcome}`,
    status: task.status === "blocked" ? "blocked" : "running",
    reviewState: task.status === "blocked" ? "blocked" : "in-progress",
    ownerRole: task.ownerRole,
    evidenceState: "template",
    nextActionLabel: task.status === "blocked" ? "Resolve the blocker before collecting command evidence" : "Open command blocks when execution evidence is available",
    relatedTaskIds: [task.id]
  });
}

function createLogArtifact(snapshot: CockpitArtifactSnapshot): CockpitArtifact {
  const runningTasks = snapshot.board.tasks.filter((task) => task.status === "running");

  if (runningTasks.length === 0) {
    return createArtifact(snapshot, "log", {
      title: "No run logs are available",
      summary: "Readable logs will appear after a workflow or agent lane starts producing execution output.",
      status: "not-available",
      reviewState: "not-required",
      ownerRole: "Operator",
      evidenceState: "empty",
      nextActionLabel: "Start a workflow to collect logs",
      relatedTaskIds: []
    });
  }

  return createArtifact(snapshot, "log", {
    title: `${runningTasks.length} active lane${runningTasks.length === 1 ? "" : "s"} can produce logs`,
    summary: runningTasks.map((task) => task.title).join("; "),
    status: "running",
    reviewState: "in-progress",
    ownerRole: "Operator",
    evidenceState: "template",
    nextActionLabel: "Summarize logs into reviewable evidence",
    relatedTaskIds: runningTasks.map((task) => task.id)
  });
}

function createTestArtifact(snapshot: CockpitArtifactSnapshot): CockpitArtifact {
  const task = getPrimaryValidationTask(snapshot.board);

  if (!task) {
    return createArtifact(snapshot, "test", {
      title: "Validation has not started",
      summary: "Tests, lint, build, and review evidence will appear after AGENT33 has something to validate.",
      status: "not-available",
      reviewState: "not-started",
      ownerRole: "Reviewer",
      evidenceState: "empty",
      nextActionLabel: "Create or run a task before validation",
      relatedTaskIds: [],
      validationItems: []
    });
  }

  return createArtifact(snapshot, "test", {
    title: task.title,
    summary: task.outcome,
    status: task.status === "complete" ? "done" : "needs-review",
    reviewState: task.status === "complete" ? "approved" : "needs-review",
    ownerRole: "Reviewer",
    evidenceState: "template",
    nextActionLabel: "Review validation evidence",
    relatedTaskIds: [task.id],
    validationItems: getValidationItemsForTask(task)
  });
}

function createRiskArtifact(snapshot: CockpitArtifactSnapshot): CockpitArtifact {
  const task = getFirstTaskByStatus(snapshot.board, "blocked");

  if (!task) {
    return createArtifact(snapshot, "risk", {
      title: "No active blocker is attached",
      summary: "Risk and blocker artifacts will appear here when a task needs approval, setup, or repair before it can continue.",
      status: "not-available",
      reviewState: "not-required",
      ownerRole: "Coordinator",
      evidenceState: "empty",
      nextActionLabel: "Continue monitoring for blockers",
      relatedTaskIds: []
    });
  }

  return createArtifact(snapshot, "risk", {
    title: task.title,
    summary: task.outcome,
    status: "blocked",
    reviewState: "blocked",
    ownerRole: task.ownerRole,
    evidenceState: "template",
    nextActionLabel: "Resolve the blocker before continuing",
    relatedTaskIds: [task.id]
  });
}

function createApprovalArtifact(snapshot: CockpitArtifactSnapshot): CockpitArtifact {
  const blockedTask = getFirstTaskByStatus(snapshot.board, "blocked");
  const reviewTask = getFirstTaskByStatus(snapshot.board, "review");
  const task = blockedTask ?? reviewTask;

  if (!task) {
    return createArtifact(snapshot, "approval", {
      title: "No approval is currently requested",
      summary: "Approval requests will explain what runs, why it is needed, and which task will unblock.",
      status: "not-available",
      reviewState: "not-required",
      ownerRole: "Operator",
      evidenceState: "empty",
      nextActionLabel: "No approval needed yet",
      relatedTaskIds: []
    });
  }

  return createArtifact(snapshot, "approval", {
    title: task.status === "blocked" ? "Approval needed to unblock work" : "Review gate ready",
    summary: `${task.title}: ${task.outcome}`,
    status: task.status === "blocked" ? "blocked" : "needs-review",
    reviewState: task.status === "blocked" ? "blocked" : "needs-review",
    ownerRole: "Operator",
    evidenceState: "template",
    nextActionLabel: task.status === "blocked" ? "Review the requested approval" : "Approve or request changes",
    relatedTaskIds: [task.id]
  });
}

function createActivityArtifact(snapshot: CockpitArtifactSnapshot): CockpitArtifact {
  const activeAgents = snapshot.board.agents.filter((agent) => agent.state !== "Ready");

  return createArtifact(snapshot, "activity", {
    title: activeAgents.length > 0 ? `${activeAgents.length} agent lane${activeAgents.length === 1 ? "" : "s"} active` : "Agent roster is ready",
    summary:
      activeAgents.length > 0
        ? activeAgents.map((agent) => `${agent.role}: ${agent.focus}`).join("; ")
        : "Coordinator, Builder, Scout, and Reviewer handoffs will appear here as typed activity events.",
    status: activeAgents.length > 0 ? "running" : "ready",
    reviewState: activeAgents.length > 0 ? "in-progress" : "not-started",
    ownerRole: "Coordinator",
    evidenceState: "template",
    nextActionLabel: activeAgents.length > 0 ? "Watch lane handoffs" : "Assign or start a task",
    relatedTaskIds: snapshot.board.tasks.map((task) => task.id)
  });
}

function createOutcomeArtifact(snapshot: CockpitArtifactSnapshot): CockpitArtifact {
  const outcome = detectOutcomeCompletion(snapshot.board);

  return createArtifact(snapshot, "outcome", {
    title: outcome.title,
    summary: outcome.summary,
    status: outcome.status,
    reviewState: outcome.reviewState,
    ownerRole: outcome.task?.ownerRole ?? "Operator",
    evidenceState: outcome.evidenceState,
    nextActionLabel: outcome.nextActionLabel,
    relatedTaskIds: outcome.task ? [outcome.task.id] : [],
    outcomeState: outcome.state,
    handoffState: outcome.handoffState
  });
}

export function buildCockpitArtifacts(snapshot: CockpitArtifactSnapshot): ReadonlyArray<CockpitArtifact> {
  return [
    createPlanArtifact(snapshot),
    createCommandArtifact(snapshot),
    createLogArtifact(snapshot),
    createTestArtifact(snapshot),
    createRiskArtifact(snapshot),
    createApprovalArtifact(snapshot),
    createActivityArtifact(snapshot),
    createOutcomeArtifact(snapshot)
  ];
}

export function getCockpitArtifactsForWorkspace(workspaceId: string): ReadonlyArray<CockpitArtifact> {
  if (!DEMO_MODE) return [];
  if (!isWorkspaceSessionId(workspaceId)) {
    throw new Error(
      `Cannot build cockpit artifacts for unknown workspaceId "${workspaceId}". Known workspace IDs: ${WORKSPACE_SESSION_IDS.join(", ")}.`
    );
  }

  return buildCockpitArtifacts({
    workspace: getWorkspaceSession(workspaceId),
    board: getWorkspaceBoard(workspaceId)
  });
}

export function getCockpitArtifactsByKind(
  workspaceId: string
): Readonly<Record<CockpitArtifactKind, CockpitArtifact>> {
  return Object.fromEntries(
    getCockpitArtifactsForWorkspace(workspaceId).map((artifact) => [artifact.kind, artifact])
  ) as Record<CockpitArtifactKind, CockpitArtifact>;
}
