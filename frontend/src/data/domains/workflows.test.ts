import { describe, expect, it } from "vitest";

import { workflowsDomain } from "./workflows";

function getOperation(id: string) {
  const operation = workflowsDomain.operations.find((entry) => entry.id === id);
  expect(operation).toBeDefined();
  return operation!;
}

describe("workflowsDomain", () => {
  it("matches the current backend workflow route order", () => {
    expect(
      workflowsDomain.operations.map((operation) => `${operation.method} ${operation.path}`)
    ).toEqual([
      "GET /v1/workflows/",
      "GET /v1/workflows/{name}",
      "POST /v1/workflows/",
      "POST /v1/workflows/{name}/execute",
      "POST /v1/workflows/{name}/schedule",
      "GET /v1/workflows/schedules",
      "DELETE /v1/workflows/schedules/{job_id}",
      "GET /v1/workflows/{name}/history",
      "GET /v1/visualizations/workflows/{workflow_id}/graph"
    ]);
  });

  it("wires the create and execute operations to improvement-cycle presets", () => {
    const createWorkflow = getOperation("workflows-create");
    expect(createWorkflow.presetBinding).toEqual({
      group: "improvement-cycle",
      presetIds: ["retrospective", "metrics-review"],
      helpText:
        "Apply a canonical improvement-cycle template from core/workflows/improvement-cycle/*.workflow.yaml."
    });
    expect(createWorkflow.instructionalText).toContain("Improvement-cycle presets");

    const executeWorkflow = getOperation("workflows-execute");
    expect(executeWorkflow.presetBinding).toEqual(createWorkflow.presetBinding);
    expect(executeWorkflow.uxHint).toBe("workflow-execute");
  });

  it("keeps the default create and execute payloads intact alongside preset wiring", () => {
    const createBody = JSON.parse(getOperation("workflows-create").defaultBody ?? "{}");
    expect(createBody.name).toBe("hello-flow");
    expect(createBody.steps[0].action).toBe("transform");

    const executeBody = JSON.parse(getOperation("workflows-execute").defaultBody ?? "{}");
    expect(executeBody.inputs.name).toBe("AGENT-33");
    expect(executeBody).not.toHaveProperty("run_id");
  });
});
