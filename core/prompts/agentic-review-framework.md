# Orchestrated Agentic PR Review Framework

**Version**: 1.0
**Purpose**: Continuous refinement through multi-agent retrospective analysis

---

## Executive Summary

This framework establishes a systematic approach to continuous codebase refinement through orchestrated agent teams. By analyzing batches of merged PRs, specialized agents identify improvement opportunities and propose refinement PRs that address technical debt, architectural drift, documentation gaps, and testing coverage before they compound.

**Cadence**: Refinement cycle triggers after every 3 significant PRs merged to main branch.

---

## The Agent Team

### 1. Orchestrator Agent
**Role**: Coordination and synthesis
**Responsibilities**:
- Sequences agent execution based on dependencies
- Aggregates findings across all agents
- Resolves conflicting recommendations
- Prioritizes refinement items by impact/effort
- Produces final refinement PR specifications

**Inputs**: All agent reports
**Outputs**: Prioritized refinement backlog, PR specifications

---

### 2. Architecture Agent
**Role**: Structural integrity and pattern consistency
**Responsibilities**:
- Analyzes architectural decisions across PR batch
- Identifies pattern drift or inconsistencies
- Detects coupling increases or cohesion decreases
- Evaluates dependency graph changes
- Proposes structural refactoring

**Review Questions**:
- Did these PRs follow established patterns?
- Are there new patterns that should be standardized?
- Has coupling increased between modules?
- Are there SOLID principle violations?
- Should abstractions be introduced or removed?

**Outputs**: Architecture deviation report, refactoring proposals

---

### 3. Testing Agent
**Role**: Test coverage and quality assurance
**Responsibilities**:
- Measures coverage delta across PR batch
- Identifies untested code paths introduced
- Evaluates test quality (not just quantity)
- Detects test pattern inconsistencies
- Proposes test additions and improvements

**Review Questions**:
- What new code lacks test coverage?
- Are existing tests still valid after changes?
- Are test patterns consistent across the codebase?
- Are there integration test gaps?
- Should any manual tests be automated?

**Outputs**: Coverage gap report, test specifications

---

### 4. Documentation Agent
**Role**: Knowledge preservation and clarity
**Responsibilities**:
- Audits documentation currency after changes
- Identifies undocumented public APIs
- Evaluates inline comment quality
- Checks README and guide accuracy
- Proposes documentation updates

**Review Questions**:
- Do code comments match current behavior?
- Are public interfaces documented?
- Do architectural docs reflect current state?
- Are setup/build instructions accurate?
- Should new concepts be explained?

**Outputs**: Documentation gap report, content specifications

---

### 5. Debug Agent
**Role**: Reliability and observability
**Responsibilities**:
- Analyzes error handling patterns
- Evaluates logging coverage and quality
- Identifies potential failure modes
- Reviews exception propagation
- Proposes reliability improvements

**Review Questions**:
- Are new error cases handled appropriately?
- Is logging sufficient for debugging?
- Are there silent failures or swallowed exceptions?
- Do error messages aid troubleshooting?
- Are there race conditions or edge cases?

**Outputs**: Reliability assessment, hardening proposals

---

### 6. Use Case Agent
**Role**: Feature completeness and user experience
**Responsibilities**:
- Maps PRs to user-facing functionality
- Identifies incomplete user flows
- Evaluates feature discoverability
- Reviews UX consistency
- Proposes UX refinements

**Review Questions**:
- Do features work end-to-end?
- Are edge cases handled gracefully?
- Is behavior consistent across similar features?
- Are there missing validation messages?
- Should features be more discoverable?

**Outputs**: Feature gap report, UX improvement proposals

---

### 7. Security Agent
**Role**: Vulnerability prevention and compliance
**Responsibilities**:
- Scans for OWASP Top 10 vulnerabilities
- Reviews authentication/authorization changes
- Audits data handling and validation
- Checks dependency security advisories
- Proposes security hardening

**Review Questions**:
- Are inputs properly validated and sanitized?
- Are secrets handled securely?
- Are dependencies up to date and secure?
- Are authorization checks consistent?
- Are there injection vulnerabilities?

**Outputs**: Security assessment, remediation proposals

---

### 8. Performance Agent
**Role**: Efficiency and scalability
**Responsibilities**:
- Identifies algorithmic complexity concerns
- Reviews resource utilization patterns
- Evaluates caching opportunities
- Detects potential bottlenecks
- Proposes optimization opportunities

**Review Questions**:
- Are there O(n²) or worse algorithms introduced?
- Are database queries efficient?
- Are there memory leak risks?
- Should caching be added?
- Are async patterns used appropriately?

**Outputs**: Performance assessment, optimization proposals

---

## The Review Process

### Phase 1: PR Collection (Orchestrator)
```
1. Identify last N PRs merged to main (default: 10)
2. Extract PR metadata:
   - PR number, title, description
   - Files changed, lines added/removed
   - Author, reviewers, merge date
3. Clone diff content for each PR
4. Identify PR dependencies and relationships
5. Create review manifest for agent distribution
```

### Phase 2: Parallel Analysis (All Specialists)
```
1. Each agent receives review manifest
2. Agents analyze PRs through their specialized lens
3. Agents produce structured findings:
   - Issue category and severity
   - Affected files and line ranges
   - Specific recommendation
   - Estimated effort (S/M/L)
4. Agents complete within time bounds
```

### Phase 3: Synthesis (Orchestrator)
```
1. Collect all agent reports
2. Deduplicate overlapping findings
3. Resolve conflicting recommendations
4. Score items by: impact × (1/effort) × urgency
5. Group related items into coherent PRs
6. Produce refinement PR specifications
```

### Phase 4: Refinement PR Generation
```
1. For each PR specification:
   - Create branch from main
   - Generate implementation plan
   - Execute changes (or defer to human)
   - Create PR with full context
2. Link refinement PRs to source PRs
3. Tag with refinement-cycle label
```

---

## Refinement PR Specification Format

```markdown
## Refinement PR: [Title]

### Source Analysis
- **Trigger PRs**: #101, #102, #103
- **Identified By**: [Agent Name]
- **Category**: Architecture | Testing | Documentation | Debug | Security | Performance | UX

### Problem Statement
[Clear description of the issue or improvement opportunity]

### Proposed Changes
1. [Specific change 1]
2. [Specific change 2]
...

### Files Affected
- `path/to/file1.cs` - [nature of change]
- `path/to/file2.cs` - [nature of change]

### Acceptance Criteria
- [ ] [Criterion 1]
- [ ] [Criterion 2]

### Effort Estimate
- Size: S | M | L
- Risk: Low | Medium | High

### Dependencies
- Requires: [any prerequisites]
- Blocks: [any dependent work]
```

---

## Execution Cadence

### Trigger Conditions
A refinement cycle triggers when ANY of:
1. 3 significant PRs merged since last cycle
2. 2 weeks elapsed since last cycle
3. Manual trigger requested
4. Critical finding from continuous monitoring

### Cycle Timeline
```
Day 0: Trigger detected
Day 0: Phase 1 - PR Collection (< 1 hour)
Day 0: Phase 2 - Parallel Analysis (< 2 hours)
Day 0: Phase 3 - Synthesis (< 1 hour)
Day 1: Phase 4 - PR Generation (varies)
Day 1+: Human review and merge
```

### Output Expectations
Per cycle, expect:
- 2-5 refinement PRs generated
- 60% address technical debt
- 25% improve test coverage
- 15% documentation/other

---

## Agent Invocation Template

### For Claude Code / AI Assistants

```markdown
## Orchestrated PR Review Task

You are the [AGENT_ROLE] agent in a multi-agent review team.

### Your Mission
Analyze the following PRs through your specialized lens and produce a structured findings report.

### PRs Under Review
[List of PR numbers, titles, and summaries]

### Your Review Questions
[Agent-specific questions from framework]

### Output Format
For each finding, provide:
1. **Category**: [Your domain category]
2. **Severity**: Critical | High | Medium | Low
3. **PR Source**: Which PR(s) introduced this
4. **Location**: File path and line range
5. **Issue**: Clear description
6. **Recommendation**: Specific action to take
7. **Effort**: S (< 1hr) | M (1-4hr) | L (> 4hr)

### Constraints
- Focus only on your domain expertise
- Be specific and actionable
- Avoid duplicate findings
- Prioritize by impact
```

---

## Integration Points

### GitHub Actions Trigger
```yaml
name: Refinement Cycle
on:
  workflow_dispatch:
  schedule:
    - cron: '0 9 * * 1'  # Weekly Monday 9am
  pull_request:
    types: [closed]
    branches: [main]

jobs:
  check-trigger:
    runs-on: ubuntu-latest
    outputs:
      should-run: ${{ steps.check.outputs.trigger }}
    steps:
      - id: check
        run: |
          # Count PRs since last refinement tag
          # Trigger if >= 3
```

### Manual Invocation
```bash
# Via Claude Code
claude "Run refinement cycle on last 10 PRs using agentic-review-framework.md"

# Via custom script
./scripts/refinement-cycle.sh --prs 10 --agents all
```

---

## Success Metrics

### Per Cycle
- Findings generated per agent
- Refinement PRs created
- PRs merged vs deferred
- Time from trigger to completion

### Over Time
- Technical debt trend (decreasing)
- Test coverage trend (increasing)
- Bug escape rate (decreasing)
- Documentation freshness score

---

## Appendix: Agent Coordination Matrix

| Agent | Depends On | Feeds Into |
|-------|------------|------------|
| Orchestrator | All agents | Final output |
| Architecture | None | Testing, Debug |
| Testing | Architecture | Debug |
| Documentation | All technical agents | Final output |
| Debug | Architecture, Testing | Performance |
| Use Case | None | Documentation |
| Security | Architecture | Debug |
| Performance | Architecture, Debug | Final output |

---

## Appendix: Severity Definitions

| Level | Definition | Response Time |
|-------|------------|---------------|
| Critical | Security vulnerability, data loss risk, breaking change | Immediate |
| High | Significant technical debt, major coverage gap | This cycle |
| Medium | Pattern inconsistency, minor gaps | Next cycle |
| Low | Nice-to-have improvements, polish | Backlog |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-15 | Initial framework |
