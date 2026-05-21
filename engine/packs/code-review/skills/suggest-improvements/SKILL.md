---
name: suggest-improvements
version: 1.0.0
description: Propose targeted refactoring and readability improvements for reviewed code.
allowed_tools:
  - file_ops
tags:
  - code-review
  - refactoring
  - readability
---

# Suggest Improvements

After a correctness and security review passes, suggest targeted improvements
to code structure, readability, testability, and maintainability. Focus on
changes that have a meaningful impact — avoid nitpicking that adds noise without value.

## Improvement Categories

1. **Readability** — rename unclear variables/functions, extract magic numbers into
   named constants, break overly long functions into smaller focused ones.
2. **Duplication** — identify copy-pasted logic that should be extracted into a
   shared function or utility.
3. **Testability** — flag code that is difficult to unit test (e.g., tight coupling
   to globals, untestable side effects in constructors) and suggest decoupling patterns.
4. **Performance** — identify obvious inefficiencies: repeated computation in loops,
   unnecessary full-table scans, missing indexes implied by query patterns.
5. **API Design** — flag confusing or inconsistent public APIs: methods that do
   too much, boolean flag parameters that should be split into two methods, missing
   return type annotations.
6. **Modernization** — suggest idiomatic replacements for deprecated patterns
   (e.g., use `pathlib` instead of `os.path`, use f-strings instead of `%`
   formatting, use dataclasses/pydantic instead of dict-of-dicts).

## Procedure

1. Read the code under review using `file_ops`.
2. Evaluate each improvement category in turn.
3. For each suggestion, record:
   - File and line range
   - Improvement category
   - Current code (quoted or described)
   - Proposed alternative
   - Rationale (1-2 sentences explaining the benefit)
4. Prioritize suggestions by impact. Lead with improvements that affect
   correctness-adjacent concerns (testability, API clarity) before purely
   cosmetic ones.
5. Summarize the total number of suggestions by category.

## Output Format

```
## Improvement Suggestions: <scope>

### High Impact

**Readability — utils.py:34-60 — Extract overly long function**
Current: `process_record()` is 27 lines and handles parsing, validation, and
database insertion in a single function.
Suggested: Split into `parse_record()`, `validate_record()`, and `save_record()`
to allow independent testing and reuse.
Rationale: Single-responsibility functions are easier to test, debug, and extend.

### Low Impact

**Modernization — config.py:5 — Use pathlib**
Current: `os.path.join(BASE_DIR, 'data')`
Suggested: `Path(BASE_DIR) / 'data'`
Rationale: pathlib is the idiomatic path API in Python 3.4+.

### Summary
High impact: 1  Medium impact: 0  Low impact: 1
```

## Quality Rules

- Suggestions must be actionable. "Consider improving readability" is not a suggestion.
- Do not suggest improvements that contradict the project's established style.
- If the code is already well-structured, state "No significant improvements suggested."
- Do not re-report issues already flagged in the correctness or security review.
