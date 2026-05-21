import type { WorkspaceSessionId } from "./workspaces";

export const DEMO_MODE = (import.meta.env.VITE_DEMO_MODE ?? "false") === "true";

export type WorkspaceRecoveryStatus = "ready" | "attention" | "blocked";

export interface WorkspaceRecoverySnapshot {
  readonly id: string;
  readonly label: string;
  readonly status: WorkspaceRecoveryStatus;
  readonly resumeAction: string;
  readonly rollbackAction: string;
  readonly budgetLabel: string;
  readonly artifactCount: number;
}

export interface WorkspaceRecoverySummary {
  readonly workspaceId: WorkspaceSessionId;
  readonly primaryMessage: string;
  readonly nextAction: string;
  readonly snapshots: ReadonlyArray<WorkspaceRecoverySnapshot>;
}

export const WORKSPACE_RECOVERY_SUMMARIES: ReadonlyArray<WorkspaceRecoverySummary> = [
  {
    workspaceId: "solo-builder",
    primaryMessage: "One safe resume point is ready.",
    nextAction: "Resume the guided plan or snapshot before starting a larger build.",
    snapshots: [
      {
        id: "solo-plan-snapshot",
        label: "Guided plan draft",
        status: "ready",
        resumeAction: "Resume planning",
        rollbackAction: "Restore intake baseline",
        budgetLabel: "1 agent / 30 min",
        artifactCount: 3
      }
    ]
  },
  {
    workspaceId: "research-build",
    primaryMessage: "Research evidence can resume from the last cited handoff.",
    nextAction: "Review the evidence snapshot before converting findings into build work.",
    snapshots: [
      {
        id: "research-evidence-snapshot",
        label: "Evidence collection",
        status: "attention",
        resumeAction: "Resume evidence pass",
        rollbackAction: "Return to scoped questions",
        budgetLabel: "2 agents / 45 min",
        artifactCount: 5
      }
    ]
  },
  {
    workspaceId: "test-review",
    primaryMessage: "Merge handoff is blocked until review evidence is refreshed.",
    nextAction: "Resume failed-check review before preparing merge notes.",
    snapshots: [
      {
        id: "quality-review-snapshot",
        label: "Validation checkpoint",
        status: "blocked",
        resumeAction: "Resume failure review",
        rollbackAction: "Return to pre-test state",
        budgetLabel: "2 agents / 25 min",
        artifactCount: 4
      }
    ]
  },
  {
    workspaceId: "shipyard",
    primaryMessage: "Multi-agent work has two recoverable checkpoints.",
    nextAction: "Resume the active build lane before assigning new shipyard work.",
    snapshots: [
      {
        id: "shipyard-build-snapshot",
        label: "Active build lane",
        status: "attention",
        resumeAction: "Resume build lane",
        rollbackAction: "Restore last merged baseline",
        budgetLabel: "4 agents / 60 min",
        artifactCount: 8
      },
      {
        id: "shipyard-review-snapshot",
        label: "Review handoff",
        status: "ready",
        resumeAction: "Open review lane",
        rollbackAction: "Return to pre-review branch",
        budgetLabel: "1 reviewer / 20 min",
        artifactCount: 3
      }
    ]
  }
];

export function getWorkspaceRecoverySummary(workspaceId: WorkspaceSessionId): WorkspaceRecoverySummary {
  if (!DEMO_MODE) {
    return { workspaceId, primaryMessage: "", nextAction: "", snapshots: [] };
  }
  const summary = WORKSPACE_RECOVERY_SUMMARIES.find((candidate) => candidate.workspaceId === workspaceId);
  if (!summary) {
    throw new Error("Workspace recovery summary is unavailable.");
  }

  return summary;
}
