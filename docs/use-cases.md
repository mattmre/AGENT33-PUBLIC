# Use Cases

This document maps practical AGENT-33 deployments to the current runtime surface in `engine/src/agent33`.

## 1. Guardrailed Code Review Pipeline

Goal:
- Run scoped, repeatable review flows with explicit risk handling.

Use these modules:
- `api/routes/workflows.py`
- `api/routes/reviews.py`
- `review/service.py`
- `evaluation/service.py`

Typical flow:
1. Register a review workflow (`/v1/workflows/`).
2. Execute workflow for a PR branch (`/v1/workflows/{name}/execute`).
3. Create review record (`/v1/reviews/`).
4. Assess risk triggers and route L1/L2 signoff.
5. Record evaluation run and regressions for release gating.

Best fit:
- Teams that require explicit two-layer review before merge.

## 2. Release Command Center

Goal:
- Move releases through frozen -> RC -> validate -> publish with checklist controls.

Use these modules:
- `api/routes/releases.py`
- `release/service.py`
- `release/checklist.py`
- `release/sync.py`
- `release/rollback.py`

Typical flow:
1. Create release (`POST /v1/releases`).
2. Freeze, cut RC, validate.
3. Update/evaluate checklist items.
4. Publish when checks pass.
5. Run sync dry-runs or real syncs.
6. Initiate rollback if needed.

Best fit:
- Teams with repeatable release compliance requirements.

## 3. Autonomous Execution Budgeting

Goal:
- Enforce hard runtime limits for file, command, and network activity.

Use these modules:
- `api/routes/autonomy.py`
- `autonomy/service.py`
- `autonomy/enforcement.py`
- `autonomy/preflight.py`

Typical flow:
1. Create and activate budget.
2. Run preflight checks.
3. Attach runtime enforcer.
4. Gate each file/command/network action through enforcement APIs.
5. Trigger and resolve escalations.

Best fit:
- High-control automation in regulated or sensitive environments.

## 4. Evaluation and Regression Gates

Goal:
- Quantify quality and block regressions across PR/merge/release gates.

Use these modules:
- `api/routes/evaluations.py`
- `evaluation/service.py`
- `evaluation/gates.py`
- `evaluation/regression.py`

Typical flow:
1. Create run for gate type (`G-PR`, `G-MRG`, `G-REL`, `G-MON`).
2. Submit task results and quality metadata.
3. Compute metrics and gate verdict.
4. Save baseline for future comparison.
5. Triage/resolve regression records.

Best fit:
- Teams with golden-task style quality gates.

## 5. Memory-Backed Agent Sessions

Goal:
- Use retrieval context from long-term memory and session observations.

Use these modules:
- `memory/long_term.py`
- `memory/rag.py`
- `memory/hybrid.py`
- `memory/progressive_recall.py`
- `api/routes/memory_search.py`

Typical flow:
1. Store observations and embeddings.
2. Query memory via progressive recall levels (`index`, `timeline`, `full`).
3. Use RAG output as augmented prompt context.
4. Summarize sessions for long-horizon context compression.

Best fit:
- Research agents and recurring task assistants.

## 6. Continuous Improvement Operations

Goal:
- Track research intake, lessons learned, checklist completion, and roadmap refresh.

Use these modules:
- `api/routes/improvements.py`
- `improvement/service.py`
- `improvement/models.py`

Typical flow:
1. Submit and triage research intake.
2. Record lessons and action items.
3. Track checklist completion by period.
4. Capture metric snapshots and trends.
5. Record roadmap refresh outcomes.

Best fit:
- Teams running explicit continuous-improvement loops.

## 7. Multi-Channel Webhook Intake

Goal:
- Accept Telegram/Discord/Slack/WhatsApp webhook events into AGENT-33.

Use these modules:
- `api/routes/webhooks.py`
- `messaging/*.py`

Typical flow:
1. Instantiate adapter(s) in-process.
2. Register adapter(s) using `register_adapter(platform, adapter)`.
3. Receive provider webhook callbacks via `/v1/webhooks/*`.
4. Enqueue platform events for downstream handling.

Best fit:
- Environments with external chat/event integrations.

Constraint:
- Adapters are not auto-registered in `main.py`; explicit bootstrap is required.

## 8. Prompt and Rollout Optimization (Experimental)

Goal:
- Collect rollouts and iterate prompts via optimization algorithms.

Use these modules:
- `training/runner.py`
- `training/optimizer.py`
- `training/scheduler.py`
- `training/store.py`

Typical flow:
1. Record rollouts and rewards.
2. Run optimizer across historical rollouts.
3. Persist prompt versions and metrics.
4. Revert to earlier versions when needed.

Constraint:
- API routes exist (`/v1/training/*`), but full runtime wiring (`training_runner`, `agent_optimizer`) is partial by default.
