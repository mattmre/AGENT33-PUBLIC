import type { CockpitArtifact, CockpitArtifactOwnerRole, CockpitValidationItem } from "./cockpitArtifacts";
import { getCockpitArtifactsForWorkspace, getValidationItemsForTask } from "./cockpitArtifacts";
import type { CockpitCommandBlock } from "./commandBlocks";
import { getCommandBlocksByTaskId, getCommandBlocksForWorkspace } from "./commandBlocks";
import type { WorkspaceTaskCard } from "./workspaceBoard";
import { getWorkspaceBoard } from "./workspaceBoard";
import type { WorkspaceSessionId } from "./workspaces";
import { WORKSPACE_SESSION_IDS, isWorkspaceSessionId } from "./workspaces";

export const DEMO_MODE = (import.meta.env.VITE_DEMO_MODE ?? "false") === "true";

export const COCKPIT_ACTIVITY_EVENT_TYPES = [
  "decision",
  "blocker",
  "approval",
  "handoff",
  "review-comment",
  "validation",
  "status"
] as const;

export const COCKPIT_ACTIVITY_SEVERITIES = ["info", "attention", "blocked", "success"] as const;
export const COCKPIT_ACTIVITY_DECISION_STATES = ["pending", "approved", "rejected", "blocked", "not-required"] as const;

export type CockpitActivityEventType = (typeof COCKPIT_ACTIVITY_EVENT_TYPES)[number];
export type CockpitActivitySeverity = (typeof COCKPIT_ACTIVITY_SEVERITIES)[number];
export type CockpitActivityDecisionState = (typeof COCKPIT_ACTIVITY_DECISION_STATES)[number];

export interface CockpitActivityEvent {
  readonly id: string;
  readonly workspaceId: WorkspaceSessionId;
  readonly type: CockpitActivityEventType;
  readonly severity: CockpitActivitySeverity;
  readonly senderRole: CockpitArtifactOwnerRole;
  readonly recipientRole: CockpitArtifactOwnerRole | "All";
  readonly title: string;
  readonly summary: string;
  readonly timestampLabel: string;
  readonly sequenceIndex?: number;
  readonly isInterAgentHandoff?: boolean;
  readonly createdAtLabel?: string;
  readonly expiresAtLabel?: string;
  readonly validationDetails?: ReadonlyArray<CockpitValidationItem>;
  readonly decisionState: CockpitActivityDecisionState;
  readonly relatedTaskId?: string;
  readonly relatedArtifactId?: string;
  readonly relatedCommandBlockId?: string;
  readonly nextActionLabel: string;
}

export interface CockpitActivityEventInput {
  readonly id: string;
  readonly workspaceId: string;
  readonly type: CockpitActivityEventType;
  readonly severity: CockpitActivitySeverity;
  readonly senderRole: CockpitArtifactOwnerRole;
  readonly recipientRole: CockpitArtifactOwnerRole | "All";
  readonly title: string;
  readonly summary: string;
  readonly timestampLabel: string;
  readonly sequenceIndex?: number;
  readonly isInterAgentHandoff?: boolean;
  readonly createdAtLabel?: string;
  readonly expiresAtLabel?: string;
  readonly validationDetails?: ReadonlyArray<CockpitValidationItem>;
  readonly decisionState?: CockpitActivityDecisionState;
  readonly relatedTaskId?: string;
  readonly relatedArtifactId?: string;
  readonly relatedCommandBlockId?: string;
  readonly nextActionLabel: string;
}

export interface ActivityTaskSnapshot {
  readonly workspaceId: WorkspaceSessionId;
  readonly timestampLabel: string;
  readonly tasks: ReadonlyArray<WorkspaceTaskCard>;
  readonly artifacts: ReadonlyArray<CockpitArtifact>;
  readonly commandBlocks: ReadonlyArray<CockpitCommandBlock>;
}

function assertWorkspaceId(workspaceId: string): asserts workspaceId is WorkspaceSessionId {
  if (!isWorkspaceSessionId(workspaceId)) {
    throw new Error(
      `Cannot build activity events for unknown workspaceId "${workspaceId}". Known workspace IDs: ${WORKSPACE_SESSION_IDS.join(", ")}.`
    );
  }
}

function getDefaultDecisionState(type: CockpitActivityEventType): CockpitActivityDecisionState {
  if (type === "decision" || type === "approval") {
    return "pending";
  }

  if (type === "blocker") {
    return "blocked";
  }

  if (type === "validation") {
    return "pending";
  }

  return "not-required";
}

export function createCockpitActivityEvent(input: CockpitActivityEventInput): CockpitActivityEvent {
  assertWorkspaceId(input.workspaceId);

  return {
    id: input.id,
    workspaceId: input.workspaceId,
    type: input.type,
    severity: input.severity,
    senderRole: input.senderRole,
    recipientRole: input.recipientRole,
    title: input.title,
    summary: input.summary,
    timestampLabel: input.timestampLabel,
    sequenceIndex: input.sequenceIndex,
    isInterAgentHandoff: input.isInterAgentHandoff,
    createdAtLabel: input.createdAtLabel,
    expiresAtLabel: input.expiresAtLabel,
    validationDetails: input.validationDetails,
    decisionState: input.decisionState ?? getDefaultDecisionState(input.type),
    relatedTaskId: input.relatedTaskId,
    relatedArtifactId: input.relatedArtifactId,
    relatedCommandBlockId: input.relatedCommandBlockId,
    nextActionLabel: input.nextActionLabel
  };
}

function findArtifactForTask(
  artifacts: ReadonlyArray<CockpitArtifact>,
  task: WorkspaceTaskCard,
  preferredKinds: ReadonlyArray<CockpitArtifact["kind"]>
): CockpitArtifact | undefined {
  for (const kind of preferredKinds) {
    const artifact = artifacts.find((candidate) => candidate.kind === kind && candidate.relatedTaskIds.includes(task.id));
    if (artifact) {
      return artifact;
    }
  }

  return artifacts.find((candidate) => candidate.relatedTaskIds.includes(task.id));
}

function getCommandBlockIdForTask(
  commandBlocks: ReadonlyArray<CockpitCommandBlock>,
  taskId: string
): string | undefined {
  return getCommandBlocksByTaskId(commandBlocks, taskId)[0]?.id;
}

function createDecisionEvent(snapshot: ActivityTaskSnapshot, task: WorkspaceTaskCard): CockpitActivityEvent {
  const artifact = findArtifactForTask(snapshot.artifacts, task, ["plan"]);

  return createCockpitActivityEvent({
    id: `${snapshot.workspaceId}-activity-decision-${task.id}`,
    workspaceId: snapshot.workspaceId,
    type: "decision",
    severity: "info",
    senderRole: "Coordinator",
    recipientRole: "Operator",
    title: task.title,
    summary: task.outcome,
    timestampLabel: snapshot.timestampLabel,
    relatedTaskId: task.id,
    relatedArtifactId: artifact?.id,
    nextActionLabel: "Decide whether this task should start"
  });
}

function createHandoffEvent(
  snapshot: ActivityTaskSnapshot,
  task: WorkspaceTaskCard,
  sequenceIndex: number
): CockpitActivityEvent {
  const artifact = findArtifactForTask(snapshot.artifacts, task, ["command", "log", "activity"]);
  const commandBlock = getCommandBlocksByTaskId(snapshot.commandBlocks, task.id)[0];

  return createCockpitActivityEvent({
    id: `${snapshot.workspaceId}-activity-handoff-${task.id}`,
    workspaceId: snapshot.workspaceId,
    type: "handoff",
    severity: "info",
    senderRole: "Coordinator",
    recipientRole: task.ownerRole,
    title: task.title,
    summary: `${task.ownerRole} lane is working: ${task.outcome}`,
    timestampLabel: snapshot.timestampLabel,
    sequenceIndex,
    isInterAgentHandoff: true,
    relatedTaskId: task.id,
    relatedArtifactId: commandBlock?.relatedArtifactId ?? artifact?.id,
    relatedCommandBlockId: commandBlock?.id,
    nextActionLabel: "Watch for execution evidence"
  });
}

function createReviewEvents(snapshot: ActivityTaskSnapshot, task: WorkspaceTaskCard): ReadonlyArray<CockpitActivityEvent> {
  const artifact = findArtifactForTask(snapshot.artifacts, task, ["test"]);
  const approvalArtifact = snapshot.artifacts.find(
    (candidate) => candidate.kind === "approval" && candidate.relatedTaskIds.includes(task.id)
  );

  return [
    createCockpitActivityEvent({
      id: `${snapshot.workspaceId}-activity-review-${task.id}`,
      workspaceId: snapshot.workspaceId,
      type: "review-comment",
      severity: "attention",
      senderRole: task.ownerRole,
      recipientRole: "Reviewer",
      title: task.title,
      summary: task.outcome,
      timestampLabel: snapshot.timestampLabel,
      decisionState: "pending",
      relatedTaskId: task.id,
      relatedArtifactId: artifact?.id,
      nextActionLabel: "Review and approve or request changes"
    }),
    ...(approvalArtifact
      ? [
          createCockpitActivityEvent({
            id: `${snapshot.workspaceId}-activity-approval-${task.id}`,
            workspaceId: snapshot.workspaceId,
            type: "approval",
            severity: "attention",
            senderRole: task.ownerRole,
            recipientRole: "Operator",
            title: `Approval requested: ${task.title}`,
            summary: task.outcome,
            timestampLabel: snapshot.timestampLabel,
            relatedTaskId: task.id,
            relatedArtifactId: approvalArtifact.id,
            nextActionLabel: "Approve, reject, or request changes"
          })
        ]
      : [])
  ];
}

function createBlockerEvent(snapshot: ActivityTaskSnapshot, task: WorkspaceTaskCard): CockpitActivityEvent {
  const riskArtifact = findArtifactForTask(snapshot.artifacts, task, ["risk", "outcome"]);
  const commandBlockId = getCommandBlockIdForTask(snapshot.commandBlocks, task.id);

  return createCockpitActivityEvent({
    id: `${snapshot.workspaceId}-activity-blocker-${task.id}`,
    workspaceId: snapshot.workspaceId,
    type: "blocker",
    severity: "blocked",
    senderRole: task.ownerRole,
    recipientRole: "Operator",
    title: task.title,
    summary: task.outcome,
    timestampLabel: snapshot.timestampLabel,
    relatedTaskId: task.id,
    relatedArtifactId: riskArtifact?.id,
    relatedCommandBlockId: commandBlockId,
    nextActionLabel: "Resolve this blocker before approval can proceed"
  });
}

function createValidationEvent(
  snapshot: ActivityTaskSnapshot,
  task: WorkspaceTaskCard,
  sequenceIndex: number
): CockpitActivityEvent {
  const artifact = findArtifactForTask(snapshot.artifacts, task, ["outcome", "test"]);

  return createCockpitActivityEvent({
    id: `${snapshot.workspaceId}-activity-validation-${task.id}`,
    workspaceId: snapshot.workspaceId,
    type: "validation",
    severity: "success",
    senderRole: task.ownerRole,
    recipientRole: "Operator",
    title: task.title,
    summary: task.outcome,
    timestampLabel: snapshot.timestampLabel,
    sequenceIndex,
    validationDetails: getValidationItemsForTask(task),
    relatedTaskId: task.id,
    relatedArtifactId: artifact?.id,
    nextActionLabel: "Review the completed handoff"
  });
}

export function buildActivityEventsFromTasks(snapshot: ActivityTaskSnapshot): ReadonlyArray<CockpitActivityEvent> {
  return snapshot.tasks.flatMap((task, index) => {
    const sequenceIndex = index + 1;

    switch (task.status) {
      case "todo":
        return [createDecisionEvent(snapshot, task)];
      case "running":
        return [createHandoffEvent(snapshot, task, sequenceIndex)];
      case "review":
        return createReviewEvents(snapshot, task);
      case "blocked":
        return [createBlockerEvent(snapshot, task)];
      case "complete":
        return [createValidationEvent(snapshot, task, sequenceIndex)];
      default: {
        const unexpectedStatus: never = task.status;
        throw new Error(`Unhandled workspace task status: ${unexpectedStatus}`);
      }
    }
  });
}

export function getActivityEventsForWorkspace(workspaceId: string): ReadonlyArray<CockpitActivityEvent> {
  if (!DEMO_MODE) return [];
  assertWorkspaceId(workspaceId);

  const board = getWorkspaceBoard(workspaceId);
  const artifacts = getCockpitArtifactsForWorkspace(workspaceId);
  const commandBlocks = getCommandBlocksForWorkspace(workspaceId);
  const timestampLabel = artifacts.find((artifact) => artifact.kind === "activity")?.timestampLabel ?? "Workspace template";

  return buildActivityEventsFromTasks({
    workspaceId,
    timestampLabel,
    tasks: board.tasks,
    artifacts,
    commandBlocks
  });
}

export function getActivityEventsByType(
  events: ReadonlyArray<CockpitActivityEvent>,
  type: CockpitActivityEventType
): ReadonlyArray<CockpitActivityEvent> {
  return events.filter((event) => event.type === type);
}

export function getActivityEventsByArtifactId(
  events: ReadonlyArray<CockpitActivityEvent>,
  relatedArtifactId: string
): ReadonlyArray<CockpitActivityEvent> {
  return events.filter((event) => event.relatedArtifactId === relatedArtifactId);
}

export function getActivityEventsByTaskId(
  events: ReadonlyArray<CockpitActivityEvent>,
  relatedTaskId: string
): ReadonlyArray<CockpitActivityEvent> {
  return events.filter((event) => event.relatedTaskId === relatedTaskId);
}
