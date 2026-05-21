# TASKS

## Queue (unassigned)
(No tasks remaining in queue)

## Phase 3-8 Queue (assigned)
(All Phase 3-8 tasks completed - see Done section below)

## Phase 11-20 Queue (assigned)
(All Phase 11-20 tasks completed - see Done section below)

## In Progress
- [ ] (agent) T#: status / notes / blockers

## Done

### Bootstrap
- [x] Bootstrap orchestration files created (this commit)

### T2 - Warmup/Pin Script
- [x] T2: Add warmup/pin script and confirm model stays hot for 30+ minutes
  - Evidence: `scripts/warmup-pin.ps1` (PowerShell warmup script with configurable duration, ping interval, response time logging)
  - Evidence: `scripts/README.md` (documentation with usage, parameters, exit codes, verification steps)
  - Features: Connects to Ollama at localhost:11435, loads model, pings every 5 minutes, runs 35+ minutes by default, exits 0 on success

### T1 - Orchestration Protocols
- [x] T1: Create/update orchestration protocol files and validate Qwen Code tool usage
  - Evidence: `core/orchestrator/QWEN_CODE_TOOL_PROTOCOL.md` (invocation schema, validation checklist, error handling, model pinning/warmup)
  - Evidence: `core/orchestrator/agents/QWEN_WORKER_RULES.md` (code tool usage, output validation, error patterns)
  - Evidence: `core/ORCHESTRATION_INDEX.md` (updated with new protocol file)

### T3 - Orchestration Diagnostics
- [x] T3: Run a small "real task" in this repo (add diagnostics)
  - Evidence: `scripts/validate-orchestration.ps1` (validates ORCHESTRATION_INDEX.md, cross-refs, orphan detection)
  - Evidence: `scripts/README.md` (script documentation)
  - Output summary: 60 indexed files found (0 missing), 35 broken cross-refs in core/INDEX.md, 191 orphaned files detected
  - Script exits 1 (issues found) - diagnostics working as intended

### Phase 3
- [x] T4 (Phase 3): Spec-first workflow consolidation (spec-first checklist + handoff links; review pending)
  - Evidence: `core/orchestrator/handoff/SPEC_FIRST_CHECKLIST.md`, `docs/session-logs/SESSION-2026-01-16_AGENT-33_PHASE-3.md`
- [x] T5 (Phase 3): Autonomy budget + escalation guidance (autonomy template + handoff links; review pending)
  - Evidence: `core/orchestrator/handoff/AUTONOMY_BUDGET.md`, `docs/session-logs/SESSION-2026-01-16_AGENT-33_PHASE-3.md`

### Phase 4
- [x] T6 (Phase 4): Harness initializer + clean-state protocol (initializer doc; review pending)
  - Evidence: `core/orchestrator/handoff/HARNESS_INITIALIZER.md`, `docs/session-logs/SESSION-2026-01-16_AGENT-33_PHASE-4.md`
- [x] T7 (Phase 4): Progress log format + rotation guidance (progress log format doc)
  - Evidence: `core/orchestrator/handoff/PROGRESS_LOG_FORMAT.md`, `docs/session-logs/SESSION-2026-01-16_AGENT-33_PHASE-4.md`

### Phase 5
- [x] T8 (Phase 5): Policy pack v1 skeleton
  - Evidence: `core/packs/policy-pack-v1/AGENTS.md`, `core/packs/policy-pack-v1/ORCHESTRATION.md`, `core/packs/policy-pack-v1/EVIDENCE.md`, `core/packs/policy-pack-v1/RISK_TRIGGERS.md`, `core/packs/policy-pack-v1/ACCEPTANCE_CHECKS.md`, `core/packs/policy-pack-v1/PROMOTION_GUIDE.md`
- [x] T9 (Phase 5): Risk triggers extension (agentic security)
  - Evidence: `core/packs/policy-pack-v1/RISK_TRIGGERS.md`, `core/orchestrator/handoff/REVIEW_CHECKLIST.md`
- [x] T10 (Phase 5): Promotion criteria update (traceability)
  - Evidence: `core/workflows/PROMOTION_CRITERIA.md`

### Phase 6
- [x] T11 (Phase 6): MCP/tool registry governance
  - Evidence: `core/orchestrator/TOOL_GOVERNANCE.md`, `core/ORCHESTRATION_INDEX.md`, `docs/phases/PHASE-06-TOOLING-INTEGRATION-AND-MCP.md`
- [x] T12 (Phase 6): Tools-as-code guidance
  - Evidence: `core/orchestrator/TOOLS_AS_CODE.md`, `core/ORCHESTRATION_INDEX.md`, `docs/phases/PHASE-06-TOOLING-INTEGRATION-AND-MCP.md`

### Phase 7
- [x] T13 (Phase 7): Evidence capture + verification log alignment
  - Evidence: `core/orchestrator/handoff/EVIDENCE_CAPTURE.md`, `core/arch/verification-log.md`, `core/orchestrator/handoff/SESSION_WRAP.md`
- [x] T14 (Phase 7): Test matrix extension for agent workflows
  - Evidence: `core/arch/test-matrix.md`, `docs/session-logs/SESSION-2026-01-16_AGENT-33_PHASE-7.md`

### Phase 8
- [x] T15 (Phase 8): Evaluation harness + golden tasks plan
  - Evidence: `core/arch/evaluation-harness.md` (7 golden tasks, 4 golden cases, 5 metrics, evaluation playbook)
- [x] T16 (Phase 8): Baseline evaluation reporting template
  - Evidence: `core/arch/evaluation-report-template.md`, `docs/phases/PHASE-08-EVALUATION-AND-BENCHMARKING.md`

### Phase 11
- [x] T17 (Phase 11): Agent registry schema + capability taxonomy
  - Evidence: `core/orchestrator/AGENT_REGISTRY.md` (10 agents AGT-001 to AGT-010, 25 capabilities in 5 categories P/I/V/R/X, YAML schema, onboarding workflow)
- [x] T18 (Phase 11): Routing map + onboarding updates
  - Evidence: `core/orchestrator/AGENT_ROUTING_MAP.md` (quick reference table with registry IDs, escalation chains, multi-role workflows)

### Phase 12
- [x] T19 (Phase 12): Tool registry change control
  - Evidence: `core/orchestrator/TOOL_REGISTRY_CHANGE_CONTROL.md` (4 checklists CCC-01 to CCC-04, 12 provenance checks, 5 MCP checks, 3 baseline tools)
- [x] T20 (Phase 12): Deprecation + rollback guidance
  - Evidence: `core/orchestrator/TOOL_DEPRECATION_ROLLBACK.md` (4-phase deprecation workflow, 3 rollback procedures, version pinning, rollback drills)

### Phase 13
- [x] T21 (Phase 13): Code execution contract + adapter template
  - Evidence: `core/orchestrator/CODE_EXECUTION_CONTRACT.md` (execution schema, sandbox limits 4 tables, input validation 5 checks IV-01 to IV-05, adapter template with 3 examples CLI/API/MCP, progressive disclosure L0-L3)

### Phase 14
- [x] T22 (Phase 14): Prompt injection defenses + sandbox approvals
  - Evidence: `core/orchestrator/SECURITY_HARDENING.md` (prompt injection defense with 5 threat types and 5 defense layers, sandbox approval gates AG-01 to AG-05, secrets handling 4 classes and 6 rules, network/command allowlist governance, 4 red team scenarios)

### Phase 15
- [x] T23 (Phase 15): Two-layer review checklist + signoff flow
  - Evidence: `core/orchestrator/TWO_LAYER_REVIEW.md` (L1/L2 review model, reviewer assignment rules RA-01 to RA-05, L1 checklist 19 checks, L2 checklist 20 checks, signoff flow 6 states, review SLAs)

### Phase 16
- [x] T24 (Phase 16): Trace schema + artifact retention rules
  - Evidence: `core/orchestrator/TRACE_SCHEMA.md` (trace hierarchy 5 levels, failure taxonomy 10 categories F-ENV to F-UNK with 30 subcodes, 9 artifact types, retention periods, storage paths, 6 logging requirements)

### Phase 17
- [x] T25 (Phase 17): Regression gates + triage playbook
  - Evidence: `core/arch/REGRESSION_GATES.md` (4 gate types, thresholds v1.0.0, 5 golden task tags, 5 regression indicators, 7-step triage playbook, severity matrix, enforcement workflows)

### Phase 18
- [x] T26 (Phase 18): Autonomy budget enforcement
  - Evidence: `core/orchestrator/AUTONOMY_ENFORCEMENT.md` (budget schema, 10 preflight checks, 8 enforcement points, 10 stop conditions, 8 escalation triggers, policy automation)

### Phase 19
- [x] T27 (Phase 19): Release cadence + sync automation plan
  - Evidence: `core/orchestrator/RELEASE_CADENCE.md` (3 cadence types, versioning strategy, 8 release checks, sync automation with dry-run, 4 rollback procedures, release notes template)

### Phase 20
- [x] T28 (Phase 20): Research intake + continuous improvement
  - Evidence: `core/orchestrator/CONTINUOUS_IMPROVEMENT.md` (5 research types, intake template, 4 roadmap refresh frequencies, 15 CI checks CI-01 to CI-15, lessons learned template, improvement metrics IM-01 to IM-05)

## Review-to-Backlog Checklist
- Capture review inputs in `handoff/REVIEW_CAPTURE.md` when required.
- Triage findings and assign severity tags.
- Decide accept/defer/reject with rationale.
- Convert accepted findings into TASKS entries with acceptance criteria + verification.
- Record evidence in `core/arch/verification-log.md`.

## Task Template
When you pick a task:
1) Create branch: 	ask/T#-short-name
2) Update TASKS.md In Progress line with your agent name + timestamp
3) Implement minimal changes
4) Run checks/tests (or explain why not possible)
5) Capture reviewer output (if risk triggers apply) using `handoff/REVIEW_CAPTURE.md`
6) Confirm Definition of Done checklist: `handoff/DEFINITION_OF_DONE.md`
7) Commit with message: T#: <summary>
8) Update TASKS Done with summary + commit hash + verification evidence

## Minimum Task Payload
- ID and title
- Owner and start date
- Acceptance criteria
- Verification steps
- Spec-first checklist reference (`handoff/SPEC_FIRST_CHECKLIST.md`)
- Autonomy budget (when scope or risk warrants) (`handoff/AUTONOMY_BUDGET.md`)
- Reviewer required (yes/no)

## Acceptance Criteria Examples
- "CLI command exits 0 and produces expected output file."
- "Unit tests for module X pass; new test covers edge case Y."
- "Documentation updated for new flag; examples added."

## Status Update Template
- Status:
- Progress:
- Blockers:
- Next action:
