# Continuous Improvement & Research Intake

Purpose: Define research intake, roadmap refresh cadence, and continuous improvement processes for the agentic orchestration framework.

Related docs:
- `core/orchestrator/REVIEW_INTAKE.md` (PR review intake)
- `core/orchestrator/RELEASE_CADENCE.md` (release process)
- `core/arch/REGRESSION_GATES.md` (quality gates)
- `core/orchestrator/handoff/TASKS.md` (task tracking)

---

## Research Intake

### Research Types

| Type | Description | Frequency | Owner |
|------|-------------|-----------|-------|
| **External** | Industry trends, papers, tools | Quarterly | Researcher Agent |
| **Internal** | Lessons learned, retrospectives | Per release | Orchestrator |
| **Competitive** | Competitor analysis, benchmarks | Semi-annual | Researcher Agent |
| **User** | Feedback, feature requests | Continuous | Product Owner |
| **Technical** | Architecture, performance | As needed | Architect Agent |

### Research Intake Template

```yaml
research_intake:
  intake_id: RI-<YYYY>-<NNN>
  submitted_at: <ISO8601>
  submitted_by: <agent-or-human>

  classification:
    type: <external|internal|competitive|user|technical>
    category: <category-tag>
    urgency: <high|medium|low>

  content:
    title: <research-title>
    summary: <1-3 sentence summary>
    source: <url-or-reference>
    source_date: <date-of-source>

  relevance:
    impact_areas: [<area-list>]
    affected_phases: [<phase-numbers>]
    affected_agents: [<agent-list>]
    priority_score: <1-10>

  analysis:
    key_findings: [<finding-list>]
    recommendations: [<recommendation-list>]
    risks: [<risk-list>]
    opportunities: [<opportunity-list>]

  disposition:
    status: <pending|accepted|deferred|rejected>
    decision_date: <ISO8601>
    decision_by: <decider>
    rationale: <decision-rationale>
    action_items: [<task-references>]

  tracking:
    backlog_refs: [<task-ids>]
    roadmap_impact: <yes|no|tbd>
    implementation_target: <version-or-date>
```

### Research Tracking Log

Location: `core/research/RESEARCH_LOG.md`

```markdown
# Research Tracking Log

## Active Research
| ID | Title | Type | Status | Owner | Target |
|----|-------|------|--------|-------|--------|
| RI-2026-001 | Example research | external | accepted | Researcher | v2.0 |

## Completed Research
| ID | Title | Outcome | Closed |
|----|-------|---------|--------|
| RI-2025-010 | Prior research | Implemented in v1.5 | 2025-12-15 |

## Deferred/Rejected
| ID | Title | Reason | Date |
|----|-------|--------|------|
| RI-2025-008 | Rejected item | Out of scope | 2025-11-01 |
```

### Research Intake Process

```
1. SUBMIT: Research item submitted
   ├─ Fill intake template
   ├─ Classify type and urgency
   └─ Assign initial priority score
   ↓
2. TRIAGE: Weekly triage review
   ├─ Validate classification
   ├─ Assess relevance and impact
   └─ Assign to reviewer
   ↓
3. ANALYZE: Deep analysis
   ├─ Extract key findings
   ├─ Identify recommendations
   └─ Assess risks and opportunities
   ↓
4. DECIDE: Disposition decision
   ├─ Accept → Create backlog items
   ├─ Defer → Schedule for future review
   └─ Reject → Document rationale
   ↓
5. TRACK: Monitor implementation
   ├─ Link to backlog tasks
   ├─ Update roadmap if needed
   └─ Close when implemented
```

---

## Roadmap Refresh

### Refresh Cadence

| Refresh Type | Frequency | Scope | Participants |
|--------------|-----------|-------|--------------|
| **Micro** | Weekly | Sprint priorities | Orchestrator |
| **Minor** | Monthly | Phase priorities | Orchestrator + Leads |
| **Major** | Quarterly | Full roadmap | All stakeholders |
| **Ad-hoc** | As needed | Urgent changes | Decision makers |

### Roadmap Refresh Schedule

```yaml
roadmap_schedule:
  weekly_refresh:
    day: Monday
    duration: 30min
    activities:
      - Review sprint progress
      - Adjust task priorities
      - Address blockers
    output: Updated PRIORITIES.md

  monthly_refresh:
    week: First week
    duration: 2hr
    activities:
      - Review phase progress
      - Incorporate research findings
      - Rebalance phase priorities
    output: Updated phase planning docs

  quarterly_refresh:
    month: [March, June, September, December]
    duration: 4hr
    activities:
      - Full roadmap review
      - Strategic alignment check
      - Resource reallocation
      - Major/minor version planning
    output: Updated roadmap, release calendar
```

### Roadmap Ownership

| Artifact | Owner | Approver | Update Frequency |
|----------|-------|----------|------------------|
| Phase plans | Phase Lead | Orchestrator | Monthly |
| Task queue | Orchestrator | N/A | Weekly |
| Release calendar | Release Manager | Director | Quarterly |
| Strategic roadmap | Product Owner | Stakeholders | Quarterly |

### Roadmap Change Protocol

```
Minor Change (task reorder, estimate update):
  - Owner updates directly
  - No approval needed
  - Document in STATUS.md

Moderate Change (phase reorder, scope adjustment):
  - Owner proposes change
  - Orchestrator approves
  - Document in DECISIONS.md

Major Change (phase add/remove, strategic shift):
  - Owner proposes with rationale
  - Stakeholder review required
  - Full documentation trail
```

---

## Continuous Improvement

### Improvement Cadence

| Activity | Frequency | Input | Output |
|----------|-----------|-------|--------|
| **Retrospective** | Per release | Team feedback | Action items |
| **Metrics review** | Weekly | Dashboard | Trend analysis |
| **Process audit** | Monthly | Workflow analysis | Process updates |
| **Tool evaluation** | Quarterly | Tool performance | Tool decisions |

### Continuous Improvement Checklist

**Per Release Checklist (CI-REL)**:
- [ ] CI-01: Retrospective conducted
- [ ] CI-02: Lessons learned documented
- [ ] CI-03: Action items created
- [ ] CI-04: Metrics captured
- [ ] CI-05: Process improvements identified

**Monthly Checklist (CI-MON)**:
- [ ] CI-06: Workflow efficiency reviewed
- [ ] CI-07: Bottlenecks identified
- [ ] CI-08: Tool performance assessed
- [ ] CI-09: Documentation currency checked
- [ ] CI-10: Training gaps identified

**Quarterly Checklist (CI-QTR)**:
- [ ] CI-11: Full process audit completed
- [ ] CI-12: Tool stack evaluated
- [ ] CI-13: Research backlog triaged
- [ ] CI-14: Roadmap aligned with strategy
- [ ] CI-15: Governance artifacts updated

### Lessons Learned Template

```yaml
lesson_learned:
  lesson_id: LL-<YYYY>-<NNN>
  recorded_at: <ISO8601>
  recorded_by: <recorder>

  context:
    phase: <phase-number>
    release: <version>
    event_type: <success|failure|observation>

  description:
    what_happened: <description>
    root_cause: <cause-analysis>
    impact: <impact-description>

  learning:
    insight: <key-insight>
    recommendation: <recommended-action>
    applies_to: [<areas>]

  action:
    status: <pending|in_progress|completed|wont_fix>
    action_items: [<task-refs>]
    target_date: <date>
    owner: <owner>

  verification:
    implemented: <true|false>
    verified_at: <date>
    evidence: <evidence-ref>
```

### Change Log

Location: `core/CHANGELOG.md`

```markdown
# Changelog

All notable changes to the orchestration framework.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

## [Unreleased]
### Added
- New feature or capability

### Changed
- Modification to existing behavior

### Deprecated
- Feature marked for removal

### Removed
- Feature removed

### Fixed
- Bug fix

### Security
- Security-related change

## [X.Y.Z] - YYYY-MM-DD
### Added
- Specific changes...
```

### Improvement Metrics

| Metric | ID | Target | Measurement |
|--------|-----|--------|-------------|
| Cycle time | IM-01 | Decreasing trend | Task start to close |
| Rework rate | IM-02 | < 15% | Tasks requiring revision |
| First-pass success | IM-03 | > 85% | Tasks passing first review |
| Documentation lag | IM-04 | < 1 sprint | Docs behind implementation |
| Research intake velocity | IM-05 | 5+ items/quarter | Research items processed |

### Improvement Tracking Schema

```yaml
improvement_tracking:
  period: <YYYY-QN>

  metrics:
    - metric_id: IM-01
      name: Cycle time
      baseline: <baseline-value>
      current: <current-value>
      target: <target-value>
      trend: <improving|stable|declining>

  retrospectives:
    - release: <version>
      date: <date>
      participants: <count>
      action_items: <count>
      completed: <count>

  lessons_learned:
    total: <count>
    implemented: <count>
    pending: <count>

  process_changes:
    - change_id: PC-<NNN>
      description: <change>
      effective_date: <date>
      impact: <impact>
```

---

## Governance Artifact Updates

### Update Triggers

| Trigger | Artifacts Affected | Update Type |
|---------|-------------------|-------------|
| New research finding | Phase plans, roadmap | Content |
| Lesson learned | Process docs, checklists | Content |
| Release completion | Changelog, metrics | Record |
| Process change | Governance docs | Structure |
| Tool change | Tool registry, governance | Structure |

### Update Workflow

```
1. IDENTIFY: Change trigger detected
   ↓
2. ASSESS: Determine scope and impact
   ├─ Which artifacts affected?
   ├─ What type of update?
   └─ Who needs to approve?
   ↓
3. DRAFT: Prepare updates
   ├─ Follow existing format
   ├─ Maintain consistency
   └─ Include rationale
   ↓
4. REVIEW: Get approval if needed
   ├─ Minor: Self-review
   ├─ Moderate: Peer review
   └─ Major: Stakeholder review
   ↓
5. APPLY: Make updates
   ├─ Update artifacts
   ├─ Update changelog
   └─ Update cross-references
   ↓
6. VERIFY: Confirm updates
   ├─ Link validation
   ├─ Format check
   └─ Evidence capture
```

### Governance Review Cadence

| Artifact Category | Review Frequency | Owner |
|-------------------|------------------|-------|
| Handoff templates | Quarterly | Orchestrator |
| Process checklists | Monthly | QA Agent |
| Tool governance | Per tool change | Architect |
| Security policies | Quarterly | Security Agent |
| Evidence templates | Per release | QA Agent |

---

## Quick Reference

### Research Intake Checklist
- [ ] Intake template filled
- [ ] Classification assigned
- [ ] Priority scored
- [ ] Triaged within 1 week
- [ ] Decision documented
- [ ] Backlog items created (if accepted)

### Roadmap Refresh Checklist
- [ ] Current progress reviewed
- [ ] Research findings incorporated
- [ ] Priorities rebalanced
- [ ] Changes documented
- [ ] Stakeholders notified (if major)

### Continuous Improvement Checklist
- [ ] Retrospective conducted
- [ ] Lessons documented
- [ ] Metrics captured
- [ ] Actions created
- [ ] Changes tracked

---

## References

- PR review intake: `core/orchestrator/REVIEW_INTAKE.md`
- Release process: `core/orchestrator/RELEASE_CADENCE.md`
- Regression gates: `core/arch/REGRESSION_GATES.md`
- Task tracking: `core/orchestrator/handoff/TASKS.md`
- Existing research: `core/research/`
