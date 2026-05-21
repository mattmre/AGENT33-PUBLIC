import type { StarterKind } from "../workflow-starter/types";

export type UserRoleId = "founder" | "developer" | "agency" | "enterprise" | "operator";

export interface RoleProfile {
  id: UserRoleId;
  title: string;
  headline: string;
  summary: string;
  bestFor: string[];
  workflowIds: string[];
  demoScenarioIds: string[];
  setupFocus: string[];
  starterKind: StarterKind;
}

export interface ProductBrief {
  id: string;
  roleId: UserRoleId;
  title: string;
  idea: string;
  audience: string;
  startingPoint: string;
  desiredOutput: string;
  safetyScope: string;
  createdAt: string;
}
