import { useMemo } from "react";

import type { PermissionModeId } from "../data/permissionModes";
import { getPermissionActionGate, type PermissionActionCategory } from "../data/permissionActionGates";
import type { WorkspaceSessionSummary } from "../data/workspaces";
import {
  buildWorkspaceTemplateStarterDraft,
  getWorkspaceTemplateStarters
} from "../data/workspaceTemplateStarters";
import type { WorkflowStarterDraft } from "../features/workflow-starter/types";
import {
  WORKSPACE_TASK_STATUS_LABELS,
  WORKSPACE_TASK_STATUSES,
  getWorkspaceBoard,
  groupWorkspaceTasksByStatus
} from "../data/workspaceBoard";
import { getWorkspaceRecoverySummary } from "../data/workspaceRecovery";

interface WorkspaceTaskBoardProps {
  workspace: WorkspaceSessionSummary;
  permissionModeId: PermissionModeId;
  onOpenSafety: () => void;
  onOpenWorkflows: (draft?: WorkflowStarterDraft) => void;
}

const TASK_ACTION_BY_STATUS: Record<(typeof WORKSPACE_TASK_STATUSES)[number], PermissionActionCategory> = {
  todo: "start-workflow",
  running: "run-command",
  review: "approve-action",
  complete: "review-artifact",
  blocked: "approve-action"
};

export function WorkspaceTaskBoard({
  workspace,
  permissionModeId,
  onOpenSafety,
  onOpenWorkflows
}: WorkspaceTaskBoardProps): JSX.Element {
  const board = getWorkspaceBoard(workspace.id);
  const tasksByStatus = useMemo(() => groupWorkspaceTasksByStatus(board.tasks), [board.tasks]);
  const templateStarters = getWorkspaceTemplateStarters(workspace.id);
  const workflowGate = getPermissionActionGate(permissionModeId, "start-workflow");
  const recoverySummary = getWorkspaceRecoverySummary(workspace.id);

  return (
    <section className="workspace-board" aria-label={`${workspace.name} task board`}>
      <header className="workspace-board-header">
        <div>
          <span className="eyebrow">Workspace command board</span>
          <h2>{workspace.template}</h2>
          <p>{workspace.goal}</p>
        </div>
        <div className="workspace-board-actions" aria-label="Workspace board actions">
          <button
            type="button"
            onClick={() => onOpenWorkflows()}
            disabled={!workflowGate.allowed}
            aria-label={workflowGate.allowed ? "Choose workflow" : `Choose workflow locked: ${workflowGate.reason}`}
            aria-describedby="workspace-board-workflow-gate"
          >
            Choose workflow
          </button>
          <span
            id="workspace-board-workflow-gate"
            className={`permission-action-chip permission-action-chip-${workflowGate.tone}`}
          >
            {workflowGate.reason}
          </span>
          <button type="button" onClick={onOpenSafety}>
            Review approvals
          </button>
        </div>
      </header>

      <section className="workspace-template-starters" aria-label={`${workspace.template} recommended starters`}>
        <div className="workspace-template-starters-header">
          <h3>Recommended starters</h3>
          <p>Pick a beginner-safe workflow that already knows this template, role, and first task.</p>
        </div>
        <div className="workspace-template-starter-grid">
          {templateStarters.map((starter) => {
            const beginsWithTask = board.tasks.find((task) => task.id === starter.beginsWithTaskId);

            return (
              <article key={starter.id} className="workspace-template-starter-card">
                <span>{starter.assignedRole}</span>
                <strong>{starter.label}</strong>
                <p>{starter.description}</p>
                <small>
                  Starts with {beginsWithTask?.title ?? starter.beginsWithTaskId} / {starter.nextActionLabel}
                </small>
                <button
                  type="button"
                  onClick={() => onOpenWorkflows(buildWorkspaceTemplateStarterDraft(starter))}
                  disabled={!workflowGate.allowed}
                  aria-label={
                    workflowGate.allowed
                      ? `Use starter: ${starter.label}`
                      : `Use starter locked: ${starter.label}. ${workflowGate.reason}`
                  }
                  aria-describedby="workspace-board-workflow-gate"
                >
                  Use starter
                </button>
              </article>
            );
          })}
        </div>
      </section>

      <section className="workspace-recovery-panel" aria-label={`${workspace.template} recovery controls`}>
        <div className="workspace-template-starters-header">
          <h3>Recovery and workspace controls</h3>
          <p>{recoverySummary.primaryMessage} {recoverySummary.nextAction}</p>
        </div>
        <div className="workspace-recovery-grid">
          {recoverySummary.snapshots.map((snapshot) => (
            <article key={snapshot.id} className={`workspace-recovery-card workspace-recovery-card--${snapshot.status}`}>
              <span>{snapshot.status}</span>
              <strong>{snapshot.label}</strong>
              <p>{snapshot.resumeAction}</p>
              <dl>
                <div>
                  <dt>Rollback</dt>
                  <dd>{snapshot.rollbackAction}</dd>
                </div>
                <div>
                  <dt>Budget</dt>
                  <dd>{snapshot.budgetLabel}</dd>
                </div>
                <div>
                  <dt>Artifacts</dt>
                  <dd>{snapshot.artifactCount}</dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
      </section>

      <div className="workspace-board-grid">
        <div className="workspace-kanban" aria-label="Workspace task lanes">
          {WORKSPACE_TASK_STATUSES.map((status) => {
            const laneTasks = tasksByStatus[status];
            return (
              <section key={status} className="workspace-kanban-lane" aria-label={`${WORKSPACE_TASK_STATUS_LABELS[status]} tasks`}>
                <div className="workspace-lane-header">
                  <h3>{WORKSPACE_TASK_STATUS_LABELS[status]}</h3>
                  <span>{laneTasks.length}</span>
                </div>
                {laneTasks.length === 0 ? (
                  <p className="workspace-empty-lane">No tasks yet.</p>
                ) : null}
                {laneTasks.map((task) => {
                  const taskGate = getPermissionActionGate(permissionModeId, TASK_ACTION_BY_STATUS[task.status]);

                  return (
                    <article key={task.id} className={`workspace-task-card workspace-task-card--${task.status}`}>
                      <span>{task.ownerRole}</span>
                      <h4>{task.title}</h4>
                      <p>{task.outcome}</p>
                      <div className={`workspace-task-gate workspace-task-gate-${taskGate.tone}`}>
                        <strong>{taskGate.label}</strong>
                        <small>{taskGate.reason}</small>
                      </div>
                    </article>
                  );
                })}
              </section>
            );
          })}
        </div>

        <aside className="workspace-agent-roster" aria-label="Workspace agent roster">
          <div className="workspace-roster-header">
            <h3>Agent roster</h3>
            <p>Who does what in {workspace.template}: each role owns a starter task and a reviewable output.</p>
          </div>
          {board.agents.map((agent) => (
            <article key={agent.id} className="workspace-agent-card">
              <div>
                <strong>{agent.name}</strong>
                <span>{agent.role}</span>
              </div>
              <p>{agent.focus}</p>
              <small>{agent.state}</small>
            </article>
          ))}
        </aside>
      </div>
    </section>
  );
}
