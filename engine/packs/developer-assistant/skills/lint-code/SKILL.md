---
name: lint-code
version: 1.0.0
description: Lint source code using project-configured linters and auto-fix safe violations.
allowed_tools:
  - shell
  - file_ops
tags:
  - linting
  - developer
  - code-quality
---

# Lint Code

Run the project's configured linter(s) on specified files or the entire source
tree. Report violations, apply auto-fixes where safe, and explain any manual
fixes needed.

## Supported Linters

| Language | Linter | Auto-fix |
|----------|--------|----------|
| Python | ruff, flake8, pylint | ruff --fix |
| TypeScript/JS | eslint, biome | eslint --fix, biome check --apply |
| Go | golangci-lint | gofmt, goimports |
| Rust | clippy | cargo fix |
| YAML | yamllint | manual |

## Procedure

1. Detect the linter configuration by checking for:
   - `pyproject.toml` (ruff/flake8 sections), `.flake8`, `.pylintrc` → Python
   - `.eslintrc.*`, `biome.json` → JS/TS
   - `.golangci.yml` → Go
   - `clippy.toml` → Rust
   Show which linter and config file will be used before running.

2. Show the exact lint command before running.

3. Run linting in check-only mode first (no auto-fix):
   - ruff: `python -m ruff check <path>`
   - eslint: `npx eslint <path>`

4. Parse the output to group violations by:
   - **Auto-fixable**: can be fixed automatically and safely
   - **Manual**: require human judgment to fix

5. Report all violations with file, line, rule code, and description.

6. For auto-fixable violations, show the command and ask for confirmation
   before applying. Never auto-fix without showing the command.

7. For manual violations, explain what needs to change and why.

8. After any auto-fix, re-run linting to confirm the fix is complete.

## Output Format

```
## Lint Report: <path>

Linter: ruff v0.x.x  Config: pyproject.toml

### Auto-fixable (N violations)

src/module.py:12 — E501 Line too long (105 > 99 characters) [auto-fixable]
src/utils.py:34 — I001 Import block unsorted [auto-fixable]

Auto-fix command: `python -m ruff check --fix src/`
Run this? (confirm before proceeding)

### Manual fixes required (N violations)

src/api.py:88 — B006 Mutable default argument
Explanation: Using a mutable default like `def f(x=[])` shares the list across
all calls. Fix: use `def f(x=None)` and set `x = x or []` inside the function.

### Summary
Total violations: N  Auto-fixable: N  Manual: N
```

## Quality Rules

- Always show the lint command before running it.
- Never apply auto-fix without explicit confirmation.
- Explain the "why" behind manual violations, not just the "what."
- Re-run after auto-fix to verify no new violations were introduced.
