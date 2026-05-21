# developer-assistant

Developer workflow pack for AGENT-33.

## Skills

- **run-tests**: Run project tests and report results with failure diagnostics
- **lint-code**: Lint source code and apply safe auto-fixes
- **git-workflow**: Assist with branching, committing, and pull request preparation
- **explain-error**: Diagnose error messages with root cause analysis and fix steps

## Usage

```bash
agent33 packs validate engine/packs/developer-assistant
agent33 packs apply developer-assistant
```

## Tool Requirements

- `shell` for running test commands, linters, and git operations
- `file_ops` for reading source and config files
