# Refinement Relationship Policy

Purpose: define the Phase 21 preserve-original-during-refinement rule and the relationship metadata that keeps refined artifacts traceable.

## Policy

Captured source material under `collected/` is immutable. Do not edit collected files to fix, normalize, deduplicate, or reformat them.

When a captured source needs refinement:

1. Create or update a canonical artifact under `core/` or another approved canonical path.
2. Record `derived-from` on the canonical artifact when the refined artifact originates from a captured or research source.
3. Record `supersedes` when the refined artifact replaces a prior canonical artifact.
4. Keep distribution behavior in `core/orchestrator/distribution/DISTRIBUTION_SYNC_SPEC.md`; distribution copies or transforms canonical artifacts, never collected sources.
5. Preserve obsolete artifacts unless a separate cleanup approval explicitly authorizes deletion.

## Relationship Requirements

| Scenario | Required relationship | Target |
| --- | --- | --- |
| Canonical artifact promoted from source capture | `derived-from` | Original `collected/` path or current research source |
| Canonical artifact replaces an older canonical artifact | `supersedes` | Older canonical path |
| Distribution rule copies canonical content downstream | `depends-on` | Canonical source path and distribution spec |
| Research informs a phase or artifact | `contextualizes` | Phase document or target artifact |

## Sync Boundary

The historical root `sync-plan.md` file is not a current artifact. Phase 21 uses the distribution specification as the authoritative sync boundary:

- `core/orchestrator/distribution/DISTRIBUTION_SYNC_SPEC.md` defines one-way sync, immutable releases, validation, rollback, and drift detection.
- `core/orchestrator/distribution/rules/example-sync-rule.yaml` materializes the rules path used by the sync spec.
- Relationship metadata is maintained in canonical artifacts before sync; downstream sync preserves or rewrites links according to the distribution rule.

## Relationships

| Type | Target | Notes |
| --- | --- | --- |
| depends-on | `core/orchestrator/RELATIONSHIP_TYPES.md` | Defines `derived-from`, `supersedes`, `depends-on`, and `contextualizes` |
| depends-on | `core/orchestrator/distribution/DISTRIBUTION_SYNC_SPEC.md` | Authoritative current sync plan for canonical artifacts |
| contextualizes | `docs/architecture/PHASE-21-EXTENSIBILITY-PATTERNS-INTEGRATION.md` | Current Phase 21 refinement policy evidence |
