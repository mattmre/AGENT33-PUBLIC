# Core Library

This directory holds the canonical, de-duplicated reference set built from `collected/`.
It defines the model-agnostic orchestration system, AEP workflow, and reusable templates.

## Structure
- `arch/`: Agentic engineering and planning (AEP) templates and guidance.
- `agents/`: Canonical agent instructions; `agents/sources/` holds archived variants.
- `prompts/`: Canonical review frameworks and prompt packs.
- `orchestrator/`: Orchestrator rules, handoff docs, and prompt assets.
- `orchestrator/integrations/`: Platform integration specs (channels, voice/media, credentials, privacy).
- `workflows/`: Canonical GitHub workflow templates and instructions.
- `roadmap/`, `phases/`, `research/`, `user-guide/`, `api/`: Project documentation canon.
- `logs/`: Session logs and next-session narratives, partitioned by source repo.

## Orchestration Overview
- `core/ORCHESTRATION_INDEX.md`: links the orchestration system, AEP workflow, and workflows.
- `core/orchestrator/README.md`: orchestration entrypoints and roles.

## Specifications
- Handoff protocol: PLAN, TASKS, STATUS, DECISIONS, PRIORITIES.
- Roles: Director, Orchestrator, Worker (Impl/QA), Reviewer, Researcher, Documentation.
- Risk triggers: security, schema, API, CI/CD, large refactors require review.
- Evidence capture: commands, tests, artifacts, and review outcomes.
- Workflow promotion: only reusable templates move from sources to canonical.
- Platform integrations (CA-017): channel integration, voice/media, credential management, privacy-first architecture.

## Canonicalization
- Canonical choices are logged in `core/CHANGELOG.md`.
- Non-canonical variants are archived under `core/agents/sources/` and `core/workflows/sources/`.
