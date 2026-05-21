# Operator Manual

This manual ties the orchestration handoff system to the AEP workflow in `core/arch/`.

## Start Here
1) Read `core/orchestrator/handoff/STATUS.md`.
2) Read `core/orchestrator/handoff/PLAN.md`.
3) Review `core/orchestrator/handoff/TASKS.md`.

## Planning and Scope
- Use `core/arch/workflow.md` for the end-to-end AEP cycle.
- Use `core/arch/scope-lock-template.md` to lock scope before a cycle.
- Record master backlog using `core/arch/backlog-template.md`.
- Apply `core/orchestrator/handoff/SPEC_FIRST_CHECKLIST.md` before implementation.
- Capture an autonomy budget when scope or risk warrants it (`core/orchestrator/handoff/AUTONOMY_BUDGET.md`).

## Execution
1) Create or select a task in TASKS with explicit acceptance criteria.
2) Assign owner, branch name, and verification steps.
3) Implement minimal changes and run tests.
4) If review inputs exist, follow `core/orchestrator/REVIEW_INTAKE.md` and capture output in `core/orchestrator/handoff/REVIEW_CAPTURE.md`.
5) Close task using the DoD checklist.

## Verification and Logging
- Record commands and outcomes in TASKS.
- Use `core/arch/verification-log.md` as the long-term evidence log.
- Log decisions in `core/orchestrator/handoff/DECISIONS.md`.

## Model-Agnostic Guidance
- Do not assume any single model or tool.
- If a task requires a specific tool or model, note it in TASKS.

## Tool Governance
- Follow `core/orchestrator/TOOL_GOVERNANCE.md` before adding tools or MCP servers.
- Use `core/orchestrator/TOOLS_AS_CODE.md` for progressive disclosure and tooling structure.

## Orchestration Consistency Checklist
- TASKS updated with acceptance criteria and verification steps.
- Evidence capture completed.
- Review capture completed when risk triggers apply.
- Decisions logged for scope or architecture changes.
