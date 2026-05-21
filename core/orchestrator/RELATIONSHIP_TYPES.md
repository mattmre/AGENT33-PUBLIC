# Relationship Types

Defines semantic relationship primitives for connecting AGENT-33 artifacts. Use these when documenting provenance, dependencies, and artifact evolution.

## Core Relationships

| Relationship | Meaning | Direction | Example |
|--------------|---------|-----------|---------|
| `depends-on` | Artifact requires another to function | child → parent | Phase-05 depends-on Phase-03 |
| `derived-from` | Artifact was created from another | new → source | canonical-doc derived-from collected/source.md |
| `supersedes` | Artifact replaces a deprecated version | new → old | CLAUDE-v2.md supersedes CLAUDE-v1.md |
| `exemplifies` | Concrete example of an abstract pattern | example → pattern | tdd-workflow.md exemplifies workflow-template.md |
| `contextualizes` | Provides background for design decisions | research → feature | memorizer-dossier contextualizes Phase-21 |
| `explains` | Documentation clarifies a concept | docs → concept | GLOSSARY.md explains orchestrator-role |
| `chunk-of` | Section belongs to a larger document | section → parent | For document decomposition |

## Usage Guidelines

### When to Add Relationships

1. **Canonicalization**: When creating a canonical artifact from collected sources, add `derived-from` links.
2. **Version replacement**: When a new version replaces an old one, add `supersedes` link.
3. **Phase planning**: When a phase depends on prior phases, add `depends-on` links.
4. **Research intake**: When research informs a feature, add `contextualizes` link.
5. **Examples**: When documenting concrete implementations of patterns, add `exemplifies` link.

### Where to Document Relationships

- **CHANGELOG.md**: Record relationship additions in the Relationships column
- **Artifact headers**: Add a `## Relationships` section with links
- **ARTIFACT_INDEX.md**: Include `supersedes` column for version tracking

### Relationship Header Template

Add to artifact files when relationships exist:

```markdown
## Relationships

| Type | Target | Notes |
|------|--------|-------|
| derived-from | collected/example-project/docs/CLAUDE.md | Canonical baseline |
| supersedes | core/agents/CLAUDE-v1.md | Added session context |
```

## Relationship Graph Properties

- **Transitivity**: `depends-on` is transitive (A depends-on B, B depends-on C → A depends-on C)
- **Asymmetry**: All relationships are directional; reverse relationships have different semantics
- **Versioning**: `supersedes` creates a linear version chain; preserve the full chain for audit

## Related Documents

- `dedup-policy.md` - Uses `derived-from` and `supersedes` during canonicalization
- `sync-plan.md` - Tracks provenance chain with relationship types
- `core/CHANGELOG.md` - Records relationship additions
