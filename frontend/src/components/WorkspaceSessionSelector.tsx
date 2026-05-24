import {
  WORKSPACE_SESSIONS,
  isWorkspaceSessionId,
  type WorkspaceSessionId,
  type WorkspaceSessionSummary
} from "../data/workspaces";
import { getWorkspaceTaskCounts } from "../data/workspaceBoard";
import {
  buildWorkspaceTemplateStarterDraft,
  getPrimaryWorkspaceTemplateStarter
} from "../data/workspaceTemplateStarters";
import { getWorkspaceRecoverySummary } from "../data/workspaceRecovery";
import type { WorkspaceRecoverySummary } from "../data/workspaceRecovery";
import type { WorkflowStarterDraft } from "../features/workflow-starter/types";

interface WorkspaceSessionSelectorProps {
  selectedWorkspaceId: WorkspaceSessionId;
  selectedWorkspace: WorkspaceSessionSummary;
  workspaceSessions?: ReadonlyArray<WorkspaceSessionSummary>;
  recoverySummary?: WorkspaceRecoverySummary;
  onSelectWorkspace: (workspaceId: WorkspaceSessionId) => void;
  onOpenRuns: () => void;
  onOpenWorkflows: (draft?: WorkflowStarterDraft) => void;
}

export function WorkspaceSessionSelector({
  selectedWorkspaceId,
  selectedWorkspace,
  workspaceSessions = WORKSPACE_SESSIONS,
  recoverySummary,
  onSelectWorkspace,
  onOpenRuns,
  onOpenWorkflows
}: WorkspaceSessionSelectorProps): JSX.Element {
  const primaryStarter = getPrimaryWorkspaceTemplateStarter(selectedWorkspaceId);
  const taskCounts = getWorkspaceTaskCounts(selectedWorkspaceId);
  const effectiveRecoverySummary = recoverySummary ?? getWorkspaceRecoverySummary(selectedWorkspaceId);
  const primarySnapshot = effectiveRecoverySummary.snapshots[0] ?? null;

  return (
    <section className="cockpit-sidebar-context workspace-session-card" aria-label="Workspace session">
      <div className="workspace-session-heading">
        <span className="eyebrow">Workspace</span>
        <strong>{selectedWorkspace.name}</strong>
      </div>

      <label className="workspace-session-select-label" htmlFor="workspace-session-select">
        Active project template
      </label>
      <select
        id="workspace-session-select"
        className="workspace-session-select"
        value={selectedWorkspaceId}
        onChange={(event) => {
          const workspaceId = event.target.value;
          if (!isWorkspaceSessionId(workspaceId)) {
            console.error(`Unknown workspace session: ${workspaceId}`);
            return;
          }
          onSelectWorkspace(workspaceId);
        }}
      >
        {workspaceSessions.map((workspace) => (
          <option key={workspace.id} value={workspace.id}>
            {workspace.name} - {workspace.template}
          </option>
        ))}
      </select>

      <p>{selectedWorkspace.goal}</p>
      {primaryStarter ? (
        <section className="workspace-session-starter" aria-label="Recommended workspace starter">
          <span>Best first workflow</span>
          <strong>{primaryStarter.label}</strong>
          <p>{primaryStarter.description}</p>
        </section>
      ) : null}

      <dl className="workspace-session-stats" aria-label="Workspace snapshot">
        <div>
          <dt>RUN</dt>
          <dd>{taskCounts.running}</dd>
        </div>
        <div>
          <dt>REV</dt>
          <dd>{taskCounts.review}</dd>
        </div>
        <div>
          <dt>BLK</dt>
          <dd>{taskCounts.blocked}</dd>
        </div>
      </dl>

      <section className="workspace-session-recovery" aria-label="Workspace recovery">
        <span>Recovery</span>
        <strong>{effectiveRecoverySummary.primaryMessage}</strong>
        <p>{effectiveRecoverySummary.nextAction}</p>
        {primarySnapshot ? (
          <small>
            {primarySnapshot.resumeAction} / {primarySnapshot.budgetLabel} / {primarySnapshot.artifactCount} artifacts
          </small>
        ) : null}
      </section>

      <div className="workspace-session-actions" aria-label="Workspace quick actions">
        <button
          type="button"
          onClick={() =>
            onOpenWorkflows(primaryStarter ? buildWorkspaceTemplateStarterDraft(primaryStarter) : undefined)
          }
        >
          {primaryStarter ? `Start ${primaryStarter.label}` : "Open workflows"}
        </button>
        <button type="button" onClick={onOpenRuns}>
          View runs
        </button>
      </div>

      <small>{selectedWorkspace.updatedLabel}</small>
    </section>
  );
}
