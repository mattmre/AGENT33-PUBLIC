# JSON Schemas

**Status**: Specification  
**Source**: CA-010 (Incrementalist incrementalist.schema.json pattern)

## Overview

This directory contains JSON Schema definitions for AGENT-33 configuration and artifact types. These schemas provide:

1. **Validation** - Ensure configuration files are correct
2. **IDE Support** - IntelliSense and autocompletion
3. **Documentation** - Self-documenting configuration

## Available Schemas

| Schema | Purpose | Usage |
|--------|---------|-------|
| `agent.schema.json` | Agent definitions | Define agent roles, capabilities, constraints |
| `workflow.schema.json` | Workflow definitions | Define multi-step processes |
| `orchestrator.schema.json` | Orchestrator config | Configure execution settings |

## Usage

### In Configuration Files

Add the `$schema` property to enable IDE validation:

```json
{
  "$schema": "./core/schemas/orchestrator.schema.json",
  "version": "1.0",
  "execution": {
    "mode": "parallel",
    "parallel_limit": 4
  }
}
```

### In YAML Files

Some IDEs support schema references in YAML:

```yaml
# yaml-language-server: $schema=./core/schemas/workflow.schema.json
name: refinement-workflow
version: "1.0.0"
steps:
  - id: validate
    action: validate
```

## Schema URLs

For remote validation:

- `./core/schemas/agent.schema.json`
- `./core/schemas/workflow.schema.json`
- `./core/schemas/orchestrator.schema.json`

## IDE Configuration

### VS Code

Add to `.vscode/settings.json`:

```json
{
  "json.schemas": [
    {
      "fileMatch": ["**/agents/*.json"],
      "url": "./core/schemas/agent.schema.json"
    },
    {
      "fileMatch": ["**/workflows/*.json"],
      "url": "./core/schemas/workflow.schema.json"
    },
    {
      "fileMatch": ["agent33.config.json", ".agent33/config.json"],
      "url": "./core/schemas/orchestrator.schema.json"
    }
  ]
}
```

## Validation CLI

```bash
# Validate a configuration file
agent-33 validate --schema orchestrator config.json

# Validate all agents
agent-33 validate --schema agent core/agents/*.json

# Validate with verbose output
agent-33 validate --schema workflow --verbose workflow.json
```

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| implements | CA-010 | Incrementalist competitive analysis |
| validates | `../orchestrator/**/*.json` | Orchestrator configurations |
| validates | `../agents/**/*.json` | Agent definitions |
| validates | `../workflows/**/*.json` | Workflow definitions |
