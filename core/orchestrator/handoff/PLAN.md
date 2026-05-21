# PLAN

## Project
Local multi-agent workflow using:
- A local LLM runtime (model-agnostic)
- A terminal implementation agent
- An orchestrator agent (when available)
- Optional reviewer agent for second-opinion reviews / test planning

## Objectives
- [ ] Establish repeatable orchestration protocol (PLAN/TASKS/STATUS/DECISIONS)
- [ ] Ensure workers produce **small diffs**, **tight scope**, **tests**
- [ ] Minimize wasted tokens by using file-based state and concise updates
- [ ] Provide quick "refresh context" entrypoint for any agent

## Constraints
- Single GPU (if applicable): avoid true parallel long generations; queue is expected
- Prefer **no extra monthly charges** beyond existing subscriptions
- Keep secrets out of repo; never commit credentials or tokens

## Success Criteria
- One or more tasks completed end-to-end:
  - task picked from TASKS
  - branch created
  - change implemented
  - tests run (or best available checks)
  - diff produced + merged or ready for PR
- Any new agent can open STATUS.md + PLAN.md + TASKS.md and continue in <5 minutes.

## Spec-First Workflow
- Use `handoff/SPEC_FIRST_CHECKLIST.md` before implementation.
- Attach the checklist (or a link) in TASKS entries.

## Autonomy Budget
- Complete `handoff/AUTONOMY_BUDGET.md` for any task with elevated risk or scope.

## Minimum Required Artifacts
- Updated TASKS entry with acceptance criteria and verification steps.
- Evidence capture (commands + outcomes).
- Review capture when risk triggers apply.

## Tools
- Git + branches per task
- Local or remote LLM runtime (as available)
- Optional second-opinion reviewer

## Risks / Mitigations
- Token limit hit: workers continue locally; orchestrator resumes later
- Model cold-start latency: use warm/pin script if applicable; avoid container restarts
- Scope creep: enforce task boundaries and acceptance criteria

## Current Priorities (edit me)
1) Wire up router later (optional) *after* local workflow proves stable
2) Add agent launcher scripts (done in this bootstrap)
3) Define "definition of done" checklist for tasks (below)
