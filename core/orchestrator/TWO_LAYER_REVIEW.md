# Two-Layer Review Checklist & Signoff Flow

Purpose: Formalize review requirements for high-risk work, define reviewer assignment rules, and standardize signoff workflows.

Related docs:
- `core/orchestrator/handoff/REVIEW_CHECKLIST.md` (review checklist)
- `core/orchestrator/handoff/REVIEW_CAPTURE.md` (review capture template)
- `core/orchestrator/AGENT_REGISTRY.md` (reviewer roles)
- `core/orchestrator/SECURITY_HARDENING.md` (security controls)
- `core/packs/policy-pack-v1/RISK_TRIGGERS.md` (risk triggers)

---

## Two-Layer Review Model

### Layer Definitions

| Layer | Name | Scope | Reviewers | Required For |
|-------|------|-------|-----------|--------------|
| **L1** | Technical Review | Code quality, correctness, tests | Peer agent or senior agent | All code changes |
| **L2** | Domain Review | Architecture, security, compliance | Domain expert or human | High-risk changes |

### Layer Assignment Matrix

| Risk Level | L1 Required | L2 Required | Approval Authority |
|------------|-------------|-------------|-------------------|
| **None** | No | No | Self-approve (auto-merge) |
| **Low** | Yes | No | L1 reviewer |
| **Medium** | Yes | Yes (agent) | L1 + L2 reviewers |
| **High** | Yes | Yes (human) | L1 + human L2 reviewer |
| **Critical** | Yes | Yes (human) | L1 + designated human approver |

### Risk Level Determination

Use the highest applicable risk level from this matrix:

| Trigger Category | Examples | Risk Level |
|------------------|----------|------------|
| Documentation only | README updates, comments | None |
| Config changes | Non-sensitive config | Low |
| Code changes (isolated) | Single module, good test coverage | Low |
| API changes (internal) | Internal interface changes | Medium |
| API changes (public) | Public interface changes | High |
| Security changes | Auth, crypto, permissions | High |
| Schema changes | Data model changes | High |
| Infrastructure changes | CI/CD, deployment | High |
| Prompt/agent changes | Agent behavior, prompts | High |
| Secrets handling | Token/credential changes | Critical |
| Production data access | Production DB, PII | Critical |

---

## Reviewer Assignment Rules

### Assignment Criteria

| Criterion | Rule | Rationale |
|-----------|------|-----------|
| **RA-01: Expertise match** | Reviewer has relevant capability | Domain knowledge required |
| **RA-02: Independence** | Reviewer is not the author | Objectivity required |
| **RA-03: Availability** | Reviewer can respond within SLA | Avoid blocking |
| **RA-04: Rotation** | Avoid same reviewer pairs repeatedly | Knowledge distribution |
| **RA-05: Escalation path** | Higher-risk requires senior reviewer | Risk-appropriate oversight |

### Reviewer Role Matrix

| Change Type | L1 Reviewer (Agent) | L2 Reviewer (Domain) |
|-------------|---------------------|----------------------|
| Code implementation | AGT-006 (Implementer) | AGT-003 (Architect) |
| Test changes | AGT-009 (Tester) | AGT-005 (QA/Reporter) |
| Documentation | AGT-007 (Documentation) | AGT-001 (Orchestrator) |
| Security changes | AGT-004 (Security) | Human (security team) |
| Architecture changes | AGT-003 (Architect) | Human (tech lead) |
| Refactoring | AGT-010 (Refactorer) | AGT-003 (Architect) |
| Bug fixes | AGT-008 (Debugger) | AGT-006 (Implementer) |
| Policy changes | AGT-001 (Orchestrator) | AGT-002 (Director) |

### Escalation Triggers

| Trigger | Action |
|---------|--------|
| L1 reviewer identifies security concern | Escalate to L2 Security Agent |
| L1 reviewer identifies architecture concern | Escalate to L2 Architect |
| L2 agent reviewer uncertain | Escalate to human reviewer |
| Any reviewer identifies critical risk | Block merge, escalate to human |
| Disagreement between reviewers | Escalate to Orchestrator or Director |

---

## Review Checklist by Layer

### L1 Technical Review Checklist

#### Code Quality (L1-CQ)

- [ ] **L1-CQ-01**: Code compiles/parses without errors
- [ ] **L1-CQ-02**: No syntax errors or obvious bugs
- [ ] **L1-CQ-03**: Code follows project style guidelines
- [ ] **L1-CQ-04**: No dead code or unused imports
- [ ] **L1-CQ-05**: Variable/function names are descriptive

#### Correctness (L1-CR)

- [ ] **L1-CR-01**: Logic implements the specified behavior
- [ ] **L1-CR-02**: Edge cases are handled
- [ ] **L1-CR-03**: Error handling is appropriate
- [ ] **L1-CR-04**: No off-by-one or boundary errors
- [ ] **L1-CR-05**: No race conditions or concurrency issues

#### Testing (L1-TS)

- [ ] **L1-TS-01**: Tests exist for new functionality
- [ ] **L1-TS-02**: Tests cover critical paths
- [ ] **L1-TS-03**: Tests are deterministic
- [ ] **L1-TS-04**: Existing tests still pass
- [ ] **L1-TS-05**: Test coverage is adequate

#### Scope (L1-SC)

- [ ] **L1-SC-01**: Changes match task scope
- [ ] **L1-SC-02**: No unrelated modifications
- [ ] **L1-SC-03**: Dependencies are intentional
- [ ] **L1-SC-04**: No scope creep

### L2 Domain Review Checklist

#### Architecture (L2-AR)

- [ ] **L2-AR-01**: Design aligns with architecture principles
- [ ] **L2-AR-02**: Interfaces are well-defined
- [ ] **L2-AR-03**: Dependencies are appropriate
- [ ] **L2-AR-04**: No unnecessary coupling
- [ ] **L2-AR-05**: Scalability considerations addressed

#### Security (L2-SE)

- [ ] **L2-SE-01**: No new vulnerabilities introduced
- [ ] **L2-SE-02**: Input validation is sufficient
- [ ] **L2-SE-03**: Output encoding is correct
- [ ] **L2-SE-04**: Authentication/authorization correct
- [ ] **L2-SE-05**: Secrets handling follows policy

#### Compliance (L2-CO)

- [ ] **L2-CO-01**: Follows project policies
- [ ] **L2-CO-02**: License compliance maintained
- [ ] **L2-CO-03**: Data handling compliant
- [ ] **L2-CO-04**: Audit trail maintained
- [ ] **L2-CO-05**: Documentation requirements met

#### Impact (L2-IM)

- [ ] **L2-IM-01**: Downstream impacts identified
- [ ] **L2-IM-02**: Breaking changes documented
- [ ] **L2-IM-03**: Migration path defined if needed
- [ ] **L2-IM-04**: Rollback procedure exists
- [ ] **L2-IM-05**: Stakeholders notified

---

## Signoff Flow

### Signoff States

| State | Description | Next States |
|-------|-------------|-------------|
| **DRAFT** | Work in progress, not ready for review | READY |
| **READY** | Ready for L1 review | L1_REVIEW |
| **L1_REVIEW** | L1 reviewer assigned and reviewing | L1_APPROVED, L1_CHANGES_REQUESTED |
| **L1_CHANGES_REQUESTED** | L1 found issues requiring fixes | DRAFT |
| **L1_APPROVED** | L1 approved, awaiting L2 (if required) | L2_REVIEW, APPROVED |
| **L2_REVIEW** | L2 reviewer assigned and reviewing | L2_APPROVED, L2_CHANGES_REQUESTED |
| **L2_CHANGES_REQUESTED** | L2 found issues requiring fixes | DRAFT |
| **L2_APPROVED** | L2 approved | APPROVED |
| **APPROVED** | All required reviews complete | MERGED |
| **MERGED** | Changes merged to target branch | - |

### Signoff Record Schema

```yaml
signoff_record:
  task_id: <task-identifier>
  branch: <branch-name>
  pr_number: <pr-number>

  risk_assessment:
    risk_level: <none|low|medium|high|critical>
    triggers_identified: [<trigger-list>]
    l1_required: <true|false>
    l2_required: <true|false>

  l1_review:
    reviewer_id: <agent-or-human-id>
    reviewer_role: <role-name>
    assigned_at: <ISO8601>
    completed_at: <ISO8601>
    decision: <approved|changes_requested|escalated>
    checklist_results:
      code_quality: <pass|fail|na>
      correctness: <pass|fail|na>
      testing: <pass|fail|na>
      scope: <pass|fail|na>
    issues_found: [<issue-list>]
    comments: <reviewer-notes>

  l2_review:
    reviewer_id: <agent-or-human-id>
    reviewer_role: <role-name>
    assigned_at: <ISO8601>
    completed_at: <ISO8601>
    decision: <approved|changes_requested|escalated>
    checklist_results:
      architecture: <pass|fail|na>
      security: <pass|fail|na>
      compliance: <pass|fail|na>
      impact: <pass|fail|na>
    issues_found: [<issue-list>]
    comments: <reviewer-notes>

  final_signoff:
    approved_by: <approver-id>
    approved_at: <ISO8601>
    approval_type: <l1_only|l1_l2_agent|l1_l2_human>
    conditions: [<any-merge-conditions>]

  evidence:
    verification_log_ref: <path-to-verification-entry>
    evidence_capture_ref: <path-to-evidence>
```

### Signoff Workflow Steps

#### Step 1: Risk Assessment

```
1. Author completes work and self-review
2. Author identifies applicable risk triggers
3. System determines risk level from triggers
4. System assigns required review layers
5. Author moves task to READY state
```

#### Step 2: L1 Assignment

```
1. Orchestrator receives READY task
2. Orchestrator selects L1 reviewer per assignment rules
3. Orchestrator notifies L1 reviewer
4. L1 reviewer has SLA to begin review (default: 4h)
5. Task moves to L1_REVIEW state
```

#### Step 3: L1 Review

```
1. L1 reviewer executes L1 checklist
2. L1 reviewer documents findings
3. L1 reviewer makes decision:
   - APPROVED: All checks pass
   - CHANGES_REQUESTED: Issues found
   - ESCALATED: Security/architecture concern
4. If approved and L2 required, move to L2_REVIEW
5. If approved and no L2 required, move to APPROVED
```

#### Step 4: L2 Assignment (if required)

```
1. Orchestrator receives L1_APPROVED task requiring L2
2. Orchestrator selects L2 reviewer per assignment rules
3. Orchestrator notifies L2 reviewer
4. L2 reviewer has SLA to begin review (default: 8h for agent, 24h for human)
5. Task moves to L2_REVIEW state
```

#### Step 5: L2 Review

```
1. L2 reviewer executes L2 checklist
2. L2 reviewer documents findings
3. L2 reviewer makes decision:
   - APPROVED: All checks pass
   - CHANGES_REQUESTED: Issues found
   - ESCALATED: Critical concern requiring human
4. If approved, move to APPROVED
```

#### Step 6: Merge

```
1. Final approver records signoff
2. System verifies all requirements met
3. Task moves to APPROVED state
4. Merge executed (manual or automated)
5. Task moves to MERGED state
6. Evidence captured in verification log
```

---

## Review SLAs

| Review Type | Initial Response | Complete Review | Escalation |
|-------------|------------------|-----------------|------------|
| L1 (agent) | 1h | 4h | After 4h |
| L2 (agent) | 2h | 8h | After 8h |
| L2 (human) | 4h | 24h | After 24h |
| Critical | 30m | 2h | After 2h |

### SLA Breach Handling

| Breach Type | Action |
|-------------|--------|
| Initial response missed | Auto-escalate to alternate reviewer |
| Review completion missed | Notify Orchestrator, consider reassignment |
| Critical review delayed | Escalate to Director and human stakeholder |

---

## Review Evidence Requirements

### Required Evidence by Risk Level

| Risk Level | L1 Evidence | L2 Evidence |
|------------|-------------|-------------|
| Low | Checklist completion | N/A |
| Medium | Checklist + comments | Checklist completion |
| High | Full checklist + diff review | Full checklist + written analysis |
| Critical | Full checklist + detailed notes | Written analysis + meeting notes |

### Evidence Artifacts

| Artifact | Location | Retention |
|----------|----------|-----------|
| Signoff record | `handoff/signoffs/<task-id>.yaml` | Permanent |
| Review comments | PR or task thread | Permanent |
| Checklist results | Signoff record | Permanent |
| Verification log entry | `core/arch/verification-log.md` | Permanent |
| Evidence capture | Session log | Permanent |

---

## Quick Reference

### When to Use Two-Layer Review

Use two-layer review when ANY of these apply:
- [ ] Security, auth, or crypto changes
- [ ] Public API or interface changes
- [ ] Schema or data model changes
- [ ] Infrastructure or deployment changes
- [ ] Agent behavior or prompt changes
- [ ] Any risk trigger requiring L2 per matrix

### Review Decision Tree

```
Is this a code/config change?
├─ No → Self-approve (None risk)
└─ Yes → Check risk triggers
         ├─ No triggers → L1 only (Low risk)
         └─ Has triggers → Check trigger severity
                          ├─ Internal/isolated → L1 + L2 agent (Medium)
                          ├─ External/security → L1 + L2 human (High)
                          └─ Secrets/prod → L1 + designated human (Critical)
```

---

## References

- Review checklist: `core/orchestrator/handoff/REVIEW_CHECKLIST.md`
- Review capture: `core/orchestrator/handoff/REVIEW_CAPTURE.md`
- Agent registry: `core/orchestrator/AGENT_REGISTRY.md`
- Risk triggers: `core/packs/policy-pack-v1/RISK_TRIGGERS.md`
- Security hardening: `core/orchestrator/SECURITY_HARDENING.md`
