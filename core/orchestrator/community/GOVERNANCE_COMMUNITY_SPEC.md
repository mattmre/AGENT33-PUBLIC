# Governance & Community Specification

> Phase 10 -- AGENT-33 Orchestration Framework

## Purpose

Define contribution standards, review roles, escalation paths, and maintenance cadence for AGENT-33 as an open orchestration framework. This specification ensures consistent quality, clear ownership, and sustainable growth of the project.

## Related Documents

| Document | Path |
|----------|------|
| Two-Layer Review | `core/orchestrator/TWO_LAYER_REVIEW.md` |
| Agent Registry | `core/orchestrator/AGENT_REGISTRY.md` |
| Release Cadence | `core/orchestrator/RELEASE_CADENCE.md` |
| Continuous Improvement | `core/orchestrator/CONTINUOUS_IMPROVEMENT.md` |

---

## Contribution Model

| Role | Responsibilities | Approval Scope |
|------|-----------------|----------------|
| Maintainer | Merge authority, release management, architecture decisions | All PRs |
| Committer | Feature specs, governance updates, research | Non-breaking PRs |
| Contributor | Feature proposals, bug fixes, documentation | Requires review |
| Observer | Issue filing, discussion, feedback | No merge access |

### Role Progression

- **Observer to Contributor**: Submit a merged PR (docs or code).
- **Contributor to Committer**: Three or more merged PRs with substantive changes, nominated by a Maintainer.
- **Committer to Maintainer**: Sustained contributions over two or more quarters, demonstrated architectural understanding, nominated by existing Maintainer.

---

## Contribution Workflow

1. **Proposal** -- Open an issue with a problem statement and proposed approach.
2. **Discussion** -- Community review period (minimum 48 hours for non-trivial changes).
3. **Specification** -- Write spec in the appropriate `core/orchestrator/` directory.
4. **Review** -- Two-layer review process (L1 automated checks + L2 human/agent review).
5. **Merge** -- Maintainer approval required.
6. **Release** -- Follow `RELEASE_CADENCE.md` for inclusion in the next release.

---

## Pull Request Standards

### Title Format

```
{type}: {brief description}
```

Valid types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`.

### Body Requirements

- **Summary**: What changed and why.
- **Motivation**: Link to issue or spec driving the change.
- **Spec changes**: List any specification documents added or modified.
- **Test plan**: Steps to verify correctness.

### Labels

- `phase-{N}` -- Associated implementation phase.
- `CA-{NNN}` -- Competitive analysis item reference.
- `priority-{level}` -- One of `critical`, `high`, `medium`, `low`.

### Size Constraints

- Maximum 500 lines changed per PR. Split larger changes into incremental PRs.
- Each PR should be independently reviewable and, where possible, independently deployable.

### Evidence

All PRs must include verification evidence: commands run, test results, or verification log entries demonstrating the change works as intended.

---

## Review Assignment

| File Path Pattern | Primary Reviewer | Secondary Reviewer |
|-------------------|------------------|--------------------|
| `core/orchestrator/` | Architect | Security |
| `core/packs/` | Security | Architect |
| `core/schemas/` | Architect | QA |
| `core/research/` | Researcher | Architect |
| `core/workflows/` | QA | Implementer |
| `core/agents/` | Orchestrator | Reviewer |

When a PR spans multiple path patterns, the Primary Reviewer is determined by the path with the most changed lines. The Secondary Reviewer from that path and the Primary Reviewer from the next most-changed path both participate.

---

## Escalation Paths

| Severity | Description | Path | SLA |
|----------|-------------|------|-----|
| Critical | Security vulnerability, data loss | Maintainer -- immediate review | 4 hours |
| High | Breaking change, regression | Committer -- Maintainer review | 24 hours |
| Medium | Feature, enhancement | Contributor -- Committer review | 72 hours |
| Low | Docs, style, nits | Any reviewer | 1 week |

### Escalation Procedure

1. File an issue with the appropriate severity label.
2. Tag the responsible party per the table above.
3. If no response within the SLA, escalate to the next level (Contributor to Committer to Maintainer).
4. All escalations are logged in the issue for transparency.

---

## Maintenance Cadence

| Activity | Frequency | Owner |
|----------|-----------|-------|
| Dependency audit | Monthly | Security |
| Stale issue triage | Bi-weekly | Maintainer |
| Release planning | Bi-weekly | Maintainer + Architect |
| Spec freshness review | Quarterly | All Committers |
| Competitive analysis update | Quarterly | Researcher |
| Governance policy review | Semi-annual | Maintainer |

---

## Decision Making

- **Consensus** -- Preferred for most decisions. Agreement among active reviewers on the relevant PR or issue.
- **Maintainer override** -- Available for time-sensitive or deadlocked decisions. Must include written rationale.
- **RFC process** -- Required for architectural changes affecting more than three files or introducing new subsystems. RFCs are filed as issues with the `rfc` label and require a minimum 72-hour discussion period.
- **Decision log** -- All significant decisions are recorded in `DECISIONS.md` with date, participants, rationale, and outcome.

---

## Code of Conduct

- Professional, constructive feedback in all interactions.
- Evidence-based technical discussions; assertions should reference specs, data, or prior decisions.
- Inclusive language in code, documentation, and communication.
- No personal attacks or dismissive behavior.
- Conflicts are resolved through the escalation path defined above.

Violations are reviewed by a Maintainer and may result in restricted access per the severity of the violation.

---

## Changelog

| Date | Change | Author |
|------|--------|--------|
| 2026-01-30 | Initial specification | Implementer |
