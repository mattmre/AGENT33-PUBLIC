# scope-validation-hook

Purpose: Validate that changes stay within defined scope and acceptance criteria.

Related docs:
- `core/orchestrator/handoff/PLAN.md` (scope definition)
- `core/packs/policy-pack-v1/rules/performance.md` (scope creep prevention)
- `core/packs/policy-pack-v1/ACCEPTANCE_CHECKS.md` (acceptance criteria)

---

## Hook Configuration

```yaml
hook:
  name: scope-validation
  trigger: pre-commit
  scope: staged-files
  blocking: false  # Warn only, don't block
  tolerance: strict  # strict | relaxed
```

---

## Checks Performed

### 1. File Scope Check
- Compare modified files against PLAN.md scope
- Identify files outside defined boundaries
- Check for unexpected directories

### 2. Acceptance Criteria Alignment
- Map changes to acceptance criteria
- Identify changes not linked to criteria
- Flag additions without corresponding criteria

### 3. Change Magnitude Check
- Estimate diff size
- Compare against expected scope
- Warn on unexpectedly large changes

---

## Pseudo-code Implementation

```pseudo
function scopeValidationHook():
    # Load scope definition
    plan = parseMarkdown("handoff/PLAN.md")
    acceptanceCriteria = plan.acceptanceCriteria
    allowedPaths = plan.scope.paths
    maxDiffSize = plan.scope.maxDiff or 500  # lines default
    
    # Get changes
    stagedFiles = getStagedFiles()
    diffStats = getDiffStats()
    
    findings = []
    
    # Check file scope
    for file in stagedFiles:
        if not isInScope(file.path, allowedPaths):
            findings.append({
                type: "out-of-scope",
                severity: "warning",
                file: file.path,
                message: "File outside defined scope",
                allowedPaths: allowedPaths
            })
    
    # Check acceptance alignment
    for file in stagedFiles:
        linkedCriteria = findLinkedCriteria(file, acceptanceCriteria)
        if len(linkedCriteria) == 0:
            findings.append({
                type: "unlinked-change",
                severity: "info",
                file: file.path,
                message: "Change not linked to acceptance criteria"
            })
    
    # Check diff magnitude
    totalLines = diffStats.additions + diffStats.deletions
    if totalLines > maxDiffSize:
        findings.append({
            type: "large-diff",
            severity: "warning",
            message: f"Diff size ({totalLines} lines) exceeds expected ({maxDiffSize})",
            recommendation: "Consider splitting into smaller changes"
        })
    
    # Report findings
    if len(findings) > 0:
        reportFindings(findings)
        promptForConfirmation("Proceed with out-of-scope changes?")
    
    # Log for audit
    logScopeCheck({
        stagedFiles: stagedFiles,
        findings: findings,
        timestamp: now()
    })
    
    return ALLOW_COMMIT  # Warning only

function isInScope(filePath, allowedPaths):
    for pattern in allowedPaths:
        if matchGlob(filePath, pattern):
            return true
    return false

function findLinkedCriteria(file, criteria):
    linked = []
    for criterion in criteria:
        if criterion.affectedPaths contains file.path:
            linked.append(criterion)
        if fileContentMatches(file, criterion.keywords):
            linked.append(criterion)
    return unique(linked)

function promptForConfirmation(message):
    print("⚠️ " + message)
    print("Files outside scope:")
    for finding in findings where finding.type == "out-of-scope":
        print("  - " + finding.file)
    print("")
    print("Type 'yes' to continue or 'no' to abort:")
    # In automated mode, log and continue
```

---

## Output Format

### On Scope Warning
```
⚠️ SCOPE VALIDATION WARNING

Out-of-scope files:
  - src/unrelated/module.js (not in scope: src/auth/**)
  - tests/integration/other.test.js (not in scope)

Unlinked changes:
  - src/auth/utils.js (no acceptance criteria match)

Diff magnitude:
  - 347 lines changed (within limit of 500)

📋 Defined scope (from PLAN.md):
  - src/auth/**
  - tests/unit/auth/**

Proceed anyway? Document rationale if continuing.
```

### On Clean Check
```
✅ SCOPE VALIDATION PASSED

All changes within defined scope.
Linked to acceptance criteria: AC-001, AC-002
Diff size: 127 lines (within limit)
```

---

## Integration Notes

- Reads scope from PLAN.md (must exist)
- Warning-only mode by default (blocking optional)
- Supports glob patterns for path matching
- Logs all scope checks for audit trail
- Can be configured as blocking in strict mode
