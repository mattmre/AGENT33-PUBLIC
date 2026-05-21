import { describe, expect, it } from "vitest";

import { WORKSPACE_SESSIONS } from "./workspaces";
import {
  WORKSPACE_BOARDS,
  WORKSPACE_TASK_STATUSES,
  getWorkspaceBoard,
  getWorkspaceTaskCounts
} from "./workspaceBoard";

describe("workspace board data", () => {
  it("provides a board for every workspace template", () => {
    expect(WORKSPACE_BOARDS.map((board) => board.workspaceId).sort()).toEqual(
      WORKSPACE_SESSIONS.map((workspace) => workspace.id).sort()
    );
  });

  it("keeps every task in a supported kanban status", () => {
    const validStatuses = new Set(WORKSPACE_TASK_STATUSES);
    const allTasks = WORKSPACE_BOARDS.flatMap((board) => board.tasks);

    expect(allTasks.length).toBeGreaterThan(0);
    expect(allTasks.every((task) => validStatuses.has(task.status))).toBe(true);
  });

  it("returns the selected workspace task counts", () => {
    expect(getWorkspaceTaskCounts("shipyard")).toMatchObject({
      todo: 1,
      running: 2,
      review: 1,
      complete: 1,
      blocked: 0
    });
  });

  it("returns agent roles for the selected workspace", () => {
    expect(getWorkspaceBoard("research-build").agents.map((agent) => agent.role)).toEqual([
      "Coordinator",
      "Scout",
      "Reviewer"
    ]);
  });

  it("keeps workspace summary counts aligned to board content", () => {
    for (const workspace of WORKSPACE_SESSIONS) {
      const board = getWorkspaceBoard(workspace.id);

      expect(workspace.tasks).toBe(board.tasks.length);
      expect(workspace.agents).toBe(board.agents.length);
    }
  });
});
