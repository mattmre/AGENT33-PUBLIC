# Release Cadence & Sync Automation

Purpose: Define release cadence, versioning strategy, sync automation with dry-run steps, and rollback procedures.

Related docs:
- `core/orchestrator/TOOL_DEPRECATION_ROLLBACK.md` (tool rollback procedures)
- `core/arch/REGRESSION_GATES.md` (release gates)
- `core/orchestrator/TWO_LAYER_REVIEW.md` (review signoff)
- `core/orchestrator/TRACE_SCHEMA.md` (artifact retention)

---

## Release Cadence

### Cadence Types

| Type | Frequency | Scope | Gate Required |
|------|-----------|-------|---------------|
| **Patch** | As needed | Bug fixes, doc updates | G-MRG |
| **Minor** | Bi-weekly | New features, enhancements | G-REL |
| **Major** | Quarterly | Breaking changes, major features | G-REL + Human |

### Release Schedule

```
Week 1: Development sprint
  - Feature work, bug fixes
  - PR reviews and merges

Week 2: Stabilization
  - Mon-Wed: Final PRs, regression testing
  - Thu: Release candidate cut
  - Fri: Release (if gates pass)

Patch releases: Any time gates pass
Major releases: End of quarter (Q1=Mar, Q2=Jun, Q3=Sep, Q4=Dec)
```

### Release Calendar Template

```yaml
release_calendar:
  year: <YYYY>

  minor_releases:
    - version: <X.Y.0>
      rc_date: <YYYY-MM-DD>
      release_date: <YYYY-MM-DD>
      status: <planned|rc|released|skipped>

  major_releases:
    - version: <X.0.0>
      quarter: <Q1|Q2|Q3|Q4>
      planned_date: <YYYY-MM-DD>
      status: <planned|rc|released|delayed>

  patch_releases:
    - version: <X.Y.Z>
      release_date: <YYYY-MM-DD>
      hotfix: <true|false>
```

---

## Versioning Strategy

### Semantic Versioning

```
MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]

Examples:
1.0.0        - Initial stable release
1.1.0        - Minor feature release
1.1.1        - Patch release (bug fix)
2.0.0        - Major release (breaking changes)
1.2.0-rc.1   - Release candidate
1.2.0-beta.1 - Beta release
```

### Version Bump Rules

| Change Type | Version Bump | Examples |
|-------------|--------------|----------|
| Breaking API change | Major | Removed field, renamed method |
| New feature | Minor | New command, new capability |
| Bug fix | Patch | Error correction, typo fix |
| Documentation | Patch | README update, new examples |
| Security fix | Patch (urgent) | Vulnerability patch |

### Pre-release Tags

| Tag | Stability | Audience |
|-----|-----------|----------|
| `alpha` | Unstable | Internal testing |
| `beta` | Feature complete | Early adopters |
| `rc` | Release candidate | Final validation |

---

## Release Process

### Pre-Release Checklist

| Check | ID | Validation | Required |
|-------|----|-----------:|----------|
| All PRs merged | RL-01 | No open PRs for release | Yes |
| Gates pass | RL-02 | G-REL gate passes | Yes |
| Changelog updated | RL-03 | CHANGELOG.md current | Yes |
| Version bumped | RL-04 | Version in manifest | Yes |
| Documentation updated | RL-05 | Docs match release | Yes |
| Security review | RL-06 | No known vulnerabilities | Yes |
| Rollback tested | RL-07 | Rollback procedure verified | Major only |
| Release notes drafted | RL-08 | Notes ready for review | Yes |

### Release Workflow

```
1. Feature Freeze
   - No new features after freeze date
   - Only bug fixes and documentation
   ↓
2. Release Candidate
   - Cut RC branch: release/vX.Y.Z-rc.1
   - Run full regression suite
   - Fix any blockers
   ↓
3. Release Validation
   - All gates must pass (G-REL)
   - Final review signoff
   - Release notes approved
   ↓
4. Release Execution
   - Tag release: vX.Y.Z
   - Build release artifacts
   - Publish to distribution channels
   ↓
5. Post-Release
   - Announce release
   - Monitor for issues
   - Update documentation
```

### Release Evidence Template

```yaml
release_evidence:
  version: <X.Y.Z>
  release_date: <ISO8601>
  released_by: <releaser>

  validation:
    gate_results:
      g_rel_passed: <true|false>
      success_rate: <percentage>
      rework_rate: <percentage>
      all_tasks_passed: <true|false>

    checklist:
      - check: RL-01
        status: <pass|fail|na>
      # ... all checks

  artifacts:
    changelog_ref: <path>
    release_notes_ref: <path>
    verification_log_ref: <path>

  provenance:
    commit: <commit-hash>
    branch: <release-branch>
    build_id: <build-identifier>
    signed_by: <signer>

  distribution:
    channels: [<channel-list>]
    published_at: <ISO8601>
```

---

## Sync Automation

### Sync Types

| Type | Description | Frequency |
|------|-------------|-----------|
| **Upstream sync** | Pull from upstream source | On release |
| **Downstream sync** | Push to distribution | On release |
| **Cross-repo sync** | Sync between related repos | As needed |
| **Config sync** | Sync configuration/policies | On change |

### Sync Workflow

```
1. Pre-Sync Validation
   ├─ Check source availability
   ├─ Validate credentials
   └─ Verify target state
   ↓
2. Dry-Run (REQUIRED)
   ├─ Execute sync in preview mode
   ├─ Generate diff report
   └─ Validate expected changes
   ↓
3. Approval Gate
   ├─ Review dry-run results
   ├─ Approve or reject
   └─ Document decision
   ↓
4. Execute Sync
   ├─ Apply changes
   ├─ Capture evidence
   └─ Verify completion
   ↓
5. Post-Sync Validation
   ├─ Run smoke tests
   ├─ Verify integrity
   └─ Update sync log
```

### Dry-Run Requirements

| Requirement | Description |
|-------------|-------------|
| **DR-01** | All syncs MUST have dry-run before execution |
| **DR-02** | Dry-run output MUST be human-readable |
| **DR-03** | Dry-run MUST show all changes (add/modify/delete) |
| **DR-04** | Dry-run MUST NOT modify target state |
| **DR-05** | Dry-run results MUST be logged |
| **DR-06** | Approval MUST reference dry-run evidence |

### Sync Configuration Schema

```yaml
sync_config:
  sync_id: <unique-id>
  name: <sync-name>
  type: <upstream|downstream|cross_repo|config>

  source:
    type: <git|api|file|registry>
    location: <source-url-or-path>
    branch: <optional-branch>
    credentials: <credential-ref>

  target:
    type: <git|api|file|registry>
    location: <target-url-or-path>
    branch: <optional-branch>
    credentials: <credential-ref>

  options:
    dry_run_required: true  # Always true
    approval_required: <true|false>
    approver: <role-or-human>
    conflict_strategy: <fail|theirs|ours|merge>

  filters:
    include: [<patterns>]
    exclude: [<patterns>]

  schedule:
    trigger: <manual|on_release|cron>
    cron: <optional-cron-expression>

  notifications:
    on_success: [<notification-targets>]
    on_failure: [<notification-targets>]
```

### Sync Log Schema

```yaml
sync_log:
  sync_id: <sync-config-id>
  execution_id: <unique-execution-id>
  executed_at: <ISO8601>
  executed_by: <agent-or-human>

  dry_run:
    executed_at: <ISO8601>
    result:
      files_to_add: <count>
      files_to_modify: <count>
      files_to_delete: <count>
      total_changes: <count>
    diff_summary: <text-summary>
    diff_ref: <path-to-full-diff>

  approval:
    approved: <true|false>
    approved_by: <approver>
    approved_at: <ISO8601>
    dry_run_ref: <reference-to-dry-run>

  execution:
    started_at: <ISO8601>
    completed_at: <ISO8601>
    status: <success|partial|failed>
    changes_applied:
      added: <count>
      modified: <count>
      deleted: <count>
    errors: [<error-list>]

  verification:
    smoke_tests_passed: <true|false>
    integrity_verified: <true|false>
    notes: <optional-notes>
```

---

## Rollback Procedures

### Rollback Types

| Type | Scope | Trigger | Speed |
|------|-------|---------|-------|
| **Immediate** | Full release | Critical bug, security | Minutes |
| **Planned** | Full release | Non-critical issues | Hours |
| **Partial** | Specific components | Component failure | Minutes |
| **Config** | Configuration only | Config error | Minutes |

### Rollback Decision Matrix

| Issue Severity | User Impact | Rollback Type | Approval |
|----------------|-------------|---------------|----------|
| Critical | Widespread | Immediate | Post-hoc |
| High | Significant | Immediate/Planned | Director |
| Medium | Limited | Planned | Orchestrator |
| Low | Minimal | Defer/Fix forward | QA Agent |

### Rollback Procedure: Immediate (RB-IMM)

```
1. DETECT: Critical issue identified
   - Severity confirmed
   - Impact assessed
   ↓
2. DECIDE: Rollback decision (< 5 minutes)
   - Can be reversed by any senior agent
   - Document decision immediately
   ↓
3. EXECUTE: Revert to previous version
   - git revert or tag checkout
   - Redeploy previous artifacts
   ↓
4. VERIFY: Confirm rollback success
   - Smoke tests pass
   - Issue no longer present
   ↓
5. COMMUNICATE: Notify stakeholders
   - Incident channel
   - Status update
   ↓
6. DOCUMENT: Post-rollback
   - Rollback evidence
   - Root cause analysis
   - Prevention actions
```

### Rollback Procedure: Planned (RB-PLN)

```
1. ASSESS: Issue analysis
   - Severity and impact documented
   - Alternatives evaluated
   - Rollback plan drafted
   ↓
2. APPROVE: Get rollback approval
   - Orchestrator or Director approval
   - Scheduled time agreed
   ↓
3. PREPARE: Pre-rollback steps
   - Notify affected users
   - Backup current state
   - Prepare rollback artifacts
   ↓
4. EXECUTE: Perform rollback
   - Follow rollback checklist
   - Monitor during rollback
   ↓
5. VERIFY: Confirm success
   - Full regression suite
   - User acceptance
   ↓
6. CLOSE: Documentation
   - Evidence captured
   - Lessons learned
```

### Rollback Checklist

**Pre-Rollback**:
- [ ] Issue documented with severity
- [ ] Rollback decision approved
- [ ] Previous version identified and available
- [ ] Backup of current state created
- [ ] Stakeholders notified
- [ ] Rollback window scheduled (if planned)

**During Rollback**:
- [ ] Rollback command executed
- [ ] Progress monitored
- [ ] No unexpected errors
- [ ] Artifacts reverted correctly

**Post-Rollback**:
- [ ] Smoke tests pass
- [ ] Original issue resolved
- [ ] No new issues introduced
- [ ] Stakeholders updated
- [ ] Evidence captured
- [ ] Root cause documented

### Rollback Evidence Template

```yaml
rollback_evidence:
  rollback_id: <unique-id>
  type: <immediate|planned|partial|config>

  trigger:
    issue_id: <issue-reference>
    severity: <critical|high|medium|low>
    description: <what-triggered-rollback>
    detected_at: <ISO8601>
    detected_by: <agent-or-human>

  versions:
    rolled_back_from: <version>
    rolled_back_to: <version>

  execution:
    decided_at: <ISO8601>
    decided_by: <approver>
    executed_at: <ISO8601>
    executed_by: <executor>
    duration_minutes: <minutes>

  verification:
    smoke_tests: <pass|fail>
    issue_resolved: <true|false>
    new_issues: [<any-new-issues>]

  follow_up:
    root_cause: <cause-description>
    prevention: [<action-items>]
    post_mortem_ref: <optional-path>
```

---

## Release Notes

### Release Notes Template

```markdown
# Release Notes: vX.Y.Z

**Release Date**: YYYY-MM-DD
**Release Type**: Major | Minor | Patch

## Highlights
- [Brief summary of key changes]

## New Features
- **Feature Name**: Description of feature
  - Detail 1
  - Detail 2

## Improvements
- **Area**: Description of improvement

## Bug Fixes
- **Issue #XXX**: Description of fix

## Breaking Changes
- **Change**: Description and migration path

## Deprecations
- **Deprecated**: What's deprecated and timeline

## Security
- **CVE-XXXX**: Description and remediation

## Known Issues
- **Issue**: Description and workaround

## Upgrade Notes
- Steps for upgrading from previous version

## Contributors
- @contributor1, @contributor2

## Provenance
- Commit: [hash]
- Build: [build-id]
- Signed: [signature-info]
```

### Release Notes Schema

```yaml
release_notes:
  version: <X.Y.Z>
  release_date: <YYYY-MM-DD>
  release_type: <major|minor|patch>

  highlights: [<summary-items>]

  changes:
    features:
      - title: <feature-name>
        description: <description>
        pr_ref: <optional-pr>
    improvements:
      - title: <improvement-name>
        description: <description>
    bug_fixes:
      - issue_ref: <issue-id>
        description: <description>
    breaking_changes:
      - title: <change-name>
        description: <description>
        migration: <migration-steps>
    deprecations:
      - item: <deprecated-item>
        timeline: <removal-version>
        replacement: <optional-replacement>
    security:
      - cve: <CVE-id>
        severity: <critical|high|medium|low>
        description: <description>

  known_issues:
    - issue: <description>
      workaround: <optional-workaround>

  upgrade_notes: <upgrade-instructions>

  contributors: [<contributor-list>]

  provenance:
    commit: <hash>
    build_id: <id>
    signed_by: <signer>
```

---

## Quick Reference

### Release Checklist Summary

- [ ] RL-01: All PRs merged
- [ ] RL-02: G-REL gate passes
- [ ] RL-03: CHANGELOG updated
- [ ] RL-04: Version bumped
- [ ] RL-05: Docs updated
- [ ] RL-06: Security reviewed
- [ ] RL-07: Rollback tested (major)
- [ ] RL-08: Release notes ready

### Sync Checklist Summary

- [ ] Dry-run executed
- [ ] Dry-run results reviewed
- [ ] Changes approved
- [ ] Sync executed
- [ ] Smoke tests pass
- [ ] Sync log updated

### Rollback Decision Quick Guide

| Severity | Impact | Action |
|----------|--------|--------|
| Critical | Any | Immediate rollback |
| High | Widespread | Immediate rollback |
| High | Limited | Planned rollback |
| Medium | Any | Planned rollback or fix |
| Low | Any | Fix forward |

---

## References

- Tool rollback: `core/orchestrator/TOOL_DEPRECATION_ROLLBACK.md`
- Regression gates: `core/arch/REGRESSION_GATES.md`
- Two-layer review: `core/orchestrator/TWO_LAYER_REVIEW.md`
- Artifact retention: `core/orchestrator/TRACE_SCHEMA.md`
