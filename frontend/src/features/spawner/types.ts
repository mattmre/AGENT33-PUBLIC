/** Type definitions for the Sub-Agent Spawner (P71). */

export type IsolationMode = "local" | "subprocess" | "docker";
export type ExecutionStatus = "pending" | "running" | "completed" | "failed";

export interface ChildAgentConfig {
  agent_name: string;
  system_prompt_override: string | null;
  tool_allowlist: string[];
  autonomy_level: number;
  isolation: IsolationMode;
  pack_names: string[];
}

export interface WorkflowDefinition {
  id: string;
  name: string;
  description: string;
  parent_agent: string;
  children: ChildAgentConfig[];
  created_at: string;
  updated_at: string;
}

export interface ExecutionNode {
  agent_name: string;
  status: ExecutionStatus;
  started_at: string | null;
  completed_at: string | null;
  result_summary: string | null;
  error: string | null;
  children: ExecutionNode[];
}

export interface ExecutionTreeData {
  workflow_id: string;
  execution_id: string;
  status: ExecutionStatus;
  root: ExecutionNode;
  started_at: string | null;
  completed_at: string | null;
}
