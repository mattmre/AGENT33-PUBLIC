import type { WorkflowStarterDraft, StarterKind } from "../features/workflow-starter/types";
import type { WorkspaceAgentRole } from "./workspaceBoard";
import { getWorkspaceBoard } from "./workspaceBoard";
import type { WorkspaceSessionId } from "./workspaces";
import { WORKSPACE_SESSION_IDS } from "./workspaces";

export interface WorkspaceTemplateStarter {
  readonly id: string;
  readonly workspaceId: WorkspaceSessionId;
  readonly label: string;
  readonly description: string;
  readonly kind: StarterKind;
  readonly assignedRole: WorkspaceAgentRole;
  readonly beginsWithTaskId: string;
  readonly goal: string;
  readonly output: string;
  readonly nextActionLabel: string;
}

const WORKSPACE_TEMPLATE_STARTERS: ReadonlyArray<WorkspaceTemplateStarter> = [
  {
    id: "solo-guided-build",
    workspaceId: "solo-builder",
    label: "Guided build plan",
    description: "Turn a plain-language idea into a safe first implementation plan.",
    kind: "automation-loop",
    assignedRole: "Coordinator",
    beginsWithTaskId: "solo-intake",
    goal: "Capture the user's idea, constraints, and success criteria, then propose a safe first build workflow.",
    output: "Beginner-readable build plan with assumptions, next action, risks, and validation steps.",
    nextActionLabel: "Start by capturing the build request"
  },
  {
    id: "solo-review-loop",
    workspaceId: "solo-builder",
    label: "Review generated outputs",
    description: "Package the first generated output into an operator review handoff.",
    kind: "improvement-loop",
    assignedRole: "Reviewer",
    beginsWithTaskId: "solo-review",
    goal: "Review generated outputs, identify missing evidence, and prepare a clear approval handoff.",
    output: "Approval-ready summary with artifacts, open questions, and recommended fixes.",
    nextActionLabel: "Open the generated output review"
  },
  {
    id: "research-evidence-loop",
    workspaceId: "research-build",
    label: "Research evidence loop",
    description: "Collect sources and convert findings into a prioritized build backlog.",
    kind: "research",
    assignedRole: "Scout",
    beginsWithTaskId: "research-scout",
    goal: "Collect competitor and implementation evidence, compare options, and recommend the next build slice.",
    output: "Cited research brief with confidence notes, tradeoffs, and implementation backlog.",
    nextActionLabel: "Start evidence collection"
  },
  {
    id: "research-to-build",
    workspaceId: "research-build",
    label: "Convert findings into work",
    description: "Translate research findings into build tasks with safety gates.",
    kind: "automation-loop",
    assignedRole: "Builder",
    beginsWithTaskId: "research-convert",
    goal: "Convert approved research findings into scoped tasks, acceptance criteria, and validation steps.",
    output: "Implementation-ready task list with owners, risks, and review checkpoints.",
    nextActionLabel: "Create the implementation backlog"
  },
  {
    id: "quality-validation-loop",
    workspaceId: "test-review",
    label: "Validation repair loop",
    description: "Run checks, summarize failures, and prepare a safe merge handoff.",
    kind: "improvement-loop",
    assignedRole: "Reviewer",
    beginsWithTaskId: "quality-review",
    goal: "Review validation failures and PR comments, then produce fixes and a merge-safe handoff.",
    output: "Validation status, fixes required, commands run, and final merge recommendation.",
    nextActionLabel: "Review failures and comments"
  },
  {
    id: "quality-check-runner",
    workspaceId: "test-review",
    label: "Run validation checks",
    description: "Create a repeatable checklist for tests, lint, build, and review evidence.",
    kind: "automation-loop",
    assignedRole: "Builder",
    beginsWithTaskId: "quality-run",
    goal: "Run selected validation checks and convert the output into reviewable evidence.",
    output: "Test, lint, build, and review evidence with failures and next actions.",
    nextActionLabel: "Run checks"
  },
  {
    id: "shipyard-slice-orchestration",
    workspaceId: "shipyard",
    label: "Multi-agent slice orchestration",
    description: "Coordinate scout, builder, reviewer, and handoff lanes for a PR-sized slice.",
    kind: "automation-loop",
    assignedRole: "Coordinator",
    beginsWithTaskId: "shipyard-scope",
    goal: "Break a larger request into research, build, review, and handoff lanes without losing PR sequencing.",
    output: "Lane plan with assigned roles, risks, artifacts, validation commands, and merge handoff.",
    nextActionLabel: "Break work into lanes"
  },
  {
    id: "shipyard-risk-scout",
    workspaceId: "shipyard",
    label: "Scout implementation risks",
    description: "Research dependencies and drift risks before builders change code.",
    kind: "research",
    assignedRole: "Scout",
    beginsWithTaskId: "shipyard-scout",
    goal: "Identify dependencies, PR drift risks, and validation needs before implementation begins.",
    output: "Risk brief with recommended files to inspect, non-goals, and validation plan.",
    nextActionLabel: "Scout implementation risks"
  }
];

export function getWorkspaceTemplateStarters(
  workspaceId: WorkspaceSessionId
): ReadonlyArray<WorkspaceTemplateStarter> {
  return WORKSPACE_TEMPLATE_STARTERS.filter((starter) => starter.workspaceId === workspaceId);
}

export function getPrimaryWorkspaceTemplateStarter(
  workspaceId: WorkspaceSessionId
): WorkspaceTemplateStarter | undefined {
  return getWorkspaceTemplateStarters(workspaceId)[0];
}

export function buildWorkspaceTemplateStarterDraft(starter: WorkspaceTemplateStarter): WorkflowStarterDraft {
  return {
    id: starter.id,
    name: starter.label,
    goal: starter.goal,
    kind: starter.kind,
    output: starter.output,
    author: starter.assignedRole.toLowerCase(),
    sourceLabel: `Workspace template: ${starter.label}`
  };
}

export function validateWorkspaceTemplateStarters(
  starters: ReadonlyArray<WorkspaceTemplateStarter> = WORKSPACE_TEMPLATE_STARTERS,
  workspaceIds: ReadonlyArray<WorkspaceSessionId> = WORKSPACE_SESSION_IDS
): ReadonlyArray<string> {
  const errors: string[] = [];

  for (const workspaceId of workspaceIds) {
    const workspaceStarters = starters.filter((starter) => starter.workspaceId === workspaceId);
    if (workspaceStarters.length === 0) {
      errors.push(`${workspaceId} has no recommended starters.`);
      continue;
    }

    const board = getWorkspaceBoard(workspaceId);

    for (const starter of workspaceStarters) {
      const beginsWithTask = board.tasks.find((task) => task.id === starter.beginsWithTaskId);
      if (!beginsWithTask) {
        errors.push(`${starter.id} starts with unknown task ${starter.beginsWithTaskId}.`);
        continue;
      }
      if (beginsWithTask.ownerRole !== starter.assignedRole) {
        errors.push(`${starter.id} role ${starter.assignedRole} does not match ${beginsWithTask.id} owner ${beginsWithTask.ownerRole}.`);
      }
    }
  }

  return errors;
}

export function assertWorkspaceTemplateStarters(): void {
  const errors = validateWorkspaceTemplateStarters();
  if (errors.length > 0) {
    throw new Error(`Workspace template starter configuration is invalid:\n- ${errors.join("\n- ")}`);
  }
}
