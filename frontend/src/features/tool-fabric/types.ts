export interface ToolDiscoveryMatch {
  name: string;
  description: string;
  score: number;
  status: string;
  version: string;
  tags: string[];
}

export interface SkillDiscoveryMatch {
  name: string;
  description: string;
  score: number;
  version: string;
  tags: string[];
  pack: string | null;
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

export interface ToolDiscoveryResponse {
  query: string;
  matches: ToolDiscoveryMatch[];
}

export interface SkillDiscoveryResponse {
  query: string;
  matches: SkillDiscoveryMatch[];
}

export interface WorkflowResolutionResponse {
  query: string;
  matches: WorkflowResolutionMatch[];
}

export interface FabricPlan {
  objective: string;
  tools: ToolDiscoveryMatch[];
  skills: SkillDiscoveryMatch[];
  workflows: WorkflowResolutionMatch[];
}

export type ResourceManifestStatus = "ready" | "needs-review" | "missing";

export interface ResourceManifestItem {
  id: string;
  label: string;
  kind: "tool" | "skill" | "workflow";
  status: ResourceManifestStatus;
  trustSummary: string;
  compatibilitySummary: string;
  evidenceReceipt: string;
}

export interface ResourceManifest {
  objective: string;
  items: ResourceManifestItem[];
  summary: string;
}
