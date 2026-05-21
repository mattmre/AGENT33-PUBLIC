---
name: review-diff
version: 1.0.0
description: Review a code diff for correctness, logic errors, and style issues.
allowed_tools:
  - file_ops
  - shell
tags:
  - code-review
  - diff
  - quality
---

# Review Diff

Given a code diff (unified diff format or a PR description with changed files),
perform a thorough code review covering correctness, logic, and style.

## Procedure

1. Obtain the diff. If a file path is provided, read it with `file_ops`. If a
   git ref is given, run `git diff <ref>` via `shell`.
2. Parse the diff into changed hunks grouped by file.
3. For each changed file, review:
   - **Correctness**: does the logic implement the intended behavior? Look for
     off-by-one errors, incorrect conditionals, missing edge case handling.
   - **Error handling**: are errors caught and handled appropriately? Check for
     bare `except` clauses, swallowed exceptions, missing null checks.
   - **Data flow**: are variables initialized before use? Are mutable defaults
     avoided? Are return values checked?
   - **Style**: does the code follow the project's conventions? Flag inconsistent
     naming, overly long functions, and missing docstrings on public APIs.
4. For each issue, record:
   - File and line number(s)
   - Issue category (correctness / error-handling / data-flow / style)
   - Severity: `[BLOCKING]` or `[ADVISORY]`
   - A one-sentence description of the problem
   - A concrete suggested fix
5. Summarize the review with a pass/fail verdict and a count of blocking issues.

## Output Format

```
## Code Review: <description of change>

### Issues Found

**[BLOCKING] File.py:42 — Correctness**
Problem: The condition `if x = None` assigns rather than compares.
Fix: Change to `if x is None`.

**[ADVISORY] utils.py:17 — Style**
Problem: Function `process_data` has no docstring.
Fix: Add a one-line docstring describing its purpose and return type.

### Summary
Verdict: NEEDS CHANGES
Blocking issues: 1
Advisory issues: 1
```

## Quality Rules

- Never omit the "Fix" for any reported issue.
- If the diff is clean, report "No issues found. Approved." rather than inventing problems.
- Do not comment on lines that are unchanged context lines in the diff.
- Focus on the diff; do not audit the entire codebase unless asked.
