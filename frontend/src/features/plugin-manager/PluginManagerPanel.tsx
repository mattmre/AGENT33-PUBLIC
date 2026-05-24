import { useEffect, useMemo, useState } from "react";

import {
  disablePlugin,
  discoverPlugins,
  enablePlugin,
  fetchPluginDoctorSummary,
  fetchPluginWorkspace,
  fetchPlugins,
  installPlugin,
  linkPlugin,
  reloadPlugin,
  savePluginConfig,
  searchPlugins,
  updatePlugin
} from "./api";
import type {
  PluginDoctorReport,
  PluginSummary,
  PluginWorkspace
} from "./types";

interface PluginManagerPanelProps {
  token: string | null;
  apiKey: string | null;
  onOpenSetup: () => void;
}

type InstallMode = "copy" | "link";
type EnabledDraft = "leave" | "true" | "false";

function formatState(value: string): string {
  return value.replace(/_/g, " ");
}

function stateTone(value: string): string {
  const normalized = value.toLowerCase();
  if (normalized === "active") {
    return "active";
  }
  if (normalized === "loaded" || normalized === "disabled") {
    return "idle";
  }
  if (normalized === "error") {
    return "error";
  }
  return "unknown";
}

function doctorTone(value: string | undefined): string {
  const normalized = (value ?? "unknown").toLowerCase();
  if (normalized === "healthy" || normalized === "ok" || normalized === "pass") {
    return "active";
  }
  if (normalized === "warning" || normalized === "degraded") {
    return "idle";
  }
  if (normalized === "error" || normalized === "failed") {
    return "error";
  }
  return "unknown";
}

function prettyJson(value: unknown): string {
  if (!value || (typeof value === "object" && Object.keys(value).length === 0)) {
    return "{}";
  }
  return JSON.stringify(value, null, 2);
}

function parseJsonObject(value: string, label: string): Record<string, unknown> {
  const trimmed = value.trim();
  if (!trimmed) {
    return {};
  }

  const parsed = JSON.parse(trimmed) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON object.`);
  }
  return parsed as Record<string, unknown>;
}

function enabledValue(value: EnabledDraft): boolean | null {
  if (value === "true") {
    return true;
  }
  if (value === "false") {
    return false;
  }
  return null;
}

function contributionCount(plugin: PluginSummary): number {
  return Object.values(plugin.contributions_summary).reduce((total, count) => total + count, 0);
}

function configOverrides(workspace: PluginWorkspace | null): Record<string, unknown> {
  return (
    workspace?.config.config_overrides ??
    workspace?.config.config ??
    workspace?.detail.tenant_config?.config_overrides ??
    {}
  );
}

function permissionOverrides(workspace: PluginWorkspace | null): Record<string, boolean> {
  return (
    workspace?.config.permission_overrides ??
    workspace?.detail.tenant_config?.permission_overrides ??
    {}
  );
}

function ReportBadge({ report }: { report: PluginDoctorReport | null | undefined }): JSX.Element {
  if (!report) {
    return <span className="plugin-manager-pill plugin-manager-pill-unknown">Doctor unknown</span>;
  }
  return (
    <span className={`plugin-manager-pill plugin-manager-pill-${doctorTone(report.overall_status)}`}>
      Doctor {formatState(report.overall_status)}
    </span>
  );
}

export function PluginManagerPanel({
  token,
  apiKey,
  onOpenSetup
}: PluginManagerPanelProps): JSX.Element {
  const [plugins, setPlugins] = useState<PluginSummary[]>([]);
  const [doctorReports, setDoctorReports] = useState<Record<string, PluginDoctorReport>>({});
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<PluginWorkspace | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [stateFilter, setStateFilter] = useState("all");
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [configDraft, setConfigDraft] = useState("{}");
  const [permissionDraft, setPermissionDraft] = useState("{}");
  const [enabledDraft, setEnabledDraft] = useState<EnabledDraft>("leave");
  const [installSourcePath, setInstallSourcePath] = useState("");
  const [installName, setInstallName] = useState("");
  const [installMode, setInstallMode] = useState<InstallMode>("copy");
  const [installEnable, setInstallEnable] = useState(true);

  const authReady = Boolean(token || apiKey);

  const filteredPlugins = useMemo(() => {
    return plugins.filter((plugin) => stateFilter === "all" || plugin.state === stateFilter);
  }, [plugins, stateFilter]);

  const pluginStates = useMemo(() => {
    return Array.from(new Set(plugins.map((plugin) => plugin.state))).sort();
  }, [plugins]);

  async function loadPlugins(query = searchQuery): Promise<void> {
    if (!authReady) {
      setPlugins([]);
      setDoctorReports({});
      setSelectedName(null);
      setWorkspace(null);
      return;
    }

    setLoading(true);
    setError("");
    try {
      const [pluginResult, doctorResult] = await Promise.allSettled([
        query.trim() ? searchPlugins(token, apiKey, query.trim()) : fetchPlugins(token, apiKey),
        fetchPluginDoctorSummary(token, apiKey)
      ]);

      if (pluginResult.status === "rejected") {
        throw pluginResult.reason;
      }

      setPlugins(pluginResult.value);
      setSelectedName((current) =>
        current && pluginResult.value.some((plugin) => plugin.name === current)
          ? current
          : pluginResult.value[0]?.name ?? null
      );

      if (doctorResult.status === "fulfilled") {
        setDoctorReports(
          doctorResult.value.reports.reduce<Record<string, PluginDoctorReport>>((acc, report) => {
            acc[report.plugin_name] = report;
            return acc;
          }, {})
        );
      } else {
        setDoctorReports({});
      }
    } catch (err) {
      setPlugins([]);
      setDoctorReports({});
      setSelectedName(null);
      setWorkspace(null);
      setError(err instanceof Error ? err.message : "Plugin inventory failed");
    } finally {
      setLoading(false);
    }
  }

  async function loadSelectedPlugin(name: string): Promise<void> {
    setDetailLoading(true);
    setDetailError("");
    try {
      const loaded = await fetchPluginWorkspace(token, apiKey, name);
      setWorkspace(loaded);
      setConfigDraft(prettyJson(configOverrides(loaded)));
      setPermissionDraft(prettyJson(permissionOverrides(loaded)));
      setEnabledDraft("leave");
    } catch (err) {
      setWorkspace(null);
      setDetailError(err instanceof Error ? err.message : "Plugin detail failed");
    } finally {
      setDetailLoading(false);
    }
  }

  useEffect(() => {
    void loadPlugins("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authReady, token, apiKey]);

  useEffect(() => {
    if (!selectedName || !authReady) {
      setWorkspace(null);
      return;
    }
    void loadSelectedPlugin(selectedName);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedName, authReady]);

  async function runSelectedAction(label: string, action: () => Promise<unknown>): Promise<void> {
    if (!selectedName) {
      return;
    }
    setActionLoading(label);
    setActionError("");
    setActionMessage("");
    try {
      await action();
      setActionMessage(`${label} completed for ${selectedName}.`);
      await loadPlugins(searchQuery);
      await loadSelectedPlugin(selectedName);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : `${label} failed`);
    } finally {
      setActionLoading(null);
    }
  }

  async function handleSaveConfig(): Promise<void> {
    if (!selectedName) {
      return;
    }
    setActionLoading("Save config");
    setActionError("");
    setActionMessage("");
    try {
      const config = parseJsonObject(configDraft, "Plugin config");
      const permissions = parseJsonObject(permissionDraft, "Permission overrides");
      await savePluginConfig(
        token,
        apiKey,
        selectedName,
        config,
        enabledValue(enabledDraft),
        Object.keys(permissions).length > 0 ? (permissions as Record<string, boolean>) : null
      );
      setActionMessage(`Configuration saved for ${selectedName}.`);
      await loadSelectedPlugin(selectedName);
      await loadPlugins(searchQuery);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Plugin config save failed");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleInstall(): Promise<void> {
    if (!installSourcePath.trim()) {
      setActionError("Source path is required.");
      return;
    }

    setActionLoading("Install plugin");
    setActionError("");
    setActionMessage("");
    try {
      const result =
        installMode === "link" && installName.trim()
          ? await linkPlugin(token, apiKey, installName.trim(), installSourcePath.trim(), installEnable)
          : await installPlugin(token, apiKey, installSourcePath.trim(), installMode, installEnable);
      setActionMessage(`${result.linked ? "Linked" : "Installed"} ${result.plugin_name} ${result.version}.`);
      setInstallSourcePath("");
      setInstallName("");
      await loadPlugins(searchQuery);
      setSelectedName(result.plugin_name);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Plugin install failed");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleDiscover(): Promise<void> {
    setActionLoading("Discover plugins");
    setActionError("");
    setActionMessage("");
    try {
      const result = await discoverPlugins(token, apiKey);
      setActionMessage(`Discovery found ${result.discovered} plugin(s); ${result.total} total visible.`);
      await loadPlugins(searchQuery);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Plugin discovery failed");
    } finally {
      setActionLoading(null);
    }
  }

  if (!authReady) {
    return (
      <section className="plugin-manager-panel" aria-label="Plugin and extension manager">
        <div className="plugin-manager-empty">
          <h2>Plugins and Extensions</h2>
          <p>Connect with an operator token or API key before managing plugin lifecycle state.</p>
          <button type="button" onClick={onOpenSetup}>
            Open API access
          </button>
        </div>
      </section>
    );
  }

  const selectedReport = selectedName ? doctorReports[selectedName] ?? workspace?.doctor ?? null : null;
  const selectedPlugin = selectedName
    ? plugins.find((plugin) => plugin.name === selectedName) ?? null
    : null;

  return (
    <section className="plugin-manager-panel" aria-label="Plugin and extension manager">
      <header className="plugin-manager-header">
        <div>
          <p className="eyebrow">Phase 24 ecosystem control</p>
          <h2>Plugins and Extensions</h2>
          <p>Manage plugin lifecycle, tenant config, diagnostics, permissions, and event history.</p>
        </div>
        <div className="plugin-manager-header-actions">
          <button type="button" onClick={() => void loadPlugins(searchQuery)} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh"}
          </button>
          <button type="button" onClick={() => void handleDiscover()} disabled={actionLoading !== null}>
            {actionLoading === "Discover plugins" ? "Discovering..." : "Discover"}
          </button>
        </div>
      </header>

      {error ? <p className="plugin-manager-alert" role="alert">{error}</p> : null}
      {actionError ? <p className="plugin-manager-alert" role="alert">{actionError}</p> : null}
      {actionMessage ? <p className="plugin-manager-success" aria-live="polite">{actionMessage}</p> : null}

      <div className="plugin-manager-toolbar">
        <label>
          <span>Search plugins</span>
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Name, author, tag, description"
          />
        </label>
        <label>
          <span>State</span>
          <select value={stateFilter} onChange={(event) => setStateFilter(event.target.value)}>
            <option value="all">All states</option>
            {pluginStates.map((state) => (
              <option key={state} value={state}>
                {formatState(state)}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={() => void loadPlugins(searchQuery)} disabled={loading}>
          Apply
        </button>
      </div>

      <div className="plugin-manager-layout">
        <aside className="plugin-manager-list" aria-label="Plugin inventory">
          <div className="plugin-manager-list-summary">
            <strong>{filteredPlugins.length} visible</strong>
            <span>{plugins.length} total loaded from /v1/plugins</span>
          </div>
          {loading ? <p>Loading plugins...</p> : null}
          {!loading && filteredPlugins.length === 0 ? <p>No plugins match the current filters.</p> : null}
          {filteredPlugins.map((plugin) => (
            <button
              key={plugin.name}
              type="button"
              className={`plugin-manager-list-item${selectedName === plugin.name ? " selected" : ""}`}
              aria-pressed={selectedName === plugin.name}
              onClick={() => setSelectedName(plugin.name)}
            >
              <span className={`plugin-manager-state plugin-manager-state-${stateTone(plugin.state)}`}>
                {formatState(plugin.state)}
              </span>
              <strong>{plugin.name}</strong>
              <span>{plugin.version} · {contributionCount(plugin)} contribution(s)</span>
              <ReportBadge report={doctorReports[plugin.name]} />
            </button>
          ))}
        </aside>

        <main className="plugin-manager-detail">
          {!selectedName ? (
            <div className="plugin-manager-empty">
              <h3>Select a plugin</h3>
              <p>Choose a plugin to inspect lifecycle controls and diagnostics.</p>
            </div>
          ) : null}

          {selectedName && detailLoading ? <p>Loading plugin detail...</p> : null}
          {selectedName && detailError ? <p className="plugin-manager-alert" role="alert">{detailError}</p> : null}

          {workspace && selectedPlugin ? (
            <>
              <section className="plugin-manager-detail-hero" aria-label={`${selectedName} summary`}>
                <div>
                  <span className={`plugin-manager-state plugin-manager-state-${stateTone(workspace.detail.state)}`}>
                    {formatState(workspace.detail.state)}
                  </span>
                  <h3>{workspace.detail.name}</h3>
                  <p>{workspace.detail.description || selectedPlugin.description}</p>
                </div>
                <div className="plugin-manager-detail-actions">
                  <button
                    type="button"
                    onClick={() =>
                      void runSelectedAction("Enable plugin", () =>
                        enablePlugin(token, apiKey, workspace.detail.name)
                      )
                    }
                    disabled={actionLoading !== null || workspace.detail.state === "active"}
                  >
                    Enable
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      void runSelectedAction("Disable plugin", () =>
                        disablePlugin(token, apiKey, workspace.detail.name)
                      )
                    }
                    disabled={actionLoading !== null || workspace.detail.state !== "active"}
                  >
                    Disable
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      void runSelectedAction("Reload plugin", () =>
                        reloadPlugin(token, apiKey, workspace.detail.name)
                      )
                    }
                    disabled={actionLoading !== null}
                  >
                    Reload
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      void runSelectedAction("Update plugin", () =>
                        updatePlugin(token, apiKey, workspace.detail.name)
                      )
                    }
                    disabled={actionLoading !== null}
                  >
                    Update
                  </button>
                </div>
              </section>

              <section className="plugin-manager-metrics" aria-label="Plugin runtime status">
                <div>
                  <span>Version</span>
                  <strong>{workspace.detail.version}</strong>
                </div>
                <div>
                  <span>Runtime health</span>
                  <strong>{workspace.health?.healthy ? "Healthy" : "Needs review"}</strong>
                </div>
                <div>
                  <span>Manifest status</span>
                  <strong>{formatState(workspace.detail.status)}</strong>
                </div>
                <div>
                  <span>Doctor</span>
                  <strong>{selectedReport ? formatState(selectedReport.overall_status) : "Unknown"}</strong>
                </div>
              </section>

              <div className="plugin-manager-grid">
                <section className="plugin-manager-section">
                  <h3>Permissions</h3>
                  <dl className="plugin-manager-definition-list">
                    <div>
                      <dt>Requested</dt>
                      <dd>{(workspace.permissions?.requested ?? workspace.detail.permissions).join(", ") || "None"}</dd>
                    </div>
                    <div>
                      <dt>Granted</dt>
                      <dd>{(workspace.permissions?.granted ?? workspace.detail.granted_permissions).join(", ") || "None"}</dd>
                    </div>
                    <div>
                      <dt>Denied</dt>
                      <dd>{(workspace.permissions?.denied ?? workspace.detail.denied_permissions).join(", ") || "None"}</dd>
                    </div>
                  </dl>
                </section>

                <section className="plugin-manager-section">
                  <h3>Doctor report</h3>
                  <ReportBadge report={selectedReport} />
                  {(selectedReport?.checks ?? []).length === 0 ? <p>No doctor checks returned.</p> : null}
                  <ul className="plugin-manager-check-list">
                    {(selectedReport?.checks ?? []).map((check) => (
                      <li key={check.name}>
                        <strong>{formatState(check.name)}</strong>
                        <span className={`plugin-manager-state plugin-manager-state-${doctorTone(check.status)}`}>
                          {formatState(check.status)}
                        </span>
                        <p>{check.message}</p>
                        {check.remediation ? <small>{check.remediation}</small> : null}
                      </li>
                    ))}
                  </ul>
                </section>

                <section className="plugin-manager-section plugin-manager-config">
                  <h3>Tenant configuration</h3>
                  <label htmlFor="plugin-config-json">
                    <span>Config JSON</span>
                    <textarea
                      id="plugin-config-json"
                      value={configDraft}
                      onChange={(event) => setConfigDraft(event.target.value)}
                      rows={8}
                    />
                  </label>
                  <label htmlFor="plugin-enabled-mode">
                    <span>Enabled setting</span>
                    <select
                      id="plugin-enabled-mode"
                      value={enabledDraft}
                      onChange={(event) => setEnabledDraft(event.target.value as EnabledDraft)}
                    >
                      <option value="leave">Leave unchanged</option>
                      <option value="true">Enable for tenant</option>
                      <option value="false">Disable for tenant</option>
                    </select>
                  </label>
                  <label htmlFor="plugin-permission-json">
                    <span>Permission overrides JSON</span>
                    <textarea
                      id="plugin-permission-json"
                      value={permissionDraft}
                      onChange={(event) => setPermissionDraft(event.target.value)}
                      rows={5}
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() => void handleSaveConfig()}
                    disabled={actionLoading !== null}
                  >
                    {actionLoading === "Save config" ? "Saving..." : "Save configuration"}
                  </button>
                </section>

                <section className="plugin-manager-section">
                  <h3>Contributions</h3>
                  <dl className="plugin-manager-definition-list">
                    {Object.entries(workspace.detail.contributions).map(([kind, values]) => (
                      <div key={kind}>
                        <dt>{kind}</dt>
                        <dd>{values.length > 0 ? values.join(", ") : "None"}</dd>
                      </div>
                    ))}
                  </dl>
                </section>

                <section className="plugin-manager-section">
                  <h3>Dependencies</h3>
                  {workspace.detail.dependencies.length === 0 ? <p>No plugin dependencies declared.</p> : null}
                  <ul className="plugin-manager-compact-list">
                    {workspace.detail.dependencies.map((dependency) => (
                      <li key={dependency.name}>
                        {dependency.name} {dependency.version_constraint || ""}
                        {dependency.optional ? " · optional" : ""}
                      </li>
                    ))}
                  </ul>
                </section>

                <section className="plugin-manager-section">
                  <h3>Lifecycle events</h3>
                  {(workspace.events?.events ?? []).length === 0 ? <p>No lifecycle events returned.</p> : null}
                  <ol className="plugin-manager-event-list">
                    {(workspace.events?.events ?? []).slice(0, 8).map((event) => (
                      <li key={`${event.event_type}-${event.timestamp}`}>
                        <strong>{formatState(event.event_type)}</strong>
                        <span>{new Date(event.timestamp).toLocaleString()}</span>
                        {Object.keys(event.details).length > 0 ? <code>{JSON.stringify(event.details)}</code> : null}
                      </li>
                    ))}
                  </ol>
                </section>
              </div>
            </>
          ) : null}
        </main>

        <aside className="plugin-manager-install" aria-label="Install or link plugin">
          <h3>Install or link</h3>
          <label htmlFor="plugin-source-path">
            <span>Source path</span>
            <input
              id="plugin-source-path"
              value={installSourcePath}
              onChange={(event) => setInstallSourcePath(event.target.value)}
              placeholder="D:/plugins/my-plugin"
            />
          </label>
          <label htmlFor="plugin-install-name">
            <span>Expected name</span>
            <input
              id="plugin-install-name"
              value={installName}
              onChange={(event) => setInstallName(event.target.value)}
              placeholder="Optional for link guard"
            />
          </label>
          <label htmlFor="plugin-install-mode">
            <span>Mode</span>
            <select
              id="plugin-install-mode"
              value={installMode}
              onChange={(event) => setInstallMode(event.target.value as InstallMode)}
            >
              <option value="copy">Copy</option>
              <option value="link">Link</option>
            </select>
          </label>
          <label className="plugin-manager-checkbox">
            <input
              type="checkbox"
              checked={installEnable}
              onChange={(event) => setInstallEnable(event.target.checked)}
            />
            <span>Enable after install</span>
          </label>
          <button type="button" onClick={() => void handleInstall()} disabled={actionLoading !== null}>
            {actionLoading === "Install plugin" ? "Installing..." : "Install plugin"}
          </button>
        </aside>
      </div>
    </section>
  );
}
