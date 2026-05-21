---
name: explain-error
version: 1.0.0
description: Diagnose and explain error messages with root cause analysis and actionable fix steps.
allowed_tools:
  - file_ops
  - shell
tags:
  - debugging
  - developer
  - error-diagnosis
---

# Explain Error

Given an error message, stack trace, or log output, perform root cause analysis
and provide a clear explanation plus actionable fix steps.

## Procedure

1. Receive the error text (paste, file path, or command output).
2. Identify the error type:
   - **Runtime exception**: exception class + message (e.g., `TypeError`, `NullPointerException`)
   - **Build/compile error**: syntax or type errors from a compiler/linter
   - **Configuration error**: misconfigured environment, missing file/env var
   - **Network error**: connection refused, timeout, DNS failure
   - **Permission error**: file system or auth permission denied
3. Parse the stack trace to find:
   - **Origin**: where in the code the error was triggered
   - **Propagation**: how the error bubbled up through the call stack
   - **Root cause frame**: the innermost frame that is in the project's own code
     (not in a library or framework)
4. If additional context is needed (source file, config file, environment),
   use `file_ops` to read relevant files. Show what you are reading and why.
5. Formulate the explanation:
   - **What happened**: a plain-English description of the error
   - **Why it happened**: the root cause (what code or config triggered it)
   - **How to fix it**: numbered steps to resolve the issue
   - **How to verify**: a command or test to confirm the fix worked
6. If the error has a known solution (common library error, OS-level issue),
   provide the canonical fix directly. Reference documentation or a known
   issue URL if available.

## Output Format

```
## Error Diagnosis

**Error type**: <exception class or error category>
**Origin**: <file>:<line> in <function>
**Root cause**: <concise statement of why this happened>

---

### What Happened

<2-4 sentences explaining the error in plain English>

### Why It Happened

<Technical explanation of root cause, referencing specific code or config>

### How to Fix It

1. <First fix step — specific and actionable>
2. <Second fix step if needed>
3. ...

### How to Verify

Run: `<command>`
Expected result: <what a successful outcome looks like>
```

## Quality Rules

- Never guess if the error is ambiguous — ask for more context (full stack
  trace, relevant config file, or environment details).
- Root cause must be specific. "A null pointer was encountered" is not a root
  cause; "The `user` object is None because the database query returned no
  results for the given ID" is.
- Fix steps must be concrete. "Fix the configuration" is not a step;
  "Set `DATABASE_URL` in your `.env` file to `postgresql://...`" is.
- If the error is in a third-party library, identify whether the bug is in
  the library (provide workaround) or in the project's usage of the library
  (provide usage fix).
- Always include a verification step so the user knows when the fix is complete.
