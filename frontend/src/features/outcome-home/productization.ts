import type { OutcomeWorkflow } from "./types";
import type { WorkflowStarterLifecyclePlan } from "../workflow-starter/types";

export type ProductInputType = "text" | "file" | "url" | "choice";
export type ProductRiskLevel = "low" | "medium" | "high";

export interface ProductInputRequirement {
  id: string;
  label: string;
  type: ProductInputType;
  required: boolean;
  helperText: string;
  placeholder: string;
}

export interface ProductExampleOutput {
  title: string;
  format: "markdown" | "checklist" | "table";
  preview: string;
}

export interface ProductEstimate {
  duration: string;
  cost: string;
  risk: ProductRiskLevel;
  reviewGate: string;
}

export interface DryRunPreviewStep {
  id: string;
  title: string;
  description: string;
}

export interface StarterPackItem {
  label: string;
  reason: string;
}

export interface ProductizedWorkflow {
  id: OutcomeWorkflow["id"];
  inputs: ProductInputRequirement[];
  exampleOutputs: ProductExampleOutput[];
  estimate: ProductEstimate;
  dryRunSteps: DryRunPreviewStep[];
  starterPack: StarterPackItem[];
}

function slug(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

function getWorkflowSpecificInput(workflow: OutcomeWorkflow): ProductInputRequirement {
  if (workflow.tags.includes("repo") || workflow.tags.includes("developer")) {
    return {
      id: "repo-scope",
      label: "Repository or feature scope",
      type: "url",
      required: true,
      helperText: "Point AGENT-33 at the repo, branch, PR, or feature area to inspect.",
      placeholder: "Example: frontend/src/features/workflow-catalog"
    };
  }
  if (workflow.tags.includes("data") || workflow.tags.includes("dashboard")) {
    return {
      id: "data-source",
      label: "Data source",
      type: "file",
      required: true,
      helperText: "Describe the CSV, API, database, or metric source the dashboard should use.",
      placeholder: "Example: Stripe revenue CSV plus support ticket export"
    };
  }
  if (workflow.tags.includes("research") || workflow.kind === "research") {
    return {
      id: "research-scope",
      label: "Research question",
      type: "text",
      required: true,
      helperText: "State the decision this research should help you make.",
      placeholder: "Example: Which agent platforms should we benchmark this month?"
    };
  }
  return {
    id: "outcome-goal",
    label: "Goal in plain language",
    type: "text",
    required: true,
    helperText: "Tell AGENT-33 what you want built, planned, or packaged.",
    placeholder: workflow.goal
  };
}

export function buildProductInputs(workflow: OutcomeWorkflow): ProductInputRequirement[] {
  return [
    getWorkflowSpecificInput(workflow),
    {
      id: "success-criteria",
      label: "What counts as done?",
      type: "text",
      required: true,
      helperText: "Describe the final answer, file, plan, or artifact you expect.",
      placeholder: workflow.output
    },
    {
      id: "constraints",
      label: "Constraints or preferences",
      type: "text",
      required: false,
      helperText: "Add stack choices, deadline, budget, tools, or approval requirements.",
      placeholder: workflow.requires.join(", ")
    }
  ];
}

export function buildExampleOutputs(workflow: OutcomeWorkflow): ProductExampleOutput[] {
  const firstDeliverables = workflow.deliverables.slice(0, 3);
  return firstDeliverables.map((deliverable, index) => ({
    title: deliverable,
    format: index === 1 ? "checklist" : index === 2 ? "table" : "markdown",
    preview:
      index === 0
        ? `# ${deliverable}\n\n- Objective: ${workflow.summary}\n- Audience: ${workflow.audience}\n- First decision: confirm scope before execution.`
        : index === 1
          ? `- Confirm inputs\n- Draft ${deliverable.toLowerCase()}\n- Mark review gates before handoff`
          : `| Area | Plan |\n| --- | --- |\n| ${deliverable} | Generated from approved inputs |`
  }));
}

export function estimateWorkflowProduct(workflow: OutcomeWorkflow): ProductEstimate {
  const risk: ProductRiskLevel =
    workflow.safetyLevel === "Plan-only"
      ? "low"
      : workflow.safetyLevel === "Autopilot-ready"
        ? "high"
        : "medium";
  const cost =
    workflow.kind === "research"
      ? "$0-$3 estimated model use"
      : workflow.estimatedTime.includes("60") || workflow.estimatedTime.includes("90")
        ? "$3-$12 estimated model use"
        : "$1-$6 estimated model use";

  return {
    duration: workflow.estimatedTime,
    cost,
    risk,
    reviewGate:
      workflow.safetyLevel === "Plan-only"
        ? "Review findings before any implementation."
        : "Approve the plan before AGENT-33 writes or changes files."
  };
}

export function buildDryRunPreview(workflow: OutcomeWorkflow): DryRunPreviewStep[] {
  return [
    {
      id: `${workflow.id}-validate-inputs`,
      title: "Validate inputs",
      description: `Check required details: ${buildProductInputs(workflow)
        .filter((input) => input.required)
        .map((input) => input.label)
        .join(", ")}.`
    },
    {
      id: `${workflow.id}-draft-plan`,
      title: "Draft the work plan",
      description: `Prepare ${workflow.deliverables.slice(0, 2).join(" and ")} without executing tools.`
    },
    {
      id: `${workflow.id}-review-gate`,
      title: "Ask for review",
      description: estimateWorkflowProduct(workflow).reviewGate
    }
  ];
}

export function buildStarterPack(workflow: OutcomeWorkflow): StarterPackItem[] {
  const primaryTag = workflow.tags[0] ?? workflow.kind;
  return [
    {
      label: `${workflow.title} starter template`,
      reason: `Prefills the goal, output, and safety mode for ${workflow.audience}.`
    },
    {
      label: `${primaryTag} skill bundle`,
      reason: `Matches the workflow tags: ${workflow.tags.join(", ")}.`
    },
    {
      label: `${slug(workflow.title)} review checklist`,
      reason: "Keeps the first run review-gated and easy to inspect."
    }
  ];
}

export function productizeWorkflow(workflow: OutcomeWorkflow): ProductizedWorkflow {
  return {
    id: workflow.id,
    inputs: buildProductInputs(workflow),
    exampleOutputs: buildExampleOutputs(workflow),
    estimate: estimateWorkflowProduct(workflow),
    dryRunSteps: buildDryRunPreview(workflow),
    starterPack: buildStarterPack(workflow)
  };
}

export function buildProductBuilderLifecycle(workflow: OutcomeWorkflow): WorkflowStarterLifecyclePlan {
  const product = productizeWorkflow(workflow);
  const requiredInputs = product.inputs
    .filter((input) => input.required)
    .map((input) => input.label);

  return {
    brief: [
      workflow.goal,
      `Audience: ${workflow.audience}`,
      `Required inputs: ${requiredInputs.join(", ")}`
    ],
    plan: [
      `Prepare ${workflow.deliverables.slice(0, 3).join(", ")}.`,
      product.estimate.reviewGate,
      `Expected runtime: ${product.estimate.duration}; ${product.estimate.cost}.`
    ],
    preview: product.dryRunSteps.map((step) => `${step.title}: ${step.description}`),
    handoff: [
      `Create an editable ${workflow.kind.replace("-", " ")} workflow.`,
      `Keep safety posture as ${workflow.safetyLevel}.`,
      "Open Operations after creation so the operator can inspect running work and recover prior sessions."
    ]
  };
}
