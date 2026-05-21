import { describe, expect, it } from "vitest";

import { getPermissionActionGate } from "./permissionActionGates";

describe("permission action gates", () => {
  it("keeps observe mode read-only except artifact review", () => {
    expect(getPermissionActionGate("observe", "review-artifact")).toMatchObject({
      allowed: true,
      tone: "available"
    });
    expect(getPermissionActionGate("observe", "start-workflow")).toMatchObject({
      allowed: false,
      tone: "locked"
    });
    expect(getPermissionActionGate("observe", "run-command")).toMatchObject({
      allowed: false,
      tone: "locked"
    });
  });

  it("marks ask mode actions as approval-required instead of silently locked", () => {
    expect(getPermissionActionGate("ask", "start-workflow")).toMatchObject({
      allowed: true,
      tone: "approval-required"
    });
    expect(getPermissionActionGate("ask", "approve-action").reason).toContain("Approve or request changes");
  });

  it("allows workspace-local execution but keeps merge locked outside PR-first mode", () => {
    expect(getPermissionActionGate("workspace", "run-command")).toMatchObject({
      allowed: true,
      tone: "available"
    });
    expect(getPermissionActionGate("workspace", "merge-pr")).toMatchObject({
      allowed: false,
      tone: "locked"
    });
  });

  it("keeps restricted mode locked for execution and approvals", () => {
    expect(getPermissionActionGate("restricted", "start-workflow")).toMatchObject({
      allowed: false,
      tone: "locked"
    });
    expect(getPermissionActionGate("restricted", "approve-action")).toMatchObject({
      allowed: false,
      tone: "locked"
    });
  });

  it("throws descriptive errors for unknown runtime inputs", () => {
    expect(() => getPermissionActionGate("missing" as never, "start-workflow")).toThrow(
      /Unknown permission mode ID "missing"/
    );
    expect(() => getPermissionActionGate("ask", "missing-action" as never)).toThrow(
      /Unknown permission action "missing-action"/
    );
  });
});

