# Tools-as-Code Guidance

Purpose: keep tool schemas, wrappers, and policies in versioned files that can be loaded on demand.

Related docs:
- `core/orchestrator/CODE_EXECUTION_CONTRACT.md` (execution contract, adapter templates)
- `core/orchestrator/TOOL_GOVERNANCE.md` (allowlist policy)
- `core/orchestrator/TOOL_REGISTRY_CHANGE_CONTROL.md` (change control)

## Principles
- Progressive disclosure: load only the tool details needed for the task.
- Minimal schemas: avoid bloated or redundant inputs.
- Deterministic interfaces: stable inputs/outputs and pinned versions.
- Evidence-first: every tool entry has provenance and allowlist references.

## Workflow
1) Inventory the tool and define the required scope.
2) Create a registry entry with metadata and schema.
3) Add a wrapper or adapter in the code execution layer.
4) Add fixtures or golden outputs when possible.
5) Update allowlist and provenance checklist references.

## Progressive Disclosure Levels
- L0: name + summary + owner.
- L1: inputs/outputs summary.
- L2: full schema and constraints.
- L3: examples and fixtures.

## Example Folder Structure
```
tools/
  registry/
    mcp-example/
      tool.yaml
      schema.json
      README.md
      CHANGELOG.md
  adapters/
    python/
      mcp_example.py
  policies/
    allowlist.md
    provenance.md
```

## Acceptance Checks
- Version pinned in registry entry.
- Allowlist policy referenced and approved.
- Provenance checklist completed.
- Examples or fixtures added when feasible.
