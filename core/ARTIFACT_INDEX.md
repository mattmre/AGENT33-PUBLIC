# Artifact Index

Lightweight metadata index for efficient artifact discovery. Reduces context window consumption by providing IDs, titles, and metadata without loading full content.

## Index Format

| artifact-id | title | type | tags | created | supersedes |
|-------------|-------|------|------|---------|------------|

## Core Artifacts

### Orchestration

| artifact-id | title | type | tags | created | supersedes |
|-------------|-------|------|------|---------|------------|
| orchestration-index | Orchestration Index | index | orchestration, navigation | 2026-01-16 | - |
| orchestrator-readme | Orchestrator README | guide | orchestration, quickstart | 2026-01-16 | - |
| operator-manual | Operator Manual | guide | orchestration, handoff | 2026-01-16 | - |
| agent-routing-map | Agent Routing Map | reference | agents, routing | 2026-01-16 | - |
| relationship-types | Relationship Types | reference | relationships, provenance | 2026-01-20 | - |
| agent-memory-protocol | Agent Memory Protocol | protocol | agents, memory, autonomy | 2026-01-20 | - |

### Policy Pack v1

| artifact-id | title | type | tags | created | supersedes |
|-------------|-------|------|------|---------|------------|
| policy-pack-v1-agents | Policy Pack v1 AGENTS | policy | agents, autonomy | 2026-01-16 | - |
| policy-pack-v1-orchestration | Policy Pack v1 ORCHESTRATION | policy | orchestration, governance | 2026-01-16 | - |
| policy-pack-v1-evidence | Policy Pack v1 EVIDENCE | policy | evidence, verification | 2026-01-16 | - |
| policy-pack-v1-risk-triggers | Policy Pack v1 RISK_TRIGGERS | policy | risk, review | 2026-01-16 | - |

### AEP Workflow

| artifact-id | title | type | tags | created | supersedes |
|-------------|-------|------|------|---------|------------|
| aep-workflow | AEP Workflow | workflow | review, findings | 2026-01-16 | - |
| aep-templates | AEP Templates | reference | templates, conventions | 2026-01-16 | - |
| change-event-types | Change Event Types | reference | versioning, events | 2026-01-20 | - |

### Phases

| artifact-id | title | type | tags | created | supersedes |
|-------------|-------|------|------|---------|------------|
| phase-21-extensibility | Phase 21: Extensibility Patterns | phase | research, core | 2026-01-20 | - |

### Research

| artifact-id | title | type | tags | created | supersedes |
|-------------|-------|------|------|---------|------------|
| memorizer-v1-dossier | Memorizer-v1 Repo Dossier | research | competitive, patterns | 2026-01-20 | - |
| memorizer-v1-integration | Memorizer-v1 Integration Report | research | integration, patterns | 2026-01-20 | - |

## Search Guidance

### By Type
- `type:policy` - Governance documents
- `type:phase` - Implementation phases
- `type:research` - Research dossiers and reports
- `type:reference` - Quick-reference documents
- `type:protocol` - Agent behavior protocols

### By Tag
- `tags:orchestration` - Orchestration system documents
- `tags:agents` - Agent configuration and behavior
- `tags:relationships` - Artifact relationship documentation

### Finding Current Versions
Check `supersedes` column to find the latest version of an artifact. If an artifact has been superseded, follow the chain to the current version.

## Maintenance

When adding new artifacts:
1. Add entry to appropriate section
2. Use kebab-case for artifact-id
3. Add relevant tags (max 3-4)
4. Set created date
5. Link supersedes if replacing existing artifact
