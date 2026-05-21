import { useMemo, useRef, useState, type KeyboardEvent } from "react";

import type { PermissionModeId } from "../data/permissionModes";
import { getPermissionMode } from "../data/permissionModes";
import type { WorkspaceSessionSummary } from "../data/workspaces";
import { getCockpitArtifactsForWorkspace } from "../data/cockpitArtifacts";
import { getActivityEventsByArtifactId, getActivityEventsForWorkspace } from "../data/cockpitActivity";
import { getCommandBlocksByArtifactId, getCommandBlocksForWorkspace } from "../data/commandBlocks";
import {
  buildCockpitOpsSafetySnapshot,
  getCockpitOpsSafetyRecordsByArtifactId
} from "../data/cockpitOpsSafety";
import { formatGateLabel, groupSafetyRecordsByStatus } from "../data/safetyGatePresentation";
import {
  ARTIFACT_DRAWER_SECTIONS,
  type ArtifactDrawerSectionId
} from "../data/artifactDrawerSections";

type ArtifactReviewDrawerBaseProps = {
  workspace: WorkspaceSessionSummary;
  permissionModeId: PermissionModeId;
};

type ArtifactReviewDrawerControlledProps = ArtifactReviewDrawerBaseProps & {
  activeSectionId: ArtifactDrawerSectionId;
  onSectionChange: (sectionId: ArtifactDrawerSectionId) => void;
};

type ArtifactReviewDrawerUncontrolledProps = ArtifactReviewDrawerBaseProps & {
  activeSectionId?: undefined;
  onSectionChange?: (sectionId: ArtifactDrawerSectionId) => void;
};

type ArtifactReviewDrawerProps = ArtifactReviewDrawerControlledProps | ArtifactReviewDrawerUncontrolledProps;

export function ArtifactReviewDrawer({
  workspace,
  permissionModeId,
  activeSectionId: controlledActiveSectionId,
  onSectionChange
}: ArtifactReviewDrawerProps): JSX.Element {
  const [uncontrolledActiveSectionId, setUncontrolledActiveSectionId] = useState<ArtifactDrawerSectionId>("plan");
  const activeSectionId = controlledActiveSectionId ?? uncontrolledActiveSectionId;
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const activeSection =
    ARTIFACT_DRAWER_SECTIONS.find((section) => section.id === activeSectionId) ?? ARTIFACT_DRAWER_SECTIONS[0];
  const permissionMode = getPermissionMode(permissionModeId);
  const activeTabId = `artifact-drawer-tab-${activeSection.id}`;
  const artifacts = useMemo(() => getCockpitArtifactsForWorkspace(workspace.id), [workspace.id]);
  const activeArtifact = useMemo(
    () => artifacts.find((artifact) => artifact.sectionId === activeSection.id),
    [activeSection.id, artifacts]
  );
  const commandBlocksForWorkspace = useMemo(() => getCommandBlocksForWorkspace(workspace.id), [workspace.id]);
  const commandBlocks = useMemo(
    () => (activeArtifact ? getCommandBlocksByArtifactId(commandBlocksForWorkspace, activeArtifact.id) : []),
    [activeArtifact, commandBlocksForWorkspace]
  );
  const opsSafety = useMemo(
    () => buildCockpitOpsSafetySnapshot({ workspaceId: workspace.id, permissionModeId }),
    [permissionModeId, workspace.id]
  );
  const baseActivityEvents = useMemo(() => getActivityEventsForWorkspace(workspace.id), [workspace.id]);
  const allActivityEvents = useMemo(
    () => [...baseActivityEvents, ...opsSafety.activityEvents],
    [baseActivityEvents, opsSafety.activityEvents]
  );
  const activityEvents = useMemo(
    () =>
      activeArtifact
        ? activeSection.id === "activity"
          ? allActivityEvents
          : getActivityEventsByArtifactId(allActivityEvents, activeArtifact.id)
        : [],
    [activeArtifact, activeSection.id, allActivityEvents]
  );
  const safetyRecords = useMemo(
    () => (activeArtifact ? getCockpitOpsSafetyRecordsByArtifactId(opsSafety.records, activeArtifact.id) : []),
    [activeArtifact, opsSafety.records]
  );
  const safetyRecordGroups = useMemo(() => groupSafetyRecordsByStatus(safetyRecords), [safetyRecords]);

  function selectSection(sectionId: ArtifactDrawerSectionId, shouldFocus = false): void {
    if (controlledActiveSectionId === undefined) {
      setUncontrolledActiveSectionId(sectionId);
    }
    onSectionChange?.(sectionId);
    if (shouldFocus) {
      window.requestAnimationFrame(() => tabRefs.current[sectionId]?.focus());
    }
  }

  function onTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, sectionIndex: number): void {
    let nextIndex: number | null = null;

    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = (sectionIndex + 1) % ARTIFACT_DRAWER_SECTIONS.length;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = (sectionIndex - 1 + ARTIFACT_DRAWER_SECTIONS.length) % ARTIFACT_DRAWER_SECTIONS.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = ARTIFACT_DRAWER_SECTIONS.length - 1;
    }

    if (nextIndex !== null) {
      event.preventDefault();
      selectSection(ARTIFACT_DRAWER_SECTIONS[nextIndex].id, true);
    }
  }

  return (
    <aside className="artifact-review-drawer" aria-label="Artifact and review drawer">
      <header>
        <span className="eyebrow">Review drawer</span>
        <h2>{workspace.template}</h2>
        <p>{permissionMode.label}: {permissionMode.allowedNow}</p>
      </header>

      <div className="artifact-drawer-tabs" role="tablist" aria-label="Artifact drawer sections">
        {ARTIFACT_DRAWER_SECTIONS.map((section, sectionIndex) => (
          <button
            key={section.id}
            id={`artifact-drawer-tab-${section.id}`}
            ref={(element) => {
              tabRefs.current[section.id] = element;
            }}
            type="button"
            role="tab"
            className={section.id === activeSectionId ? "active" : ""}
            aria-controls="artifact-drawer-panel"
            aria-selected={section.id === activeSectionId}
            tabIndex={section.id === activeSectionId ? 0 : -1}
            onClick={() => selectSection(section.id)}
            onKeyDown={(event) => onTabKeyDown(event, sectionIndex)}
          >
            {section.label}
          </button>
        ))}
      </div>

      <article
        id="artifact-drawer-panel"
        className="artifact-drawer-panel"
        role="tabpanel"
        aria-labelledby={activeTabId}
      >
        <span>{activeSection.label}</span>
        <h3>{activeSection.title}</h3>
        <p>{activeSection.body}</p>
        {activeArtifact ? (
          <section className="artifact-drawer-artifact-card" aria-label={`${activeSection.label} artifact details`}>
            <strong>{activeArtifact.title}</strong>
            <p>{activeArtifact.summary}</p>
            <dl>
              <div>
                <dt>Status</dt>
                <dd>{formatGateLabel(activeArtifact.status)}</dd>
              </div>
              <div>
                <dt>Review</dt>
                <dd>{formatGateLabel(activeArtifact.reviewState)}</dd>
              </div>
              <div>
                <dt>Owner</dt>
                <dd>{activeArtifact.ownerRole}</dd>
              </div>
              <div>
                <dt>Source</dt>
                <dd>{activeArtifact.sourceLabel}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd>{activeArtifact.timestampLabel}</dd>
              </div>
              <div>
                <dt>Next</dt>
                <dd>{activeArtifact.nextActionLabel}</dd>
              </div>
            </dl>
          </section>
        ) : null}
        {commandBlocks.length > 0 ? (
          <section className="artifact-drawer-evidence-list" aria-label="Command block evidence">
            <h4>Command evidence</h4>
            {commandBlocks.map((block) => (
              <article key={block.id}>
                <strong>{block.commandLabel}</strong>
                <p>{block.outputSummary}</p>
                {block.failureSummary ? <p className="safety-record-next-action">Failure: {block.failureSummary}</p> : null}
                <small>
                  {block.sourceRole} / {formatGateLabel(block.status)} / {block.exitLabel} / {block.durationLabel} /
                  redaction {formatGateLabel(block.redactionState)}
                  {block.traceId ? ` / trace ${block.traceId}` : ""}
                </small>
              </article>
            ))}
          </section>
        ) : null}
        {activeArtifact?.validationItems && activeArtifact.validationItems.length > 0 ? (
          <section className="artifact-drawer-evidence-list" aria-label="Validation status evidence">
            <h4>Validation status</h4>
            {activeArtifact.validationItems.map((item) => (
              <article key={`${activeArtifact.id}-${item.name}`}>
                <strong>{item.name}</strong>
                <p>{item.summary}</p>
                <small>
                  {formatGateLabel(item.status)}
                  {item.durationLabel ? ` / ${item.durationLabel}` : ""}
                </small>
              </article>
            ))}
          </section>
        ) : null}
        {activityEvents.length > 0 ? (
          <section className="artifact-drawer-evidence-list" aria-label="Activity evidence">
            <h4>Activity events</h4>
            {activityEvents.map((event) => (
              <article key={event.id}>
                <strong>{event.title}</strong>
                <p>{event.summary}</p>
                {event.createdAtLabel || event.expiresAtLabel ? (
                  <p className="safety-record-next-action">
                    {[event.createdAtLabel, event.expiresAtLabel].filter(Boolean).join(" / ")}
                  </p>
                ) : null}
                {event.validationDetails && event.validationDetails.length > 0 ? (
                  <p className="safety-record-next-action">
                    Validation: {event.validationDetails.map((item) => `${item.name} ${formatGateLabel(item.status)}`).join(", ")}
                  </p>
                ) : null}
                <small>
                  {event.isInterAgentHandoff
                    ? `Mailbox handoff #${event.sequenceIndex ?? "?"} / `
                    : ""}
                  {event.senderRole} to {event.recipientRole} / {formatGateLabel(event.type)} /{" "}
                  {formatGateLabel(event.decisionState)}
                </small>
              </article>
            ))}
          </section>
        ) : null}
        {safetyRecords.length > 0 ? (
          <section className="artifact-drawer-evidence-list" aria-label="Safety evidence">
            <div className="artifact-drawer-gate-context">
              <span>Permission gate</span>
              <strong>{permissionMode.headline}</strong>
              <p>{permissionMode.reviewGate}</p>
            </div>
            {safetyRecordGroups.map((group) => (
              <div key={group.status} className={`safety-record-group safety-record-group-${group.status}`}>
                <h5>{group.heading}</h5>
                <p>{group.description}</p>
                {group.records.map((record) => (
                  <article key={record.id} className={`safety-record safety-record-${record.status}`}>
                    <strong>{record.title}</strong>
                    <p>{record.summary}</p>
                    <p className="safety-record-next-action">Next: {record.nextActionLabel}</p>
                    <small>
                      {formatGateLabel(record.status)} / {record.sourceLabel}
                    </small>
                  </article>
                ))}
              </div>
            ))}
          </section>
        ) : null}
        {activeSection.id === "outcome" && activeArtifact ? (
          <section className="artifact-drawer-evidence-list" aria-label="Outcome handoff">
            <h4>{activeArtifact.title}</h4>
            <p>{activeArtifact.summary}</p>
            <p className="safety-record-next-action">Next: {activeArtifact.nextActionLabel}</p>
            <small>
              {formatGateLabel(activeArtifact.status)} / {formatGateLabel(activeArtifact.reviewState)} /{" "}
              {activeArtifact.outcomeState ? `${formatGateLabel(activeArtifact.outcomeState)} / ` : ""}
              {activeArtifact.handoffState ? `${formatGateLabel(activeArtifact.handoffState)} / ` : ""}
              {activeArtifact.relatedTaskIds.length === 0
                ? "No linked task yet"
                : `${activeArtifact.relatedTaskIds.length} linked task${
                    activeArtifact.relatedTaskIds.length === 1 ? "" : "s"
                  }`}
            </small>
          </section>
        ) : null}
        <dl>
          <div>
            <dt>Workspace</dt>
            <dd>{workspace.name}</dd>
          </div>
          <div>
            <dt>Current status</dt>
            <dd>{workspace.status}</dd>
          </div>
          <div>
            <dt>Review gate</dt>
            <dd>{permissionMode.reviewGate}</dd>
          </div>
        </dl>
      </article>
    </aside>
  );
}
