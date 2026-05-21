---
name: git-workflow
version: 1.0.0
description: Assist with common git operations including branching, committing, and pull requests.
allowed_tools:
  - shell
tags:
  - git
  - developer
  - version-control
---

# Git Workflow

Assist with common git operations: branching, staging, committing, pushing,
and preparing pull requests. Always show commands before running them and
require confirmation for destructive operations.

## Covered Operations

1. **Branch management**: create, switch, list, delete branches
2. **Staging and committing**: stage changes, write commit messages, commit
3. **Pushing**: push to remote, set upstream tracking
4. **Pull requests**: prepare PR title and body from commit history
5. **Status checks**: show working tree status, diff, and log

## Procedure by Operation

### Creating a Branch

1. Check current branch: `git branch --show-current`
2. Ensure working tree is clean or changes are stashed.
3. Show command: `git checkout -b <branch-name>`
4. Run after confirmation.
5. Confirm the new branch is active.

### Staging and Committing

1. Show status: `git status`
2. Show diff: `git diff --stat`
3. Present specific files to stage (prefer explicit files over `git add .`).
4. Show stage command and confirm.
5. Run `git status` again to verify staged set.
6. Draft a commit message following Conventional Commits format:
   `<type>(<scope>): <summary>` where type is feat/fix/docs/refactor/test/chore.
7. Show the full commit command with the message.
8. Commit after confirmation.

### Pushing

1. Check if remote tracking branch exists: `git rev-parse --abbrev-ref @{u}`
2. If no upstream: show `git push -u origin <branch>` and confirm.
3. If upstream exists: show `git push` and confirm.
4. **Never push with `--force` without explicit instruction.**

### Preparing a Pull Request

1. Get the base branch (usually `main` or `master`): `git branch -r`
2. Show commits on this branch: `git log origin/main..HEAD --oneline`
3. Show diff summary: `git diff origin/main...HEAD --stat`
4. Draft PR title (≤70 chars) from the commit messages.
5. Draft PR body with sections: Summary (bullet points), Testing, Notes.
6. Output the `gh pr create` command for review.

## Output Format

```
## Git Operation: <operation name>

Command: `<exact git command>`

<output of command>

Status: <success / confirmation needed / error>
Next step: <what to do next>
```

## Quality Rules

- Always show the command before running it.
- Never run `git reset --hard`, `git push --force`, `git clean -f`, or
  `git checkout -- .` without explicit user instruction.
- For destructive operations, describe exactly what will be lost before asking
  for confirmation.
- Prefer `git restore --staged <file>` over `git reset HEAD <file>` for unstaging.
- Write commit messages that explain why, not just what.
