import type { CockpitArtifactOwnerRole } from "./cockpitArtifacts";
import { getCockpitArtifactsByKind } from "./cockpitArtifacts";
import type { WorkspaceTaskCard } from "./workspaceBoard";
import { getWorkspaceBoard } from "./workspaceBoard";
import type { WorkspaceSessionId } from "./workspaces";
import { WORKSPACE_SESSION_IDS, isWorkspaceSessionId } from "./workspaces";

export const COMMAND_BLOCK_STATUSES = ["queued", "running", "success", "failed", "blocked", "not-run"] as const;
export const COMMAND_BLOCK_REDACTION_STATES = ["not-required", "redacted", "review-required"] as const;

export type CommandBlockStatus = (typeof COMMAND_BLOCK_STATUSES)[number];
export type CommandBlockRedactionState = (typeof COMMAND_BLOCK_REDACTION_STATES)[number];

export interface CockpitCommandBlock {
  readonly id: string;
  readonly workspaceId: WorkspaceSessionId;
  readonly commandLabel: string;
  readonly sourceRole: CockpitArtifactOwnerRole;
  readonly status: CommandBlockStatus;
  readonly exitCode?: number;
  readonly exitLabel: string;
  readonly timestampLabel: string;
  readonly durationMs?: number;
  readonly durationLabel: string;
  readonly traceId?: string;
  readonly redactionState: CommandBlockRedactionState;
  readonly failureSummary?: string;
  readonly outputSummary: string;
  readonly relatedArtifactId: string;
  readonly relatedTaskId?: string;
  readonly nextActionLabel: string;
}

export interface CommandBlockInput {
  readonly id: string;
  readonly workspaceId: string;
  readonly commandLabel: string;
  readonly sourceRole: CockpitArtifactOwnerRole;
  readonly status: CommandBlockStatus;
  readonly exitCode?: number;
  readonly timestampLabel: string;
  readonly durationMs?: number;
  readonly traceId?: string;
  readonly redactionState: CommandBlockRedactionState;
  readonly failureSummary?: string;
  readonly outputSummary: string;
  readonly relatedArtifactId: string;
  readonly relatedTaskId?: string;
  readonly nextActionLabel?: string;
}

export interface CommandBlockTaskSnapshot {
  readonly workspaceId: WorkspaceSessionId;
  readonly relatedArtifactId: string;
  readonly timestampLabel: string;
  readonly tasks: ReadonlyArray<WorkspaceTaskCard>;
}

type CommandBackedTask = WorkspaceTaskCard & {
  readonly status: "running" | "blocked";
};

function assertWorkspaceId(workspaceId: string): asserts workspaceId is WorkspaceSessionId {
  if (!isWorkspaceSessionId(workspaceId)) {
    throw new Error(
      `Cannot build command blocks for unknown workspaceId "${workspaceId}". Known workspace IDs: ${WORKSPACE_SESSION_IDS.join(", ")}.`
    );
  }
}

export function formatCommandDuration(durationMs: number | undefined): string {
  if (durationMs === undefined) {
    return "Duration not recorded";
  }

  if (durationMs < 0) {
    throw new Error(`Command block durationMs must be zero or greater. Received ${durationMs}.`);
  }

  if (durationMs < 1000) {
    return `${durationMs} ms`;
  }

  const seconds = durationMs / 1000;
  return `${Number.isInteger(seconds) ? seconds : seconds.toFixed(1)} s`;
}

function getExitLabel(status: CommandBlockStatus, exitCode: number | undefined): string {
  if (exitCode !== undefined) {
    return `Exit ${exitCode}`;
  }

  if (status === "success" || status === "failed") {
    return "Exit code not recorded";
  }

  return "No exit code yet";
}

function getDefaultNextAction(status: CommandBlockStatus, failureSummary: string | undefined): string {
  if (status === "success") {
    return "Review the linked artifact";
  }

  if (status === "failed") {
    if (failureSummary) {
      return `Investigate failure: ${failureSummary}`;
    }
    return "Inspect the failure summary";
  }

  if (status === "blocked") {
    return "Resolve the blocker before rerunning";
  }

  if (status === "running") {
    return "Watch for completion evidence";
  }

  if (status === "queued") {
    return "Wait for the command to start";
  }

  return "Start a workflow to create command evidence";
}

export function createCockpitCommandBlock(input: CommandBlockInput): CockpitCommandBlock {
  assertWorkspaceId(input.workspaceId);

  return {
    id: input.id,
    workspaceId: input.workspaceId,
    commandLabel: input.commandLabel,
    sourceRole: input.sourceRole,
    status: input.status,
    exitCode: input.exitCode,
    exitLabel: getExitLabel(input.status, input.exitCode),
    timestampLabel: input.timestampLabel,
    durationMs: input.durationMs,
    durationLabel: formatCommandDuration(input.durationMs),
    traceId: input.traceId,
    redactionState: input.redactionState,
    failureSummary: input.failureSummary,
    outputSummary: input.outputSummary,
    relatedArtifactId: input.relatedArtifactId,
    relatedTaskId: input.relatedTaskId,
    nextActionLabel: input.nextActionLabel ?? getDefaultNextAction(input.status, input.failureSummary)
  };
}

function isCommandBackedTask(task: WorkspaceTaskCard): task is CommandBackedTask {
  return task.status === "running" || task.status === "blocked";
}

function createTemplateCommandBlock(
  workspaceId: WorkspaceSessionId,
  relatedArtifactId: string,
  timestampLabel: string,
  task: CommandBackedTask
): CockpitCommandBlock {
  return createCockpitCommandBlock({
    id: `${workspaceId}-command-${task.id}`,
    workspaceId,
    commandLabel: `${task.ownerRole} lane: ${task.title}`,
    sourceRole: task.ownerRole,
    status: task.status === "blocked" ? "blocked" : "running",
    timestampLabel,
    traceId: `${workspaceId}-trace-${task.id}`,
    redactionState: task.status === "blocked" ? "review-required" : "not-required",
    failureSummary:
      task.status === "blocked" ? `${task.title} is blocked before command evidence can complete.` : undefined,
    outputSummary: `${task.outcome} Command output has not been captured yet.`,
    relatedArtifactId,
    relatedTaskId: task.id
  });
}

export function getCommandBlocksForWorkspace(workspaceId: string): ReadonlyArray<CockpitCommandBlock> {
  assertWorkspaceId(workspaceId);

  const board = getWorkspaceBoard(workspaceId);
  const commandArtifact = getCockpitArtifactsByKind(workspaceId).command;

  return buildCommandBlocksFromTasks({
    workspaceId,
    relatedArtifactId: commandArtifact.id,
    timestampLabel: commandArtifact.timestampLabel,
    tasks: board.tasks
  });
}

export function buildCommandBlocksFromTasks(snapshot: CommandBlockTaskSnapshot): ReadonlyArray<CockpitCommandBlock> {
  const activeTasks = snapshot.tasks.filter(isCommandBackedTask);

  if (activeTasks.length === 0) {
    return [
      createCockpitCommandBlock({
        id: `${snapshot.workspaceId}-command-empty`,
        workspaceId: snapshot.workspaceId,
        commandLabel: "No command has run yet",
        sourceRole: "Operator",
        status: "not-run",
        timestampLabel: snapshot.timestampLabel,
        redactionState: "not-required",
        outputSummary: "Command blocks will appear after a task starts running through a workflow or agent lane.",
        relatedArtifactId: snapshot.relatedArtifactId
      })
    ];
  }

  return activeTasks.map((task) =>
    createTemplateCommandBlock(snapshot.workspaceId, snapshot.relatedArtifactId, snapshot.timestampLabel, task)
  );
}

export function getCommandBlocksByArtifactId(
  blocks: ReadonlyArray<CockpitCommandBlock>,
  relatedArtifactId: string
): ReadonlyArray<CockpitCommandBlock> {
  return blocks.filter((block) => block.relatedArtifactId === relatedArtifactId);
}

export function getCommandBlocksByTaskId(
  blocks: ReadonlyArray<CockpitCommandBlock>,
  relatedTaskId: string
): ReadonlyArray<CockpitCommandBlock> {
  return blocks.filter((block) => block.relatedTaskId === relatedTaskId);
}
