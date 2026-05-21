import { useMemo, useState } from "react";

import { ActivityPanel } from "../../components/ActivityPanel";
import { DomainPanel } from "../../components/DomainPanel";
import { HealthPanel } from "../../components/HealthPanel";
import type { ActivityItem, ApiResult, DomainConfig } from "../../types";

export type OperatorMode = "beginner" | "pro";

interface AdvancedControlPlanePanelProps {
  domains: DomainConfig[];
  selectedDomainId: string;
  token: string;
  apiKey: string;
  activity: ActivityItem[];
  operatorMode: OperatorMode;
  showActivityRail?: boolean;
  onOperatorModeChange: (mode: OperatorMode) => void;
  onSelectedDomainChange: (domainId: string) => void;
  onOpenModels: () => void;
  onOpenWorkflowCatalog: () => void;
  onOpenOperations: () => void;
  onOpenSafety: () => void;
  onOpenSetup: () => void;
  onResult: (label: string, result: ApiResult) => void;
}

const CONTROL_PLANE_ROUTES = [
  {
    title: "Connect runtime",
    description: "Set up providers, local models, and host execution before running direct calls.",
    actionLabel: "Open Models",
    action: "models"
  },
  {
    title: "Launch workflows",
    description: "Use packaged systems and workflow starters before editing payloads by hand.",
    actionLabel: "Browse workflows",
    action: "catalog"
  },
  {
    title: "Inspect live runs",
    description: "Move from direct calls to live orchestration timelines, blockers, and recovery.",
    actionLabel: "Open Sessions & Runs",
    action: "operations"
  },
  {
    title: "Review gates",
    description: "See active approvals and protected actions before you trigger a destructive route.",
    actionLabel: "Open Safety Center",
    action: "safety"
  },
  {
    title: "Configure access",
    description: "Update tokens and API keys if a domain route is unavailable or unauthorized.",
    actionLabel: "Open Integrations",
    action: "setup"
  }
] as const;

function domainMatchesQuery(domain: DomainConfig, query: string): boolean {
  const normalized = query.trim().toLowerCase();
  if (normalized === "") {
    return true;
  }
  return (
    domain.title.toLowerCase().includes(normalized) ||
    domain.description.toLowerCase().includes(normalized) ||
    domain.operations.some((operation) => {
      return (
        operation.title.toLowerCase().includes(normalized) ||
        operation.description.toLowerCase().includes(normalized) ||
        operation.path.toLowerCase().includes(normalized)
      );
    })
  );
}

export function AdvancedControlPlanePanel({
  domains,
  selectedDomainId,
  token,
  apiKey,
  activity,
  operatorMode,
  showActivityRail = true,
  onOperatorModeChange,
  onSelectedDomainChange,
  onOpenModels,
  onOpenWorkflowCatalog,
  onOpenOperations,
  onOpenSafety,
  onOpenSetup,
  onResult
}: AdvancedControlPlanePanelProps): JSX.Element {
  const [advancedSearch, setAdvancedSearch] = useState("");
  const selectedDomain = useMemo(
    () => domains.find((domain) => domain.id === selectedDomainId) ?? domains[0],
    [domains, selectedDomainId]
  );
  const matchedDomains = useMemo(
    () => domains.filter((domain) => domainMatchesQuery(domain, advancedSearch)),
    [advancedSearch, domains]
  );
  const visibleDomain = useMemo(() => {
    if (matchedDomains.length === 0) {
      return null;
    }
    return matchedDomains.find((domain) => domain.id === selectedDomainId) ?? matchedDomains[0];
  }, [matchedDomains, selectedDomainId]);

  if (selectedDomain === undefined) {
    return <p className="advanced-quarantine-empty">No technical domains are registered.</p>;
  }

  function openRoute(action: (typeof CONTROL_PLANE_ROUTES)[number]["action"]): void {
    if (action === "models") {
      onOpenModels();
    } else if (action === "catalog") {
      onOpenWorkflowCatalog();
    } else if (action === "operations") {
      onOpenOperations();
    } else if (action === "safety") {
      onOpenSafety();
    } else if (action === "setup") {
      onOpenSetup();
    }
  }

  const modeTitle =
    operatorMode === "pro" ? "Live control plane" : "Guided control plane";
  const modeDescription =
    operatorMode === "pro"
      ? "Runtime domains, health, and direct route execution are visible together in the live shell."
      : "Guided actions stay in the foreground while raw domains remain mounted, so the design stays consistent with the live product surface.";

  return (
    <section className={`control-plane-shell control-plane-shell-${operatorMode}`} aria-label="Control plane">
      <header className="control-plane-hero">
        <div className="control-plane-hero-copy">
          <p className="advanced-quarantine-eyebrow">AGENT-33 control plane</p>
          <h2>{modeTitle}</h2>
          <p>{modeDescription}</p>
          <div className="control-plane-hero-actions">
            {CONTROL_PLANE_ROUTES.map((route) => (
              <button key={route.action} type="button" onClick={() => openRoute(route.action)}>
                {route.actionLabel}
              </button>
            ))}
          </div>
        </div>

        <div className="control-plane-mode-card">
          <span className="eyebrow">Mode</span>
          <strong>{operatorMode === "pro" ? "Live runtime emphasis" : "Guided route emphasis"}</strong>
          <p>
            {operatorMode === "pro"
              ? "Direct surfaces stay front and center so the runtime shell matches the design kit."
              : "Guided paths stay prominent for quick launches, approvals, and safer operator actions without hiding the live domains."}
          </p>
          <button
            type="button"
            onClick={() => onOperatorModeChange(operatorMode === "pro" ? "beginner" : "pro")}
          >
            {operatorMode === "pro" ? "Prioritize guided routes" : "Prioritize live controls"}
          </button>
        </div>
      </header>

      <div className="control-plane-grid">
        <aside className="control-plane-sidebar" aria-label="Control plane sidebar">
          <HealthPanel />

          <section className="control-plane-sidebar-card">
            <div className="control-plane-sidebar-header">
              <span className="eyebrow">Domain search</span>
              <strong>Technical surfaces</strong>
            </div>
            <label className="control-plane-search-field">
              Search domains and operations
              <input
                value={advancedSearch}
                onChange={(event) => setAdvancedSearch(event.target.value)}
                placeholder="agents, workflows, memory, reviews..."
              />
            </label>
            <p className="control-plane-sidebar-note">
              {matchedDomains.length} domains match the current filter.
            </p>
          </section>

          <nav className="control-plane-domain-nav" aria-label="Technical domains">
            <span className="main-nav-group-label">Domains</span>
            {matchedDomains.map((domain) => (
              <button
                key={domain.id}
                type="button"
                className={domain.id === visibleDomain?.id ? "active" : ""}
                onClick={() => onSelectedDomainChange(domain.id)}
                aria-current={domain.id === visibleDomain?.id ? "page" : undefined}
              >
                <span className="main-nav-button-label">{domain.title}</span>
                <small>{domain.description}</small>
              </button>
            ))}
            {matchedDomains.length === 0 ? (
              <p className="advanced-quarantine-empty">No domains match this search.</p>
            ) : null}
          </nav>
        </aside>

        <div className="control-plane-main">
          {operatorMode === "beginner" ? (
            <section className="control-plane-route-grid" aria-label="Guided control plane actions">
              {CONTROL_PLANE_ROUTES.map((route) => (
                <article key={route.action} className="control-plane-route-card">
                  <span className="eyebrow">Guided route</span>
                  <strong>{route.title}</strong>
                  <p>{route.description}</p>
                  <button type="button" onClick={() => openRoute(route.action)}>
                    {route.actionLabel}
                  </button>
                </article>
              ))}
            </section>
          ) : null}

          {visibleDomain ? (
            <DomainPanel
              domain={visibleDomain}
              token={token}
              apiKey={apiKey}
              externalFilter={advancedSearch}
              onResult={onResult}
            />
          ) : (
            <p className="advanced-quarantine-empty">No domains match this search.</p>
          )}
        </div>

        {showActivityRail ? (
          <ActivityPanel
            token={token || null}
            activity={activity}
            activeSurfaceLabel={visibleDomain?.title ?? "No matching domain"}
            contextLabel={
              visibleDomain?.description ?? "Adjust the filter to restore a visible technical surface."
            }
            operatorMode={operatorMode}
            onOpenOperations={onOpenOperations}
            onOpenSafety={onOpenSafety}
            onOpenWorkflowCatalog={onOpenWorkflowCatalog}
          />
        ) : null}
      </div>
    </section>
  );
}
