import { describe, expect, it } from "vitest";

import {
  buildConnectCards,
  buildDoctorChecks,
  buildFirstSuccessPath,
  buildLiveDoctorChecks,
  getConnectScore
} from "./helpers";
import type { OnboardingStatus } from "../onboarding/types";

const READY_STATUS: OnboardingStatus = {
  completed_count: 2,
  total_count: 3,
  overall_complete: false,
  steps: [
    {
      step_id: "OB-01",
      category: "runtime",
      title: "Database",
      description: "Runtime database",
      completed: true,
      remediation: ""
    },
    {
      step_id: "OB-02",
      category: "models",
      title: "Model",
      description: "Model provider",
      completed: true,
      remediation: ""
    },
    {
      step_id: "OB-08",
      category: "api",
      title: "API",
      description: "API protection",
      completed: false,
      remediation: "Review API safety."
    }
  ]
};

describe("connect center helpers", () => {
  it("builds beginner-readable connection cards from onboarding status", () => {
    const cards = buildConnectCards(true, READY_STATUS);

    expect(cards).toHaveLength(6);
    expect(cards.find((card) => card.id === "model-provider")?.status).toBe("ready");
    expect(cards.find((card) => card.id === "safety-approvals")?.status).toBe("attention");
    expect(cards.every((card) => card.actionLabel.length > 0)).toBe(true);
    expect(cards.every((card) => card.verification.testAction.length > 0)).toBe(true);
    expect(cards.find((card) => card.id === "mcp-tools")?.verification.setupHint).toContain("GitHub");
  });

  it("marks engine access as attention when credentials are missing", () => {
    const cards = buildConnectCards(false, null);

    expect(cards[0]).toMatchObject({
      id: "engine-access",
      status: "attention",
      target: "setup"
    });
  });

  it("summarizes known readiness without counting unknown cards", () => {
    expect(getConnectScore(buildConnectCards(true, READY_STATUS))).toBe("3 of 4 known checks ready");
  });

  it("builds doctor checks that separate blockers from inspection work", () => {
    const checks = buildDoctorChecks(buildConnectCards(true, READY_STATUS));

    expect(checks.find((check) => check.id === "doctor-access")?.status).toBe("ready");
    expect(checks.find((check) => check.id === "doctor-generation")?.status).toBe("ready");
    expect(checks.find((check) => check.id === "doctor-tools")?.status).toBe("blocked");
    expect(checks.find((check) => check.id === "doctor-tools")?.remediation).toContain("approval");
  });

  it("holds first success until blocking setup checks are fixed", () => {
    const path = buildFirstSuccessPath(buildConnectCards(true, READY_STATUS));

    expect(path.ready).toBe(false);
    expect(path.title).toBe("Fix tool and safety path first");
    expect(path.proof).toContain("durable proof");
  });

  it("maps live doctor status findings into visible checks", () => {
    const checks = buildLiveDoctorChecks([
      {
        id: "DOC-04",
        category: "llm",
        severity: "error",
        owner: "models",
        message: "Model provider failed",
        fix_action: "Open model setup",
        stale_age_seconds: 0,
        evidence_refs: ["doctor:DOC-04:llm"]
      }
    ]);

    expect(checks[0]).toMatchObject({
      id: "live-DOC-04",
      status: "blocked",
      owner: "models",
      remediation: "Open model setup",
      evidenceRefs: ["doctor:DOC-04:llm"]
    });
  });
});
