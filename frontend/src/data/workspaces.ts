export const DEMO_MODE = (import.meta.env.VITE_DEMO_MODE ?? "false") === "true";

export const WORKSPACE_SESSION_IDS = [
  "solo-builder",
  "research-build",
  "test-review",
  "shipyard"
] as const;

export type WorkspaceSessionId = (typeof WORKSPACE_SESSION_IDS)[number];

export interface WorkspaceSessionSummary {
  readonly id: WorkspaceSessionId;
  readonly name: string;
  readonly template: string;
  readonly goal: string;
  readonly status: "Ready" | "Planning" | "Running";
  readonly updatedLabel: string;
  readonly agents: number;
  readonly tasks: number;
}

export const DEFAULT_WORKSPACE_SESSION_ID: WorkspaceSessionId = "solo-builder";

export const WORKSPACE_SESSIONS: ReadonlyArray<WorkspaceSessionSummary> = [
  {
    id: "solo-builder",
    name: "Local Shipyard",
    template: "Solo Builder",
    goal: "Turn a plain-language idea into a guided build plan.",
    status: "Ready",
    updatedLabel: "Default workspace",
    agents: 2,
    tasks: 3
  },
  {
    id: "research-build",
    name: "Research Sprint",
    template: "Research + Build",
    goal: "Collect evidence, compare options, and convert findings into implementation tasks.",
    status: "Planning",
    updatedLabel: "Template",
    agents: 3,
    tasks: 4
  },
  {
    id: "test-review",
    name: "Quality Gate",
    template: "Test + Review",
    goal: "Validate changes, review artifacts, and prepare a merge-ready handoff.",
    status: "Ready",
    updatedLabel: "Template",
    agents: 2,
    tasks: 4
  },
  {
    id: "shipyard",
    name: "Multi-Agent Shipyard",
    template: "Multi-Agent Shipyard",
    goal: "Coordinate scout, builder, reviewer, and operator lanes for larger work.",
    status: "Running",
    updatedLabel: "Template",
    agents: 4,
    tasks: 5
  }
];

const WORKSPACE_SESSION_ID_SET = new Set<string>(WORKSPACE_SESSION_IDS);

export function isWorkspaceSessionId(value: string | null): value is WorkspaceSessionId {
  return value !== null && WORKSPACE_SESSION_ID_SET.has(value);
}

export function getWorkspaceSession(id: WorkspaceSessionId): WorkspaceSessionSummary {
  const workspace = WORKSPACE_SESSIONS.find((candidate) => candidate.id === id);
  if (!workspace) {
    throw new Error(`Unknown workspace session: ${id}`);
  }

  return workspace;
}
