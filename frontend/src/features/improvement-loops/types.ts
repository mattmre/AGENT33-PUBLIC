export type ImprovementLoopPresetId =
  | "competitive-research"
  | "platform-improvement"
  | "operator-ux-review";

export type ResearchLauncherId =
  | "weekly-competitive-scan"
  | "weekly-operator-ux-watch"
  | "monthly-agent-os-horizon";

export interface ImprovementLoopPreset {
  id: ImprovementLoopPresetId;
  title: string;
  summary: string;
  defaultWorkflowName: string;
  defaultGoal: string;
  defaultOutput: string;
  defaultCron: string;
  cadenceLabel: string;
  focusAreas: string[];
}

export interface ResearchLaunchPlan {
  id: ResearchLauncherId;
  presetId: ImprovementLoopPresetId;
  title: string;
  summary: string;
  workflowName: string;
  goal: string;
  output: string;
  schedule: string;
  cadenceLabel: string;
  buttonLabel: string;
}

export interface ImprovementLoopForm {
  workflowName: string;
  goal: string;
  output: string;
  schedule: string;
  author: string;
}

export interface LoopWorkflowRequest {
  name: string;
  version: string;
  description: string;
  triggers: {
    manual: boolean;
    schedule: string | null;
  };
  inputs: Record<string, { type: string; description: string; required: boolean; default?: string | string[] }>;
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

export interface WorkflowScheduleResponse {
  job_id: string;
  workflow_name: string;
  schedule_type: string;
  schedule_expr: string;
  inputs: Record<string, unknown>;
}
