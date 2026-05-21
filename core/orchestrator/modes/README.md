# Dry Run Mode

**Status**: Specification  
**Source**: CA-011 (Incrementalist competitive analysis)  
**Priority**: Medium

## Overview

Dry run mode allows simulation of orchestration workflows without executing side effects. This enables safe preview of what would happen before committing to actual execution.

## Entry Points

- `DRY_RUN_SPEC.md` - Detailed specification

## Core Concept

In dry run mode:
- All analysis and planning runs normally
- Agent invocations are simulated
- File writes are logged but not performed
- A detailed execution plan is generated

## Quick Example

```bash
# Preview what would happen
agent-33 run --dry-run

# Output plan to file
agent-33 run --dry-run --plan-output plan.md
```

## Output

Dry run produces a structured plan:

```markdown
# Execution Plan (Dry Run)

**Generated**: 2026-01-20T15:30:00Z  
**Mode**: parallel (limit: 4)  
**Artifacts**: 12 affected

## Detection Summary
- Changed files: 5
- Trigger matches: 0 (incremental)
- Affected artifacts: 12

## Execution Order

### Level 1 (No Dependencies)
1. `core/prompts/SYSTEM.md` → refinement-agent
2. `core/prompts/WORKER.md` → refinement-agent

### Level 2 (Depends on Level 1)
3. `core/agents/worker.md` → refinement-agent
4. `core/agents/reviewer.md` → refinement-agent

## Estimated Duration
- Sequential: ~15 minutes
- Parallel (4): ~5 minutes
```

## Use Cases

1. **CI/CD Planning** - Preview pipeline before execution
2. **Change Impact** - Understand what will be affected
3. **Cost Estimation** - Estimate token usage
4. **Debugging** - Verify detection and routing logic

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| depends-on | `DRY_RUN_SPEC.md` | Full specification |
| uses | `../parallel/EXECUTION_MODES.md` | Mode definitions |
| implements | CA-011 | Incrementalist competitive analysis |
