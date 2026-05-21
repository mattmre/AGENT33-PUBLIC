export interface SkillDraftRequest {
  name: string;
  description: string;
  use_case: string;
  workflow_steps: string[];
  success_criteria: string[];
  allowed_tools: string[];
  approval_required_for: string[];
  tags: string[];
  category: string;
  author: string;
  autonomy_level: string | null;
  invocation_mode: "user-only" | "llm-only" | "both";
  execution_context: "inline" | "fork";
  install: boolean;
  overwrite: boolean;
}

export interface SkillDraftResponse {
  skill: {
    name: string;
    description: string;
    allowed_tools: string[];
    approval_required_for: string[];
    tags: string[];
    category: string;
    author: string;
    command_name?: string | null;
  };
  markdown: string;
  installed: boolean;
  path: string | null;
  warnings: string[];
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
