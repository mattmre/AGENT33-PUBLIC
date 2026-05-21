# Config File Auto-Generation

**Status**: Specification  
**Source**: CA-016 (Incrementalist competitive analysis)  
**Priority**: Low

## Overview

The Config Generation system creates initial configuration files for AGENT-33 projects. This reduces setup friction and ensures configurations follow best practices.

## Entry Points

- `GENERATOR_SPEC.md` - Generator specification

## Quick Start

```bash
# Generate default configuration
agent-33 init

# Generate with specific options
agent-33 init --parallel --parallel-limit 8

# Generate only specific configs
agent-33 init --only orchestrator

# Preview without writing
agent-33 init --dry-run
```

## Generated Files

| File | Purpose |
|------|---------|
| `agent33.config.json` | Orchestrator configuration |
| `.agent33/triggers.yaml` | Custom trigger definitions |
| `.agent33/filters.yaml` | Include/exclude patterns |
| `.vscode/settings.json` | VS Code schema integration |

## Use Cases

1. **New Project Setup** - Generate starter configuration
2. **Best Practices** - Encode recommended settings
3. **Migration** - Upgrade from older config format
4. **Templates** - Generate project-specific configs

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| depends-on | `GENERATOR_SPEC.md` | Full specification |
| uses | `../../schemas/*.schema.json` | Schema validation |
| implements | CA-016 | Incrementalist competitive analysis |
