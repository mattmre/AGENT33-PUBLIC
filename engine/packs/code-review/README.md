# code-review

Automated code review pack for AGENT-33.

## Skills

- **review-diff**: Review a code diff for correctness, logic errors, and style issues
- **check-security**: Scan code for security vulnerabilities with CWE references
- **suggest-improvements**: Propose targeted refactoring and readability improvements

## Usage

```bash
agent33 packs validate engine/packs/code-review
agent33 packs apply code-review
```

## Tool Requirements

- `file_ops` for reading source files
- `shell` for running `git diff` and similar commands
