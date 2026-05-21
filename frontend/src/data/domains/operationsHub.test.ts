import { describe, expect, it } from "vitest";

import { operationsHubDomain } from "./operationsHub";

describe("operationsHubDomain", () => {
  it("should have correct domain id", () => {
    expect(operationsHubDomain.id).toBe("operations");
  });

  it("should have correct domain metadata", () => {
    expect(operationsHubDomain.title).toBe("Operations Hub");
    expect(operationsHubDomain.description).toBeDefined();
  });

  it("should include process and ingestion operator operations", () => {
    expect(operationsHubDomain.operations.length).toBe(8);
  });

  it("should have all required operation fields", () => {
    operationsHubDomain.operations.forEach((op) => {
      expect(op.id).toBeDefined();
      expect(op.title).toBeDefined();
      expect(op.description).toBeDefined();
      expect(op.method).toMatch(/^(GET|POST)$/);
      expect(op.path).toMatch(/^\/v1\/(operations|ingestion)\//);
    });
  });

  it("should have unique operation ids", () => {
    const ids = operationsHubDomain.operations.map((op) => op.id);
    const uniqueIds = new Set(ids);
    expect(uniqueIds.size).toBe(ids.length);
  });

  it("should map hub overview to correct backend route", () => {
    const hubOverview = operationsHubDomain.operations.find(
      (op) => op.id === "operations-hub-overview"
    );
    expect(hubOverview).toBeDefined();
    expect(hubOverview?.method).toBe("GET");
    expect(hubOverview?.path).toBe("/v1/operations/hub");
  });

  it("should map process detail to correct backend route", () => {
    const processDetail = operationsHubDomain.operations.find(
      (op) => op.id === "operations-process-detail"
    );
    expect(processDetail).toBeDefined();
    expect(processDetail?.method).toBe("GET");
    expect(processDetail?.path).toBe("/v1/operations/processes/{process_id}");
    expect(processDetail?.defaultPathParams?.process_id).toBeDefined();
  });

  it("should map process control to correct backend route", () => {
    const processControl = operationsHubDomain.operations.find(
      (op) => op.id === "operations-process-control"
    );
    expect(processControl).toBeDefined();
    expect(processControl?.method).toBe("POST");
    expect(processControl?.path).toBe("/v1/operations/processes/{process_id}/control");
    expect(processControl?.defaultPathParams?.process_id).toBeDefined();
  });

  it("should have valid default body for process control", () => {
    const processControl = operationsHubDomain.operations.find(
      (op) => op.id === "operations-process-control"
    );
    expect(processControl?.defaultBody).toBeDefined();

    if (processControl?.defaultBody) {
      const body = JSON.parse(processControl.defaultBody);
      expect(body.action).toMatch(/^(pause|resume|cancel)$/);
      expect(typeof body.reason).toBe("string");
    }
  });

  it("should have path params for operations requiring process_id", () => {
    const opsWithProcessId = [
      "operations-process-detail",
      "operations-process-control",
      "ingestion-asset-history",
      "ingestion-review-approve",
      "ingestion-review-reject"
    ];

    opsWithProcessId.forEach((opId) => {
      const op = operationsHubDomain.operations.find((o) => o.id === opId);
      expect(op?.defaultPathParams).toBeDefined();
      if (opId.startsWith("operations-")) {
        expect(op?.defaultPathParams?.process_id).toBe("replace-with-process-id");
      } else {
        expect(op?.defaultPathParams?.asset_id).toBe("replace-with-asset-id");
      }
    });
  });

  it("should not use stale endpoint paths", () => {
    operationsHubDomain.operations.forEach((op) => {
      // Old stale path that no longer exists in backend
      expect(op.path).not.toBe("/v1/operations/processes");
      // Old lifecycle path replaced by /control
      expect(op.path).not.toContain("/lifecycle");
    });
  });

  it("should expose ingestion review queue and history endpoints", () => {
    const queueOperation = operationsHubDomain.operations.find(
      (op) => op.id === "ingestion-review-queue"
    );
    const historyOperation = operationsHubDomain.operations.find(
      (op) => op.id === "ingestion-asset-history"
    );

    expect(queueOperation?.path).toBe("/v1/ingestion/review-queue");
    expect(historyOperation?.path).toBe("/v1/ingestion/candidates/{asset_id}/history");
  });
});
