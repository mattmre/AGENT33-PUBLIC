---
name: run-tests
version: 1.0.0
description: Run project tests and report results with failure diagnostics and fix suggestions.
allowed_tools:
  - shell
  - file_ops
tags:
  - testing
  - developer
  - ci
---

# Run Tests

Execute the project's test suite, interpret results, and provide diagnostics
for any failures. Support common test frameworks: pytest (Python), Jest (JS/TS),
Go test, and cargo test (Rust).

## Procedure

1. Detect the test framework by checking for:
   - `pyproject.toml` or `pytest.ini` → pytest
   - `package.json` with "jest" key → Jest
   - `go.mod` → go test
   - `Cargo.toml` → cargo test
   If multiple frameworks are detected, ask the user which to run or run all.

2. Show the exact command before running: `shell: <command>`

3. Run the test command. Standard commands:
   - pytest: `python -m pytest <args> -q`
   - Jest: `npm test -- --ci`
   - Go: `go test ./... -v`
   - Rust: `cargo test`

4. Capture both stdout and stderr.

5. Parse the output:
   - Count: passed, failed, skipped, errored
   - Identify each failing test by name
   - Extract the failure message and stack trace

6. For each failing test, provide:
   - **Test name**: the full test ID
   - **Failure type**: assertion error, exception, timeout, or other
   - **Failure message**: the actual vs expected values or exception text
   - **Likely cause**: a 1-2 sentence diagnosis based on the error
   - **Suggested fix**: a concrete next step (check a specific line, add a
     missing mock, update a snapshot, etc.)

7. Report a final summary: overall pass/fail status, counts, and total
   duration.

## Output Format

```
## Test Run: <project/scope>

Command: `<exact command run>`

### Results

Status: PASSED | FAILED
Passed: N  Failed: N  Skipped: N  Duration: Xs

### Failures

#### Test: test_module::test_function_name
Type: AssertionError
Message: assert 42 == 43
Likely cause: The function returns the cached value from a previous test state.
Fix: Ensure test isolation by resetting the cache in setUp/teardown.

### Summary
<Overall assessment: all green, or N failures requiring attention>
```

## Quality Rules

- Always show the command before running it.
- Do not modify test files or production code to make tests pass without
  explaining the change and confirming with the user.
- If tests pass, report it clearly: "All N tests passed."
- If a test framework is not detected, report the situation and ask rather
  than guessing.
