# Regression Gates & Triage Playbook

Purpose: Define gating thresholds for agent performance, tag golden tasks for enforcement, and provide a playbook for triaging regressions.

Related docs:
- `core/arch/evaluation-harness.md` (golden tasks, metrics, playbook)
- `core/orchestrator/TRACE_SCHEMA.md` (failure taxonomy)
- `core/arch/verification-log.md` (verification entries)
- `core/orchestrator/TWO_LAYER_REVIEW.md` (review signoff)

---

## Regression Gate Model

### Gate Types

| Gate | Trigger Point | Blocking | Owner |
|------|--------------|----------|-------|
| **G-PR** | Pull request submission | Yes | Orchestrator |
| **G-MRG** | Pre-merge validation | Yes | Reviewer |
| **G-REL** | Pre-release check | Yes | Director |
| **G-MON** | Continuous monitoring | No | QA Agent |

### Gate Hierarchy

```
G-MON (Continuous)
    ↓ alert
G-PR (PR Gate)
    ↓ pass
G-MRG (Merge Gate)
    ↓ pass
G-REL (Release Gate)
    ↓ pass
DEPLOYED
```

---

## Gating Thresholds

### Version: 1.0.0

| Metric | Gate | Threshold | Action on Breach |
|--------|------|-----------|------------------|
| **M-01: Success Rate** | G-PR | ≥ 80% | Block PR |
| **M-01: Success Rate** | G-MRG | ≥ 90% | Block merge |
| **M-01: Success Rate** | G-REL | ≥ 95% | Block release |
| **M-03: Rework Rate** | G-PR | ≤ 30% | Warn |
| **M-03: Rework Rate** | G-MRG | ≤ 20% | Block merge |
| **M-03: Rework Rate** | G-REL | ≤ 10% | Block release |
| **M-05: Scope Adherence** | G-PR | ≥ 90% | Block PR |
| **M-05: Scope Adherence** | G-MRG | = 100% | Block merge |
| **Golden Tasks Pass** | G-MRG | All critical | Block merge |
| **Golden Tasks Pass** | G-REL | All | Block release |

### Threshold Schema

```yaml
threshold:
  threshold_id: <unique-id>
  version: <semver>
  effective_date: <ISO8601>

  metric:
    id: <M-01|M-02|M-03|M-04|M-05>
    name: <metric-name>

  gates:
    - gate: <G-PR|G-MRG|G-REL|G-MON>
      operator: <gte|lte|eq|gt|lt>
      value: <threshold-value>
      action: <block|warn|alert>
      bypass_allowed: <true|false>
      bypass_approver: <role-or-human>

  metadata:
    owner: <threshold-owner>
    rationale: <why-this-threshold>
    review_cadence: <quarterly|monthly|on-change>
    last_reviewed: <ISO8601>
```

### Threshold Bypass Rules

| Condition | Bypass Allowed | Approver Required |
|-----------|---------------|-------------------|
| Critical hotfix | Yes | Director + Human |
| Known flaky test | Yes | QA Agent |
| Dependency blocker | Yes | Architect |
| Schedule pressure | No | - |
| Convenience | No | - |

---

## Golden Task Gating Tags

### Tag Definitions

| Tag | Description | Gate Level |
|-----|-------------|------------|
| **GT-CRITICAL** | Must pass for any merge | G-MRG |
| **GT-RELEASE** | Must pass for release | G-REL |
| **GT-SMOKE** | Quick sanity check | G-PR |
| **GT-REGRESSION** | Historical failure area | G-MRG |
| **GT-OPTIONAL** | Nice-to-have validation | G-MON |

### Golden Task Registry with Tags

| Task | Name | Tags | Owner | Last Validated |
|------|------|------|-------|----------------|
| GT-01 | Documentation-Only Task | GT-SMOKE, GT-CRITICAL | Documentation Agent | - |
| GT-02 | Task Queue Update | GT-CRITICAL | Orchestrator | - |
| GT-03 | Cross-Reference Validation | GT-RELEASE | QA Agent | - |
| GT-04 | Template Instantiation | GT-SMOKE, GT-RELEASE | Documentation Agent | - |
| GT-05 | Scope Lock Enforcement | GT-CRITICAL, GT-REGRESSION | Orchestrator | - |
| GT-06 | Evidence Capture Workflow | GT-CRITICAL | QA Agent | - |
| GT-07 | Multi-File Coordinated Update | GT-RELEASE, GT-REGRESSION | Architect | - |

### Golden Case Registry with Tags

| Case | Name | Tags | Owner | Last Validated |
|------|------|------|-------|----------------|
| GC-01 | Clean Single-File PR | GT-SMOKE | Reviewer | - |
| GC-02 | Multi-File Consistency PR | GT-CRITICAL, GT-RELEASE | Architect | - |
| GC-03 | Out-of-Scope PR Rejection | GT-CRITICAL, GT-REGRESSION | Orchestrator | - |
| GC-04 | Rework-Required PR | GT-RELEASE | Reviewer | - |

### Gate Execution Matrix

| Gate | Required Tags | Execution |
|------|--------------|-----------|
| G-PR | GT-SMOKE | All smoke tasks must pass |
| G-MRG | GT-CRITICAL | All critical tasks must pass |
| G-REL | GT-RELEASE | All release tasks must pass |
| G-MON | GT-OPTIONAL | Tracked but non-blocking |

---

## Regression Detection

### Regression Indicators

| Indicator | Description | Severity |
|-----------|-------------|----------|
| **RI-01** | Previously passing task now fails | High |
| **RI-02** | Metric drops below threshold | Medium |
| **RI-03** | New failure category appears | Medium |
| **RI-04** | Time-to-green increases significantly | Low |
| **RI-05** | Flaky test becomes consistent failure | High |

### Regression Record Schema

```yaml
regression:
  regression_id: <unique-id>
  detected_at: <ISO8601>
  detected_by: <agent-or-system>

  indicator:
    type: <RI-01|RI-02|RI-03|RI-04|RI-05>
    description: <what-was-detected>

  baseline:
    metric: <metric-id>
    previous_value: <value>
    current_value: <value>
    threshold: <threshold-value>

  affected:
    tasks: [<task-ids>]
    tests: [<test-ids>]
    commits: [<commit-hashes>]

  classification:
    severity: <low|medium|high|critical>
    category: <F-XXX from failure taxonomy>
    root_cause: <identified|investigating|unknown>

  triage:
    status: <new|investigating|identified|fixing|resolved|wontfix>
    assignee: <agent-or-human>
    eta: <optional-estimated-resolution>

  resolution:
    resolved_at: <ISO8601>
    resolved_by: <agent-or-human>
    fix_commit: <commit-hash>
    post_mortem_ref: <optional-path>
```

---

## Triage Playbook

### Step 1: Detection and Logging

**Trigger**: Gate failure or monitoring alert

**Actions**:
1. Create regression record with detected indicator
2. Capture immediate context:
   - Failing task/test output
   - Recent commits since last green
   - Environment details
3. Assign initial severity based on indicator type
4. Log in `core/arch/regression-log.md`

**Template**:
```markdown
## Regression: REG-YYYYMMDD-XXXX

- **Detected**: YYYY-MM-DD HH:MM
- **Indicator**: RI-XX
- **Severity**: [low|medium|high|critical]
- **Status**: new
- **Assignee**: [pending]

### Observation
[What failed and how it was detected]

### Context
- Last green commit: [hash]
- First failing commit: [hash]
- Commits in range: [count]
```

### Step 2: Initial Assessment

**Goal**: Determine scope and urgency

**Actions**:
1. Check if failure is flaky (re-run 2x)
2. Identify affected gates (G-PR, G-MRG, G-REL)
3. Check for related recent changes
4. Update severity if needed

**Assessment Questions**:
| Question | Answer Options | Impact |
|----------|----------------|--------|
| Is it reproducible? | Yes/No/Flaky | Determines investigation priority |
| Which gates blocked? | List gates | Determines urgency |
| How many tasks affected? | Count | Determines scope |
| Is there a workaround? | Yes/No | Determines blocking impact |

### Step 3: Root Cause Investigation

**Goal**: Identify the cause of regression

**Actions**:
1. Review commits in failure range
2. Check for environment changes
3. Review recent configuration changes
4. Examine failure taxonomy for category

**Investigation Checklist**:
- [ ] Reviewed commit diff for suspicious changes
- [ ] Checked for dependency updates
- [ ] Verified environment consistency
- [ ] Compared failing vs passing trace logs
- [ ] Identified failure category (F-XXX)

**Root Cause Categories**:
| Category | Examples | Typical Fix |
|----------|----------|-------------|
| Code change | Bug in new code | Revert or fix |
| Config change | Bad configuration | Restore config |
| Dependency | Updated dependency | Pin or update |
| Environment | Missing tool/permission | Fix environment |
| Test issue | Flaky or outdated test | Fix test |
| Data issue | Bad test data | Fix data |

### Step 4: Resolution Planning

**Goal**: Define fix approach

**Actions**:
1. Determine fix strategy:
   - Revert: Quick, safe, for clear regressions
   - Forward fix: When revert is complex
   - Test fix: When test is wrong
   - Configuration fix: When config is wrong
2. Estimate effort and timeline
3. Assign to appropriate agent/human
4. Update regression record

**Resolution Strategies**:
| Strategy | When to Use | Risk |
|----------|-------------|------|
| Revert | Clear regression from recent commit | Low |
| Forward fix | Complex to revert, fix is small | Medium |
| Skip/Disable | Flaky test, non-critical | Medium |
| Defer | Low priority, no immediate impact | Low |

### Step 5: Fix Implementation

**Goal**: Resolve the regression

**Actions**:
1. Implement chosen fix strategy
2. Verify fix locally (re-run failing tasks)
3. Create PR with fix
4. Reference regression record in PR

**Fix PR Requirements**:
- [ ] References regression ID
- [ ] Includes evidence of fix (task now passes)
- [ ] No new regressions introduced
- [ ] Reviewed by appropriate agent

### Step 6: Verification and Closure

**Goal**: Confirm resolution and prevent recurrence

**Actions**:
1. Verify fix in CI/gate context
2. Confirm all affected tasks pass
3. Update regression record to resolved
4. Document lessons learned

**Closure Checklist**:
- [ ] All affected tasks pass
- [ ] Gates unblocked
- [ ] Regression record updated
- [ ] Post-mortem written (if high/critical)
- [ ] Prevention measures identified

### Step 7: Post-Mortem (for High/Critical)

**Goal**: Learn and prevent recurrence

**Template**:
```markdown
## Post-Mortem: REG-YYYYMMDD-XXXX

### Timeline
- [time] Regression introduced by commit [hash]
- [time] Regression detected by [gate/monitor]
- [time] Investigation started
- [time] Root cause identified
- [time] Fix deployed
- [time] Verified and closed

### Root Cause
[Detailed explanation of what caused the regression]

### Impact
- Gates blocked: [list]
- Duration: [time]
- Tasks affected: [list]

### Resolution
[What was done to fix it]

### Prevention
- [ ] [Action item 1]
- [ ] [Action item 2]

### Lessons Learned
[What we learned from this incident]
```

---

## Regression Severity Matrix

| Severity | Criteria | Response Time | Escalation |
|----------|----------|---------------|------------|
| **Critical** | Release gate blocked, multiple critical tasks fail | 1 hour | Immediate to Director |
| **High** | Merge gate blocked, critical task fails | 4 hours | QA Agent + Architect |
| **Medium** | PR gate blocked, non-critical failures | 1 day | QA Agent |
| **Low** | Monitoring alert, optional task fails | 1 week | Logged only |

---

## Gate Enforcement Workflow

### PR Gate (G-PR)

```
1. PR submitted
2. Run GT-SMOKE tasks
3. Calculate M-01, M-05
4. Check thresholds:
   - M-01 ≥ 80%? → Continue
   - M-05 ≥ 90%? → Continue
   - Both pass? → PR gate PASS
   - Either fail? → PR gate FAIL, block PR
```

### Merge Gate (G-MRG)

```
1. PR approved by reviewers
2. Run GT-CRITICAL tasks
3. Calculate M-01, M-03, M-05
4. Check thresholds:
   - M-01 ≥ 90%? → Continue
   - M-03 ≤ 20%? → Continue
   - M-05 = 100%? → Continue
   - All critical tasks pass? → Continue
   - All pass? → Merge gate PASS
   - Any fail? → Merge gate FAIL, block merge
```

### Release Gate (G-REL)

```
1. Release candidate ready
2. Run ALL golden tasks (GT-SMOKE + GT-CRITICAL + GT-RELEASE)
3. Calculate all metrics
4. Check thresholds:
   - M-01 ≥ 95%? → Continue
   - M-03 ≤ 10%? → Continue
   - All golden tasks pass? → Continue
   - All pass? → Release gate PASS
   - Any fail? → Release gate FAIL, block release
```

---

## Quick Reference

### Gate Thresholds Summary

| Metric | G-PR | G-MRG | G-REL |
|--------|------|-------|-------|
| Success Rate (M-01) | ≥ 80% | ≥ 90% | ≥ 95% |
| Rework Rate (M-03) | ≤ 30% (warn) | ≤ 20% | ≤ 10% |
| Scope Adherence (M-05) | ≥ 90% | = 100% | = 100% |
| Critical Tasks | - | All pass | All pass |
| All Tasks | - | - | All pass |

### Triage Quick Steps

1. **Detect**: Log regression, assign severity
2. **Assess**: Reproducible? Scope? Workaround?
3. **Investigate**: Find root cause (check commits, config, deps)
4. **Plan**: Choose strategy (revert, fix, skip, defer)
5. **Fix**: Implement and verify
6. **Close**: Update records, post-mortem if needed

### Severity Quick Guide

| Impact | Gates Blocked | Severity |
|--------|--------------|----------|
| Release blocked | G-REL | Critical |
| Merge blocked | G-MRG | High |
| PR blocked | G-PR | Medium |
| Alert only | G-MON | Low |

---

## References

- Evaluation harness: `core/arch/evaluation-harness.md`
- Failure taxonomy: `core/orchestrator/TRACE_SCHEMA.md`
- Verification log: `core/arch/verification-log.md`
- Two-layer review: `core/orchestrator/TWO_LAYER_REVIEW.md`
