# Architecture & Planning (Architecture & Planning)

Architecture & Planning is a manual-checkpoint workflow that sends a coordinated swarm of agents back through historical PRs to surface deferred work, normalize it into a single master refinement backlog, and drive remediation in strict severity order. It extends the micro refinement loop used for the last 10 PRs into a phase-level engine that activates after full phases complete or at explicit human checkpoints.

This workflow is designed for breadth and accountability: it is intentionally slow, audit-heavy, and conservative. The output is a master listing of refinement work with verified file paths, actionable fixes, and a recorded decision trail (implemented, deferred, or blocked). The loop continues until all severities are resolved or formally deferred with a scheduled follow-up.

Core idea:
- Architecture and planning happen before remediation.
- Agents re-validate every inherited finding against current main.
- Work is cut into small, coherent PRs by severity tier.
- Remediation does not advance tiers until the current tier is empty or formally blocked.
- Every step leaves auditable traces (tracker, PR links, evidence).

Use Architecture & Planning when:
- A phase finishes and the team needs a deep cleanup pass.
- The backlog of deferred fixes is growing or unclear.
- You need an authoritative master list of refinement work to drive the next cycle.

What success looks like:
- A single, normalized master backlog with verified findings and acceptance criteria.
- A tracker mapping each finding to owning agent, PR, status, and evidence.
- Remediation PRs that are reviewable, cohesive, and tested.
- Clear defer/blocked rationales with scheduled follow-ups.

Key reference:
- `docs/Architecture & Planning/orchestrator-briefing.md`

Cycle checklists:
- `docs/Architecture & Planning/orchestrator-briefing.md`

Authoritative file list:
- `docs/INDEX.md`

Minimum artifacts per cycle:
- Scope lock record
- Backlog file
- Tracker file
- Tracker pointer
- Backlog index entry
- Tracker index entry
- Verification log entries

Cycle ID format:
- `AEP-YYYYMMDD-N` (N is a global increment)

Cycle ID allocation:
- Increment N sequentially in `docs/Architecture & Planning/tracker-index.md`.

Default per-cycle evidence log:
- `docs/Architecture & Planning/cycles/YYYY-MM-DD/verification-log.md`

Additional references:
- `docs/Architecture & Planning/workflow.md`
- `docs/Architecture & Planning/templates.md`
- `docs/Architecture & Planning/next-session.md`
- `docs/Architecture & Planning/phase-planning.md`
- `docs/Architecture & Planning/schedule-and-tracking.md`
- `docs/Architecture & Planning/tier-close-checklist.md`
- `docs/Architecture & Planning/cycle-summary-template.md`
- `docs/Architecture & Planning/cycle-summaries/README.md`
- `docs/Architecture & Planning/backlog-template.md`
- `docs/Architecture & Planning/backlog-index.md`
- `docs/Architecture & Planning/tracker-pointer.md`
- `docs/Architecture & Planning/tracker-index.md`
- `docs/Architecture & Planning/verification-log.md`
- `docs/Architecture & Planning/phase-summary-template.md`
- `docs/Architecture & Planning/phase-summaries/README.md`
- `docs/Architecture & Planning/risk-memo-template.md`
- `docs/Architecture & Planning/risk-memos/README.md`
- `docs/Architecture & Planning/risk-memos/closed/README.md`
- `docs/Architecture & Planning/agent-learning.md`
- `docs/Architecture & Planning/change-log.md`
- `docs/Architecture & Planning/scope-lock-template.md`
- `docs/Architecture & Planning/glossary.md`
- `docs/Architecture & Planning/test-matrix.md`
- `docs/Architecture & Planning/active-tracker-template.md`
- `docs/Architecture & Planning/cycle-layout-template.md`
