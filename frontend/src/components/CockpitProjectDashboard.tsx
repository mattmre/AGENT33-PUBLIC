import type { PermissionModeId } from "../data/permissionModes";
import { getPermissionMode } from "../data/permissionModes";
import { getPermissionActionGate } from "../data/permissionActionGates";
import type { WorkspaceSessionSummary } from "../data/workspaces";
import { getWorkspaceTaskCounts } from "../data/workspaceBoard";
import type { CockpitArtifact } from "../data/cockpitArtifacts";
import { buildCockpitOpsSafetySnapshot } from "../data/cockpitOpsSafety";
import { getSafetyGateCta, getTopSafetyGateRecords } from "../data/safetyGatePresentation";
import { SafetyGateIndicator } from "./SafetyGateIndicator";

interface CockpitProjectDashboardProps {
  workspace: WorkspaceSessionSummary;
  permissionModeId: PermissionModeId;
  onReviewCurrentWork: () => void;
  onOpenWorkflows: () => void;
  onOpenSafety: () => void;
  showDetailSections?: boolean;
}

function getRecommendedAction(workspace: WorkspaceSessionSummary): string {
  if (workspace.status === "Running") {
    return "Open Sessions & Runs to inspect live progress, blockers, and review gates.";
  }

  if (workspace.status === "Planning") {
    return "Choose a workflow and turn the planning notes into an executable task sequence.";
  }

  return "Start with a guided workflow so AGENT33 can create the first safe task plan.";
}

function getArtifactStatusLabel(artifact: CockpitArtifact): string {
  return `${artifact.status.replace(/-/g, " ")} / ${artifact.reviewState.replace(/-/g, " ")}`;
}

export function CockpitProjectDashboard({
  workspace,
  permissionModeId,
  onReviewCurrentWork,
  onOpenWorkflows,
  onOpenSafety,
  showDetailSections = true
}: CockpitProjectDashboardProps): JSX.Element {
  const permissionMode = getPermissionMode(permissionModeId);
  const taskCounts = getWorkspaceTaskCounts(workspace.id);
  const activeTaskCount = taskCounts.running + taskCounts.review + taskCounts.blocked;
  const attentionTaskLabel = activeTaskCount === 1 ? "1 task needs attention" : `${activeTaskCount} tasks need attention`;
  const opsSafety = buildCockpitOpsSafetySnapshot({ workspaceId: workspace.id, permissionModeId });
  const artifacts = opsSafety.artifacts;
  const safetyCta = getSafetyGateCta(opsSafety, permissionModeId);
  const safetySignals = getTopSafetyGateRecords(opsSafety.records, 4);
  const priorityGateRecords = safetySignals.slice(0, 3);
  const workflowGate = getPermissionActionGate(permissionModeId, "start-workflow");

  return (
    <section className="cockpit-project-dashboard" aria-label="Project cockpit dashboard">
      <header className="cockpit-dashboard-hero">
        <div>
          <span className="eyebrow">Project cockpit</span>
          <h2>{workspace.name}</h2>
          <p>{workspace.goal}</p>
          <p className="cockpit-dashboard-crumb">
            <span>WS</span>
            <b>{workspace.id}</b>
            <span className="sep">·</span>
            <span>TEMPLATE</span>
            <b>{workspace.template}</b>
            <span className="sep">·</span>
            <span>TASKS</span>
            <b>{workspace.tasks}</b>
          </p>
        </div>
        <div className="cockpit-dashboard-status" aria-label="Current project status">
          <span>{workspace.status}</span>
          <strong>{permissionMode.label}</strong>
        </div>
      </header>

      <div className="cockpit-dashboard-grid">
        <article className="cockpit-dashboard-card">
          <span className="eyebrow">Current run</span>
          <strong>{attentionTaskLabel}</strong>
          <p>{getRecommendedAction(workspace)}</p>
          <button type="button" onClick={onReviewCurrentWork}>
            Review task board
          </button>
        </article>

        <article className="cockpit-dashboard-card">
          <span className="eyebrow">Recommended next action</span>
          <strong>Use a guided workflow</strong>
          <p>Route the current project through a prebuilt starter instead of raw JSON or endpoint setup.</p>
          <button
            type="button"
            onClick={onOpenWorkflows}
            disabled={!workflowGate.allowed}
            aria-label={workflowGate.allowed ? "Choose workflow" : `Choose workflow locked: ${workflowGate.reason}`}
            aria-describedby="cockpit-dashboard-workflow-gate"
          >
            Choose workflow
          </button>
          <span
            id="cockpit-dashboard-workflow-gate"
            className={`permission-action-chip permission-action-chip-${workflowGate.tone}`}
          >
            {workflowGate.tone === "approval-required" ? "Approval required" : workflowGate.reason}
          </span>
        </article>

        <article className={`cockpit-dashboard-card cockpit-dashboard-safety-card safety-cta-${safetyCta.intent}`}>
          <span className="eyebrow">Safety gate</span>
          <strong>{opsSafety.summary.primaryMessage}</strong>
          <p>{opsSafety.summary.nextAction}</p>
          <SafetyGateIndicator permissionModeId={permissionModeId} opsSafetyRecords={opsSafety.records} isCompact />
          <div className="cockpit-dashboard-gate-list" aria-label="Top safety gate records">
            {priorityGateRecords.map((record) => (
              <span key={record.id} className={`safety-gate-row safety-gate-row-${record.status}`}>
                {record.title}: {record.nextActionLabel}
              </span>
            ))}
          </div>
          <button type="button" onClick={onOpenSafety}>
            {safetyCta.label}
          </button>
        </article>
      </div>

      {showDetailSections ? (
        <>
          <section className="cockpit-dashboard-timeline" aria-label="Artifact timeline">
            <div className="cockpit-dashboard-section-heading">
              <div>
                <span className="eyebrow">Artifacts</span>
                <h3>Review timeline</h3>
              </div>
              <p>Typed evidence cards show owner, review state, timestamp, and the next safe action.</p>
            </div>
            <div className="cockpit-dashboard-artifacts">
              {artifacts.map((artifact) => (
                <article key={artifact.id} className={`artifact-card artifact-card-${artifact.status}`}>
                  <span>{artifact.kind}</span>
                  <strong>{artifact.title}</strong>
                  <p>{artifact.summary}</p>
                  <dl className="artifact-card-meta">
                    <div>
                      <dt>Status</dt>
                      <dd>{getArtifactStatusLabel(artifact)}</dd>
                    </div>
                    <div>
                      <dt>Owner</dt>
                      <dd>{artifact.ownerRole}</dd>
                    </div>
                    <div>
                      <dt>Source</dt>
                      <dd>{artifact.sourceLabel}</dd>
                    </div>
                    <div>
                      <dt>Updated</dt>
                      <dd>{artifact.timestampLabel}</dd>
                    </div>
                  </dl>
                  <p className="artifact-card-next-action">Next: {artifact.nextActionLabel}</p>
                  <button
                    type="button"
                    aria-label={`Review ${artifact.kind} artifact: ${artifact.title}`}
                    onClick={onReviewCurrentWork}
                  >
                    Review current work
                  </button>
                </article>
              ))}
            </div>
          </section>

          <section className="cockpit-dashboard-safety-signals" aria-label="Safety and coordination signals">
            <div className="cockpit-dashboard-section-heading">
              <div>
                <span className="eyebrow">Coordination</span>
                <h3>{opsSafety.summary.primaryMessage}</h3>
              </div>
              <p>{opsSafety.summary.nextAction}</p>
            </div>
            <div className="cockpit-dashboard-signal-grid">
              {safetySignals.map((signal) => (
                <article key={signal.id} className={`cockpit-safety-signal signal-${signal.status}`}>
                  <span>{signal.kind.replace(/-/g, " ")}</span>
                  <strong>{signal.title}</strong>
                  <p>{signal.summary}</p>
                  <small>
                    {signal.sourceLabel} {"->"} {signal.relatedArtifactKind} artifact
                  </small>
                </article>
              ))}
            </div>
          </section>
        </>
      ) : null}
    </section>
  );
}
