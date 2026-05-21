import type { DomainConfig } from "../types";
import { agentsDomain } from "./domains/agents";
import { authDomain } from "./domains/auth";
import { autonomyDomain } from "./domains/autonomy";
import { chatDomain } from "./domains/chat";
import { componentSecurityDomain } from "./domains/componentSecurity";
import { dashboardDomain } from "./domains/dashboard";
import { evaluationsDomain } from "./domains/evaluations";
import { explanationsDomain } from "./domains/explanations";
import { healthDomain } from "./domains/health";
import { improvementsDomain } from "./domains/improvements";
import { memoryDomain } from "./domains/memory";
import { releasesDomain } from "./domains/releases";
import { reviewsDomain } from "./domains/reviews";
import { tracesDomain } from "./domains/traces";
import { trainingDomain } from "./domains/training";
import { webhooksDomain } from "./domains/webhooks";
import { workflowsDomain } from "./domains/workflows";
import { operationsHubDomain } from "./domains/operationsHub";
import { outcomesDomain } from "./domains/outcomes";
import { multimodalDomain } from "./domains/multimodal";
import { selfEvolutionDomain } from "./domains/selfEvolution";
import { sessionsDomain } from "./domains/sessions";
import { researchDomain } from "./domains/research";
import { modulesDomain } from "./domains/modules";
import { tasksDomain } from "./domains/tasks";

export const domains: DomainConfig[] = [
  healthDomain,
  authDomain,
  chatDomain,
  agentsDomain,
  workflowsDomain,
  explanationsDomain,
  memoryDomain,
  reviewsDomain,
  tracesDomain,
  evaluationsDomain,
  autonomyDomain,
  releasesDomain,
  improvementsDomain,
  dashboardDomain,
  trainingDomain,
  webhooksDomain,
  componentSecurityDomain,
  operationsHubDomain,
  outcomesDomain,
  multimodalDomain,
  selfEvolutionDomain,
  sessionsDomain,
  researchDomain,
  modulesDomain,
  tasksDomain
];
