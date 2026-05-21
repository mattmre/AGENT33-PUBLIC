# Orchestration Meta Analysis

Date: 2026-01-16
Scope: Orchestration system docs, prompts, agent rules, workflow templates, and handoff artifacts.

## Meta Analysis (System Health)
- The orchestration core is coherent: PLAN/TASKS/STATUS/DECISIONS is consistent with PROMPT_PACK and SYSTEM/WORKER rules.
- Canonical references exist but lack a single “operator manual” that ties AEP workflow to local orchestrator execution.
- Workflow templates are partially promoted; large project-specific workflows should remain source-only unless explicitly required.
- Agent roles are defined but do not include a “Director” role; this is a naming gap vs the requested structure.
- Model-agnostic requirement: current wording references specific models/tools; needs a model-neutral framing for orchestration guidance.

## Orchestrator Perspective
- Strength: Handoff files are well-defined and minimal.
- Gap: No standard “Definition of Done” checklist tied directly to TASKS entries.
- Recommendation: Add a DoD checklist template to `core/orchestrator/handoff/TASKS.md` or a separate `core/orchestrator/handoff/DEFINITION_OF_DONE.md`.

## Director Perspective (Oversight)
- Strength: DECISIONS log exists; PLAN has objectives.
- Gap: No portfolio-level prioritization or cadence view for multi-repo orchestration.
- Recommendation: Add a lightweight `core/orchestrator/handoff/PRIORITIES.md` with a rolling 2-week horizon.

## Analyzer Perspective (Quality + Risk)
- Strength: SYSTEM/WORKER rules mandate minimal diffs and test execution.
- Gap: No explicit risk rubric for when to require reviewer involvement.
- Recommendation: Add a “risk trigger” section in `core/orchestrator/prompts/SYSTEM.md`.

## Researcher Perspective (Evidence + Context)
- Strength: Architecture & Planning workflow is comprehensive.
- Gap: Links in `core/arch/workflow.md` point to `docs/...` instead of `core/...`.
- Recommendation: Update links or add a short note that `core/` is the canonical store.

## Context Perspective (Project-Specific Handoff)
- Strength: `core/agents/CLAUDE.md` now includes condensed contexts for source projects.
- Gap: Context sections are appended without a TOC or selection guidance.
- Recommendation: Add a short “Context Selector” table to `core/agents/CLAUDE.md` or to `core/agents/CLAUDE_SOURCES.md`.

## Documentation Perspective
- Strength: `core/README.md`, `core/agents/README.md`, `core/workflows/README.md` created.
- Gap: No summary doc for orchestration system and its entrypoints.
- Recommendation: Add `core/orchestrator/README.md` with “Start Here” instructions.

## Reviewer Perspective
- Strength: Review rules in `GEMINI_REVIEW_RULES.md` are concise.
- Gap: There is no explicit mapping of reviewer outputs back into TASKS/DECISIONS.
- Recommendation: Add “review output capture” step in `core/orchestrator/handoff/TASKS.md` template.

---

# Planning

## Objectives
1) Normalize orchestration entrypoints (README + navigation).
2) Add DoD and risk triggers to reduce ambiguity.
3) Clarify canonical vs source workflow sets.
4) Enforce model-agnostic framing in orchestrator guidance.

## Proposed Tasks (Draft)
- T4: Add `core/orchestrator/README.md` and link to handoff docs.
- T5: Add `DEFINITION_OF_DONE.md` and wire into TASKS template.
- T6: Add workflow source index + promotion criteria.
- T7: Add risk triggers to SYSTEM.md.
- T8: Replace model-specific language in prompts with model-agnostic terms.

## Scheduling
- Week 1: T4, T6, T8 (doc-only changes)
- Week 2: T5, T7 (policy updates after review)

---

# Implementation Notes (Planned)
- Keep changes documentation-only unless otherwise approved.
- All changes should update `core/CHANGELOG.md`.

# Review & Research Notes
- Some workflow sources contain deploy/test pipelines for a different product; do not promote unless needed.
- .NET pipeline and dependabot config have been promoted as reusable templates.
