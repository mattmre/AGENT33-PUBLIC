export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "unknown";

export interface RunDashboardCard {
  id: string;
  title: string;
  agent: string;
  status: RunStatus;
  outcome: string;
  updatedAt: string;
  artifacts: string[];
  nextActions: string[];
  replayHint: string;
  resultPath: string;
  proofItems: string[];
  proofSections: RunProofSection[];
}

export interface RunProofSection {
  label: string;
  count: number;
  items: string[];
}

type SessionRecord = Record<string, unknown>;

function asRecord(value: unknown): SessionRecord {
  return value && typeof value === "object" ? (value as SessionRecord) : {};
}

function readString(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === "string" && value.trim() !== "") {
      return value.trim();
    }
  }
  return "";
}

function readList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => {
      if (typeof item === "string") {
        return item;
      }
      const record = asRecord(item);
      return readString(
        record.name,
        record.title,
        record.message,
        record.path,
        record.type,
        record.label,
        record.id
      );
    })
    .filter(Boolean);
}

export function normalizeRunStatus(value: unknown): RunStatus {
  const status = readString(value).toLowerCase();
  if (["queued", "pending", "scheduled"].includes(status)) {
    return "queued";
  }
  if (["running", "in_progress", "active", "started"].includes(status)) {
    return "running";
  }
  if (["success", "succeeded", "complete", "completed", "done"].includes(status)) {
    return "succeeded";
  }
  if (["failed", "failure", "error", "cancelled", "canceled"].includes(status)) {
    return "failed";
  }
  return "unknown";
}

function buildArtifacts(session: SessionRecord): string[] {
  const evidence = readList(session.evidence);
  if (evidence.length > 0) {
    return evidence.slice(0, 5);
  }

  const explicitArtifacts = readList(session.artifacts);
  if (explicitArtifacts.length > 0) {
    return explicitArtifacts.slice(0, 5);
  }

  const inferred = [
    readList(session.files).length > 0 ? "Files" : "",
    readList(session.diffs).length > 0 ? "Diffs" : "",
    readList(session.logs).length > 0 ? "Logs" : "",
    readList(session.screenshots).length > 0 ? "Screenshots" : ""
  ].filter(Boolean);

  return inferred.length > 0 ? inferred : ["Run summary"];
}

function buildProofSection(label: string, items: string[]): RunProofSection | null {
  if (items.length === 0) {
    return null;
  }
  return {
    label,
    count: items.length,
    items: items.slice(0, 4)
  };
}

export function buildRunProofSections(session: SessionRecord): RunProofSection[] {
  const evidence = readList(session.evidence);
  const artifacts = readList(session.artifacts);
  const events = readList(session.events);
  const logs = readList(session.logs);
  const verifications = readList(session.verifications);
  const result = readString(session.result_path, session.result_url, session.output_path);

  return [
    buildProofSection("Evidence", evidence),
    buildProofSection("Artifacts", artifacts),
    buildProofSection("Events", events),
    buildProofSection("Verification", verifications),
    buildProofSection("Logs", logs),
    result ? buildProofSection("Result", [result]) : null
  ].filter((section): section is RunProofSection => section !== null);
}

function normalizeLedgerRecord(session: SessionRecord): SessionRecord {
  const task = asRecord(session.task);
  const run = asRecord(session.run);
  if (Object.keys(task).length === 0 || Object.keys(run).length === 0) {
    return session;
  }

  return {
    ...session,
    id: readString(run.id),
    title: readString(task.title),
    status: readString(run.status),
    updated_at: readString(run.created_at, task.created_at),
    agent: readString(run.source_id) || "Run ledger",
    summary: readString(session.summary) || `Ledger run for ${readString(task.title, run.id)}`,
    evidence: session.evidence,
    events: session.events
  };
}

export function buildRunNextActions(status: RunStatus): string[] {
  if (status === "failed") {
    return ["Review failure", "Replay with safer settings", "Open logs"];
  }
  if (status === "succeeded") {
    return ["Review artifacts", "Continue next step", "Export summary"];
  }
  if (status === "running") {
    return ["Watch timeline", "Check approvals", "Open logs"];
  }
  if (status === "queued") {
    return ["Review queue", "Confirm provider", "Check approvals"];
  }
  return ["Inspect details", "Find artifacts", "Decide next step"];
}

export function buildRunDashboardCards(sessions: unknown[]): RunDashboardCard[] {
  return sessions.map((session, index) => {
    const record = normalizeLedgerRecord(asRecord(session));
    const id = readString(record.id, record.session_id, record.run_id) || `session-${index + 1}`;
    const status = normalizeRunStatus(readString(record.status, record.state, record.result_status));
    const agent = readString(record.agent, record.agent_name, record.owner, record.created_by) || "Unassigned agent";
    const title = readString(record.title, record.name, record.goal, record.task) || `Run ${id}`;
    const outcome =
      readString(record.outcome, record.summary, record.result, record.message) ||
      (status === "unknown" ? "No outcome reported yet." : "Outcome summary not attached yet.");
    const updatedAt = readString(record.updated_at, record.completed_at, record.created_at) || "Time unknown";
    const artifacts = buildArtifacts(record);
    const eventCount = Array.isArray(record.events) ? record.events.length : 0;
    const proofSections = buildRunProofSections(record);
    const proofItems = [
      artifacts.length > 0 ? `${artifacts.length} artifact${artifacts.length === 1 ? "" : "s"}` : "",
      eventCount > 0 ? `${eventCount} event${eventCount === 1 ? "" : "s"}` : "",
      proofSections.length > 0
        ? `${proofSections.length} proof section${proofSections.length === 1 ? "" : "s"}`
        : "",
      status === "succeeded" ? "Outcome ready" : "",
      status === "failed" ? "Failure evidence required" : ""
    ].filter(Boolean);

    return {
      id,
      title,
      agent,
      status,
      outcome,
      updatedAt,
      artifacts,
      nextActions: buildRunNextActions(status),
      resultPath: `/results/${encodeURIComponent(id)}`,
      proofItems,
      proofSections,
      replayHint:
        status === "failed"
          ? "Replay after reviewing logs and lowering autonomy."
          : "Replay can reuse this run context when backend support is available."
    };
  });
}
