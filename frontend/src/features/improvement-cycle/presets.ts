import retrospectiveWorkflowSource from "../../../../core/workflows/improvement-cycle/retrospective.workflow.yaml?raw";
import metricsReviewWorkflowSource from "../../../../core/workflows/improvement-cycle/metrics-review.workflow.yaml?raw";
import type {
  OperationPresetBinding,
  WorkflowExecutePresetProjection,
  WorkflowPresetDefinition
} from "../../types";
import { parseCanonicalWorkflowYaml } from "./workflowYaml";

const retrospectiveWorkflowDefinition = parseCanonicalWorkflowYaml(
  retrospectiveWorkflowSource
);
const metricsReviewWorkflowDefinition = parseCanonicalWorkflowYaml(
  metricsReviewWorkflowSource
);

function getWorkflowName(definition: Record<string, unknown>): string {
  const workflowName = definition.name;
  if (typeof workflowName !== "string" || workflowName.length === 0) {
    throw new Error("Canonical workflow definition is missing a valid name");
  }
  return workflowName;
}

const retrospectiveWorkflowName = getWorkflowName(retrospectiveWorkflowDefinition);
const metricsReviewWorkflowName = getWorkflowName(metricsReviewWorkflowDefinition);

export const improvementCycleWorkflowPresets: readonly WorkflowPresetDefinition[] = [
  {
    id: "retrospective",
    workflowName: retrospectiveWorkflowName,
    label: "Retrospective improvement cycle",
    description: "Create or run a deterministic retrospective scaffold for a completed session.",
    sourcePath: "core/workflows/improvement-cycle/retrospective.workflow.yaml",
    workflowDefinition: retrospectiveWorkflowDefinition,
    executePreset: {
      pathParams: { name: retrospectiveWorkflowName },
      body: {
        inputs: {
          session_id: "session-57",
          scope: "frontend",
          participants: ["implementer", "reviewer"],
          wins: ["Live workflow graph refresh shipped."],
          improvement_areas: ["Tighten template drift checks."]
        }
      },
      executionMode: "single"
    }
  },
  {
    id: "metrics-review",
    workflowName: metricsReviewWorkflowName,
    label: "Metrics review improvement cycle",
    description: "Create or run a deterministic metrics review scaffold for a review period.",
    sourcePath: "core/workflows/improvement-cycle/metrics-review.workflow.yaml",
    workflowDefinition: metricsReviewWorkflowDefinition,
    executePreset: {
      pathParams: { name: metricsReviewWorkflowName },
      body: {
        inputs: {
          review_period: "2026-03-01 to 2026-03-07",
          baseline_period: "2026-02-23 to 2026-02-29",
          focus_areas: ["build-health", "api-alignment"],
          metrics_snapshot: {
            build_pass_rate: "98%",
            api_mismatches: 0
          }
        }
      },
      executionMode: "single"
    }
  }
];

export const improvementCyclePresetBinding: OperationPresetBinding = {
  group: "improvement-cycle",
  presetIds: improvementCycleWorkflowPresets.map((preset) => preset.id),
  helpText:
    "Apply a canonical improvement-cycle template from core/workflows/improvement-cycle/*.workflow.yaml."
};

export function getImprovementCyclePresetById(
  presetId: string
): WorkflowPresetDefinition | undefined {
  return improvementCycleWorkflowPresets.find((preset) => preset.id === presetId);
}

export function buildWorkflowCreatePresetBody(presetId: string): string {
  const preset = getImprovementCyclePresetById(presetId);
  if (!preset) {
    throw new Error(`Unknown workflow preset: ${presetId}`);
  }
  return JSON.stringify(preset.workflowDefinition, null, 2);
}

export function buildWorkflowExecutePreset(presetId: string): WorkflowExecutePresetProjection {
  const preset = getImprovementCyclePresetById(presetId);
  if (!preset) {
    throw new Error(`Unknown workflow preset: ${presetId}`);
  }
  return preset.executePreset;
}
