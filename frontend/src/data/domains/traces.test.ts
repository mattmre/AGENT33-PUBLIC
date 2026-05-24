import { describe, expect, it } from "vitest";

import { tracesDomain } from "./traces";

function getOperation(id: string) {
  const operation = tracesDomain.operations.find((entry) => entry.id === id);
  expect(operation).toBeDefined();
  return operation!;
}

function parseDefaultBody(id: string) {
  return JSON.parse(getOperation(id).defaultBody ?? "{}") as Record<string, unknown>;
}

describe("tracesDomain", () => {
  it("keeps create-trace defaults aligned with the backend request model", () => {
    expect(parseDefaultBody("traces-create")).toEqual({
      task_id: "T-001",
      session_id: "SES-20260524-120000-A1B2",
      run_id: "RUN-20260524-120001-C3D4",
      agent_id: "AGT-006",
      agent_role: "implementer",
      model: "gpt-5"
    });
  });

  it("keeps action and completion defaults aligned with trace API fields", () => {
    expect(parseDefaultBody("traces-action")).toEqual({
      step_id: "STP-001",
      action_id: "ACT-001",
      tool: "shell",
      input_data: "echo hello",
      output_data: "hello",
      exit_code: 0,
      duration_ms: 100,
      status: "success"
    });

    expect(parseDefaultBody("traces-complete")).toEqual({
      status: "completed",
      failure_code: "",
      failure_message: ""
    });
  });

  it("keeps failure defaults aligned with the backend failure taxonomy", () => {
    expect(parseDefaultBody("traces-failure-add")).toEqual({
      message: "Timeout during external call",
      category: "F-TMO",
      severity: "medium",
      subcode: "F-TMO-003"
    });
  });
});
