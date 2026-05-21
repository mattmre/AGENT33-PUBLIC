import { PERMISSION_MODE_IDS, type PermissionModeId } from "./permissionModes";

export const PERMISSION_ACTION_CATEGORIES = [
  "review-artifact",
  "start-workflow",
  "run-command",
  "approve-action",
  "merge-pr"
] as const;

export type PermissionActionCategory = (typeof PERMISSION_ACTION_CATEGORIES)[number];
export type PermissionActionTone = "available" | "approval-required" | "locked";

export interface PermissionActionGate {
  readonly action: PermissionActionCategory;
  readonly allowed: boolean;
  readonly tone: PermissionActionTone;
  readonly label: string;
  readonly reason: string;
}

const ACTION_LABELS: Record<PermissionActionCategory, string> = {
  "review-artifact": "Review allowed",
  "start-workflow": "Workflow launch",
  "run-command": "Command run",
  "approve-action": "Approval decision",
  "merge-pr": "Merge decision"
};

const ACTION_GATE_MATRIX: Record<PermissionModeId, Record<PermissionActionCategory, Omit<PermissionActionGate, "action" | "label">>> = {
  observe: {
    "review-artifact": {
      allowed: true,
      tone: "available",
      reason: "Read-only artifact review is available."
    },
    "start-workflow": {
      allowed: false,
      tone: "locked",
      reason: "Observe only keeps workflow launch read-only until you choose a more active mode."
    },
    "run-command": {
      allowed: false,
      tone: "locked",
      reason: "Observe only blocks command execution."
    },
    "approve-action": {
      allowed: false,
      tone: "locked",
      reason: "Observe only cannot approve actions."
    },
    "merge-pr": {
      allowed: false,
      tone: "locked",
      reason: "Observe only cannot merge or ship changes."
    }
  },
  ask: {
    "review-artifact": {
      allowed: true,
      tone: "available",
      reason: "Review is safe in ask mode."
    },
    "start-workflow": {
      allowed: true,
      tone: "approval-required",
      reason: "AGENT33 will ask before tools, writes, or external changes run."
    },
    "run-command": {
      allowed: true,
      tone: "approval-required",
      reason: "Commands require operator approval before execution."
    },
    "approve-action": {
      allowed: true,
      tone: "approval-required",
      reason: "Approve or request changes before AGENT33 continues."
    },
    "merge-pr": {
      allowed: true,
      tone: "approval-required",
      reason: "Merges remain explicitly gated."
    }
  },
  workspace: {
    "review-artifact": {
      allowed: true,
      tone: "available",
      reason: "Artifact review is available."
    },
    "start-workflow": {
      allowed: true,
      tone: "available",
      reason: "Workspace-local workflow steps can start."
    },
    "run-command": {
      allowed: true,
      tone: "available",
      reason: "Workspace-local commands can run while risky steps stay gated."
    },
    "approve-action": {
      allowed: true,
      tone: "approval-required",
      reason: "High-risk actions still require approval."
    },
    "merge-pr": {
      allowed: false,
      tone: "locked",
      reason: "Switch to PR-first mode before merge decisions."
    }
  },
  "pr-first": {
    "review-artifact": {
      allowed: true,
      tone: "available",
      reason: "Artifact and PR review are available."
    },
    "start-workflow": {
      allowed: true,
      tone: "available",
      reason: "Branch-based workflow steps can start."
    },
    "run-command": {
      allowed: true,
      tone: "available",
      reason: "Validation and implementation commands can run in the branch workflow."
    },
    "approve-action": {
      allowed: true,
      tone: "approval-required",
      reason: "Review comments and high-risk steps remain gated."
    },
    "merge-pr": {
      allowed: true,
      tone: "approval-required",
      reason: "Merge requires explicit operator approval."
    }
  },
  restricted: {
    "review-artifact": {
      allowed: true,
      tone: "available",
      reason: "Guidance and review remain available."
    },
    "start-workflow": {
      allowed: false,
      tone: "locked",
      reason: "Restricted mode keeps workflow launch locked."
    },
    "run-command": {
      allowed: false,
      tone: "locked",
      reason: "Restricted mode blocks command execution."
    },
    "approve-action": {
      allowed: false,
      tone: "locked",
      reason: "Restricted mode blocks approvals until the mode changes."
    },
    "merge-pr": {
      allowed: false,
      tone: "locked",
      reason: "Restricted mode blocks merge decisions."
    }
  }
};

export function getPermissionActionGate(
  modeId: PermissionModeId,
  action: PermissionActionCategory
): PermissionActionGate {
  const modeGates = ACTION_GATE_MATRIX[modeId];
  if (!modeGates) {
    throw new Error(
      `Unknown permission mode ID "${modeId}" in getPermissionActionGate. Known mode IDs: ${PERMISSION_MODE_IDS.join(", ")}.`
    );
  }

  const gate = modeGates[action];
  const label = ACTION_LABELS[action];
  if (!gate || !label) {
    throw new Error(
      `Unknown permission action "${action}" for mode "${modeId}" in getPermissionActionGate. Known actions: ${PERMISSION_ACTION_CATEGORIES.join(", ")}.`
    );
  }

  return {
    action,
    label,
    ...gate
  };
}

