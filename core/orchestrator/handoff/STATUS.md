# STATUS (quick refresh)

## Repo Purpose
This repo captures a model-agnostic orchestration protocol. STATUS should record the current runtime and operational context.

## Handoff Ownership
- Current owner:
- Backup owner:

## Runtime Assumptions Checklist
- Local runtime available (or specified alternative).
- Repo in expected state (no unknown dirty changes).
- Required environment variables documented.

## Spec-First + Autonomy
- Spec-first checklist: `handoff/SPEC_FIRST_CHECKLIST.md`
- Autonomy budget template: `handoff/AUTONOMY_BUDGET.md`

## Runtime Protocols
- Harness initializer + clean-state protocol: `handoff/HARNESS_INITIALIZER.md`
- Progress log format + rotation: `handoff/PROGRESS_LOG_FORMAT.md`
## Local Runtime (example)
- Local LLM runtime on localhost:11435
- Containerized deployment with persistent model volume

## Key Commands
Start:
- docker compose up -d --pull always

Bootstrap/pin model:
- powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap-qwen.ps1
Warm/pin model:
- powershell -ExecutionPolicy Bypass -File .\scripts\warmup-pin.ps1

Test:
- Invoke-RestMethod GET http://localhost:11435/api/tags
- POST generate to /api/generate

## Agent Protocol
- Orchestrator edits: PLAN.md, TASKS.md, DECISIONS.md
- Workers take tasks, make branches, keep diffs small, run checks, update TASKS.

## Known Constraints
- Single GPU: generation is effectively serialized (queued). Use multiple agents to parallelize I/O + testing + review, not simultaneous token generation.

## Task Status Glossary
- queued: in TASKS queue, not started.
- in_progress: active work underway.
- blocked: waiting on a dependency or decision.
- review: awaiting reviewer input.
- done: verified and documented.

## Task Status Mapping
- queued -> in_progress: owner assigned and work started.
- in_progress -> review: risk triggers apply and review requested.
- in_progress -> done: no review required and evidence captured.
- review -> done: review outcomes resolved and evidence captured.

## Handoff File Map
- STATUS.md: runtime assumptions and constraints.
- PLAN.md: objectives and success criteria.
- TASKS.md: task queue and status.
- DECISIONS.md: architecture decisions and rationale.
- PRIORITIES.md: rolling horizon priorities.
- SPEC_FIRST_CHECKLIST.md: spec-first workflow checklist + sample spec.
- AUTONOMY_BUDGET.md: scope and escalation template per task.
- HARNESS_INITIALIZER.md: initializer steps and clean-state protocol.
- PROGRESS_LOG_FORMAT.md: progress log fields + rotation guidance.
