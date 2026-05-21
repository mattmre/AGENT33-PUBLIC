import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AuthPanel } from "./components/AuthPanel";
import { AppNavigation } from "./components/AppNavigation";
import { ArtifactReviewDrawer } from "./components/ArtifactReviewDrawer";
import { CockpitProjectDashboard } from "./components/CockpitProjectDashboard";
import { GlobalSearch } from "./components/GlobalSearch";
import { PermissionModeControl } from "./components/PermissionModeControl";
import { ShipyardLaneScaffold } from "./components/ShipyardLaneScaffold";
import { SkipLink } from "./components/SkipLink";
import { WorkspaceSessionSelector } from "./components/WorkspaceSessionSelector";
import { WorkspaceTaskBoard } from "./components/WorkspaceTaskBoard";
import { LiveVoicePanel } from "./features/voice/LiveVoicePanel";
import { MessagingSetup } from "./features/integrations/MessagingSetup";
import { ModelConnectionWizardPanel } from "./features/model-connection/ModelConnectionWizardPanel";
import { ChatInterface } from "./features/chat/ChatInterface";
import { OperationsHubPanel } from "./features/operations-hub/OperationsHubPanel";
import { IngestionReviewPanel } from "./features/operations-hub/IngestionReviewPanel";
import { OutcomesDashboardPanel } from "./features/outcomes-dashboard/OutcomesDashboardPanel";
import { SessionAnalyticsDashboard } from "./features/session-analytics/SessionAnalyticsDashboard";
import AgentBuilderPage from "./features/agent-builder/AgentBuilderPage";
import "./features/agent-builder/AgentBuilderPage.css";
import { PackMarketplacePage } from "./features/pack-marketplace";
import "./features/pack-marketplace/PackMarketplacePage.css";
import { SpawnerPage } from "./features/spawner";
import { ToolCatalogPage } from "./features/tool-catalog";
import { ImpactDashboardPanel } from "./features/impact-dashboard";
import { SafetyCenterPanel } from "./features/safety-center/SafetyCenterPanel";
import { PolicyControlPanel } from "./features/policy-control/PolicyControlPanel";
import { SkillWizardPanel } from "./features/skill-wizard/SkillWizardPanel";
import { ToolFabricPanel } from "./features/tool-fabric/ToolFabricPanel";
import { ResourceCatalogPanel } from "./features/resource-catalog/ResourceCatalogPanel";
import { WorkflowStarterPanel } from "./features/workflow-starter/WorkflowStarterPanel";
import { WorkflowCatalogPanel } from "./features/workflow-catalog/WorkflowCatalogPanel";
import { ImprovementLoopsPanel } from "./features/improvement-loops/ImprovementLoopsPanel";
import { McpHealthPanel } from "./features/mcp-health/McpHealthPanel";
import { OutcomeHomePanel } from "./features/outcome-home/OutcomeHomePanel";
import { DemoModePanel } from "./features/demo-mode/DemoModePanel";
import { RoleIntakePanel } from "./features/role-intake/RoleIntakePanel";
import { UnifiedConnectCenterPanel } from "./features/connect-center/UnifiedConnectCenterPanel";
import { isUserRoleId } from "./features/role-intake/data";
import { HelpAssistantDrawer } from "./features/help-assistant/HelpAssistantDrawer";
import {
  AdvancedControlPlanePanel,
  type OperatorMode
} from "./features/advanced/AdvancedControlPlanePanel";
import { DesignKitSurfacesPanel } from "./features/design-kit/DesignKitSurfacesPanel";
import { PlanningPanel } from "./features/planning";
import { SupportPanel } from "./features/support";
import { SandboxingPanel } from "./features/sandboxing";
import { domains } from "./data/domains";
import {
  DEFAULT_APP_TAB,
  ROLE_SELECTED_DEFAULT_APP_TAB,
  getAppTabDescription,
  getAppTabGroup,
  getAppTabLabel,
  type AppTab
} from "./data/navigation";
import {
  DEFAULT_WORKSPACE_SESSION_ID,
  getWorkspaceSession,
  isWorkspaceSessionId,
  type WorkspaceSessionId
} from "./data/workspaces";
import {
  DEFAULT_PERMISSION_MODE_ID,
  isPermissionModeId,
  type PermissionModeId
} from "./data/permissionModes";
import {
  DEFAULT_COCKPIT_OPERATOR_MODE,
  DEFAULT_ARTIFACT_DRAWER_SECTION_ID,
  createCockpitUrl,
  isCockpitOperatorMode,
  readCockpitUrlState,
  type ArtifactDrawerSectionId,
  type CockpitUrlState
} from "./lib/cockpitUrlState";
import { saveApiKey, saveToken, getSavedApiKey, getSavedToken } from "./lib/auth";
import type { ActivityItem, ApiResult } from "./types";
import type { HelpAssistantTarget } from "./features/help-assistant/types";
import type { WorkflowStarterDraft } from "./features/workflow-starter/types";
import type { UserRoleId } from "./features/role-intake/types";

const ROLE_STORAGE_KEY = "agent33:selected-role";
const WORKSPACE_SESSION_STORAGE_KEY = "agent33:selected-workspace-session";
const PERMISSION_MODE_STORAGE_KEY = "agent33:permission-mode";
const OPERATOR_MODE_STORAGE_KEY = "agent33:operator-mode";

function getSavedUserRole(): UserRoleId | null {
  if (typeof window === "undefined") {
    return null;
  }

  const savedRole = window.sessionStorage.getItem(ROLE_STORAGE_KEY);
  return isUserRoleId(savedRole) ? savedRole : null;
}

function getSavedWorkspaceSessionId(): WorkspaceSessionId {
  if (typeof window === "undefined") {
    return DEFAULT_WORKSPACE_SESSION_ID;
  }

  const savedWorkspaceId = window.sessionStorage.getItem(WORKSPACE_SESSION_STORAGE_KEY);
  return isWorkspaceSessionId(savedWorkspaceId) ? savedWorkspaceId : DEFAULT_WORKSPACE_SESSION_ID;
}

function getSavedPermissionModeId(): PermissionModeId {
  if (typeof window === "undefined") {
    return DEFAULT_PERMISSION_MODE_ID;
  }

  const savedPermissionMode = window.sessionStorage.getItem(PERMISSION_MODE_STORAGE_KEY);
  return isPermissionModeId(savedPermissionMode) ? savedPermissionMode : DEFAULT_PERMISSION_MODE_ID;
}

function getSavedOperatorMode(): OperatorMode {
  if (typeof window === "undefined") {
    return DEFAULT_COCKPIT_OPERATOR_MODE;
  }

  const savedOperatorMode = window.sessionStorage.getItem(OPERATOR_MODE_STORAGE_KEY);
  return isCockpitOperatorMode(savedOperatorMode) ? savedOperatorMode : DEFAULT_COCKPIT_OPERATOR_MODE;
}

function saveOperatorMode(mode: OperatorMode): void {
  if (typeof window !== "undefined") {
    window.sessionStorage.setItem(OPERATOR_MODE_STORAGE_KEY, mode);
  }
}

function getCurrentCockpitUrlState(fallbackState: Partial<CockpitUrlState>): CockpitUrlState {
  if (typeof window === "undefined") {
    return readCockpitUrlState("", fallbackState);
  }

  return readCockpitUrlState(window.location.search, fallbackState);
}

export default function App(): JSX.Element {
  const [initialCockpitUrlState] = useState(() =>
    getCurrentCockpitUrlState({
      activeTab: getSavedUserRole() ? ROLE_SELECTED_DEFAULT_APP_TAB : DEFAULT_APP_TAB,
      workspaceId: getSavedWorkspaceSessionId(),
      permissionModeId: getSavedPermissionModeId(),
      drawerSectionId: DEFAULT_ARTIFACT_DRAWER_SECTION_ID,
      operatorMode: getSavedOperatorMode()
    })
  );
  const [activeTab, setActiveTab] = useState<AppTab>(initialCockpitUrlState.activeTab);

  // Legacy Domain Panel State (Maintained for Advanced Settings)
  const [selectedDomainId, setSelectedDomainId] = useState(domains[0]?.id ?? "overview");
  const [operatorMode, setOperatorModeState] = useState<OperatorMode>(initialCockpitUrlState.operatorMode);
  const [token, setTokenState] = useState(getSavedToken());
  const [apiKey, setApiKeyState] = useState(getSavedApiKey());
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [workflowStarterDraft, setWorkflowStarterDraft] = useState<WorkflowStarterDraft | null>(null);
  const [selectedRole, setSelectedRole] = useState<UserRoleId | null>(getSavedUserRole);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<WorkspaceSessionId>(initialCockpitUrlState.workspaceId);
  const [permissionModeId, setPermissionModeId] = useState<PermissionModeId>(initialCockpitUrlState.permissionModeId);
  const [drawerSectionId, setDrawerSectionId] = useState<ArtifactDrawerSectionId>(
    initialCockpitUrlState.drawerSectionId
  );
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const selectedWorkspace = getWorkspaceSession(selectedWorkspaceId);
  const selectedWorkspaceStatus = selectedWorkspace.status.toLowerCase();
  const showCockpitDashboard = activeTab === "operations";
  const activeTabGroup = getAppTabGroup(activeTab);
  const activeTabDescription = getAppTabDescription(activeTab);
  const currentCockpitUrlState = useMemo(
    (): CockpitUrlState => ({
      activeTab,
      workspaceId: selectedWorkspaceId,
      permissionModeId,
      drawerSectionId,
      operatorMode
    }),
    [activeTab, selectedWorkspaceId, permissionModeId, drawerSectionId, operatorMode]
  );
  const currentCockpitUrlStateRef = useRef(currentCockpitUrlState);
  const isApplyingBrowserNavigationRef = useRef(false);
  const hasSyncedInitialUrlRef = useRef(false);

  useEffect(() => {
    function onPopState(): void {
      const nextState = getCurrentCockpitUrlState(currentCockpitUrlStateRef.current);
      isApplyingBrowserNavigationRef.current = true;
      setActiveTab(nextState.activeTab);
      setSelectedWorkspaceId(nextState.workspaceId);
      setPermissionModeId(nextState.permissionModeId);
      setDrawerSectionId(nextState.drawerSectionId);
      setOperatorModeState(nextState.operatorMode);
      saveOperatorMode(nextState.operatorMode);
    }

    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    currentCockpitUrlStateRef.current = currentCockpitUrlState;
    const nextUrl = createCockpitUrl(window.location.href, currentCockpitUrlState);
    const currentUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;

    if (nextUrl === currentUrl) {
      hasSyncedInitialUrlRef.current = true;
      isApplyingBrowserNavigationRef.current = false;
      return;
    }

    const shouldReplace = !hasSyncedInitialUrlRef.current || isApplyingBrowserNavigationRef.current;
    window.history[shouldReplace ? "replaceState" : "pushState"](null, "", nextUrl);
    hasSyncedInitialUrlRef.current = true;
    isApplyingBrowserNavigationRef.current = false;
  }, [currentCockpitUrlState]);

  useEffect(() => {
    setIsSidebarOpen(false);
  }, [activeTab]);

  function setToken(tokenValue: string): void {
    setTokenState(tokenValue);
    saveToken(tokenValue);
  }

  function setApiKey(apiKeyValue: string): void {
    setApiKeyState(apiKeyValue);
    saveApiKey(apiKeyValue);
  }

  const setOperatorMode = useCallback((mode: OperatorMode): void => {
    setOperatorModeState(mode);
    saveOperatorMode(mode);
  }, []);

  const onResult = useCallback((label: string, result: ApiResult): void => {
    const item: ActivityItem = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      at: new Date().toLocaleTimeString(),
      label,
      status: result.status,
      durationMs: result.durationMs,
      url: result.url
    };
    setActivity((prev) => [item, ...prev].slice(0, 15));
  }, []);

  const openWorkflowStarter = useCallback((draft?: WorkflowStarterDraft): void => {
    setWorkflowStarterDraft(draft ?? null);
    setActiveTab("starter");
  }, []);

  const chooseRole = useCallback((roleId: UserRoleId): void => {
    setSelectedRole(roleId);
    if (typeof window !== "undefined") {
      window.sessionStorage.setItem(ROLE_STORAGE_KEY, roleId);
    }
  }, []);

  const openHelpTarget = useCallback((target: HelpAssistantTarget): void => {
    setActiveTab(target);
  }, []);

  const selectWorkspace = useCallback((workspaceId: WorkspaceSessionId): void => {
    setSelectedWorkspaceId(workspaceId);
    if (typeof window !== "undefined") {
      window.sessionStorage.setItem(WORKSPACE_SESSION_STORAGE_KEY, workspaceId);
    }
  }, []);

  const selectPermissionMode = useCallback((modeId: PermissionModeId): void => {
    setPermissionModeId(modeId);
    if (typeof window !== "undefined") {
      window.sessionStorage.setItem(PERMISSION_MODE_STORAGE_KEY, modeId);
    }
  }, []);

  const focusOperationsBoard = useCallback((): void => {
    const operationsBoard = document.getElementById("operations-workspace-board");
    if (!operationsBoard) {
      throw new Error("Operations workspace board anchor is unavailable.");
    }

    operationsBoard.scrollIntoView({ block: "start" });
    operationsBoard.focus();
  }, []);

  const stageActions = useMemo(
    () =>
      [
        activeTab === "starter"
          ? null
          : {
              label: "Launch workflow",
              onClick: () => openWorkflowStarter()
            },
        activeTab === "operations"
          ? null
          : {
              label: "View runs",
              onClick: () => setActiveTab("operations")
            },
        activeTab === "models"
          ? null
          : {
              label: "Connect models",
              onClick: () => setActiveTab("models")
            },
        activeTab === "safety"
          ? null
          : {
              label: "Review approvals",
              onClick: () => setActiveTab("safety")
            }
      ].filter((action): action is { label: string; onClick: () => void } => action !== null),
    [activeTab, openWorkflowStarter]
  );

  return (
    <div className="consumer-app-shell">
      <SkipLink />
      <header className="consumer-topbar">
        <div className="brand">
          <div className="logo-orb" aria-hidden="true"></div>
          <h1>AGENT-33</h1>
        </div>
        <button
          type="button"
          className="consumer-nav-toggle"
          aria-controls="cockpit-sidebar"
          aria-expanded={isSidebarOpen}
          onClick={() => setIsSidebarOpen((current) => !current)}
        >
          {isSidebarOpen ? "Close navigation" : "Open navigation"}
        </button>
      </header>

      <button
        type="button"
        className={`cockpit-sidebar-backdrop${isSidebarOpen ? " cockpit-sidebar-backdrop-visible" : ""}`}
        aria-label="Close navigation"
        onClick={() => setIsSidebarOpen(false)}
      />

      <div className="cockpit-layout">
        <aside
          id="cockpit-sidebar"
          className={`cockpit-sidebar${isSidebarOpen ? " cockpit-sidebar-open" : ""}`}
          aria-label="Workspace navigation"
        >
          <div className="cockpit-sidebar-mobile-head">
            <div>
              <span className="main-nav-group-label">Navigation</span>
              <strong>{selectedWorkspace.name}</strong>
            </div>
            <button type="button" onClick={() => setIsSidebarOpen(false)}>
              Close
            </button>
          </div>
          <section className="cockpit-sidebar-hero" aria-label="Workspace overview">
            <div className="cockpit-sidebar-hero-copy">
              <span className="main-nav-group-label">Current workspace</span>
              <strong>{selectedWorkspace.name}</strong>
              <p>{selectedWorkspace.template} template tuned for {selectedWorkspace.goal}.</p>
            </div>
            <div className="cockpit-sidebar-hero-meta">
              <span>{selectedWorkspaceStatus}</span>
              <small>{selectedWorkspace.updatedLabel}</small>
            </div>
          </section>
          <AppNavigation activeTab={activeTab} onNavigate={setActiveTab} />
          <section className="cockpit-sidebar-context cockpit-sidebar-actions" aria-label="Quick actions">
            <span className="main-nav-group-label">Go next</span>
            <p>Move to the next likely operator action without searching the whole cockpit.</p>
            <div className="cockpit-sidebar-action-grid">
              {stageActions.map((action) => (
                <button key={action.label} type="button" onClick={action.onClick}>
                  {action.label}
                </button>
              ))}
            </div>
          </section>
          <section className="cockpit-sidebar-context cockpit-sidebar-search" aria-label="Global search">
            <span className="main-nav-group-label">Search</span>
            <p>Jump to memory and prior execution context without leaving the sidebar.</p>
            <GlobalSearch token={token || null} />
          </section>
          <WorkspaceSessionSelector
            selectedWorkspaceId={selectedWorkspaceId}
            onSelectWorkspace={selectWorkspace}
            onOpenRuns={() => setActiveTab("operations")}
            onOpenWorkflows={openWorkflowStarter}
          />
          <PermissionModeControl
            selectedModeId={permissionModeId}
            operatorMode={operatorMode}
            onSelectMode={selectPermissionMode}
            onOperatorModeChange={setOperatorMode}
          />
        </aside>

        <main className="cockpit-main" id="main-content" role="main">
          <div className="cockpit-context-bar" aria-label="Current workspace context">
            <div className="cockpit-context-copy">
              <span className="eyebrow">{activeTabGroup?.label ?? "Workspace"}</span>
              <strong>{getAppTabLabel(activeTab)}</strong>
              <span className="cockpit-context-note">
                {activeTabDescription || "Use the sidebar to switch surfaces and keep work in one lane."}
              </span>
            </div>
            <div className="cockpit-context-stage">
              <span>{selectedWorkspace.name}</span>
              <small>{selectedWorkspaceStatus} · {selectedWorkspace.goal}</small>
            </div>
          </div>

          <div className={showCockpitDashboard ? "cockpit-workspace-stage cockpit-workspace-stage-with-drawer" : "cockpit-workspace-stage"}>
            <div className="cockpit-stage-content">
              <div className="consumer-content">
                {showCockpitDashboard ? (
                  <CockpitProjectDashboard
                    workspace={selectedWorkspace}
                    permissionModeId={permissionModeId}
                    onReviewCurrentWork={focusOperationsBoard}
                    onOpenWorkflows={() => setActiveTab("starter")}
                    onOpenSafety={() => setActiveTab("safety")}
                  />
                ) : null}
        {activeTab === "guide" && (
          <div className="consumer-role-intake-layout">
            <RoleIntakePanel
              selectedRole={selectedRole}
              onSelectRole={chooseRole}
              onOpenDemo={() => setActiveTab("demo")}
              onOpenModels={() => setActiveTab("models")}
              onOpenWorkflowCatalog={() => setActiveTab("catalog")}
              onOpenWorkflowStarter={openWorkflowStarter}
            />
          </div>
        )}

        {activeTab === "start" && (
          <div className="consumer-onboarding-layout">
            <OutcomeHomePanel
              selectedRole={selectedRole}
              token={token}
              apiKey={apiKey}
              onOpenSetup={() => setActiveTab("setup")}
              onOpenModels={() => setActiveTab("models")}
              onOpenDemo={() => setActiveTab("demo")}
              onOpenChat={() => setActiveTab("chat")}
              onOpenOperations={() => setActiveTab("operations")}
              onOpenWorkflowStarter={openWorkflowStarter}
              onOpenLoops={() => setActiveTab("loops")}
              onOpenMcp={() => setActiveTab("mcp")}
              onOpenAdvanced={() => setActiveTab("advanced")}
              onResult={onResult}
            />
          </div>
        )}

        {activeTab === "connect" && (
          <div className="consumer-connect-center-layout">
            <UnifiedConnectCenterPanel
              token={token}
              apiKey={apiKey}
              onNavigate={setActiveTab}
              onResult={onResult}
            />
          </div>
        )}

        {activeTab === "demo" && (
          <div className="consumer-demo-mode-layout">
            <DemoModePanel
              selectedRole={selectedRole}
              onOpenModels={() => setActiveTab("models")}
              onOpenWorkflowCatalog={() => setActiveTab("catalog")}
              onOpenWorkflowStarter={openWorkflowStarter}
            />
          </div>
        )}

        {/* Chat Central -> Render new ChatInterface */}
        {activeTab === "chat" && (
          <div className="consumer-chat-layout">
            <div className="consumer-chat-shortcuts" aria-label="Chat launch shortcuts">
              <button
                className="consumer-chat-shortcut"
                onClick={() => setActiveTab("voice")}
              >
                <strong>Voice session</strong>
                <small>Move the conversation into live voice and dictation.</small>
              </button>
              <button
                className="consumer-chat-shortcut"
                onClick={() => setActiveTab("setup")}
              >
                <strong>Connect integrations</strong>
                <small>Fix provider or token gaps before you start a live thread.</small>
              </button>
              <button
                className="consumer-chat-shortcut"
                onClick={() => setActiveTab("advanced")}
              >
                <strong>Open control plane</strong>
                <small>Drop into raw controls only when the guided path is too shallow.</small>
              </button>
            </div>
            <ChatInterface token={token} apiKey={apiKey} />
          </div>
        )}

        {/* Model Connection -> plain-language provider setup and probe flow */}
        {activeTab === "models" && (
          <div className="consumer-model-wizard-layout">
            <ModelConnectionWizardPanel
              token={token}
              apiKey={apiKey}
              onOpenSetup={() => setActiveTab("setup")}
              onOpenWorkflowCatalog={() => setActiveTab("catalog")}
              onResult={onResult}
            />
          </div>
        )}

        {/* Voice Call -> Render LiveVoicePanel cleanly centered */}
        {activeTab === "voice" && (
          <div className="consumer-voice-layout">
            <LiveVoicePanel token={token || null} onOpenSetup={() => setActiveTab("setup")} />
          </div>
        )}

        {/* Integrations Setup -> Render new MessagingSetup component */}
        {activeTab === "setup" && (
          <div className="consumer-setup-layout">
            <MessagingSetup token={token} apiKey={apiKey} />
            <div className="auth-settings-card">
              <h3>Agent API Access</h3>
              <p>Configure internal tokens to securely access the AGENT-33 engine.</p>
              <AuthPanel
                token={token}
                apiKey={apiKey}
                onTokenChange={setToken}
                onApiKeyChange={setApiKey}
              />
            </div>
          </div>
        )}

        {/* Review Queue -> direct operator surface for candidate assets */}
        {activeTab === "review" && (
          <div className="consumer-review-layout">
            <IngestionReviewPanel token={token} apiKey={apiKey} onResult={onResult} />
          </div>
        )}

        {/* Safety Center -> direct HITL approval surface for governed tool calls */}
        {activeTab === "safety" && (
          <div className="consumer-safety-layout">
            <SafetyCenterPanel
              token={token}
              apiKey={apiKey}
              onOpenSetup={() => setActiveTab("setup")}
              onResult={onResult}
            />
          </div>
        )}

        {activeTab === "policy" && (
          <div className="consumer-policy-layout">
            <PolicyControlPanel token={token} />
          </div>
        )}

        {/* Skill Wizard -> plain-language skill authoring and installation */}
        {activeTab === "skills" && (
          <div className="consumer-skill-wizard-layout">
            <SkillWizardPanel
              token={token}
              apiKey={apiKey}
              onOpenSetup={() => setActiveTab("setup")}
              onResult={onResult}
            />
          </div>
        )}

        {/* Tool Fabric -> adaptive tool/skill/workflow discovery */}
        {activeTab === "fabric" && (
          <div className="consumer-tool-fabric-layout">
            <ToolFabricPanel
              token={token}
              apiKey={apiKey}
              onOpenSetup={() => setActiveTab("setup")}
              onOpenTools={() => setActiveTab("tools")}
              onOpenSkills={() => setActiveTab("skills")}
              onOpenWorkflowStarter={() => openWorkflowStarter()}
              onResult={onResult}
            />
          </div>
        )}

        {activeTab === "resources" && (
          <div className="consumer-resource-catalog-layout">
            <ResourceCatalogPanel token={token || null} apiKey={apiKey || null} />
          </div>
        )}

        {/* MCP Health -> server/tool/sync readiness for external tool fabric */}
        {activeTab === "mcp" && (
          <div className="consumer-mcp-health-layout">
            <McpHealthPanel
              token={token}
              apiKey={apiKey}
              onOpenSetup={() => setActiveTab("setup")}
              onOpenToolFabric={() => setActiveTab("fabric")}
              onOpenTools={() => setActiveTab("tools")}
              onResult={onResult}
            />
          </div>
        )}

        {/* Workflow Catalog -> curated outcome systems with safe starter routing */}
        {activeTab === "catalog" && (
          <div className="consumer-workflow-catalog-layout">
            <WorkflowCatalogPanel
              onOpenWorkflowStarter={openWorkflowStarter}
              onOpenSetup={() => setActiveTab("setup")}
              onOpenOperations={() => setActiveTab("operations")}
            />
          </div>
        )}

        {/* Workflow Starter -> guided research and loop workflow creation */}
        {activeTab === "starter" && (
          <div className="consumer-workflow-starter-layout">
            <WorkflowStarterPanel
              token={token}
              apiKey={apiKey}
              onOpenSetup={() => setActiveTab("setup")}
              onOpenSpawner={() => setActiveTab("spawner")}
              onOpenOperations={() => setActiveTab("operations")}
              initialDraft={workflowStarterDraft}
              onResult={onResult}
            />
          </div>
        )}

        {/* Improvement Loops -> recurring research and improvement workflows */}
        {activeTab === "loops" && (
          <div className="consumer-improvement-loops-layout">
            <ImprovementLoopsPanel
              token={token}
              apiKey={apiKey}
              onOpenSetup={() => setActiveTab("setup")}
              onOpenOperations={() => setActiveTab("operations")}
              onOpenWorkflowStarter={() => openWorkflowStarter()}
              onResult={onResult}
            />
          </div>
        )}

        {/* Operations Hub -> Unified lifecycle view with pause/resume/cancel controls */}
        {activeTab === "operations" && (
          <div className="consumer-operations-layout">
            <ShipyardLaneScaffold
              workspace={selectedWorkspace}
              permissionModeId={permissionModeId}
              onOpenSafety={() => setActiveTab("safety")}
              onOpenWorkflows={openWorkflowStarter}
            />
            <div id="operations-workspace-board" className="operations-workspace-board-anchor" tabIndex={-1}>
              <WorkspaceTaskBoard
                workspace={selectedWorkspace}
                permissionModeId={permissionModeId}
                onOpenSafety={() => setActiveTab("safety")}
                onOpenWorkflows={openWorkflowStarter}
              />
            </div>
            <OperationsHubPanel token={token} apiKey={apiKey} onResult={onResult} />
          </div>
        )}

        {/* Outcomes Dashboard -> Trend analysis, domain filtering, decline-triggered improvements */}
        {activeTab === "outcomes" && (
          <div className="consumer-outcomes-layout">
            <OutcomesDashboardPanel token={token} apiKey={apiKey} onResult={onResult} />
          </div>
        )}

        {/* Session Analytics -> Usage insights, model costs, daily activity */}
        {activeTab === "analytics" && (
          <div className="consumer-analytics-layout">
            <SessionAnalyticsDashboard token={token} apiKey={apiKey} onResult={onResult} />
          </div>
        )}

        {/* Impact Dashboard -> ROI, pack impact, week-over-week trends */}
        {activeTab === "impact" && (
          <div className="consumer-impact-layout">
            <ImpactDashboardPanel token={token} apiKey={apiKey} onResult={onResult} />
          </div>
        )}

        {/* Tool Catalog -> Runtime tool catalog with search, filters, schema */}
        {activeTab === "tools" && (
          <div className="consumer-tools-layout">
            <ToolCatalogPage token={token || null} apiKey={apiKey || null} />
          </div>
        )}

        {activeTab === "marketplace" && (
          <div className="consumer-marketplace-layout">
            <PackMarketplacePage
              token={token || null}
              apiKey={apiKey || null}
              onOpenWorkflowStarter={openWorkflowStarter}
            />
          </div>
        )}

        {/* Agent Builder -> Visual agent creation with capability toggles and preview */}
        {activeTab === "builder" && (
          <div className="consumer-builder-layout">
            <AgentBuilderPage token={token} apiKey={apiKey} />
          </div>
        )}

        {/* Sub-Agent Spawner -> Visual workflow builder for parent-child delegation */}
        {activeTab === "spawner" && (
          <div className="consumer-spawner-layout">
            <SpawnerPage token={token} apiKey={apiKey} />
          </div>
        )}

        {/* Advanced Settings -> quarantined raw control plane */}
        {activeTab === "advanced" && (
          <AdvancedControlPlanePanel
            domains={domains}
            selectedDomainId={selectedDomainId}
            token={token}
            apiKey={apiKey}
            activity={activity}
            operatorMode={operatorMode}
            onOperatorModeChange={setOperatorMode}
            onSelectedDomainChange={setSelectedDomainId}
            onOpenModels={() => setActiveTab("models")}
            onOpenWorkflowCatalog={() => setActiveTab("catalog")}
            onOpenOperations={() => setActiveTab("operations")}
            onOpenSafety={() => setActiveTab("safety")}
            onOpenSetup={() => setActiveTab("setup")}
            onResult={onResult}
          />
        )}
        {activeTab === "design-kit" && (
          <div className="consumer-design-kit-layout">
            <DesignKitSurfacesPanel onNavigate={setActiveTab} />
          </div>
        )}

        {activeTab === "planning" && (
          <div className="consumer-planning-layout">
            <PlanningPanel token={token || null} />
          </div>
        )}

        {activeTab === "support" && (
          <div className="consumer-support-layout">
            <SupportPanel token={token || null} />
          </div>
        )}

        {activeTab === "sandboxing" && (
          <div className="consumer-sandboxing-layout">
            <SandboxingPanel token={token || null} />
          </div>
        )}
              </div>
            </div>
            {showCockpitDashboard ? (
              <ArtifactReviewDrawer
                workspace={selectedWorkspace}
                permissionModeId={permissionModeId}
                activeSectionId={drawerSectionId}
                onSectionChange={setDrawerSectionId}
              />
            ) : null}
          </div>
        </main>
      </div>
      <HelpAssistantDrawer onNavigate={openHelpTarget} />
    </div>
  );
}
