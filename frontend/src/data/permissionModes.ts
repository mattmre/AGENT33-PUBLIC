export const PERMISSION_MODE_IDS = [
  "observe",
  "ask",
  "workspace",
  "pr-first",
  "restricted"
] as const;

export type PermissionModeId = (typeof PERMISSION_MODE_IDS)[number];

export interface PermissionModeDefinition {
  readonly id: PermissionModeId;
  readonly label: string;
  readonly headline: string;
  readonly description: string;
  readonly allowedNow: string;
  readonly reviewGate: string;
  readonly tone: "safe" | "guided" | "active" | "review" | "locked";
}

export const DEFAULT_PERMISSION_MODE_ID: PermissionModeId = "ask";

export const PERMISSION_MODES: ReadonlyArray<PermissionModeDefinition> = [
  {
    id: "observe",
    label: "Observe only",
    headline: "Watch without changing anything.",
    description: "Agents can explain, inspect visible state, and draft plans, but execution stays off.",
    allowedNow: "Read-only planning and status review",
    reviewGate: "User must approve every action",
    tone: "safe"
  },
  {
    id: "ask",
    label: "Ask before action",
    headline: "Confirm before tools or changes run.",
    description: "Best default for beginners: AGENT33 can prepare the next step and asks before acting.",
    allowedNow: "Plans, setup guidance, and queued actions",
    reviewGate: "User approval before commands, writes, or external changes",
    tone: "guided"
  },
  {
    id: "workspace",
    label: "Auto within workspace",
    headline: "Low-risk workspace actions can run.",
    description: "Routine actions inside the selected workspace may proceed while risky steps stay gated.",
    allowedNow: "Workspace-local build, test, lint, and file edits",
    reviewGate: "Approval required for secrets, network, deletion, and external side effects",
    tone: "active"
  },
  {
    id: "pr-first",
    label: "PR-first implementation",
    headline: "Prefer reviewable branches and pull requests.",
    description: "Implementation work should land through branches, checks, review comments, and PR outcomes.",
    allowedNow: "Branch-based implementation and validation",
    reviewGate: "Merge, destructive changes, and high-risk automation remain gated",
    tone: "review"
  },
  {
    id: "restricted",
    label: "Restricted / high-risk locked",
    headline: "High-risk controls stay locked.",
    description: "Use this when secrets, production targets, deletion, or broad automation need extra caution.",
    allowedNow: "Guidance, triage, and safe route recommendations",
    reviewGate: "Explicit approval required before any high-risk surface opens",
    tone: "locked"
  }
];

const PERMISSION_MODE_ID_SET = new Set<string>(PERMISSION_MODE_IDS);

export function isPermissionModeId(value: string | null): value is PermissionModeId {
  return value !== null && PERMISSION_MODE_ID_SET.has(value);
}

export function getPermissionMode(modeId: PermissionModeId): PermissionModeDefinition {
  const mode = PERMISSION_MODES.find((candidate) => candidate.id === modeId);
  if (!mode) {
    throw new Error(
      `Permission mode configuration is unavailable for modeId "${modeId}". Known IDs: ${PERMISSION_MODE_IDS.join(", ")}.`
    );
  }

  return mode;
}
