# MDC Rules Format

**Status**: Specification  
**Source**: CA-012 (Incrementalist .cursor/rules/ pattern)  
**Priority**: Medium

## Overview

MDC (Markdown Cursor) is a structured format for defining agent rules that combines YAML frontmatter with markdown content. This format enables:

1. **Structured metadata** - Role, globs, description in frontmatter
2. **Rich content** - Patterns, examples, guidelines in markdown
3. **IDE integration** - Glob-based activation in compatible editors
4. **Composability** - Rules can reference other rules

## File Structure

```
core/packs/mdc-rules/
├── README.md           # This file
├── orchestrator.mdc    # Orchestrator agent rules
├── refinement.mdc      # Refinement workflow rules
└── evidence.mdc        # Evidence capture rules
```

## MDC Format

```markdown
---
description: Short description for IDE tooltips
globs:
  - "core/orchestrator/**/*.md"
  - "core/agents/**/*.md"
role: agent  # or: user, system
alwaysApply: false  # true = always active
---

# Rule Title

Rule content in markdown format.

## Patterns

Describe patterns to follow.

## Examples

Show example code or content.

## Anti-Patterns

Describe what to avoid.
```

## Available Rules

| Rule | Scope | Purpose |
|------|-------|---------|
| `orchestrator.mdc` | Orchestration files | Agent coordination patterns |
| `refinement.mdc` | Refinement workflows | Artifact refinement guidelines |
| `evidence.mdc` | Evidence capture | Verification documentation |

## Usage

### In Compatible Editors

Editors like Cursor automatically apply rules based on glob patterns when editing matching files.

### In AGENT-33 Workflows

Rules can be loaded and applied to agent prompts:

```python
def load_applicable_rules(file_path: str) -> List[MDCRule]:
    """Load all rules whose globs match the file path."""
    rules = []
    for rule_file in Path("core/packs/mdc-rules").glob("*.mdc"):
        rule = parse_mdc(rule_file)
        if rule.matches(file_path) or rule.always_apply:
            rules.append(rule)
    return rules
```

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| contains | `orchestrator.mdc` | Orchestration rules |
| contains | `refinement.mdc` | Refinement rules |
| contains | `evidence.mdc` | Evidence rules |
| implements | CA-012 | Incrementalist competitive analysis |
