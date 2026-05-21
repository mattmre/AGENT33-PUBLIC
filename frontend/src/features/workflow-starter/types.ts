export type StarterKind = "research" | "improvement-loop" | "automation-loop";
export type WorkflowStarterReadinessStatus = "ready" | "attention" | "unknown";
export type WorkflowStarterProviderHealthState =
  | "available"
  | "empty"
  | "unavailable"
  | "error";
export type WorkflowStarterModelHealthState = "ready" | "needs_attention" | "unavailable";

export interface WorkflowStarterDraft {
  id: string;
  name: string;
  goal: string;
  kind: StarterKind;
  output: string;
  schedule?: string;
  author?: string;
  sourceLabel?: string;
  sourcePack?: string;
  sourcePackVersion?: string;
  sourceOutcomeId?: string;
  lifecyclePlan?: WorkflowStarterLifecyclePlan;
}

export interface WorkflowStarterLifecyclePlan {
  brief: string[];
  plan: string[];
  preview: string[];
  handoff: string[];
}

export interface WorkflowStarterRequest {
  name: string;
  version: string;
  description: string;
  triggers: {
    manual: boolean;
    schedule: string | null;
  };
  inputs: Record<string, { type: string; description: string; required: boolean; default?: string }>;
  outputs: Record<string, { type: string; description: string; required: boolean }>;
  steps: Array<{
    id: string;
    name: string;
    action: "invoke-agent" | "validate";
    agent?: string;
    inputs: Record<string, unknown>;
    depends_on: string[];
  }>;
  execution: {
    mode: "dependency-aware";
    continue_on_error: boolean;
    fail_fast: boolean;
    dry_run: boolean;
  };
  metadata: {
    author: string;
    tags: string[];
  };
}

export interface WorkflowCreateResponse {
  name: string;
  version: string;
  step_count: number;
  created: boolean;
}

export interface WorkflowResolutionMatch {
  name: string;
  description: string;
  score: number;
  source: string;
  version: string;
  tags: string[];
  source_path: string;
  pack: string | null;
}

export interface WorkflowResolutionResponse {
  query: string;
  matches: WorkflowResolutionMatch[];
}

export interface SkillDiscoveryMatch {
  name: string;
  description: string;
  score: number;
  version: string;
  tags: string[];
  pack: string | null;
}

export interface SkillDiscoveryResponse {
  query: string;
  matches: SkillDiscoveryMatch[];
}

export interface WorkflowStarterModelHealthProvider {
  provider: string;
  label: string;
  state: WorkflowStarterProviderHealthState;
  ok: boolean;
  baseUrl: string;
  modelCount: number;
  message: string;
  action: string;
}

export interface WorkflowStarterModelHealth {
  overallState: WorkflowStarterModelHealthState;
  summary: string;
  readyProviderCount: number;
  attentionProviderCount: number;
  totalModelCount: number;
  providers: WorkflowStarterModelHealthProvider[];
}

export interface WorkflowStarterSessionSummary {
  session_id: string;
  purpose: string;
  status: string;
  started_at: string;
  updated_at: string;
  ended_at: string | null;
  task_count: number;
  tasks_completed: number;
  event_count: number;
  parent_session_id: string | null;
  tenant_id: string;
}
