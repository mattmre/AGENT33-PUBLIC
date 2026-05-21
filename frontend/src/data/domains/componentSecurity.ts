import type { DomainConfig } from "../../types";

export const componentSecurityDomain: DomainConfig = {
  id: "component-security",
  title: "Component Security",
  description: "Security scans, findings, profiles.",
  operations: [
    {
      id: "sec-create-run",
      title: "Create Run",
      method: "POST",
      path: "/v1/component-security/runs",
      description: "Create new security scan run.",
      defaultBody: JSON.stringify(
        {
          target: {
            repository_path: "/path/to/repository",
            commit_ref: "",
            branch: "main"
          },
          profile: "quick",
          options: {
            timeout_seconds: 600,
            fail_on_high: true,
            scan_dependencies: true,
            scan_secrets: true
          },
          requested_by: "",
          session_id: "",
          release_candidate_id: "",
          execute_now: true
        },
        null,
        2
      )
    },
    {
      id: "sec-list-runs",
      title: "List Runs",
      method: "GET",
      path: "/v1/component-security/runs",
      description: "List component security runs.",
      defaultQuery: {
        limit: "20"
      }
    },
    {
      id: "sec-get-run",
      title: "Get Run",
      method: "GET",
      path: "/v1/component-security/runs/{run_id}",
      description: "Get run details by ID.",
      defaultPathParams: {
        run_id: "replace-with-run-id"
      }
    },
    {
      id: "sec-get-findings",
      title: "Get Findings",
      method: "GET",
      path: "/v1/component-security/runs/{run_id}/findings",
      description: "Fetch findings for a run.",
      defaultPathParams: {
        run_id: "replace-with-run-id"
      }
    },
    {
      id: "sec-cancel-run",
      title: "Cancel Run",
      method: "POST",
      path: "/v1/component-security/runs/{run_id}/cancel",
      description: "Cancel a running or pending run.",
      defaultPathParams: {
        run_id: "replace-with-run-id"
      }
    },
    {
      id: "sec-delete-run",
      title: "Delete Run",
      method: "DELETE",
      path: "/v1/component-security/runs/{run_id}",
      description: "Delete run and associated findings.",
      defaultPathParams: {
        run_id: "replace-with-run-id"
      }
    },
    {
      id: "sec-run-status",
      title: "Get Status",
      method: "GET",
      path: "/v1/component-security/runs/{run_id}/status",
      description: "Get status for polling clients.",
      defaultPathParams: {
        run_id: "replace-with-run-id"
      }
    },
    {
      id: "sec-get-sarif",
      title: "Export SARIF",
      method: "GET",
      path: "/v1/component-security/runs/{run_id}/sarif",
      description: "Export findings as SARIF 2.1.0 JSON.",
      defaultPathParams: {
        run_id: "replace-with-run-id"
      }
    },
    {
      id: "sec-llm-scan",
      title: "LLM Security Scan",
      method: "POST",
      path: "/v1/component-security/runs/{run_id}/llm-scan",
      description: "Run AI-specific security scan.",
      defaultPathParams: {
        run_id: "replace-with-run-id"
      }
    },
    {
      id: "sec-list-mcp-servers",
      title: "List MCP Servers",
      method: "GET",
      path: "/v1/component-security/mcp-servers",
      description: "List registered MCP security servers."
    },
    {
      id: "sec-register-mcp-server",
      title: "Register MCP Server",
      method: "POST",
      path: "/v1/component-security/mcp-servers",
      description: "Register an MCP security server.",
      defaultBody: JSON.stringify(
        {
          name: "semgrep",
          transport: "stdio",
          config: {
            command: "npx",
            args: ["-y", "@semgrep/mcp"],
            scan_tool_name: "scan"
          }
        },
        null,
        2
      )
    },
    {
      id: "sec-delete-mcp-server",
      title: "Remove MCP Server",
      method: "DELETE",
      path: "/v1/component-security/mcp-servers/{name}",
      description: "Remove a registered MCP security server.",
      defaultPathParams: {
        name: "replace-with-server-name"
      }
    }
  ]
};
