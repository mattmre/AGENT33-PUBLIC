export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export type OperationUxHint = "workflow-execute" | "workflow-schedule" | "agent-iterative" | "workflow-graph" | "health" | "health-channels" | "explanation-html";
export type WorkflowExecutionMode = "single" | "repeat" | "autonomous";

export interface WorkflowExecutePresetProjection {
  pathParams: Record<string, string>;
  body: Record<string, unknown>;
  executionMode?: WorkflowExecutionMode;
}

export interface WorkflowPresetDefinition {
  id: string;
  workflowName: string;
  label: string;
  description: string;
  sourcePath: string;
  workflowDefinition: Record<string, unknown>;
  executePreset: WorkflowExecutePresetProjection;
}

export interface OperationPresetBinding {
  group: "improvement-cycle";
  presetIds: string[];
  helpText?: string;
  applyLabel?: string;
}

export interface SchemaParameter {
  name: string;
  type: string;
  description: string;
  required: boolean;
}

export interface SchemaInfo {
  parameters?: SchemaParameter[];
  headers?: SchemaParameter[];
  body?: {
    description: string;
    example: string;
  };
}

export interface OperationConfig {
  id: string;
  title: string;
  method: HttpMethod;
  path: string;
  description: string;
  instructionalText?: string;
  schemaInfo?: SchemaInfo;
  defaultPathParams?: Record<string, string>;
  defaultQuery?: Record<string, string>;
  defaultHeaders?: Record<string, string>;
  defaultBody?: string;
  uxHint?: OperationUxHint;
  presetBinding?: OperationPresetBinding;
}

export interface DomainConfig {
  id: string;
  title: string;
  description: string;
  operations: OperationConfig[];
}

export interface ApiResult {
  status: number;
  durationMs: number;
  url: string;
  data: unknown;
  ok: boolean;
}

export interface ActivityItem {
  id: string;
  at: string;
  label: string;
  status: number;
  durationMs: number;
  url: string;
}

export interface RuntimeConfig {
  API_BASE_URL: string;
}

export interface WorkflowLiveEvent {
  type: string;
  run_id: string;
  workflow_name: string;
  timestamp: number;
  event_id?: string;
  step_id?: string;
  data?: Record<string, unknown>;
}

export interface WorkflowLiveTransportConnection {
  close: () => void;
}

// -- Agent Builder Types (P66) -----------------------------------------------

export interface AgentBuilderState {
  name: string;
  description: string;
  role: string;
  version: string;
  canReadFiles: boolean;
  canWriteFiles: boolean;
  canSearchWeb: boolean;
  canRunCode: boolean;
  canCallAPIs: boolean;
  systemPromptPreview: string;
  isPreviewLoading: boolean;
  testMessage: string;
  testResponse: string;
  isTestLoading: boolean;
}

export interface AgentDefinitionExport {
  name: string;
  version: string;
  role: string;
  description: string;
  capabilities: string[];
  governance: {
    scope: string;
    network: string;
    approval_required: string[];
    tool_policies: Record<string, string>;
  };
  autonomy_level: string;
}
