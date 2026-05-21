import type { AppTab } from "../../data/navigation";
import "./DesignKitSurfacesPanel.css";

type SurfaceStatus = "wired" | "shell" | "reference" | "legacy";

interface DesignKitSurface {
  readonly title: string;
  readonly kitSource: string;
  readonly summary: string;
  readonly status: SurfaceStatus;
  readonly targetTab?: AppTab;
  readonly targetLabel?: string;
}

interface DesignKitSurfacesPanelProps {
  onNavigate: (tab: AppTab) => void;
}

interface QuickJump {
  readonly title: string;
  readonly targetTab: AppTab;
  readonly targetLabel: string;
}

export const DESIGN_KIT_QUICK_JUMPS: ReadonlyArray<QuickJump> = [
  { title: "Operations Cockpit", targetTab: "operations", targetLabel: "Open Operations Cockpit" },
  { title: "Sessions & Runs", targetTab: "operations", targetLabel: "Open Sessions & Runs" },
  { title: "Advanced Controls", targetTab: "advanced", targetLabel: "Open Advanced" },
  { title: "Integrations", targetTab: "setup", targetLabel: "Open Integrations" },
  { title: "Safety Center", targetTab: "safety", targetLabel: "Open Safety Center" }
];

export const DESIGN_KIT_LIVE_SURFACES: ReadonlyArray<DesignKitSurface> = [
  {
    title: "AuthPanel",
    kitSource: "design-system/ui_kits/control-plane/AuthPanel.html",
    summary: "Local sign-in and token wiring already live in the app's setup flow.",
    status: "wired",
    targetTab: "setup",
    targetLabel: "Open Integrations"
  },
  {
    title: "HealthPanel / HealthPanelFull",
    kitSource: "design-system/ui_kits/control-plane/HealthPanel.html",
    summary: "Health surfaces are available from the advanced control plane and runtime probes.",
    status: "wired",
    targetTab: "advanced",
    targetLabel: "Open Advanced"
  },
  {
    title: "PermissionModeControl",
    kitSource: "design-system/ui_kits/control-plane/PermissionModeControl.html",
    summary: "The permission selector is now mounted in the live shell sidebar instead of a stacked context bar.",
    status: "shell",
    targetTab: "operations",
    targetLabel: "Open Operations Cockpit"
  },
  {
    title: "SafetyGateIndicator",
    kitSource: "design-system/ui_kits/control-plane/SafetyGateIndicator.html",
    summary: "Gate review and override flows are wired to the live safety surface.",
    status: "wired",
    targetTab: "safety",
    targetLabel: "Open Safety Center"
  },
  {
    title: "WorkflowGraph",
    kitSource: "design-system/ui_kits/control-plane/WorkflowGraph.html",
    summary: "Workflow authoring lives in the starter flow where users can assemble and inspect steps.",
    status: "wired",
    targetTab: "starter",
    targetLabel: "Open Workflow Starter"
  },
  {
    title: "WorkspaceTaskBoard",
    kitSource: "design-system/ui_kits/control-plane/WorkspaceTaskBoard.html",
    summary: "The task board is already mounted inside the sessions and runs cockpit view.",
    status: "wired",
    targetTab: "operations",
    targetLabel: "Open Sessions & Runs"
  },
  {
    title: "ShipyardLaneScaffold",
    kitSource: "design-system/ui_kits/control-plane/ShipyardLaneScaffold.html",
    summary: "The lane scaffold is part of the live operations workspace.",
    status: "wired",
    targetTab: "operations",
    targetLabel: "Open Sessions & Runs"
  },
  {
    title: "ArtifactReviewDrawer",
    kitSource: "design-system/ui_kits/control-plane/ArtifactReviewDrawer.html",
    summary: "The review drawer is mounted in the operations shell when the cockpit dashboard is active.",
    status: "wired",
    targetTab: "operations",
    targetLabel: "Open Sessions & Runs"
  },
  {
    title: "ObservationStream",
    kitSource: "design-system/ui_kits/control-plane/ObservationStream.html",
    summary: "Live observations are embedded in the operations flow rather than a standalone route.",
    status: "wired",
    targetTab: "operations",
    targetLabel: "Open Sessions & Runs"
  }
];

export const DESIGN_KIT_SHARED_REFERENCES: ReadonlyArray<DesignKitSurface> = [
  {
    title: "Topbar / Sidebar / Dashboard / ActivityPanel",
    kitSource: "design-system/ui_kits/control-plane/App.jsx",
    summary: "These kit shell pieces now map to the live operations cockpit landing surface.",
    status: "shell",
    targetTab: "operations",
    targetLabel: "Open Operations Cockpit"
  },
  {
    title: "GlobalSearch",
    kitSource: "design-system/ui_kits/control-plane/GlobalSearch.html",
    summary: "Search is live in the shared cockpit shell on every view, not behind a separate panel.",
    status: "shell",
    targetTab: "guide",
    targetLabel: "Open Guide / Intake"
  },
  {
    title: "DomainPanel",
    kitSource: "design-system/ui_kits/control-plane/DomainPanel.html",
    summary: "The domain explorer is mounted inside the advanced control plane.",
    status: "wired",
    targetTab: "advanced",
    targetLabel: "Open Advanced"
  },
  {
    title: "Sessions Dashboard",
    kitSource: "frontend/src/features/sessions/Dashboard.tsx",
    summary: "The run dashboard is embedded inside Sessions & Runs, but it is not a standalone tab.",
    status: "reference",
    targetTab: "operations",
    targetLabel: "Open Sessions & Runs"
  }
];

export const DESIGN_KIT_LEGACY_SURFACES: ReadonlyArray<DesignKitSurface> = [
  {
    title: "OperationsHub / ControlPanel / ProcessList",
    kitSource: "frontend/src/features/operations-hub/*.tsx",
    summary: "Older placeholder entrypoints are legacy; the current Operations Hub is mounted inside Sessions & Runs.",
    status: "legacy"
  },
  {
    title: "Standalone HTML pages",
    kitSource: "design-system/ui_kits/control-plane/*.html",
    summary: "Several kit pages remain standalone reference surfaces rather than live runtime routes.",
    status: "reference"
  }
];

function SurfaceCard({
  surface,
  onNavigate
}: {
  readonly surface: DesignKitSurface;
  readonly onNavigate: (tab: AppTab) => void;
}): JSX.Element {
  const targetTab = surface.targetTab;

  return (
    <article className={`design-kit-surface-card design-kit-surface-card--${surface.status}`}>
      <div className="design-kit-surface-head">
        <div>
          <p className="design-kit-surface-eyebrow">
            {surface.status === "wired"
              ? "Live-wired"
              : surface.status === "shell"
                ? "Shell-level"
                : surface.status === "legacy"
                  ? "Legacy"
                  : "Reference"}
          </p>
          <h3>{surface.title}</h3>
        </div>
        <span className="design-kit-surface-pill">{surface.status}</span>
      </div>
      <p className="design-kit-surface-summary">{surface.summary}</p>
      <p className="design-kit-surface-source">
        <span>Source</span>
        <code>{surface.kitSource}</code>
      </p>
      {targetTab ? (
        <button type="button" className="design-kit-surface-link" onClick={() => onNavigate(targetTab)}>
          {surface.targetLabel ?? "Open live surface"}
        </button>
      ) : (
        <span className="design-kit-surface-muted">No live route wired.</span>
      )}
    </article>
  );
}

export function DesignKitSurfacesPanel({ onNavigate }: DesignKitSurfacesPanelProps): JSX.Element {
  return (
    <section className="design-kit-surfaces-page" aria-label="Design kit surfaces">
      <header className="design-kit-surfaces-hero">
        <div>
          <p className="design-kit-surfaces-eyebrow">Design-system / control-plane</p>
          <h2>Design Kit Surfaces</h2>
          <p>
            This page exposes the source kit references and points into the live runtime tabs that actually
            mount them. It keeps the wiring truthful by calling out what is live, embedded, or legacy-only.
          </p>
        </div>
        <div className="design-kit-surfaces-actions" aria-label="Quick runtime jumps">
          {DESIGN_KIT_QUICK_JUMPS.map((jump) => (
            <button key={jump.title} type="button" onClick={() => onNavigate(jump.targetTab)}>
              {jump.targetLabel}
            </button>
          ))}
        </div>
      </header>

      <section className="design-kit-surfaces-section" aria-labelledby="design-kit-live-heading">
        <div className="design-kit-surfaces-section-head">
          <h3 id="design-kit-live-heading">Live-wired surfaces</h3>
          <p>These kit pieces already have a live destination in the runtime app.</p>
        </div>
        <div className="design-kit-surface-grid">
          {DESIGN_KIT_LIVE_SURFACES.map((surface) => (
            <SurfaceCard key={surface.title} surface={surface} onNavigate={onNavigate} />
          ))}
        </div>
      </section>

      <section className="design-kit-surfaces-section" aria-labelledby="design-kit-shared-heading">
        <div className="design-kit-surfaces-section-head">
          <h3 id="design-kit-shared-heading">Shell and reference surfaces</h3>
          <p>These pieces are present in the runtime shell or embedded within an existing live view.</p>
        </div>
        <div className="design-kit-surface-grid">
          {DESIGN_KIT_SHARED_REFERENCES.map((surface) => (
            <SurfaceCard key={surface.title} surface={surface} onNavigate={onNavigate} />
          ))}
        </div>
      </section>

      <section className="design-kit-surfaces-section" aria-labelledby="design-kit-legacy-heading">
        <div className="design-kit-surfaces-section-head">
          <h3 id="design-kit-legacy-heading">Legacy and standalone references</h3>
          <p>These files remain useful as references, but they are not mounted as first-class app routes.</p>
        </div>
        <div className="design-kit-surface-grid">
          {DESIGN_KIT_LEGACY_SURFACES.map((surface) => (
            <SurfaceCard key={surface.title} surface={surface} onNavigate={onNavigate} />
          ))}
        </div>
      </section>
    </section>
  );
}
