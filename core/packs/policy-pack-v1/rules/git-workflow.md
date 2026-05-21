# Git Workflow Rules

Purpose: Define version control standards for commits, branches, and pull requests.

## Rules

### 1. Conventional Commits Format

**Requirement**: Use Conventional Commits format for all commit messages.

**Format**:
```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

**Types**:
| Type | Use For |
|------|---------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `style` | Formatting (no code change) |
| `refactor` | Code change (no feature/fix) |
| `perf` | Performance improvement |
| `test` | Adding/updating tests |
| `chore` | Maintenance tasks |
| `ci` | CI/CD changes |

**Examples**:
```
feat(parser): add WhatsApp message parsing

fix: resolve null pointer in date formatting

docs: update API reference for v2 endpoints

refactor(auth): extract token validation to separate module
```

**Enforcement**:
- Validate commit message format before push
- Reject malformed messages with guidance

### 2. Branch Naming Conventions

**Requirement**: Use consistent, descriptive branch names.

**Format**: `<type>/<short-description>`

**Types**:
| Prefix | Use For |
|--------|---------|
| `feature/` | New features |
| `fix/` | Bug fixes |
| `hotfix/` | Urgent production fixes |
| `docs/` | Documentation changes |
| `refactor/` | Code refactoring |
| `test/` | Test additions/changes |
| `chore/` | Maintenance tasks |

**Guidelines**:
- Use lowercase with hyphens (kebab-case)
- Keep descriptions concise (2-4 words)
- Include ticket/issue number if applicable

**Examples**:
```
feature/user-authentication
fix/date-parsing-edge-case
docs/api-reference-update
refactor/extract-validation-module
feature/ISSUE-123-export-pdf
```

### 3. Pull Request Requirements

**Requirement**: PRs must meet quality standards before merge.

**PR Checklist**:
- [ ] Descriptive title following commit convention
- [ ] Description explaining what and why
- [ ] Linked to issue/task (if applicable)
- [ ] Tests pass (CI green)
- [ ] No merge conflicts
- [ ] Documentation updated (if applicable)

**PR Description Template**:
```markdown
## Summary
Brief description of changes.

## Changes
- Change 1
- Change 2

## Testing
How changes were tested.

## Related Issues
Closes #123
```

**Reference**: PR template at `core/workflows/PULL_REQUEST_TEMPLATE.md`.

### 4. Review Requirements

**Requirement**: Changes require appropriate review before merge.

**Review Matrix**:
| Change Type | Minimum Reviewers | Review Focus |
|-------------|-------------------|--------------|
| Feature | 1 | Correctness, design |
| Bug fix | 1 | Root cause addressed |
| Security | 2 (1 security-aware) | Security implications |
| Refactor | 1 | No behavior change |
| Docs only | 1 (or self-merge) | Accuracy, clarity |

**Reviewer Responsibilities**:
- Verify code correctness
- Check for edge cases
- Validate test coverage
- Confirm documentation accuracy
- Note any concerns or questions

**Reference**: Two-layer review process in `core/orchestrator/TWO_LAYER_REVIEW.md`.

### 5. Commit Hygiene

**Requirement**: Keep commits clean and meaningful.

**Guidelines**:
- One logical change per commit
- Commit messages explain "why" not just "what"
- No commits with just "WIP" or "fix"
- Squash fixup commits before merge
- Never commit broken code to main branch

**Prohibited Commit Content**:
- Secrets or credentials
- Large binary files (use LFS if needed)
- Generated files (add to .gitignore)
- IDE-specific settings (unless team-shared)

### 6. Branch Protection

**Requirement**: Protect main/production branches.

**Recommended Settings**:
- Require PR before merge (no direct push)
- Require status checks to pass
- Require review approval
- Enforce linear history (optional)

## Enforcement Checklist

Before creating a PR:

- [ ] Branch name follows convention
- [ ] Commits use conventional format
- [ ] Each commit is logical unit of work
- [ ] No secrets or large binaries
- [ ] PR description complete
- [ ] Tests pass locally

## Cross-References

- PR template: `core/workflows/PULL_REQUEST_TEMPLATE.md`
- Two-layer review: `core/orchestrator/TWO_LAYER_REVIEW.md`
- Evidence capture: `core/packs/policy-pack-v1/EVIDENCE.md`
- Risk triggers: `core/packs/policy-pack-v1/RISK_TRIGGERS.md`
