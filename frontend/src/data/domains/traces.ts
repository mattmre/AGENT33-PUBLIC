import type { DomainConfig } from "../../types";

export const tracesDomain: DomainConfig = {
  id: "traces",
  title: "Traces",
  description: "Trace lifecycle and failure handling.",
  operations: [
    {
      id: "traces-create",
      title: "Create Trace",
      method: "POST",
      path: "/v1/traces/",
      description: "Create a trace session.",
      defaultBody: JSON.stringify(
        {
          task_id: "T-001",
          session_id: "SES-20260524-120000-A1B2",
          run_id: "RUN-20260524-120001-C3D4",
          agent_id: "AGT-006",
          agent_role: "implementer",
          model: "gpt-5"
        },
        null,
        2
      )
    },
    {
      id: "traces-list",
      title: "List Traces",
      method: "GET",
      path: "/v1/traces/",
      description: "List traces."
    },
    {
      id: "traces-get",
      title: "Get Trace",
      method: "GET",
      path: "/v1/traces/{trace_id}",
      description: "Get trace detail.",
      defaultPathParams: {
        trace_id: "replace-with-trace-id"
      }
    },
    {
      id: "traces-action",
      title: "Add Trace Action",
      method: "POST",
      path: "/v1/traces/{trace_id}/actions",
      description: "Append action event.",
      defaultPathParams: {
        trace_id: "replace-with-trace-id"
      },
      defaultBody: JSON.stringify(
        {
          step_id: "STP-001",
          action_id: "ACT-001",
          tool: "shell",
          input_data: "echo hello",
          output_data: "hello",
          exit_code: 0,
          duration_ms: 100,
          status: "success"
        },
        null,
        2
      )
    },
    {
      id: "traces-complete",
      title: "Complete Trace",
      method: "POST",
      path: "/v1/traces/{trace_id}/complete",
      description: "Mark trace complete.",
      defaultPathParams: {
        trace_id: "replace-with-trace-id"
      },
      defaultBody: JSON.stringify(
        {
          status: "completed",
          failure_code: "",
          failure_message: ""
        },
        null,
        2
      )
    },
    {
      id: "traces-failure-add",
      title: "Add Trace Failure",
      method: "POST",
      path: "/v1/traces/{trace_id}/failures",
      description: "Record a failure event.",
      defaultPathParams: {
        trace_id: "replace-with-trace-id"
      },
      defaultBody: JSON.stringify(
        {
          message: "Timeout during external call",
          category: "F-TMO",
          severity: "medium",
          subcode: "F-TMO-003"
        },
        null,
        2
      )
    },
    {
      id: "traces-failure-list",
      title: "List Trace Failures",
      method: "GET",
      path: "/v1/traces/{trace_id}/failures",
      description: "List failures for trace.",
      defaultPathParams: {
        trace_id: "replace-with-trace-id"
      }
    }
  ]
};
