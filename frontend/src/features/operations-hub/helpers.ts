import type {
  OperationsHubProcessAction,
  OperationsHubProcessDetail,
  OperationsHubProcessSummary,
  OperationsReviewableOutputPlan,
  OperationsTimelineItem,
  OperationsTimelineSummary,
  OperationsTimelineTone
} from "./types";

function normalizeStatus(status: string): string {
  return status.trim().toLowerCase();
}

const ACTIVE_STATUSES = new Set(["active", "running", "in_progress", "processing", "executing"]);
const ATTENTION_STATUSES = new Set([
  "failed",
  "error",
  "crashed",
  "rejected",
  "revoked",
  "cancelled",
  "expired",
  "paused",
  "suspended",
  "pending",
  "draft"
]);
const DONE_STATUSES = new Set(["completed", "success", "validated", "published", "verified"]);

export function getStatusClass(status: string): string {
  const normalized = normalizeStatus(status);
  if (normalized === "running" || normalized === "active") {
    return "status-running";
  }
  if (normalized === "validated" || normalized === "published") {
    return "status-ok";
  }
  if (normalized === "paused" || normalized === "suspended") {
    return "status-paused";
  }
  if (normalized === "pending" || normalized === "draft") {
    return "status-pending";
  }
  if (normalized === "candidate") {
    return "status-pending";
  }
  if (normalized === "cancelled" || normalized === "expired") {
    return "status-cancelled";
  }
  if (normalized === "completed" || normalized === "success" || normalized === "verified") {
    return "status-ok";
  }
  if (
    normalized === "failed" ||
    normalized === "error" ||
    normalized === "crashed" ||
    normalized === "rejected" ||
    normalized === "revoked"
  ) {
    return "status-error";
  }
  return "status-pending";
}

export function getStatusLabel(status: string): string {
  const text = status.replace(/[_-]+/g, " ").trim();
  if (text === "") {
    return "Unknown";
  }
  return text
    .split(" ")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function filterAndSortProcesses(
  processes: OperationsHubProcessSummary[],
  statusFilter: string,
  textFilter: string
): OperationsHubProcessSummary[] {
  const normalizedStatusFilter = normalizeStatus(statusFilter);
  const normalizedTextFilter = textFilter.trim().toLowerCase();

  return [...processes]
    .filter((process) => {
      if (normalizedStatusFilter === "all" || normalizedStatusFilter === "") {
        return true;
      }
      return normalizeStatus(process.status) === normalizedStatusFilter;
    })
    .filter((process) => {
      if (normalizedTextFilter === "") {
        return true;
      }
      return (
        process.name.toLowerCase().includes(normalizedTextFilter) ||
        process.id.toLowerCase().includes(normalizedTextFilter) ||
        process.type.toLowerCase().includes(normalizedTextFilter)
      );
    })
    .sort((left, right) => {
      return new Date(right.started_at).getTime() - new Date(left.started_at).getTime();
    });
}

export function getTimelineTone(status: string): OperationsTimelineTone {
  const normalized = normalizeStatus(status);
  if (ACTIVE_STATUSES.has(normalized)) {
    return "active";
  }
  if (ATTENTION_STATUSES.has(normalized)) {
    return "attention";
  }
  if (DONE_STATUSES.has(normalized)) {
    return "done";
  }
  return "neutral";
}

export function summarizeOperations(
  processes: OperationsHubProcessSummary[]
): OperationsTimelineSummary {
  const summary = processes.reduce(
    (counts, process) => {
      const tone = getTimelineTone(process.status);
      if (tone === "active") {
        counts.active += 1;
      } else if (tone === "attention") {
        counts.attention += 1;
      } else if (tone === "done") {
        counts.done += 1;
      }
      return counts;
    },
    { active: 0, attention: 0, done: 0 }
  );

  if (processes.length === 0) {
    return {
      total: 0,
      ...summary,
      primaryMessage: "No agent work is running right now.",
      nextAction: "Launch a workflow from the catalog when you are ready."
    };
  }

  if (summary.attention > 0) {
    return {
      total: processes.length,
      ...summary,
      primaryMessage: `${summary.attention} item${summary.attention === 1 ? "" : "s"} need attention.`,
      nextAction: "Open the highlighted item, read the latest step, then resume, cancel, or fix the input."
    };
  }

  if (summary.active > 0) {
    return {
      total: processes.length,
      ...summary,
      primaryMessage: `${summary.active} item${summary.active === 1 ? " is" : "s are"} actively working.`,
      nextAction: "Watch the timeline for the next completed step or interruption."
    };
  }

  return {
    total: processes.length,
    ...summary,
    primaryMessage: "All visible work is finished.",
    nextAction: "Review completed outputs or start the next workflow."
  };
}

function describeProcessType(type: string): string {
  return type.replace(/[_-]+/g, " ").trim() || "agent work";
}

function buildProcessTimelineCopy(process: OperationsHubProcessSummary): {
  title: string;
  description: string;
} {
  const tone = getTimelineTone(process.status);
  const processType = describeProcessType(process.type);
  const statusLabel = getStatusLabel(process.status).toLowerCase();
  if (tone === "active") {
    return {
      title: `${process.name} is running`,
      description: `AGENT-33 is actively working on this ${processType}.`
    };
  }
  if (tone === "attention") {
    return {
      title: `${process.name} needs attention`,
      description: `This ${processType} is ${statusLabel}. Open it to decide whether to resume, cancel, or fix inputs.`
    };
  }
  if (tone === "done") {
    return {
      title: `${process.name} finished`,
      description: `This ${processType} reached ${statusLabel}. Review the output before starting follow-up work.`
    };
  }
  return {
    title: `${process.name} updated`,
    description: `This ${processType} is currently ${statusLabel}.`
  };
}

function buildActionTimelineItem(
  process: OperationsHubProcessDetail,
  action: OperationsHubProcessAction
): OperationsTimelineItem {
  const isComplete = action.completed_at !== null;
  return {
    id: `${process.id}:${action.step_id}`,
    processId: process.id,
    title: isComplete ? `${action.step_id} completed` : `${action.step_id} is in progress`,
    description: `${action.action_count} recorded action${
      action.action_count === 1 ? "" : "s"
    } for ${process.name}.`,
    timestamp: action.completed_at ?? process.started_at,
    tone: isComplete ? "done" : "active"
  };
}

export function buildOperationsTimeline(
  processes: OperationsHubProcessSummary[],
  selectedProcess: OperationsHubProcessDetail | null,
  limit = 8
): OperationsTimelineItem[] {
  const processItems = processes.map((process) => {
    const copy = buildProcessTimelineCopy(process);
    return {
      id: `${process.id}:status`,
      processId: process.id,
      title: copy.title,
      description: copy.description,
      timestamp: process.started_at,
      tone: getTimelineTone(process.status)
    };
  });

  const actionItems =
    selectedProcess?.actions?.map((action) => buildActionTimelineItem(selectedProcess, action)) ?? [];

  return [...actionItems, ...processItems]
    .sort((left, right) => new Date(right.timestamp).getTime() - new Date(left.timestamp).getTime())
    .slice(0, limit);
}

export function canPause(detail: OperationsHubProcessDetail): boolean {
  return detail.type === "autonomy_budget" && normalizeStatus(detail.status) === "active";
}

export function canResume(detail: OperationsHubProcessDetail): boolean {
  return detail.type === "autonomy_budget" && normalizeStatus(detail.status) === "suspended";
}

export function canCancel(detail: OperationsHubProcessDetail): boolean {
  const normalized = normalizeStatus(detail.status);
  if (detail.type === "trace") {
    return normalized === "running";
  }
  if (detail.type === "autonomy_budget") {
    return normalized === "active" || normalized === "suspended" || normalized === "draft";
  }
  return false;
}

export function buildReviewableOutputPlan(
  detail: OperationsHubProcessDetail
): OperationsReviewableOutputPlan {
  const tone = getTimelineTone(detail.status);
  const actionCount = detail.actions?.reduce((total, action) => total + action.action_count, 0) ?? 0;
  const stepCount = detail.actions?.length ?? 0;
  const processType = describeProcessType(detail.type);

  if (tone === "attention") {
    return {
      statusLabel: `${getStatusLabel(detail.status)} needs operator review`,
      primaryAction: "Retry only after checking the latest failure, inputs, and approval gate.",
      fixAction: "Create a fix task with the failing step, command evidence, and expected artifact.",
      reviewGate: "Human review required before resume or rerun.",
      budgetLabel: `${Math.max(1, stepCount)} step${stepCount === 1 ? "" : "s"} to inspect / lower autonomy`,
      artifacts: ["Failure summary", "Replay notes", "Fix checklist"]
    };
  }

  if (tone === "active") {
    return {
      statusLabel: `${getStatusLabel(detail.status)} and producing reviewable output`,
      primaryAction: "Watch the timeline and wait for the next step boundary before interrupting.",
      fixAction: "Capture a checkpoint if the run drifts or budget pressure increases.",
      reviewGate: "Review generated artifacts before approving follow-up actions.",
      budgetLabel: `${Math.max(1, actionCount)} recorded action${actionCount === 1 ? "" : "s"} / live budget`,
      artifacts: ["Live timeline", "Current command log", "Pending approval queue"]
    };
  }

  if (tone === "done") {
    return {
      statusLabel: `${getStatusLabel(detail.status)} and ready for output review`,
      primaryAction: "Review artifacts and decide whether to continue, export, or close.",
      fixAction: "Open a follow-up task only if validation or review evidence is missing.",
      reviewGate: "Outcome review before next workflow.",
      budgetLabel: `${Math.max(1, stepCount)} completed step${stepCount === 1 ? "" : "s"} / no active spend`,
      artifacts: ["Outcome summary", "Validation evidence", "Follow-up queue"]
    };
  }

  return {
    statusLabel: `${getStatusLabel(detail.status)} with limited evidence`,
    primaryAction: `Inspect this ${processType} before choosing a control action.`,
    fixAction: "Attach logs or replay evidence before retrying.",
    reviewGate: "Operator decision required.",
    budgetLabel: "Budget unknown",
    artifacts: ["Run summary", "Available metadata", "Operator notes"]
  };
}

export function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}
