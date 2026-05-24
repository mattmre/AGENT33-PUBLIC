# Imported Capability Packs

Purpose: Record the Phase 47 imported capability packs that bridge EVOKORE skills into AGENT-33's existing pack, workflow, and discovery surfaces.

## Bundled Packs

| Pack | Runtime Path | Imported Skills |
| --- | --- | --- |
| `hive-family` | `engine/packs/hive-family/` | `hive`, `hive-concepts`, `hive-create`, `hive-patterns`, `hive-test` |
| `workflow-ops` | `engine/packs/workflow-ops/` | `planning-with-files`, `docs-architect`, `pr-manager`, `webapp-testing` |
| `platform-builder` | `engine/packs/platform-builder/` | `mcp-builder`, `repo-ingestor` |

## Workflow Templates

The imported packs are wired into the workflow catalog via:

- `core/workflows/capability-packs/implementation-session.workflow.yaml`
- `core/workflows/capability-packs/repo-ingestion.workflow.yaml`
- `core/workflows/capability-packs/pr-review-orchestration.workflow.yaml`
- `core/workflows/capability-packs/docs-overhaul.workflow.yaml`
- `core/workflows/capability-packs/webapp-lifecycle-testing.workflow.yaml`

These templates pass explicit `active_skills` through the workflow bridge so the imported packs are used as real runtime capabilities rather than passive documentation.
