import type { WorkflowStarterDraft } from "../workflow-starter/types";
import type { UserRoleId } from "../role-intake/types";

export type DemoStepTone = "done" | "active" | "attention";

export interface DemoRunStep {
  id: string;
  title: string;
  description: string;
  tone: DemoStepTone;
}

export interface DemoArtifact {
  id: string;
  title: string;
  description: string;
  contents: string[];
}

export interface DemoScenario {
  id: string;
  title: string;
  audience: string;
  complexity: "Beginner" | "Intermediate";
  timeEstimate: string;
  forRoles?: UserRoleId[];
  outcome: string;
  prompt: string;
  sampleInputs: string[];
  runSteps: DemoRunStep[];
  artifacts: DemoArtifact[];
  starterDraft: WorkflowStarterDraft;
}
