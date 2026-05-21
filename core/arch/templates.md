# Architecture & Planning Templates And Conventions

Selected options:
- Finding IDs: Option A
- Branch prefixes: Option A

## Acceptance Criteria Template
Format:
- AC1:
- AC2:
- AC3:

## Impact Rubric
- High: user-facing breakage, security risk, data loss, or major stability issues.
- Medium: reliability, correctness, or performance issues with limited blast radius.
- Low: minor UX, docs, or low-risk cleanup.

## Effort Rubric
- S: <= 2 hours
- M: <= 1 day
- L: > 1 day

## Split/Merge Criteria
- Merge findings when they share the same root cause and can be verified by one test run.
- Split findings when they cross components, require different owners, or exceed one review sitting.

## Finding ID Convention
Format: `AEP-YYYYMMDD-PRNNN-SEQ`

Example: `AEP-20260116-PR042-003`

Rules:
- `YYYYMMDD` is the cycle start date.
- `PRNNN` is the scanned PR number (zero-padded).
- `SEQ` is a per-PR sequence number (zero-padded).
- If PR number is unknown, use `PR000`.

## Branch Naming Convention
Format: `aep/<severity>/<finding-id>/<short-theme>`

Examples:
- `aep/critical/AEP-20260116-PR042-003/null-guard`
- `aep/high/AEP-20260116-PR107-001/retry-backoff`

Rules:
- Severity is one of `critical|high|medium|low`.
- Keep `<short-theme>` to 2-4 words, kebab-case.

## Tracker Table (Markdown)
Required columns:
- finding-id
- severity
- owning-agent
- PR/branch
- status
- commit hash
- verification evidence
- verification-log entry id

Example header:
| finding-id | severity | owning-agent | PR/branch | status | commit hash | verification evidence | verification-log entry id |
| --- | --- | --- | --- | --- | --- | --- |

Status values:
- open
- in-progress
- blocked
- deferred
- merged

## Status Log Entry (Short Form)
Format:
- `YYYY-MM-DD`: finding-id - status - note

## PR Title Convention
Format:
- `[AEP][<severity>] <finding-id>: <short theme>`

## Commit Message Convention
Format:
- `AEP: <finding-id> - <short theme>`

Multi-finding commits:
- Use the primary finding-id in the commit message.
- List additional finding-ids in the PR description.

## Relationship Documentation

When artifacts have relationships to other documents, add a Relationships section:

```markdown
## Relationships

| Type | Target | Notes |
|------|--------|-------|
| derived-from | collected/repo/path.md | Source artifact |
| depends-on | docs/phases/PHASE-03-SPEC-FIRST-ORCHESTRATION-WORKFLOW.md | Prerequisite |
```

Common relationship types:
- `depends-on` - Phase or artifact prerequisites
- `derived-from` - Canonical artifact from collected source
- `supersedes` - New version replaces deprecated artifact
- `exemplifies` - Concrete example of abstract pattern
- `contextualizes` - Research informing design

See `core/orchestrator/RELATIONSHIP_TYPES.md` for full taxonomy.
