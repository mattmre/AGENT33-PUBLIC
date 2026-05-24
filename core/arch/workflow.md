# Architecture & Planning Workflow Specification

See orchestration overview: `core/ORCHESTRATION_INDEX.md`.

Quick links (canonical `core/arch` paths):
- `core/arch/README.md`
- `core/arch/orchestrator-briefing.md`
- `core/INDEX.md`
- `core/arch/templates.md`
- `core/arch/phase-planning.md`
- `core/arch/next-session.md`
- `core/arch/schedule-and-tracking.md`
- `core/arch/scope-lock-template.md`
- `core/arch/glossary.md`
- `core/arch/test-matrix.md`
- `core/arch/active-tracker-template.md`
- `core/arch/cycle-layout-template.md`
- `core/arch/tracker-pointer.md`
- `core/arch/tracker-index.md`
- `core/arch/backlog-index.md`
- `core/arch/verification-log.md`
- `core/arch/change-log.md`
- `core/arch/agent-learning.md`
- `core/arch/risk-memo-template.md`
- `core/arch/phase-summary-template.md`
- `core/arch/tier-close-checklist.md`

## Inputs
- `docs/agentic-review-framework.md`
- Latest refinement report (e.g., `docs/refinement-cycle-YYYY-MM-DD.md`)
- PR list and date range (explicit scope for the sweep)
- Current main branch state
- Master backlog file (recommended: `docs/Architecture & Planning/backlog-YYYY-MM-DD.md`)
- Active tracker pointer: `docs/Architecture & Planning/tracker-pointer.md`
- Backlog index: `docs/Architecture & Planning/backlog-index.md`
- Tracker index: `docs/Architecture & Planning/tracker-index.md`
- Test matrix: `docs/Architecture & Planning/test-matrix.md`
- Glossary: `docs/Architecture & Planning/glossary.md`
- Active tracker template: `docs/Architecture & Planning/active-tracker-template.md`

## Roles
- Orchestrator (primary owner, planning + triage)
- Specialist agents: Architecture, Security, Testing, Performance, Reliability/Debug, Documentation, UX
- Verification agent (optional, can be shared with Testing)

## Triggers
- Manual checkpoints
- End of major phase or roadmap milestone

## Severity model
- Critical, High, Medium, Low
- Sorting: Severity first, then impact x (1/effort), then dependency order

## Workflow (ARCH phase)
1. Scope lock
   - Define PR range and time window.
   - Freeze inputs (refinement report + framework + PR list).

2. Discovery + normalization
   - Orchestrator ingests `agentic-review-framework.md` and the latest refinement report.
   - Normalize all findings into a single backlog with unique IDs.
   - De-duplicate, merge overlaps, and assign provisional severity.
   - Record backlog in `docs/Architecture & Planning/backlog-YYYY-MM-DD.md`.

3. Parallel re-validation
   - Spawn specialist agents to re-validate findings against current main.
   - Each agent must attach exact file paths and line ranges.
   - Propose the smallest safe fix, acceptance criteria, and effort sizing (S/M/L).

4. Architecture and planning synthesis
   - Orchestrator merges validated findings into a master backlog.
   - Re-score and re-rank using the sorting model.
   - Identify dependency chains and blockers.

## Workflow (ENGINEERING phase)
5. Tiered remediation execution
   - Start with Critical, then High, Medium, Low.
   - For each tier, generate small, reviewable remediation PRs (one coherent theme per PR).
   - Do not advance to the next tier until current tier is empty or blocked with a written unblock plan.
   - If any item is marked blocked, elevate it to immediate priority for unblock planning.
   - Tier exit requires verification evidence logged for every item.
   - Tier close checklist (auditability):
     - All findings show verification evidence in tracker and cycle verification log.
     - Phase summaries exist for all PRs in the tier.
     - Risk memos (Critical/High) archived if merged and verified.
     - Use `docs/Architecture & Planning/tier-close-checklist.md`.

6. Verification
   - After each PR: run build and full relevant tests.
   - Capture commands and results in the tracker.
   - Mirror evidence in the cycle verification log (default: `docs/Architecture & Planning/cycles/YYYY-MM-DD/verification-log.md`).
   - Add logging/doc updates when required by the fix.

7. Closure
   - Post a concise phase summary after each PR: what closed, what remains, what is next.
   - Use `docs/Architecture & Planning/phase-summary-template.md`.
   - Store summaries in `docs/Architecture & Planning/phase-summaries/`.
   - Naming convention: `YYYY-MM-DD_PR-###_summary.md`.
   - Record end-of-cycle summary using `docs/Architecture & Planning/cycle-summary-template.md`.
   - Repeat until all tiers are remediated or formally deferred.

## Deliverables
- Master backlog
- Remediation PRs by tier
- Audit-grade tracker log
- Phase summaries

## Tracker format (required)
Location: Use the path in `docs/Architecture & Planning/tracker-pointer.md` as authoritative.
Accepted paths:
- `docs/refinement-remediation/YYYY-MM-DD_tracker.md` (legacy)
- `docs/Architecture & Planning/cycles/YYYY-MM-DD/tracker-YYYY-MM-DD.md` (per-cycle)

Required columns:
- finding-id
- severity
- owning-agent
- PR/branch
- status
- commit hash
- verification evidence (test command + result)
- verification-log entry id

## Backlog entry format
Each finding must include:
- finding-id
- title
- severity
- impact
- effort (S/M/L)
- file path + line range
- recommended minimal fix
- acceptance criteria
- dependencies (finding-ids)
- blockers

Dependency ordering:
- Use dependency lists to topologically order findings within the same severity tier.

## Concurrency Protocol
- Single editor per file at a time (backlog, tracker, change-log, verification-log).
- Each finding has one owning agent; only that agent edits its entry.
- If conflicts occur, prefer the version with newer verification evidence and merge manually.
- Parallel cycles are allowed only with separate backlog and tracker files, and separate entries in the indexes.
- Use a current editor lock block for backlog and tracker files.
## Backlog Authority
- Each cycle has exactly one master backlog file referenced in `backlog-index.md`.

## Per-Cycle Logs
- When using the cycle layout, prefer per-cycle `change-log.md` and `agent-learning.md`.

## Ownership Handoff
- If an owning agent is inactive for 2 sessions, reassign in `change-log.md`.
- Handoff requires a short note: status, next action, and last verification result.

## PR Theme Cohesion
- A PR should address a single root cause or tightly related cluster.
- If more than 3 findings are required, split by component or test boundary.

## Blocked Escalation
- If blocked persists for 2 sessions, escalate to Orchestrator + owner with a decision logged in `change-log.md`.

## Verification Evidence
- Required for every merged fix: command and outcome in tracker plus `verification-log.md`.
- If test selection is partial, record rationale and reference the test matrix.

## Impact/Effort Calibration
- Use the rubrics in `docs/Architecture & Planning/templates.md`.

## Naming Conventions
- Backlog: `docs/Architecture & Planning/backlog-YYYY-MM-DD.md`
- Risk memos: `docs/Architecture & Planning/risk-memos/risk-memo-<finding-id>.md`

## Dispute Resolution
- If severity or fix approach is disputed, Orchestrator decides with one neutral agent within 1 session.

## Definition of done
- Finding has a merged PR or a documented defer/blocked entry with a scheduled follow-up.
- Tracker has evidence of test execution and results.
- Tier is empty or blocked with a written unblock plan.

## Guardrails
- Do not expand scope mid-cycle without re-locking the scope.
- Fixes must be minimal and safe; no refactors unless required by the fix.
- Each PR must be reviewable within one sitting.
- No tier skipping.
- Enforce commit message convention from `docs/Architecture & Planning/templates.md`.

## Enhancements (Research-Informed)
- Add explicit governance checkpoints: require human approval at scope lock, tier completion, and defer decisions.
- Use a lightweight change-management log for any scope change or defer (who/why/when).
- Treat post-merge review as a first-class step: require a remediation PR plan for any deviation from review guidelines.
- Track debt lifecycle states (new, validated, scheduled, in-progress, verified, deferred) to avoid limbo items.
- Capture a short risk memo for each Critical/High item to preserve context across sessions.
