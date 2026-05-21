import type { DomainConfig } from "../../types";

export const releasesDomain: DomainConfig = {
  id: "releases",
  title: "Releases",
  description: "Release lifecycle, sync, rollback.",
  operations: [
    {
      id: "release-create",
      title: "Create Release",
      method: "POST",
      path: "/v1/releases",
      description: "Create release record.",
      defaultBody: JSON.stringify(
        {
          version: "0.2.0",
          branch: "main",
          commit_hash: "abc123"
        },
        null,
        2
      )
    },
    {
      id: "release-list",
      title: "List Releases",
      method: "GET",
      path: "/v1/releases",
      description: "List releases."
    },
    {
      id: "release-get",
      title: "Get Release",
      method: "GET",
      path: "/v1/releases/{release_id}",
      description: "Get release detail.",
      defaultPathParams: {
        release_id: "replace-with-release-id"
      }
    },
    {
      id: "release-freeze",
      title: "Freeze Release",
      method: "POST",
      path: "/v1/releases/{release_id}/freeze",
      description: "Freeze release.",
      defaultPathParams: {
        release_id: "replace-with-release-id"
      },
      defaultBody: "{}"
    },
    {
      id: "release-rc",
      title: "Mark RC",
      method: "POST",
      path: "/v1/releases/{release_id}/rc",
      description: "Transition to RC.",
      defaultPathParams: {
        release_id: "replace-with-release-id"
      },
      defaultBody: "{}"
    },
    {
      id: "release-validate",
      title: "Validate Release",
      method: "POST",
      path: "/v1/releases/{release_id}/validate",
      description: "Run release validation.",
      defaultPathParams: {
        release_id: "replace-with-release-id"
      },
      defaultBody: "{}"
    },
    {
      id: "release-publish",
      title: "Publish Release",
      method: "POST",
      path: "/v1/releases/{release_id}/publish",
      description: "Publish release.",
      defaultPathParams: {
        release_id: "replace-with-release-id"
      },
      defaultBody: "{}"
    },
    {
      id: "release-checklist-get",
      title: "Get Checklist",
      method: "GET",
      path: "/v1/releases/{release_id}/checklist",
      description: "Get release checklist.",
      defaultPathParams: {
        release_id: "replace-with-release-id"
      }
    },
    {
      id: "release-checklist-patch",
      title: "Update Checklist",
      method: "PATCH",
      path: "/v1/releases/{release_id}/checklist",
      description: "Patch checklist entries.",
      defaultPathParams: {
        release_id: "replace-with-release-id"
      },
      defaultBody: JSON.stringify(
        {
          item_id: "CL-01",
          status: "done"
        },
        null,
        2
      )
    },
    {
      id: "release-sync-rule-create",
      title: "Create Sync Rule",
      method: "POST",
      path: "/v1/releases/sync/rules",
      description: "Create downstream sync rule.",
      defaultBody: JSON.stringify(
        {
          target_repo: "org/downstream-repo",
          branch: "main"
        },
        null,
        2
      )
    },
    {
      id: "release-sync-rule-list",
      title: "List Sync Rules",
      method: "GET",
      path: "/v1/releases/sync/rules",
      description: "List sync rules."
    },
    {
      id: "release-sync-dry-run",
      title: "Sync Dry Run",
      method: "POST",
      path: "/v1/releases/sync/rules/{rule_id}/dry-run",
      description: "Dry-run sync rule.",
      defaultPathParams: {
        rule_id: "replace-with-rule-id"
      },
      defaultBody: "{}"
    },
    {
      id: "release-sync-execute",
      title: "Execute Sync Rule",
      method: "POST",
      path: "/v1/releases/sync/rules/{rule_id}/execute",
      description: "Execute sync rule.",
      defaultPathParams: {
        rule_id: "replace-with-rule-id"
      },
      defaultBody: "{}"
    },
    {
      id: "release-rollback",
      title: "Rollback Release",
      method: "POST",
      path: "/v1/releases/{release_id}/rollback",
      description: "Rollback release.",
      defaultPathParams: {
        release_id: "replace-with-release-id"
      },
      defaultBody: JSON.stringify(
        {
          reason: "Validation failed"
        },
        null,
        2
      )
    },
    {
      id: "release-rollbacks",
      title: "List Rollbacks",
      method: "GET",
      path: "/v1/releases/rollbacks",
      description: "List rollback events."
    },
    {
      id: "release-rollback-recommend",
      title: "Recommend Rollback",
      method: "POST",
      path: "/v1/releases/rollback/recommend",
      description: "Get rollback recommendation.",
      defaultBody: JSON.stringify(
        {
          release_id: "replace-with-release-id"
        },
        null,
        2
      )
    }
  ]
};
