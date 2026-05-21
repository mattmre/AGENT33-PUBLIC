import { apiRequest } from "../../lib/api";
import type { ApiResult } from "../../types";
import type { LoopWorkflowRequest, WorkflowCreateResponse, WorkflowScheduleResponse } from "./types";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function asWorkflowCreateResponse(data: unknown): WorkflowCreateResponse | null {
  if (!isObject(data)) {
    return null;
  }
  if (
    typeof data.name !== "string" ||
    typeof data.version !== "string" ||
    typeof data.step_count !== "number" ||
    typeof data.created !== "boolean"
  ) {
    return null;
  }
  return {
    name: data.name,
    version: data.version,
    step_count: data.step_count,
    created: data.created
  };
}

export function asWorkflowScheduleResponse(data: unknown): WorkflowScheduleResponse | null {
  if (!isObject(data)) {
    return null;
  }
  if (
    typeof data.job_id !== "string" ||
    typeof data.workflow_name !== "string" ||
    typeof data.schedule_type !== "string" ||
    typeof data.schedule_expr !== "string" ||
    !isObject(data.inputs)
  ) {
    return null;
  }
  return {
    job_id: data.job_id,
    workflow_name: data.workflow_name,
    schedule_type: data.schedule_type,
    schedule_expr: data.schedule_expr,
    inputs: data.inputs
  };
}

export function createLoopWorkflow(
  body: LoopWorkflowRequest,
  token: string,
  apiKey: string
): Promise<ApiResult> {
  return apiRequest({
    method: "POST",
    path: "/v1/workflows/",
    token,
    apiKey,
    body: JSON.stringify(body)
  });
}

export function scheduleLoopWorkflow(
  workflowName: string,
  cronExpr: string,
  inputs: Record<string, unknown>,
  token: string,
  apiKey: string
): Promise<ApiResult> {
  return apiRequest({
    method: "POST",
    path: "/v1/workflows/{name}/schedule",
    pathParams: { name: workflowName },
    token,
    apiKey,
    body: JSON.stringify({ cron_expr: cronExpr, inputs })
  });
}
