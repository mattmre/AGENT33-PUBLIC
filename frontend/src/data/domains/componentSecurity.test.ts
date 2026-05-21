import { describe, expect, it } from "vitest";

import { componentSecurityDomain } from "./componentSecurity";

describe("componentSecurityDomain", () => {
  it("should have correct domain id", () => {
    expect(componentSecurityDomain.id).toBe("component-security");
  });

  it("should have correct domain metadata", () => {
    expect(componentSecurityDomain.title).toBe("Component Security");
    expect(componentSecurityDomain.description).toBeDefined();
  });

  it("should have exactly 12 operations", () => {
    expect(componentSecurityDomain.operations.length).toBe(12);
  });

  it("should have all required operation fields", () => {
    componentSecurityDomain.operations.forEach((op) => {
      expect(op.id).toBeDefined();
      expect(op.title).toBeDefined();
      expect(op.description).toBeDefined();
      expect(op.method).toMatch(/^(GET|POST|DELETE)$/);
      expect(op.path).toMatch(/^\/v1\/component-security/);
    });
  });

  it("should have unique operation ids", () => {
    const ids = componentSecurityDomain.operations.map((op) => op.id);
    const uniqueIds = new Set(ids);
    expect(uniqueIds.size).toBe(ids.length);
  });

  it("should map to correct backend routes", () => {
    const operations = componentSecurityDomain.operations;

    // Create Run
    const createRun = operations.find((op) => op.id === "sec-create-run");
    expect(createRun?.method).toBe("POST");
    expect(createRun?.path).toBe("/v1/component-security/runs");

    // List Runs
    const listRuns = operations.find((op) => op.id === "sec-list-runs");
    expect(listRuns?.method).toBe("GET");
    expect(listRuns?.path).toBe("/v1/component-security/runs");

    // Get Run
    const getRun = operations.find((op) => op.id === "sec-get-run");
    expect(getRun?.method).toBe("GET");
    expect(getRun?.path).toBe("/v1/component-security/runs/{run_id}");

    // Get Findings
    const getFindings = operations.find((op) => op.id === "sec-get-findings");
    expect(getFindings?.method).toBe("GET");
    expect(getFindings?.path).toBe("/v1/component-security/runs/{run_id}/findings");

    // Cancel Run
    const cancelRun = operations.find((op) => op.id === "sec-cancel-run");
    expect(cancelRun?.method).toBe("POST");
    expect(cancelRun?.path).toBe("/v1/component-security/runs/{run_id}/cancel");

    // Delete Run
    const deleteRun = operations.find((op) => op.id === "sec-delete-run");
    expect(deleteRun?.method).toBe("DELETE");
    expect(deleteRun?.path).toBe("/v1/component-security/runs/{run_id}");

    // Get Status
    const getStatus = operations.find((op) => op.id === "sec-run-status");
    expect(getStatus?.method).toBe("GET");
    expect(getStatus?.path).toBe("/v1/component-security/runs/{run_id}/status");

    // Export SARIF
    const getSarif = operations.find((op) => op.id === "sec-get-sarif");
    expect(getSarif?.method).toBe("GET");
    expect(getSarif?.path).toBe("/v1/component-security/runs/{run_id}/sarif");

    // LLM Security Scan
    const llmScan = operations.find((op) => op.id === "sec-llm-scan");
    expect(llmScan?.method).toBe("POST");
    expect(llmScan?.path).toBe("/v1/component-security/runs/{run_id}/llm-scan");

    // List MCP Servers
    const listMcp = operations.find((op) => op.id === "sec-list-mcp-servers");
    expect(listMcp?.method).toBe("GET");
    expect(listMcp?.path).toBe("/v1/component-security/mcp-servers");

    // Register MCP Server
    const registerMcp = operations.find((op) => op.id === "sec-register-mcp-server");
    expect(registerMcp?.method).toBe("POST");
    expect(registerMcp?.path).toBe("/v1/component-security/mcp-servers");

    // Delete MCP Server
    const deleteMcp = operations.find((op) => op.id === "sec-delete-mcp-server");
    expect(deleteMcp?.method).toBe("DELETE");
    expect(deleteMcp?.path).toBe("/v1/component-security/mcp-servers/{name}");
  });

  it("should have valid default values for create run", () => {
    const createRun = componentSecurityDomain.operations.find((op) => op.id === "sec-create-run");
    expect(createRun?.defaultBody).toBeDefined();

    if (createRun?.defaultBody) {
      const body = JSON.parse(createRun.defaultBody);
      expect(body.target).toBeDefined();
      expect(body.target.repository_path).toBeDefined();
      expect(body.profile).toMatch(/^(quick|standard|deep)$/);
      expect(body.options).toBeDefined();
    }
  });

  it("should have path params for operations requiring run_id", () => {
    const opsWithRunId = [
      "sec-get-run",
      "sec-get-findings",
      "sec-cancel-run",
      "sec-delete-run",
      "sec-run-status",
      "sec-get-sarif",
      "sec-llm-scan"
    ];

    opsWithRunId.forEach((opId) => {
      const op = componentSecurityDomain.operations.find((o) => o.id === opId);
      expect(op?.defaultPathParams).toBeDefined();
      expect(op?.defaultPathParams?.run_id).toBe("replace-with-run-id");
    });
  });

  it("should have path params for operations requiring name", () => {
    const deleteMcp = componentSecurityDomain.operations.find(
      (o) => o.id === "sec-delete-mcp-server"
    );
    expect(deleteMcp?.defaultPathParams).toBeDefined();
    expect(deleteMcp?.defaultPathParams?.name).toBe("replace-with-server-name");
  });

  it("should have valid default body for MCP server registration", () => {
    const registerMcp = componentSecurityDomain.operations.find(
      (op) => op.id === "sec-register-mcp-server"
    );
    expect(registerMcp?.defaultBody).toBeDefined();

    if (registerMcp?.defaultBody) {
      const body = JSON.parse(registerMcp.defaultBody);
      expect(body.name).toBeDefined();
      expect(body.transport).toBeDefined();
      expect(body.config).toBeDefined();
    }
  });
});
