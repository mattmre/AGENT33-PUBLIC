# System-Level Coding Rules (Model-Agnostic)

This document outlines the general coding rules and constraints that all agents must follow when working with the local agent orchestration system.

## Core Principles

### 1. Single Source of Truth
All system state is maintained in documentation files:
- PLAN.md for goals and acceptance criteria
- TASKS.md for task queue and status
- STATUS.md for current repository state
- DECISIONS.md for design decisions

### 2. Minimal Changes
- Make the smallest change that meets acceptance criteria
- Avoid unnecessary refactoring or over-engineering
- Focus on functionality over aesthetics

### 3. Documentation-First Approach
- Update documentation files before and after changes
- All documentation must be kept in sync with code
- Clear, concise descriptions of changes and reasoning

## Technical Constraints

### 4. Local Development
- All development occurs locally with the configured tooling
- No required cloud LLM dependency
- Resources limited to available hardware
- Use containers or virtual environments when applicable

### 5. GPU Resource Management
If using GPU-accelerated models, document constraints here.
- Limit parallel model loads when VRAM is constrained
- Set queue limits appropriate to hardware
- Use memory-optimized cache formats
- Enable attention optimizations if supported

### 6. Context Management
- Document context limits per model/tool
- Manage memory limits in models
- Handle long context properly without overflow

## Execution Workflow Rules

### 7. Task Management
- Tasks are picked from TASKS.md queue
- Each task has explicit acceptance criteria
- Status updates are made in TASKS.md
- Branch names follow pattern: `ask/T#-short-name`

### 8. Implementation Requirements
- Output commands, unified diffs, and test results
- Provide clear explanations of what was done and why
- Focus on correctness over code style
- Keep changes focused and targeted

### 9. Testing Standards
- Run tests after implementation
- Ensure results are provided to orchestrator
- Verify that changes don't break existing functionality
- Address any failing tests

## Inter-Agent Communication

### 10. Coordination with Orchestrator
- Follow orchestrator's PLAN.md for project goals
- Adhere to TASKS.md for task prioritization
- Return diff results and test outputs clearly
- Request clarification on acceptance criteria when needed

### 11. Status Updates
- Update TASKS.md regularly with progress
- Provide clear status messages in task records
- Indicate when tasks are complete or blocked
- Communicate any challenges or roadblocks clearly

## Quality Standards

### 12. Change Quality
- Maintain backward compatibility
- Follow existing code patterns
- Keep implementation simple and clear
- Avoid introducing new bugs

### 13. Documentation Quality
- All changes must be documented
- Updates to system documentation must be accurate
- Use clear and consistent terminology
- Review documentation for correctness after changes

## Special Considerations

### 14. Ollama-Specific Rules
If Ollama is used, specify environment variables in STATUS.md.

### 15. Windows Environment
- Use PowerShell scripts (.ps1) for local execution
- Follow Windows path conventions
- Account for Windows-specific limitations and quirks
- Ensure PowerShell execution policies allow script execution

## Reference

This system should maintain the principles from the following documents:
- WORKER_RULES.md - specific worker behavior rules
- PROMPT_PACK.md - reusable prompts for agents
- DECISIONS.md - design decisions record

## Risk Triggers (Require Reviewer)
- Security-sensitive changes (auth, encryption, secrets handling)
- Data schema changes or migrations
- Public API/interface changes
- Changes affecting CI/CD or deployment workflows
- Large refactors or broad formatting changes

## Risk Trigger Matrix

| Trigger | Reviewer Required | Evidence Required |
| --- | --- | --- |
| Security/Auth/Crypto | Yes | Review capture + evidence |
| Schema/Data Model | Yes | Review capture + migration/test proof |
| Public API | Yes | Review capture + compatibility notes |
| CI/CD or Deployment | Yes | Review capture + pipeline evidence |
| Large Refactor | Yes | Review capture + test suite summary |
