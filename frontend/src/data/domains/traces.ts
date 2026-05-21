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
          run_id: "run-001",
          metadata: { source: "ui" }
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
          action: "read_file",
          status: "ok"
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
      defaultBody: "{}"
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
          code: "ERR_TIMEOUT",
          message: "Timeout during external call"
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
