# AGENT-33 Documentation Index

## Project Overview

AGENT-33 is a master aggregation repo for model-agnostic orchestration workflows, agent guidance, and reusable governance assets.

---

## Quick Links

| Document | Description |
|----------|-------------|
| [Orchestration Index](ORCHESTRATION_INDEX.md) | Entry point for orchestration workflows |
| [Core README](README.md) | Canonical core structure and usage |
| [Phase Planning](../docs/phase-planning.md) | AGENT-33 development phases |
| [Phase Index](../docs/phases/README.md) | AGENT-33 phase list and sequencing |

---

## Research Documents

| Document | Description |
|----------|-------------|
| [Agentic Orchestration Trends 2025H2](research/agentic-orchestration-trends-2025H2.md) | Industry trends and guidance for agentic coding |
| [Security Analysis](research/06-SECURITY-ANALYSIS.md) | External platform security vulnerability analysis |
| [Feature Parity](research/07-FEATURE-PARITY.md) | Feature comparison and security hardening mapping |

---

## Phase Templates (Generic)

| Document | Description |
|----------|-------------|
| [Phase Templates](phases/README.md) | Generic, reusable phase outlines (examples) |

---

## AGENT-33 Phase Plan

The canonical AGENT-33 phases live in `docs/phases/`.
Use the phase index for sequencing and dependency order:
`../docs/phases/README.md`

---

## Platform Integration Specifications (CA-017)

| Document | Description |
|----------|-------------|
| [Integration Specs Index](orchestrator/integrations/README.md) | Overview, design principles, and integration checklist |
| [Channel Integration](orchestrator/integrations/CHANNEL_INTEGRATION_SPEC.md) | Multi-platform messaging channel architecture |
| [Voice & Media](orchestrator/integrations/VOICE_MEDIA_SPEC.md) | Voice interaction and media processing (privacy-first) |
| [Credential Management](orchestrator/integrations/CREDENTIAL_MANAGEMENT_SPEC.md) | Vault-backed credential storage and rotation |
| [Privacy Architecture](orchestrator/integrations/PRIVACY_ARCHITECTURE.md) | Encryption at rest, consent model, data lifecycle |

---

---

## Agentic Engineering And Planning

| Document | Description |
|----------|-------------|
| [Architecture & Planning Overview](arch/README.md) | Narrative overview for Architecture & Planning |
| [Architecture & Planning Orchestrator Briefing](arch/orchestrator-briefing.md) | Session-start narrative and folder index |
| [Architecture & Planning Workflow Spec](arch/workflow.md) | End-to-end workflow specification |
| [Architecture & Planning Templates](arch/templates.md) | ID, branch, and tracker conventions |
| Architecture & Planning Session Handoff | Session handoff checklist (operator-maintained) |
| [Architecture & Planning Phase Planning](arch/phase-planning.md) | Long-running planning record |
| [Architecture & Planning Schedule And Tracking](arch/schedule-and-tracking.md) | Cadence and gates |
| [Architecture & Planning Tier Close Checklist](arch/tier-close-checklist.md) | Tier close audit checklist |
| [Architecture & Planning Cycle Summary Template](arch/cycle-summary-template.md) | End-of-cycle summary template |
| [Architecture & Planning Cycle Summaries](arch/cycle-summaries/README.md) | Cycle summary storage location |
| [Architecture & Planning Backlog Template](arch/backlog-template.md) | Master backlog template |
| [Architecture & Planning Backlog Index](arch/backlog-index.md) | Backlog index across cycles |
| [Architecture & Planning Tracker Pointer](arch/tracker-pointer.md) | Active tracker link |
| [Architecture & Planning Tracker Index](arch/tracker-index.md) | Tracker index across cycles |
| [Architecture & Planning Verification Log](arch/verification-log.md) | Test/build evidence log |
| [Architecture & Planning Phase Summary Template](arch/phase-summary-template.md) | Per-PR or per-phase summary template |
| [Architecture & Planning Phase Summaries](arch/phase-summaries/README.md) | Phase summary storage location |
| [Architecture & Planning Risk Memo Template](arch/risk-memo-template.md) | Critical/High risk memo template |
| [Architecture & Planning Risk Memos](arch/risk-memos/README.md) | Risk memo storage location |
| [Architecture & Planning Risk Memo Archive](arch/risk-memos/closed/README.md) | Closed risk memo archive |
| [Architecture & Planning Agent Learning](arch/agent-learning.md) | Cross-session learnings |
| [Architecture & Planning Change Log](arch/change-log.md) | Scope/defer decision log |
| [Architecture & Planning Scope Lock Template](arch/scope-lock-template.md) | Scope lock record |
| [Architecture & Planning Glossary](arch/glossary.md) | Shared terminology |
| [Architecture & Planning Test Matrix](arch/test-matrix.md) | Test selection guidance |
| [Architecture & Planning Active Tracker Template](arch/active-tracker-template.md) | Tracker template with lock block |
| [Architecture & Planning Cycle Layout Template](arch/cycle-layout-template.md) | Optional parallel cycle layout |

---

## Statistics

| Metric | Value |
|--------|-------|
| Total Phase Templates | 40 |
| AGENT-33 Phases | 10 |
| Research Documents | 3 |

---

## Getting Started

### For Developers
1. Start at `core/ORCHESTRATION_INDEX.md`
2. Follow `core/orchestrator/README.md` and `core/orchestrator/OPERATOR_MANUAL.md`
3. Use `core/arch/workflow.md` for AEP cycles

### For AI Agents
1. Read `core/agents/CLAUDE.md` for agent instructions
2. Follow `core/orchestrator/AGENT_REGISTRY.md` for role definitions
3. Use `core/orchestrator/AGENT_ROUTING_MAP.md` for task routing

### For Project Planning
1. Review `docs/phases/README.md` for phase index
2. Consult [Feature Comparison Matrix](research/05-FEATURE-COMPARISON-MATRIX.md)
3. Review `core/orchestrator/COMPETITIVE_FEATURES_INDEX.md` for feature backlog

---

## Document Maintenance

This documentation should be updated as:
- New phases are completed
- Requirements change
- New research is conducted
- Community feedback is incorporated

Last Updated: 2026-01-30

---

## Runtime Engine

The `engine/` directory contains the working Python implementation of the specifications defined in `core/`. It translates the orchestration designs, agent definitions, workflow schemas, and governance policies into executable runtime modules.

### Key Engine Resources

| Resource | Description |
|----------|-------------|
| [Getting Started](../engine/docs/getting-started.md) | Installation and first run |
| [Architecture](../engine/docs/architecture.md) | Engine architecture overview |
| [API Reference](../engine/docs/api-reference.md) | Programmatic API documentation |
| [Workflow Guide](../engine/docs/workflow-guide.md) | Building and running workflows |
| [Agent Guide](../engine/docs/agent-guide.md) | Defining and routing agents |
| [Security Guide](../engine/docs/security-guide.md) | Credentials, vaults, and access control |
| [Integration Guide](../engine/docs/integration-guide.md) | Messaging and platform integrations |
| [CLI Reference](../engine/docs/cli-reference.md) | Command-line interface usage |
| [Use Cases](../engine/docs/use-cases.md) | End-to-end usage examples |
| [Orchestration Mapping](../engine/docs/orchestration-mapping.md) | How core specs map to engine modules |
| [Feature Roadmap](../engine/docs/feature-roadmap.md) | Planned engine enhancements |

For a detailed mapping of orchestration concepts to engine modules, see the [Engine Implementation section in the Orchestration Index](ORCHESTRATION_INDEX.md#engine-implementation).
