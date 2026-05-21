# Tool Deprecation & Rollback Guidance

Purpose: Define procedures for deprecating tools and rolling back to previous versions when issues occur.

Related docs:
- `core/orchestrator/TOOL_REGISTRY_CHANGE_CONTROL.md` (change control checklists)
- `core/orchestrator/TOOL_GOVERNANCE.md` (allowlist policy and provenance)
- `core/packs/policy-pack-v1/RISK_TRIGGERS.md` (security risk triggers)

---

## Deprecation Workflow

### Phase 1: Deprecation Decision

| Step | Action | Output |
|------|--------|--------|
| 1.1 | **Identify deprecation trigger** | Document reason (security, obsolescence, replacement, cost) |
| 1.2 | **Impact assessment** | List all tasks, agents, and workflows using the tool |
| 1.3 | **Replacement evaluation** | Identify replacement tool or alternative approach |
| 1.4 | **Timeline proposal** | Define deprecation notice period and removal date |
| 1.5 | **Approval request** | Record decision in DECISIONS.md with rationale |

### Phase 2: Deprecation Notice

| Step | Action | Output |
|------|--------|--------|
| 2.1 | **Update tool status** | Set `status: deprecated` in registry entry |
| 2.2 | **Add deprecation metadata** | Include deprecation_date, removal_date, replacement_tool |
| 2.3 | **Document migration path** | Create migration guide if replacement exists |
| 2.4 | **Notify dependents** | Update TASKS with migration tasks for affected workflows |
| 2.5 | **Update documentation** | Add deprecation warnings to relevant docs |

### Phase 3: Migration Period

| Step | Action | Output |
|------|--------|--------|
| 3.1 | **Track migration progress** | Monitor migration tasks in TASKS.md |
| 3.2 | **Provide support** | Answer questions, resolve migration issues |
| 3.3 | **Verify migrations** | Confirm workflows work with replacement tool |
| 3.4 | **Update evidence** | Record successful migrations in verification log |
| 3.5 | **Extend if needed** | Extend deadline if critical migrations incomplete |

### Phase 4: Removal

| Step | Action | Output |
|------|--------|--------|
| 4.1 | **Final dependency check** | Confirm no active dependencies remain |
| 4.2 | **Set blocked status** | Update `status: blocked` in registry |
| 4.3 | **Remove from allowlist** | Delete or comment out allowlist entry |
| 4.4 | **Archive registry entry** | Move to archived tools section |
| 4.5 | **Final documentation** | Update docs to remove references |
| 4.6 | **Record completion** | Log removal in DECISIONS.md |

---

## Deprecation Entry Template

```yaml
tool_id: TL-XXX
name: <tool-name>
status: deprecated
deprecation:
  reason: <security|obsolescence|replacement|cost|other>
  decision_date: YYYY-MM-DD
  decision_ref: <link-to-DECISIONS-entry>
  notice_period: <N days/weeks>
  removal_date: YYYY-MM-DD
  replacement:
    tool_id: <replacement-tool-id>
    migration_guide: <link-to-guide>
  impact:
    - <affected-workflow-1>
    - <affected-workflow-2>
  migration_status: <pending|in_progress|complete>
```

---

## Rollback Guidance

### When to Rollback

| Trigger | Severity | Action |
|---------|----------|--------|
| **Security vulnerability** | Critical | Immediate rollback + block |
| **Breaking change** | High | Rollback within 24 hours |
| **Functionality regression** | Medium | Rollback within 1 week or hotfix |
| **Performance degradation** | Low | Evaluate and decide |
| **Compatibility issue** | Medium | Rollback or workaround |

### Rollback Prerequisites

Before rolling back, ensure:
- [ ] Previous version is available and verified
- [ ] Previous version provenance is still valid
- [ ] Rollback will not introduce known vulnerabilities
- [ ] Dependent workflows can tolerate version change
- [ ] Rollback plan is documented and approved

---

## Rollback Procedures

### RB-01: Immediate Rollback (Critical)

**Use when**: Security vulnerability, data corruption risk, or system instability.

| Step | Action | Time |
|------|--------|------|
| 1 | **Block current version** | Immediately |
| 2 | **Notify stakeholders** | Within 15 minutes |
| 3 | **Restore previous version** | Within 1 hour |
| 4 | **Verify functionality** | Within 2 hours |
| 5 | **Document incident** | Within 24 hours |

```bash
# Example: Rollback git to previous version
# 1. Identify previous version
git log --oneline -5

# 2. Verify previous version provenance
# (check checksums, signatures)

# 3. Revert or pin to previous version
# (method depends on package manager)

# 4. Verify rollback
git --version
```

### RB-02: Planned Rollback (Non-Critical)

**Use when**: Regression discovered during testing or gradual issues.

| Step | Action | Time |
|------|--------|------|
| 1 | **Document issue** | Same day |
| 2 | **Create rollback task** | Same day |
| 3 | **Test previous version** | 1-2 days |
| 4 | **Schedule rollback** | As planned |
| 5 | **Execute rollback** | Per schedule |
| 6 | **Verify and document** | Same day |

### RB-03: Partial Rollback (Scope-Limited)

**Use when**: Issue affects only specific functionality or workflows.

| Step | Action | Notes |
|------|--------|-------|
| 1 | **Identify affected scope** | Which commands/features are broken |
| 2 | **Restrict tool scope** | Update allowlist to exclude broken features |
| 3 | **Document workaround** | Provide alternative for affected workflows |
| 4 | **Monitor for fix** | Track upstream fix availability |
| 5 | **Restore scope** | Re-enable when fixed version available |

---

## Rollback Checklist

### Pre-Rollback

- [ ] Issue documented with reproduction steps
- [ ] Previous version identified and verified
- [ ] Rollback approved (if non-critical, record in TASKS)
- [ ] Stakeholders notified
- [ ] Rollback steps reviewed

### During Rollback

- [ ] Current version blocked or removed
- [ ] Previous version installed/restored
- [ ] Configuration restored (if needed)
- [ ] Basic functionality verified
- [ ] Dependent workflows tested

### Post-Rollback

- [ ] Full verification completed
- [ ] Registry entry updated (version, status, notes)
- [ ] Incident documented in DECISIONS.md
- [ ] Root cause analysis initiated (if needed)
- [ ] Upstream issue reported (if applicable)
- [ ] Next steps defined (fix, alternative, permanent rollback)

---

## Rollback Evidence Template

```markdown
## Rollback Record: <tool-name> <version>

### Trigger
- **Date**: YYYY-MM-DD
- **Severity**: Critical/High/Medium/Low
- **Issue**: <brief description>
- **Impact**: <affected workflows>

### Rollback Details
- **From version**: <problematic-version>
- **To version**: <rollback-version>
- **Method**: <package manager/manual/container>
- **Executed by**: <agent or human>
- **Execution time**: <duration>

### Verification
- **Functionality check**: PASS/FAIL
- **Workflow tests**: PASS/FAIL
- **Evidence**: <link to verification log>

### Follow-up
- **Root cause**: <known/investigating/unknown>
- **Upstream issue**: <link if reported>
- **Permanent fix ETA**: <date or TBD>
- **Next review**: YYYY-MM-DD
```

---

## Version Pinning Strategy

### Pinning Levels

| Level | Description | Use Case |
|-------|-------------|----------|
| **Exact** | `1.2.3` | Critical tools, security-sensitive |
| **Patch** | `1.2.x` or `~1.2.3` | Stable tools, allow bug fixes |
| **Minor** | `1.x` or `^1.2.3` | Flexible tools, allow features |
| **Latest** | `*` | Not recommended for production |

### Recommended Pinning

| Tool Category | Pinning Level | Review Cadence |
|---------------|---------------|----------------|
| Security tools | Exact | Monthly |
| Build tools | Patch | Quarterly |
| Dev tools | Minor | Quarterly |
| Optional tools | Minor | Semi-annually |

---

## Rollback Testing

### Periodic Rollback Drills

To ensure rollback procedures work:

1. **Schedule**: Quarterly rollback drill for critical tools
2. **Scope**: Test rollback of one tool per drill
3. **Execute**: Follow RB-02 procedure in test environment
4. **Verify**: Confirm rollback completes successfully
5. **Document**: Record drill results and improvements

### Drill Checklist

- [ ] Drill scheduled and announced
- [ ] Test environment prepared
- [ ] Previous version cached/available
- [ ] Rollback executed per procedure
- [ ] Functionality verified
- [ ] Timing recorded
- [ ] Issues documented
- [ ] Procedure updated if needed

---

## References

- Change control checklists: `core/orchestrator/TOOL_REGISTRY_CHANGE_CONTROL.md`
- Tool governance: `core/orchestrator/TOOL_GOVERNANCE.md`
- Risk triggers: `core/packs/policy-pack-v1/RISK_TRIGGERS.md`
- Evidence capture: `core/orchestrator/handoff/EVIDENCE_CAPTURE.md`
- Decisions log: `core/orchestrator/handoff/DECISIONS.md`
