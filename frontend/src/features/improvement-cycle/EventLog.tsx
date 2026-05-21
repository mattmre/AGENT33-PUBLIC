import type { WorkflowLiveEvent } from "../../types";

interface EventLogProps {
  events: WorkflowLiveEvent[];
}

function formatTimestamp(ts: number): string {
  const date = new Date(ts * 1000);
  return date.toLocaleTimeString();
}

export function EventLog({ events }: EventLogProps): JSX.Element {
  if (events.length === 0) {
    return (
      <div className="wizard-event-log">
        <h4>Event Log</h4>
        <p className="wizard-muted">No events received yet.</p>
      </div>
    );
  }

  return (
    <div className="wizard-event-log">
      <h4>Event Log ({events.length})</h4>
      <ul className="wizard-event-list" role="log" aria-live="polite">
        {events.map((event, index) => (
          <li key={index} className="wizard-event-entry">
            <span className="wizard-event-time">
              {event.timestamp ? formatTimestamp(event.timestamp) : "--:--:--"}
            </span>
            <span className="wizard-event-type">{event.type}</span>
            {event.step_id && (
              <span className="wizard-event-step">[{event.step_id}]</span>
            )}
            {event.data?.status != null ? (
              <span className="wizard-event-status">
                {String(event.data.status)}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
