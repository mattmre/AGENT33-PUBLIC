import { describe, expect, it } from "vitest";

import {
  buildRunProofSections,
  buildRunDashboardCards,
  buildRunNextActions,
  normalizeRunStatus
} from "./runSummary";

describe("run summary helpers", () => {
  it("normalizes common run statuses", () => {
    expect(normalizeRunStatus("completed")).toBe("succeeded");
    expect(normalizeRunStatus("in_progress")).toBe("running");
    expect(normalizeRunStatus("error")).toBe("failed");
    expect(normalizeRunStatus("pending")).toBe("queued");
    expect(normalizeRunStatus("mystery")).toBe("unknown");
  });

  it("builds user-readable run cards from flexible session records", () => {
    const [card] = buildRunDashboardCards([
      {
        session_id: "ses-1",
        agent_name: "safe-implementer",
        status: "completed",
        goal: "Build landing page",
        summary: "Created plan and artifacts.",
        artifacts: [{ name: "plan.md" }, { path: "diff.patch" }],
        updated_at: "now"
      }
    ]);

    expect(card.id).toBe("ses-1");
    expect(card.agent).toBe("safe-implementer");
    expect(card.status).toBe("succeeded");
    expect(card.artifacts).toEqual(["plan.md", "diff.patch"]);
    expect(card.nextActions).toContain("Review artifacts");
    expect(card.resultPath).toBe("/results/ses-1");
  });

  it("builds result cards from run-ledger records", () => {
    const [card] = buildRunDashboardCards([
      {
        task: { id: "task-1", title: "Ship result page" },
        run: {
          id: "run-1",
          status: "succeeded",
          source_id: "workflow-1",
          created_at: "2026-05-05T00:00:00Z"
        },
        events: [{ id: "event-1", message: "Done" }],
        evidence: [{ id: "evidence-1", title: "Validation summary" }]
      }
    ]);

    expect(card.id).toBe("run-1");
    expect(card.title).toBe("Ship result page");
    expect(card.agent).toBe("workflow-1");
    expect(card.artifacts).toEqual(["Validation summary"]);
    expect(card.proofItems).toEqual([
      "1 artifact",
      "1 event",
      "2 proof sections",
      "Outcome ready"
    ]);
    expect(card.proofSections).toEqual([
      { label: "Evidence", count: 1, items: ["Validation summary"] },
      { label: "Events", count: 1, items: ["Done"] }
    ]);
  });

  it("normalizes proof sections from evidence, verification, logs, and result paths", () => {
    expect(
      buildRunProofSections({
        evidence: [{ title: "Audit record" }],
        verifications: ["pytest"],
        logs: [{ path: "logs/run.txt" }],
        result_path: "results/run-1.json"
      })
    ).toEqual([
      { label: "Evidence", count: 1, items: ["Audit record"] },
      { label: "Verification", count: 1, items: ["pytest"] },
      { label: "Logs", count: 1, items: ["logs/run.txt"] },
      { label: "Result", count: 1, items: ["results/run-1.json"] }
    ]);
  });

  it("recommends safer actions for failed runs", () => {
    expect(buildRunNextActions("failed")).toEqual([
      "Review failure",
      "Replay with safer settings",
      "Open logs"
    ]);
  });
});
