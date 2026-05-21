# Spec-First Workflow Checklist

Use this checklist before implementation to lock scope and acceptance criteria.

## Checklist
- Problem statement (what is broken or missing)
- Goals (explicit outcomes)
- Non-goals (out of scope)
- Assumptions (inputs, environments, constraints)
- Dependencies (blocked by or blocking)
- Risks (security, data model, API, CI/CD)
- Acceptance checks (deterministic, verifiable)
- Evidence plan (commands, outputs, artifacts)
- Test plan (unit/integration/manual)
- Data model or schema changes (yes/no, impact)
- Interface changes (CLI/API/file format)
- Rollout and rollback plan

## Sample Spec (Minimal)
**Problem:** Handoff docs lack a consistent spec-first checklist.  
**Goals:** Add a checklist and reference it from handoff docs.  
**Non-goals:** Changing task tracking semantics or CLI behavior.  
**Assumptions:** Docs-only change; no tests required.  
**Acceptance Checks:** Checklist file exists; PLAN/STATUS/README reference it.  

## Usage
Attach the checklist (or a link) in the task entry in `handoff/TASKS.md`.
