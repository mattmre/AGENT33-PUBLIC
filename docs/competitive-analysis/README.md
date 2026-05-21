# Competitive Analysis — Autonomous Protocol

AGENT-33 generates competitive analyses on demand rather than storing static snapshots.

## Triggering Analysis

```bash
# Analyze a specific competitor
agent33 intake https://github.com/org/competitor-repo

# Regenerate the full competitive landscape
agent33 analyze --competitive
```

## Methodology

1. **Repo Intake** — Clone and generate dossier (see `docs/self-improvement/intake-protocol.md`)
2. **Feature Extraction** — Map capabilities to `docs/research/templates/FEATURE_MATRIX_SCHEMA.md`
3. **Gap Analysis** — Compare against AGENT-33's current feature set
4. **Improvement Proposals** — Generate actionable proposals for each identified gap
5. **Summary** — Produce a dated summary stored in engine memory

## Output Locations

| Artifact | Location |
|----------|----------|
| Repo dossiers | `docs/research/repo_dossiers/` |
| Feature matrix | Generated on demand from dossiers |
| Gap analysis | Engine memory (queryable via API) |
| Improvement proposals | Engine memory → applied via self-improvement loop |

## Templates

Analysis uses the templates in `docs/research/templates/`:
- `REPO_DOSSIER_TEMPLATE.md` — Per-repo structured analysis
- `FEATURE_MATRIX_SCHEMA.md` — Cross-repo feature comparison schema
