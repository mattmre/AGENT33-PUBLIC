import { describe, expect, it } from "vitest";

import {
  DEFAULT_WORKSPACE_SESSION_ID,
  WORKSPACE_SESSIONS,
  WORKSPACE_SESSION_IDS,
  getWorkspaceSession,
  isWorkspaceSessionId
} from "./workspaces";

describe("workspace sessions", () => {
  it("keeps default and template ids valid", () => {
    expect(isWorkspaceSessionId(DEFAULT_WORKSPACE_SESSION_ID)).toBe(true);
    expect(WORKSPACE_SESSIONS.map((workspace) => workspace.id)).toEqual(WORKSPACE_SESSION_IDS);
  });

  it("provides BridgeSpace-style starter templates", () => {
    expect(WORKSPACE_SESSIONS.map((workspace) => workspace.template)).toEqual([
      "Solo Builder",
      "Research + Build",
      "Test + Review",
      "Multi-Agent Shipyard"
    ]);
  });

  it("returns the selected workspace summary", () => {
    expect(getWorkspaceSession("shipyard").name).toBe("Multi-Agent Shipyard");
  });
});
