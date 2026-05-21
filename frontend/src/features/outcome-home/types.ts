import type { StarterKind } from "../workflow-starter/types";

export type OutcomeWorkflowId =
  | "build-first-app"
  | "create-landing-page"
  | "analyze-repo"
  | "competitive-research"
  | "saas-scaffold"
  | "internal-tool"
  | "data-dashboard"
  | "security-review"
  | "test-generation"
  | "release-readiness"
  | "client-kickoff"
  | "enterprise-program";

export interface OutcomeWorkflow {
  id: OutcomeWorkflowId;
  title: string;
  audience: string;
  summary: string;
  goal: string;
  output: string;
  kind: StarterKind;
  estimatedTime: string;
  safetyLevel: "Review-gated" | "Plan-only" | "Autopilot-ready";
  deliverables: string[];
  requires: string[];
  tags: string[];
}
