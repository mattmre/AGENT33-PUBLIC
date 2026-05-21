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

1. **Repo Intake** — Clone the target repository and generate a structured
   dossier covering orchestration, state model, tooling, observability, and
   extensibility (see [`docs/self-improvement/intake-protocol.md`](../self-improvement/intake-protocol.md)).
2. **Feature Extraction** — Capture orchestration primitive, state model,
   safety/governance, tooling protocol, observability, and productization
   posture for cross-repo comparison.
3. **Gap Analysis** — Compare against AGENT-33's current feature set.
4. **Improvement Proposals** — Generate actionable proposals for each
   identified gap.
5. **Summary** — Produce a dated summary stored in engine memory.

## Output Locations

| Artifact | Location |
|----------|----------|
| Repo dossiers | Engine memory (queryable via API) |
| Feature matrix | Generated on demand from dossiers |
| Gap analysis | Engine memory (queryable via API) |
| Improvement proposals | Engine memory, applied via self-improvement loop |
