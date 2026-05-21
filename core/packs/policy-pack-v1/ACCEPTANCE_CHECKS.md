# ACCEPTANCE_CHECKS.md (Policy Pack v1)

Purpose: Default acceptance checks per change type.

## Required (fill in per repo)
- Unit tests:
- Lint/format:
- Type checking:
- Build/package:

## Conditional
- Parser changes: parser-specific fixtures + golden outputs.
- IO changes: integration tests for read/write paths.
- Performance changes: benchmark or perf regression.
- Security changes: relevant security checks.
