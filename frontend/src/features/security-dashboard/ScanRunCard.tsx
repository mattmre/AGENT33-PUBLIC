import type { SecurityRun } from "./SecurityDashboard";

interface ScanRunCardProps {
  run: SecurityRun;
  isSelected: boolean;
  onSelect: () => void;
  onDownloadSarif: () => void;
}

function statusClass(status: string): string {
  switch (status) {
    case "completed":
      return "status-completed";
    case "failed":
    case "timeout":
      return "status-failed";
    case "running":
      return "status-running";
    case "cancelled":
      return "status-cancelled";
    default:
      return "status-pending";
  }
}

export function ScanRunCard({
  run,
  isSelected,
  onSelect,
  onDownloadSarif,
}: ScanRunCardProps): JSX.Element {
  const hasFindings =
    run.status === "completed" && run.findings_count > 0;
  const createdDate = new Date(run.created_at).toLocaleString();

  return (
    <div
      className={`scan-run-card ${isSelected ? "selected" : ""}`}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
    >
      <div className="scan-run-header">
        <span className={`status-indicator ${statusClass(run.status)}`}>
          {run.status.toUpperCase()}
        </span>
        <span className="profile-badge">{run.profile}</span>
        <span className="run-id">{run.id}</span>
      </div>

      <div className="scan-run-meta">
        <span>{run.target.repository_path}</span>
        {run.target.branch && <span>({run.target.branch})</span>}
        <span className="run-date">{createdDate}</span>
      </div>

      {run.status === "completed" && run.findings_summary && (
        <div className="findings-mini-summary">
          {run.findings_summary.critical > 0 && (
            <span className="severity-critical">
              C:{run.findings_summary.critical}
            </span>
          )}
          {run.findings_summary.high > 0 && (
            <span className="severity-high">
              H:{run.findings_summary.high}
            </span>
          )}
          {run.findings_summary.medium > 0 && (
            <span className="severity-medium">
              M:{run.findings_summary.medium}
            </span>
          )}
          {run.findings_summary.low > 0 && (
            <span className="severity-low">
              L:{run.findings_summary.low}
            </span>
          )}
          {run.findings_summary.info > 0 && (
            <span className="severity-info">
              I:{run.findings_summary.info}
            </span>
          )}
          {run.findings_count === 0 && (
            <span className="no-findings-badge">Clean</span>
          )}
        </div>
      )}

      {run.error_message && (
        <div className="run-error">{run.error_message}</div>
      )}

      {run.metadata.tools_executed.length > 0 && (
        <div className="tools-list">
          Tools: {run.metadata.tools_executed.join(", ")}
        </div>
      )}

      <div className="scan-run-actions">
        {hasFindings && (
          <button
            className="sarif-btn"
            onClick={(e) => {
              e.stopPropagation();
              onDownloadSarif();
            }}
          >
            Download SARIF
          </button>
        )}
      </div>
    </div>
  );
}
