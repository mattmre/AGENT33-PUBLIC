# Agent Memory Protocol

Instructs agents on autonomous knowledge management within AGENT-33 sessions.

## Core Principles

1. **Search before acting** - At session start, query relevant artifacts before making changes
2. **Store reusable knowledge** - Persist insights in agent-learning.md or CHANGELOG
3. **Relate what you find** - Add relationships between discovered artifacts
4. **Retire obsolete entries** - Mark deprecated items with `supersedes` links
5. **Never ask permission** for routine memory operations

## Session Start Checklist

1. Read `docs/next session/next-session-narrative.md` for context
2. Check `core/CHANGELOG.md` for recent changes
3. Query `core/ARTIFACT_INDEX.md` for relevant artifacts
4. Review any `supersedes` chains to find current versions

## Knowledge Storage Guidelines

### What to Store

| Store | Don't Store |
|-------|-------------|
| Reusable patterns discovered | Session-specific debug notes |
| Convention clarifications | Temporary workarounds |
| Relationship discoveries | Personal preferences |
| Verified command outputs | Speculative ideas |

### Where to Store

| Knowledge Type | Location |
|----------------|----------|
| Codebase conventions | Agent memory tool (if available) |
| Artifact relationships | Source artifact's `## Relationships` section |
| Session learnings | `agent-learning.md` (for reusable insights) |
| New artifacts | Appropriate core/ subdirectory |

## Relationship Creation

When discovering connections between artifacts:

1. Identify relationship type from `core/orchestrator/RELATIONSHIP_TYPES.md`
2. Add to source artifact's `## Relationships` section
3. Record in CHANGELOG.md with relationship notation
4. Update ARTIFACT_INDEX.md if a new artifact was created

## Artifact Retirement

When an artifact is obsolete:

1. Create new artifact with updated content
2. Add `supersedes` relationship to new artifact
3. Do NOT delete the old artifact (preserve for audit)
4. Update any documents referencing the old artifact

## Autonomous Operations

Agents may perform without explicit permission:
- Reading any artifact in `core/` or `docs/`
- Adding relationship annotations
- Updating CHANGELOG.md with discoveries
- Creating session logs in `core/logs/`

Agents should ask before:
- Deleting or renaming artifacts
- Modifying `collected/` (immutable by policy)
- Changing governance documents (policy packs, rules)

## Related Documents

- `core/orchestrator/RELATIONSHIP_TYPES.md` - Relationship taxonomy
- `core/ARTIFACT_INDEX.md` - Artifact discovery
- `core/CHANGELOG.md` - Change tracking
- `dedup-policy.md` - Immutability rules
