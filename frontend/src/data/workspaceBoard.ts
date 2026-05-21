import type { WorkspaceSessionId } from "./workspaces";

export const DEMO_MODE = (import.meta.env.VITE_DEMO_MODE ?? "false") === "true";

export const WORKSPACE_TASK_STATUSES = ["todo", "running", "review", "complete", "blocked"] as const;

export type WorkspaceTaskStatus = (typeof WORKSPACE_TASK_STATUSES)[number];

export interface WorkspaceTaskCard {
  readonly id: string;
  readonly title: string;
  readonly outcome: string;
  readonly status: WorkspaceTaskStatus;
  readonly ownerRole: WorkspaceAgentRole;
}

export type WorkspaceAgentRole = "Coordinator" | "Builder" | "Scout" | "Reviewer";

export interface WorkspaceAgentCard {
  readonly id: string;
  readonly name: string;
  readonly role: WorkspaceAgentRole;
  readonly focus: string;
  readonly state: "Ready" | "Working" | "Reviewing" | "Waiting";
}

export interface WorkspaceBoard {
  readonly workspaceId: WorkspaceSessionId;
  readonly tasks: ReadonlyArray<WorkspaceTaskCard>;
  readonly agents: ReadonlyArray<WorkspaceAgentCard>;
}

export const WORKSPACE_TASK_STATUS_LABELS: Record<WorkspaceTaskStatus, string> = {
  todo: "Todo",
  running: "Running",
  review: "Review",
  complete: "Complete",
  blocked: "Blocked"
};

export const WORKSPACE_BOARDS: ReadonlyArray<WorkspaceBoard> = [
  {
    workspaceId: "solo-builder",
    tasks: [
      {
        id: "solo-intake",
        title: "Capture the build request",
        outcome: "Plain-language goal, constraints, and success criteria.",
        status: "todo",
        ownerRole: "Coordinator"
      },
      {
        id: "solo-plan",
        title: "Draft the first workflow",
        outcome: "Recommended starter plan with safe next action.",
        status: "running",
        ownerRole: "Builder"
      },
      {
        id: "solo-review",
        title: "Review generated outputs",
        outcome: "Operator-ready summary and artifacts to approve.",
        status: "review",
        ownerRole: "Reviewer"
      }
    ],
    agents: [
      {
        id: "solo-coordinator",
        name: "Guide",
        role: "Coordinator",
        focus: "Keeps the user on the safest next step.",
        state: "Ready"
      },
      {
        id: "solo-builder",
        name: "Builder",
        role: "Builder",
        focus: "Turns selected workflows into implementation tasks.",
        state: "Working"
      }
    ]
  },
  {
    workspaceId: "research-build",
    tasks: [
      {
        id: "research-question",
        title: "Define research questions",
        outcome: "Scope and comparison criteria for the research loop.",
        status: "todo",
        ownerRole: "Coordinator"
      },
      {
        id: "research-scout",
        title: "Collect evidence",
        outcome: "Sources, observations, and confidence notes.",
        status: "running",
        ownerRole: "Scout"
      },
      {
        id: "research-convert",
        title: "Convert findings into work",
        outcome: "Prioritized implementation backlog.",
        status: "review",
        ownerRole: "Builder"
      },
      {
        id: "research-handoff",
        title: "Review research handoff",
        outcome: "Approved direction for the next build slice.",
        status: "complete",
        ownerRole: "Reviewer"
      }
    ],
    agents: [
      {
        id: "research-coordinator",
        name: "Coordinator",
        role: "Coordinator",
        focus: "Maintains questions, scope, and decision gates.",
        state: "Ready"
      },
      {
        id: "research-scout",
        name: "Scout",
        role: "Scout",
        focus: "Finds competitor patterns and supporting evidence.",
        state: "Working"
      },
      {
        id: "research-reviewer",
        name: "Reviewer",
        role: "Reviewer",
        focus: "Checks whether research is actionable and cited.",
        state: "Reviewing"
      }
    ]
  },
  {
    workspaceId: "test-review",
    tasks: [
      {
        id: "quality-scope",
        title: "Identify validation scope",
        outcome: "Tests, lint, build, and review targets.",
        status: "todo",
        ownerRole: "Coordinator"
      },
      {
        id: "quality-run",
        title: "Run checks",
        outcome: "Fresh validation result for the selected change.",
        status: "running",
        ownerRole: "Builder"
      },
      {
        id: "quality-review",
        title: "Review failures and comments",
        outcome: "Fixes ready for PR update.",
        status: "review",
        ownerRole: "Reviewer"
      },
      {
        id: "quality-merge",
        title: "Prepare merge handoff",
        outcome: "Merge-safe summary and final status.",
        status: "blocked",
        ownerRole: "Coordinator"
      }
    ],
    agents: [
      {
        id: "quality-builder",
        name: "Fixer",
        role: "Builder",
        focus: "Applies fixes from test and review feedback.",
        state: "Working"
      },
      {
        id: "quality-reviewer",
        name: "Reviewer",
        role: "Reviewer",
        focus: "Verifies the change is merge-ready.",
        state: "Reviewing"
      }
    ]
  },
  {
    workspaceId: "shipyard",
    tasks: [
      {
        id: "shipyard-scope",
        title: "Break work into lanes",
        outcome: "Separate research, build, review, and merge tracks.",
        status: "todo",
        ownerRole: "Coordinator"
      },
      {
        id: "shipyard-scout",
        title: "Scout implementation risks",
        outcome: "Known dependencies and drift risks.",
        status: "running",
        ownerRole: "Scout"
      },
      {
        id: "shipyard-build",
        title: "Build the next slice",
        outcome: "PR-ready implementation with tests.",
        status: "running",
        ownerRole: "Builder"
      },
      {
        id: "shipyard-review",
        title: "Review and reconcile",
        outcome: "Actionable comments resolved before merge.",
        status: "review",
        ownerRole: "Reviewer"
      },
      {
        id: "shipyard-log",
        title: "Update session handoff",
        outcome: "Durable state for the next fresh agent.",
        status: "complete",
        ownerRole: "Coordinator"
      }
    ],
    agents: [
      {
        id: "shipyard-coordinator",
        name: "Coordinator",
        role: "Coordinator",
        focus: "Sequences work and prevents PR drift.",
        state: "Ready"
      },
      {
        id: "shipyard-scout",
        name: "Scout",
        role: "Scout",
        focus: "Researches patterns and risk before build work.",
        state: "Working"
      },
      {
        id: "shipyard-builder",
        name: "Builder",
        role: "Builder",
        focus: "Implements the active slice.",
        state: "Working"
      },
      {
        id: "shipyard-reviewer",
        name: "Reviewer",
        role: "Reviewer",
        focus: "Reviews changed code and validates the handoff.",
        state: "Reviewing"
      }
    ]
  }
];

export function getWorkspaceBoard(workspaceId: WorkspaceSessionId): WorkspaceBoard {
  if (!DEMO_MODE) {
    return { workspaceId, tasks: [], agents: [] };
  }
  const board = WORKSPACE_BOARDS.find((candidate) => candidate.workspaceId === workspaceId);
  if (!board) {
    throw new Error("Workspace board is unavailable.");
  }

  return board;
}

function createEmptyTaskBuckets(): Record<WorkspaceTaskStatus, WorkspaceTaskCard[]> {
  return {
    todo: [],
    running: [],
    review: [],
    complete: [],
    blocked: []
  };
}

export function groupWorkspaceTasksByStatus(
  tasks: ReadonlyArray<WorkspaceTaskCard>
): Record<WorkspaceTaskStatus, WorkspaceTaskCard[]> {
  const tasksByStatus = createEmptyTaskBuckets();

  for (const task of tasks) {
    tasksByStatus[task.status].push(task);
  }

  return tasksByStatus;
}

export function getWorkspaceTaskCounts(workspaceId: WorkspaceSessionId): Record<WorkspaceTaskStatus, number> {
  const tasksByStatus = groupWorkspaceTasksByStatus(getWorkspaceBoard(workspaceId).tasks);

  return {
    todo: tasksByStatus.todo.length,
    running: tasksByStatus.running.length,
    review: tasksByStatus.review.length,
    complete: tasksByStatus.complete.length,
    blocked: tasksByStatus.blocked.length
  };
}
