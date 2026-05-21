import { describe, expect, it } from "vitest";

import { improvementsDomain } from "./improvements";

function getOperation(id: string) {
  const operation = improvementsDomain.operations.find((entry) => entry.id === id);
  expect(operation).toBeDefined();
  return operation!;
}

describe("improvementsDomain", () => {
  it("describes the improvements domain and exposes unique operation ids", () => {
    expect(improvementsDomain.id).toBe("improvements");
    expect(improvementsDomain.title).toBe("Improvements");
    expect(improvementsDomain.operations).toHaveLength(32);

    const ids = improvementsDomain.operations.map((operation) => operation.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("matches the backend improvements route order", () => {
    expect(
      improvementsDomain.operations.map((operation) => `${operation.method} ${operation.path}`)
    ).toEqual([
      "POST /v1/improvements/intakes",
      "POST /v1/improvements/intakes/competitive/repos",
      "POST /v1/improvements/feature-candidates/score",
      "GET /v1/improvements/intakes",
      "GET /v1/improvements/intakes/{intake_id}",
      "POST /v1/improvements/intakes/{intake_id}/transition",
      "POST /v1/improvements/lessons",
      "GET /v1/improvements/lessons",
      "GET /v1/improvements/lessons/{lesson_id}",
      "POST /v1/improvements/lessons/{lesson_id}/complete-action",
      "POST /v1/improvements/lessons/{lesson_id}/verify",
      "POST /v1/improvements/checklists",
      "GET /v1/improvements/checklists",
      "GET /v1/improvements/checklists/{checklist_id}",
      "POST /v1/improvements/checklists/{checklist_id}/complete",
      "GET /v1/improvements/checklists/{checklist_id}/evaluate",
      "GET /v1/improvements/metrics",
      "GET /v1/improvements/metrics/history",
      "POST /v1/improvements/metrics/snapshot",
      "POST /v1/improvements/metrics/default-snapshot",
      "GET /v1/improvements/metrics/trend/{metric_id}",
      "POST /v1/improvements/refreshes",
      "GET /v1/improvements/refreshes",
      "GET /v1/improvements/refreshes/{refresh_id}",
      "POST /v1/improvements/refreshes/{refresh_id}/complete",
      "POST /v1/improvements/learning/signals",
      "GET /v1/improvements/learning/signals",
      "GET /v1/improvements/learning/summary",
      "GET /v1/improvements/learning/trends",
      "GET /v1/improvements/learning/calibration",
      "POST /v1/improvements/learning/backup",
      "POST /v1/improvements/learning/restore"
    ]);
  });

  it("uses the current intake and lesson payload contracts", () => {
    const createIntake = JSON.parse(getOperation("imp-intake-create").defaultBody ?? "{}");
    expect(createIntake.summary).toContain("frontend control plane");
    expect(createIntake).not.toHaveProperty("details");

    const transition = JSON.parse(getOperation("imp-intake-transition").defaultBody ?? "{}");
    expect(transition.new_status).toBe("triaged");
    expect(transition).not.toHaveProperty("to_state");

    const completeAction = JSON.parse(
      getOperation("imp-lesson-complete-action").defaultBody ?? "{}"
    );
    expect(completeAction.action_index).toBe(0);
    expect(completeAction).not.toHaveProperty("action_id");
  });

  it("uses the current checklist, metrics, and refresh payload contracts", () => {
    const checklistCreate = JSON.parse(
      getOperation("imp-checklist-create").defaultBody ?? "{}"
    );
    expect(checklistCreate.period).toBe("monthly");
    expect(checklistCreate.reference).toBe("2026-03");
    expect(checklistCreate).not.toHaveProperty("name");
    expect(checklistCreate).not.toHaveProperty("items");

    const checklistComplete = JSON.parse(
      getOperation("imp-checklist-complete").defaultBody ?? "{}"
    );
    expect(checklistComplete.check_id).toBe("CI-01");
    expect(checklistComplete.notes).toContain("Session 57");

    const metricsDefault = getOperation("imp-metrics-default");
    expect(metricsDefault.defaultQuery).toEqual({ period: "2026-Q1" });
    expect(metricsDefault.defaultBody).toBeUndefined();

    const refreshCreate = JSON.parse(getOperation("imp-refresh-create").defaultBody ?? "{}");
    expect(refreshCreate.scope).toBe("minor");
    expect(refreshCreate.participants).toContain("engineering");
    expect(refreshCreate.activities).toContain("prioritization");
    expect(refreshCreate).not.toHaveProperty("title");
  });

  it("exposes the competitive scoring and learning endpoints", () => {
    expect(getOperation("imp-intake-competitive-repos").path).toBe(
      "/v1/improvements/intakes/competitive/repos"
    );
    expect(getOperation("imp-feature-candidates-score").path).toBe(
      "/v1/improvements/feature-candidates/score"
    );

    const learningPaths = improvementsDomain.operations
      .filter((operation) => operation.path.startsWith("/v1/improvements/learning/"))
      .map((operation) => `${operation.method} ${operation.path}`);

    expect(learningPaths).toEqual([
      "POST /v1/improvements/learning/signals",
      "GET /v1/improvements/learning/signals",
      "GET /v1/improvements/learning/summary",
      "GET /v1/improvements/learning/trends",
      "GET /v1/improvements/learning/calibration",
      "POST /v1/improvements/learning/backup",
      "POST /v1/improvements/learning/restore"
    ]);

    for (const id of [
      "imp-learning-signal-create",
      "imp-learning-signal-list",
      "imp-learning-summary",
      "imp-learning-trends",
      "imp-learning-calibration"
    ]) {
      expect(getOperation(id).instructionalText).toContain("returns 404");
    }

    expect(getOperation("imp-learning-backup").instructionalText).toContain(
      "remain available even when improvement learning is disabled"
    );
    expect(getOperation("imp-learning-restore").instructionalText).toContain(
      "remain available even when improvement learning is disabled"
    );

    const restoreBody = JSON.parse(getOperation("imp-learning-restore").defaultBody ?? "{}");
    expect(restoreBody.backup_path).toBe("/path/to/agent33-learning-backup.json");
  });
});
