---
task_id: ING-YYYYMMDD-example
kind: ingestion
title: Short task title
owner: codex
status: draft
target: org/repo-or-remediation-target
summary: >
  One-sentence summary of the repo-ingestion or remediation effort.
acceptance_criteria:
  - Capture the primary source evidence in docs/research/.
  - Record the adoption decision and explicit non-goals.
  - Keep repository-root-relative links back to the active session planning files instead of duplicating the queue.
evidence:
  - docs/research/example-source-note.md
planning_refs:
  # repository-root-relative paths; resolve these from the repository root.
  - task_plan.md
  - findings.md
  - progress.md
research_refs:
  - docs/architecture/ROADMAP-REBASE-2026-03-26.md
created_at: 2026-03-28T00:00:00Z
updated_at: 2026-03-28T00:00:00Z
---

# Outcome

Summarize the ingestion or remediation decision in one short paragraph.

## Notes

- Add progress notes only if they materially change the ingestion outcome.
- Resolve `planning_refs` from the repository root.
- Keep the artifact small; the detailed queue and session log stay in the active session planning files (`docs/sessions/active/`).

## Deferred Follow-ups

- Note deferred work here only when it is specific to this ingestion target.
