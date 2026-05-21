# Evidence Capture Template

Use this to record commands and verification outcomes for any non-trivial change.

## Task
- ID:
- Owner:
- Branch/PR:
- Date:

## Primary Verification
Commands and outputs that directly demonstrate acceptance criteria are met.

### Commands Run
| Command | Output Summary | Exit Code |
|---------|---------------|-----------|
| `<command>` | `<summary>` | 0/1 |

### Full Output (if applicable)
```
<paste full output for audit trail>
```

## Secondary Verification
Additional checks that support primary verification (linting, type checks, etc.).

### Commands Run
| Command | Output Summary | Exit Code |
|---------|---------------|-----------|
| `<command>` | `<summary>` | 0/1 |

## Diff Summary
| Files Changed | Lines Added | Lines Removed | Rationale |
|---------------|-------------|---------------|-----------|
| `<file>` | +N | -N | `<why>` |

## Test Results
- Test suite:
- Outcome (pass/fail + count):
- Coverage (if available):
- Notes:

## Review Outcomes
- Reviewer:
- Required issues:
- Suggested improvements:
- Status (approved/changes-requested/pending):

## Artifacts
- Logs: `<path or link>`
- Reports: `<path or link>`
- Screenshots: `<path or link>`

## Evidence Checklist
- [ ] Commands recorded with exact CLI
- [ ] Outputs captured (summary + full if non-trivial)
- [ ] Diff summary documented
- [ ] Tests recorded with pass/fail count
- [ ] Review outcomes captured (if applicable)
- [ ] Artifacts linked

## Example (Completed)
### Primary Verification
| Command | Output Summary | Exit Code |
|---------|---------------|-----------|
| `pytest tests/unit/parser_test.py -v` | 24 passed, 0 failed | 0 |

### Diff Summary
| Files Changed | Lines Added | Lines Removed | Rationale |
|---------------|-------------|---------------|-----------|
| `src/parser.py` | +15 | -3 | Added error handling for malformed input |
| `tests/unit/parser_test.py` | +20 | -0 | Added test for malformed input edge case |
