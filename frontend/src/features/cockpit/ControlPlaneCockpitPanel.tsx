import { CockpitProjectDashboard } from "../../components/CockpitProjectDashboard";
import { DomainPanel } from "../../components/DomainPanel";
import { HealthPanel } from "../../components/HealthPanel";
import { getPermissionMode, type PermissionModeId } from "../../data/permissionModes";
import type { WorkspaceSessionSummary } from "../../data/workspaces";
import type { ApiResult, DomainConfig } from "../../types";
import { useLiveCockpitData } from "./useLiveCockpitData";

const COCKPIT_PRIMARY_DOMAIN_IDS = ["agents", "workflows", "sessions", "reviews", "auth"] as const;

export function getCockpitPrimaryDomains(domains: DomainConfig[]): DomainConfig[] {
  const prioritized = COCKPIT_PRIMARY_DOMAIN_IDS.map((id) => domains.find((domain) => domain.id === id)).filter(
    (domain): domain is DomainConfig => domain !== undefined
  );
  return prioritized.length > 0 ? prioritized : domains.slice(0, 5);
}

interface ControlPlaneCockpitPanelProps {
  workspace: WorkspaceSessionSummary;
  permissionModeId: PermissionModeId;
  domains: DomainConfig[];
  selectedDomainId: string;
  token: string;
  apiKey: string;
  onSelectedDomainChange: (domainId: string) => void;
  onOpenOperations: () => void;
  onOpenWorkflowStarter: () => void;
  onOpenSafety: () => void;
  onOpenSetup: () => void;
  onResult: (label: string, result: ApiResult) => void;
}

export function ControlPlaneCockpitPanel({
  workspace,
  permissionModeId,
  domains,
  selectedDomainId,
  token,
  apiKey,
  onSelectedDomainChange,
  onOpenOperations,
  onOpenWorkflowStarter,
  onOpenSafety,
  onOpenSetup,
  onResult
}: ControlPlaneCockpitPanelProps): JSX.Element {
  const primaryDomains = getCockpitPrimaryDomains(domains);
  const selectedDomain = primaryDomains.find((domain) => domain.id === selectedDomainId) ?? primaryDomains[0] ?? null;
  const permissionMode = getPermissionMode(permissionModeId);
  const liveData = useLiveCockpitData(token);

  return (
    <section className="live-cockpit-panel" aria-label="Operations cockpit">
      <CockpitProjectDashboard
        workspace={workspace}
        permissionModeId={permissionModeId}
        onReviewCurrentWork={onOpenOperations}
        onOpenWorkflows={onOpenWorkflowStarter}
        onOpenSafety={onOpenSafety}
        showDetailSections={false}
      />

      <section className="live-cockpit-summary-block" aria-label="Live runtime summary">
        <div className="live-cockpit-section-head">
          <div>
            <p className="eyebrow">Live runtime</p>
            <h3>Active sessions and agents</h3>
          </div>
          {liveData.loading && <span className="live-cockpit-loading-badge">Loading…</span>}
        </div>
        <div className="live-cockpit-summary-stats">
          <div className="live-cockpit-stat">
            <span className="live-cockpit-stat-value">{liveData.activeSessions}</span>
            <span className="live-cockpit-stat-label">Active sessions</span>
          </div>
          <div className="live-cockpit-stat">
            <span className="live-cockpit-stat-value">{liveData.runningWorkflows}</span>
            <span className="live-cockpit-stat-label">Running workflows</span>
          </div>
          <div className="live-cockpit-stat">
            <span className="live-cockpit-stat-value">{liveData.activeAgents}</span>
            <span className="live-cockpit-stat-label">Active agents</span>
          </div>
        </div>
      </section>

      <section className="live-cockpit-health-block" aria-label="Runtime health block">
        <div className="live-cockpit-section-head">
          <div>
            <p className="eyebrow">Runtime health</p>
            <h3>Current services and operator posture</h3>
          </div>
          <div className="live-cockpit-section-meta">
            <span>{permissionMode.label}</span>
            <span>{workspace.updatedLabel}</span>
          </div>
        </div>
        <HealthPanel />
      </section>

      <section className="live-cockpit-api-block" aria-label="API surface">
        <div className="live-cockpit-section-head">
          <div>
            <p className="eyebrow">API surface</p>
            <h3>{selectedDomain?.title ?? "Runtime endpoints"}</h3>
            <p className="live-cockpit-section-copy">
              {selectedDomain?.description ??
                "Choose a live surface to inspect runtime routes, guarded actions, and execution payloads."}
            </p>
          </div>
          <div className="live-cockpit-quick-actions" aria-label="Cockpit quick actions">
            <button type="button" onClick={onOpenOperations}>
              Review board
            </button>
            <button type="button" onClick={onOpenWorkflowStarter}>
              Browse starters
            </button>
            <button type="button" onClick={onOpenSafety}>
              Review gates
            </button>
            <button type="button" onClick={onOpenSetup}>
              Integrations
            </button>
          </div>
        </div>

        <div className="live-cockpit-domain-tabs" role="tablist" aria-label="Primary cockpit surfaces">
          {primaryDomains.map((domain) => (
            <button
              key={domain.id}
              type="button"
              role="tab"
              className={domain.id === selectedDomain?.id ? "active" : ""}
              aria-selected={domain.id === selectedDomain?.id}
              onClick={() => onSelectedDomainChange(domain.id)}
            >
              <span>{domain.title}</span>
              <small>{domain.operations.length} ops</small>
            </button>
          ))}
        </div>

        {selectedDomain ? (
          <DomainPanel
            domain={selectedDomain}
            token={token}
            apiKey={apiKey}
            onResult={onResult}
          />
        ) : (
          <p className="advanced-quarantine-empty">No cockpit domains are registered.</p>
        )}
      </section>
    </section>
  );
}
