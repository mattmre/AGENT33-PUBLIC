import { describe, expect, it } from "vitest";

import { releasesDomain } from "./releases";

function getOperation(id: string) {
  const operation = releasesDomain.operations.find((entry) => entry.id === id);
  expect(operation).toBeDefined();
  return operation!;
}

function defaultBody(id: string) {
  return JSON.parse(getOperation(id).defaultBody ?? "{}");
}

describe("releasesDomain", () => {
  it("keeps create-release defaults aligned with backend evidence fields", () => {
    expect(defaultBody("release-create")).toEqual({
      version: "0.2.0",
      release_type: "minor",
      description: "Release candidate for validation.",
      branch: "main",
      commit_hash: "abc123",
      build_id: "build-123",
      changelog_ref: "core/CHANGELOG.md",
      release_notes_ref: "release-notes/0.2.0.md"
    });
  });

  it("keeps checklist, sync, and rollback defaults backend-shaped", () => {
    expect(defaultBody("release-checklist-patch")).toMatchObject({
      check_id: "RL-01",
      status: "pass",
      message: "All release PRs are merged."
    });
    expect(defaultBody("release-sync-rule-create")).toMatchObject({
      source_pattern: "core/**/*.md",
      target_repo: "org/downstream-repo",
      target_path: "docs/agent33",
      strategy: "copy",
      frequency: "on_release"
    });
    expect(defaultBody("release-sync-execute")).toMatchObject({
      approved_dry_run_execution_id: "replace-with-dry-run-execution-id",
      confirm_real_io: true
    });
    expect(defaultBody("release-rollback-recommend")).toEqual({
      severity: "critical",
      impact: "high"
    });
  });
});
