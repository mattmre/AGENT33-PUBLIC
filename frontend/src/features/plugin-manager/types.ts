export interface PluginSummary {
  name: string;
  version: string;
  description: string;
  state: string;
  author: string;
  tags: string[];
  contributions_summary: Record<string, number>;
}

export interface PluginDependency {
  name: string;
  version_constraint?: string;
  optional?: boolean;
}

export interface PluginDetail {
  name: string;
  version: string;
  description: string;
  author: string;
  license: string;
  homepage: string;
  repository: string;
  state: string;
  status: string;
  permissions: string[];
  granted_permissions: string[];
  denied_permissions: string[];
  contributions: Record<string, string[]>;
  dependencies: PluginDependency[];
  tags: string[];
  tenant_config?: PluginConfigRecord | null;
  error?: string | null;
}

export interface PluginConfigRecord {
  plugin_name?: string;
  updated?: boolean;
  tenant_id?: string;
  enabled?: boolean;
  config?: Record<string, unknown>;
  config_overrides?: Record<string, unknown>;
  permission_overrides?: Record<string, boolean>;
}

export interface PluginHealthResponse {
  plugin_name: string;
  healthy: boolean;
  details: Record<string, unknown>;
}

export interface PluginPermissionInventory {
  plugin_name: string;
  requested: string[];
  granted: string[];
  denied: string[];
}

export interface PluginDoctorCheck {
  name: string;
  status: string;
  message: string;
  remediation: string;
}

export interface PluginDoctorReport {
  plugin_name: string;
  state: string;
  overall_status: string;
  checks: PluginDoctorCheck[];
  permissions: PluginPermissionInventory;
  install_source: string;
  installed_path: string;
}

export interface PluginDoctorSummary {
  count: number;
  reports: PluginDoctorReport[];
}

export interface PluginLifecycleEvent {
  event_type: string;
  plugin_name: string;
  version: string;
  timestamp: string;
  details: Record<string, unknown>;
}

export interface PluginEventsResponse {
  plugin_name: string | null;
  count: number;
  events: PluginLifecycleEvent[];
}

export interface PluginInstallResponse {
  success: boolean;
  plugin_name: string;
  version: string;
  mode: "copy" | "link";
  linked: boolean;
  installed_path: string;
  source_path: string;
  warnings: string[];
  errors: string[];
}

export interface PluginSearchResponse {
  query: string;
  count: number;
  plugins: PluginSummary[];
}

export interface PluginDiscoverResponse {
  discovered: number;
  total: number;
}

export interface PluginWorkspace {
  detail: PluginDetail;
  config: PluginConfigRecord;
  health: PluginHealthResponse | null;
  permissions: PluginPermissionInventory | null;
  doctor: PluginDoctorReport | null;
  events: PluginEventsResponse | null;
}
