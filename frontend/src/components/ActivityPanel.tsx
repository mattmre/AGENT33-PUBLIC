import { ObservationStream } from "./ObservationStream";
import type { ActivityItem } from "../types";

interface ActivityPanelProps {
  token: string | null;
  activity: ActivityItem[];
  activeSurfaceLabel: string;
  contextLabel: string;
  operatorMode: "beginner" | "pro";
  onOpenOperations: () => void;
  onOpenSafety: () => void;
  onOpenWorkflowCatalog: () => void;
}

export function ActivityPanel({
  token,
  activity,
  activeSurfaceLabel,
  contextLabel,
  operatorMode,
  onOpenOperations,
  onOpenSafety,
  onOpenWorkflowCatalog
}: ActivityPanelProps): JSX.Element {
  return (
    <aside className="activity-rail" aria-label="Activity and runtime signals">
      <section className="activity-rail-summary">
        <span className="eyebrow">Live shell</span>
        <strong>{activeSurfaceLabel}</strong>
        <p>{contextLabel}</p>
        <dl className="activity-rail-stats">
          <div>
            <dt>Mode</dt>
            <dd>{operatorMode === "pro" ? "Direct" : "Guided"}</dd>
          </div>
          <div>
            <dt>Calls</dt>
            <dd>{activity.length}</dd>
          </div>
          <div>
            <dt>Focus</dt>
            <dd>{activeSurfaceLabel}</dd>
          </div>
        </dl>
        <div className="activity-rail-actions">
          <button type="button" onClick={onOpenOperations}>
            Open runs
          </button>
          <button type="button" onClick={onOpenSafety}>
            Review gates
          </button>
          <button type="button" onClick={onOpenWorkflowCatalog}>
            Browse workflows
          </button>
        </div>
      </section>

      <ObservationStream token={token} />

      <section className="activity-rail-log">
        <div className="activity-rail-log-header">
          <div>
            <span className="eyebrow">Recent calls</span>
            <h3>Operator activity</h3>
          </div>
          <small>{activity.length === 0 ? "No calls yet" : `${activity.length} recent events`}</small>
        </div>
        {activity.length === 0 ? (
          <p className="activity-rail-empty">
            Trigger a workflow, safety action, or domain call and the live control plane will log it here.
          </p>
        ) : (
          <div className="activity-list">
            {activity.map((item) => (
              <article key={item.id} className="activity-item">
                <p className="activity-time">{item.at}</p>
                <h3>{item.label}</h3>
                <p>
                  <span className={item.status < 400 ? "status-ok" : "status-error"}>
                    <span className="sr-only">{item.status < 400 ? "Success" : "Error"}:</span>
                    {item.status}
                  </span>
                  {" in "}
                  {item.durationMs}ms
                </p>
                <p className="activity-url">{item.url}</p>
              </article>
            ))}
          </div>
        )}
      </section>
    </aside>
  );
}
