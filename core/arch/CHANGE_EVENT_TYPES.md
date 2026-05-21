# Change Event Types

Defines typed events for document versioning and CHANGELOG entries. Inspired by event-sourced patterns for maintaining rich audit trails.

## Event Types

| Event Type | Description | Display Text Example |
|------------|-------------|---------------------|
| `artifact_created` | New artifact added to repository | "Created prompt-pack-v1" |
| `content_updated` | Artifact content modified | "+15 -3 lines changed" |
| `metadata_updated` | Tags, title, or metadata changed | "Updated tags: +governance" |
| `relationship_added` | New relationship link created | "Added depends-on → Phase-03" |
| `artifact_superseded` | Artifact replaced by newer version | "Superseded by prompt-pack-v2" |
| `artifact_reverted` | Rollback to previous version | "Reverted to v2" |
| `artifact_archived` | Moved to archive/deprecated status | "Archived (no longer maintained)" |

## CHANGELOG Integration

Use event types in CHANGELOG entries for consistency:

```markdown
### Documentation Updates
| Date | File | Change Type | Notes |
| --- | --- | --- | --- |
| 2026-01-20 | core/orchestrator/RELATIONSHIP_TYPES.md | artifact_created | Phase 21 deliverable |
| 2026-01-20 | core/arch/templates.md | content_updated | Added relationship guidance |
| 2026-01-20 | dedup-policy.md | relationship_added | Added link to RELATIONSHIP_TYPES.md |
```

## Display Text Conventions

### artifact_created
- Format: "Created {artifact-name}"
- Include parent directory if ambiguous

### content_updated
- Format: "+{added} -{removed} lines changed" or brief description
- For major rewrites: "Major revision: {summary}"

### metadata_updated
- Format: "Updated {field}: +{added} -{removed}"
- Examples: "Updated tags: +governance -draft", "Updated title: New Name"

### relationship_added
- Format: "Added {relationship-type} → {target}"
- Use artifact-id or short name for target

### artifact_superseded
- Format: "Superseded by {new-artifact}"
- Add rationale in Notes column

### artifact_reverted
- Format: "Reverted to {version}"
- Add reason in Notes column

## Event Properties

Each event conceptually has:
- **timestamp**: When the event occurred (YYYY-MM-DD for CHANGELOG)
- **artifact**: The artifact affected
- **actor**: Who/what made the change (agent, user)
- **event_type**: One of the types above
- **details**: Event-specific data (diff stats, relationship type, etc.)

## Related Documents

- `core/CHANGELOG.md` - Uses event types for entries
- `core/ARTIFACT_INDEX.md` - Tracks supersedes chains
- `core/orchestrator/RELATIONSHIP_TYPES.md` - Defines relationship types for relationship_added events
