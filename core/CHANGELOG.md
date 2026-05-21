## Template (for new entries)
### Canonicalization Decisions
| Date | Canonical File | Sources Considered | Rationale (Recency/Completeness/Reuse) | Notes |
| --- | --- | --- | --- | --- |
| YYYY-MM-DD | core/<path> | collected/<repo>/<path>, ... |  |  |

## [Unreleased]

### Session: 2026-02-12 — PR Review, Merge Sprint, Phase 11 Implementation
| Action | Detail |
| --- | --- |
| PR #19 merged | Complete 10 partial competitive features (CA-007 through CA-060) — backpressure, filters, IO manager, migration, partitioning, state machine extensions, file change sensor, metrics, state model testing |
| PR #17 merged | Hygiene & validation — gitignore, pycache cleanup, lint/type fixes, `zip(strict=True)` |
| PR #13 merged | Phase 21 extensibility patterns integration (Tiers 1-4) — relationship types, agent memory protocol, artifact index, change event types |
| PR #18 merged | Integration wiring — security middleware, DB/Redis/NATS connections, agent-workflow bridge, CORS fix, URL redaction, prompt injection guard |
| Post-merge fixes | Missing `import time` in metrics.py, AsyncMock->MagicMock for httpx sync `.json()` in reader/search tests |
| PR #21 merged | Phase 11 agent registry — 25-entry capability taxonomy, expanded roles, registry search, FastAPI DI, workflow bridge, 6 agent definitions, 28 tests |
| Branch cleanup | Deleted 16 merged branches (4 PR branches + 12 old feature branches), 1 stale branch replaced |
| Test status | 100 passed, 0 failed on main |

### Research Intake
| Date | Action | Source | Target | Rationale | Relationships |
| --- | --- | --- | --- | --- | --- |
| 2026-01-20 | Research dossier created | petabridge/memorizer-v1 (dev branch) | docs/research/repo_dossiers/memorizer__petabridge__memorizer-v1.md | Competitive research for extensibility patterns | contextualizes → Phase-21 |
| 2026-01-20 | Master feature matrix updated | memorizer dossier | docs/research/master_feature_matrix.md, .csv | Added memorizer-v1 row | derived-from → dossier |
| 2026-01-20 | Phase plan created | memorizer dossier section 10 | docs/phases/PHASE-21-EXTENSIBILITY-PATTERNS-INTEGRATION.md | Integration roadmap for adaptable patterns | derived-from → dossier |

### Documentation Updates
| Date | File | Change Type | Notes |
| --- | --- | --- | --- |
| 2026-01-20 | core/orchestrator/RELATIONSHIP_TYPES.md | artifact_created | Phase 21 Tier 1 - Relationship typing system |
| 2026-01-20 | core/arch/templates.md | content_updated | Added relationship documentation guidance |
| 2026-01-20 | core/agents/AGENT_MEMORY_PROTOCOL.md | artifact_created | Phase 21 Tier 2 - Autonomous agent memory protocol |
| 2026-01-20 | core/packs/policy-pack-v1/AGENTS.md | content_updated | Added Knowledge Management section with protocol links |
| 2026-01-20 | core/ORCHESTRATION_INDEX.md | content_updated | Added Agent Memory section |
| 2026-01-20 | core/ARTIFACT_INDEX.md | artifact_created | Phase 21 Tier 3 - Lightweight artifact index |
| 2026-01-20 | core/arch/CHANGE_EVENT_TYPES.md | artifact_created | Phase 21 Tier 4 - Typed change events |
| 2026-01-20 | dedup-policy.md | content_updated | Added immutability principle and relationship types |
| 2026-01-20 | sync-plan.md | content_updated | Added relationship tracking and immutability |
| 2026-01-20 | docs/phases/README.md | content_updated | Added Phase 21 to index |

### Canonicalization Decisions
| Date | Canonical File | Sources Considered | Rationale (Recency/Completeness/Reuse) | Notes |
| --- | --- | --- | --- | --- |
| 2026-01-30 | core/orchestrator/COMPETITIVE_FEATURES_INDEX.md | docs/competitive-analysis/* (12 analyses) | De-duplicated 136 raw features into 65 unique items across 5 clusters with implementation mappings. | Master feature index. |
| 2026-01-30 | core/orchestrator/workflows/* (3 specs) | Dagster, Conductor, Orca, Kestra, Camunda | Asset-first workflow, DAG execution engine, expression language (CA-018 to CA-030). | Cluster 1: Workflow Definition. |
| 2026-01-30 | core/orchestrator/agent-protocols/* (3 specs) | OpenAI Swarm, Agency Swarm, wshobson/agents | Agent handoff, communication flow, guardrails (CA-031 to CA-040). | Cluster 2: Agent Coordination. |
| 2026-01-30 | core/orchestrator/statecharts/* (3 specs) | XState, Camunda, Conductor | Statechart format, task registry, backpressure (CA-041 to CA-050). | Cluster 3: State Machines & Decision. |
| 2026-01-30 | core/orchestrator/decision/DECISION_ROUTING_SPEC.md | Osmedeus, Conductor, Camunda | Switch/case, weighted, rule-based decision routing (CA-042). | Cluster 3. |
| 2026-01-30 | core/orchestrator/lineage/LINEAGE_TRACKING_SPEC.md | Dagster, Orca | Artifact lineage, provenance, impact analysis, visualization (CA-051). | Cluster 4. |
| 2026-01-30 | core/orchestrator/sensors/ARTIFACT_SENSOR_SPEC.md | Dagster, Kestra | Event-driven artifact sensors and triggers (CA-052). | Cluster 4. |
| 2026-01-30 | core/orchestrator/observability/HEALTH_DASHBOARD_SPEC.md | Dagster, all tools | Health monitoring, alerting, status dashboard (CA-053). | Cluster 4. |
| 2026-01-30 | core/orchestrator/testing/WORKFLOW_TESTING_FRAMEWORK.md | Dagster, XState | Unit/integration/model-based workflow testing (CA-054). | Cluster 4. |
| 2026-01-30 | core/orchestrator/plugins/PLUGIN_REGISTRY_SPEC.md | Osmedeus, Kestra | Plugin system with lifecycle, isolation, governance (CA-055). | Cluster 4. |
| 2026-01-30 | core/orchestrator/distribution/DISTRIBUTION_SYNC_SPEC.md | Phase 9 | Downstream repo sync rules, PR templates, validation (CA-061). | Phase 9: Distribution & Sync. |
| 2026-01-30 | core/orchestrator/community/GOVERNANCE_COMMUNITY_SPEC.md | Phase 10 | Contribution model, review assignment, escalation, maintenance cadence (CA-062). | Phase 10: Governance & Community. |
| 2026-01-30 | core/research/06-SECURITY-ANALYSIS.md | External platform analysis | Full platform security analysis identifying plaintext credentials, information leaking, third-party dependency risks. | New research document. |
| 2026-01-30 | core/research/07-FEATURE-PARITY.md | External platform analysis | Feature-by-feature parity mapping with security improvements. | New research document. |
| 2026-01-30 | core/orchestrator/integrations/CHANNEL_INTEGRATION_SPEC.md | External channel architecture (20+ platforms) | Security-hardened channel integration spec with tiered platform classification. | New specification (CA-017). |
| 2026-01-30 | core/orchestrator/integrations/VOICE_MEDIA_SPEC.md | External STT/TTS/vision features | Privacy-first voice and media processing with local-first preference. | New specification (CA-017). |
| 2026-01-30 | core/orchestrator/integrations/CREDENTIAL_MANAGEMENT_SPEC.md | External auth-profiles analysis | Vault/keyring mandatory credential management replacing plaintext patterns. | New specification (CA-017). |
| 2026-01-30 | core/orchestrator/integrations/PRIVACY_ARCHITECTURE.md | External data flow analysis | Privacy-first architecture with encryption at rest, consent requirements, data minimization. | New specification (CA-017). |
| 2026-01-30 | core/orchestrator/integrations/README.md | (new) | Integration specifications index. | New specification. |
| 2026-01-16 | core/arch/* (AEP templates & guides) | collected/*/docs/Architecture & Planning/* | Identical copies across repos; selected canonical baseline. | Removed suffixed variants in core/arch. |
| 2026-01-16 | core/prompts/agentic-review-framework.md | collected/*/docs/agentic-review-framework.md | Identical copies; selected canonical baseline. |  |
| 2026-01-16 | core/prompts/agentic-review-prompts.md | collected/*/docs/agentic-review-prompts.md | Identical copies; selected canonical baseline. |  |
| 2026-01-16 | core/agents/CLAUDE.md | collected/*/CLAUDE.md and collected/*/docs/CLAUDE.md | Selected most complete variant (25,208 bytes). |  |
| 2026-01-16 | core/agents/CLAUDE_SESSION_WRAP_CONTEXT_AGENT.md | collected/*/docs/CLAUDE_SESSION_WRAP_CONTEXT_AGENT.md | Identical copies; selected canonical baseline. |  |
| 2026-01-16 | core/agents/AGENTS.md | collected/*/AGENTS.md | Selected most complete variant. |  |
| 2026-01-16 | core/orchestrator/* | collected/*/local-agent-orchestrator/* | Only repo containing orchestrator assets. |  |
| 2026-01-16 | core/workflows/* | collected/*/.github/* | Baseline workflow set; other repos pending merge review. |  |
| 2026-01-16 | core/workflows/instructions/csharp.instructions.md | collected/*/.github/instructions/csharp.instructions.md | Only repo providing C# instruction file. | Promoted to canonical instructions. |
| 2026-01-16 | core/workflows/instructions/python.instructions.md | collected/*/.github/instructions/python.instructions.md | Only repo providing Python instruction file. | Promoted to canonical instructions. |
| 2026-01-16 | core/agents/sources/* | collected/*/CLAUDE.md, collected/*/AGENTS.md, collected/*/docs/agentic-review-*.md | Archived for reference; non-canonical. | Flattened filenames. |
| 2026-01-16 | core/workflows/sources/* | collected/*/.github/* | Archived for later workflow merge. |  |
| 2026-01-16 | core/agents/AGENTS.md | collected/*/AGENTS.md | Consolidated project-specific constraints into a single core file. |  |
| 2026-01-16 | core/agents/CLAUDE_SOURCES.md | core/agents/sources/* | Added index for archived CLAUDE variants. |  |
| 2026-01-16 | core/workflows/workflows/dotnet-build.yml | collected/*/.github/workflows/dotnet-build.yml | Selected as reusable .NET CI template. |  |
| 2026-01-16 | core/workflows/dependabot.yml | collected/*/.github/dependabot.yml | Simple baseline dependabot config. |  |
| 2026-01-16 | core/agents/CLAUDE.md | core/agents/sources/* CLAUDE variants | Added condensed sections for source project contexts. |  |
| 2026-01-16 | core/orchestrator/README.md | (new) | Added model-agnostic orchestrator entrypoint. |  |
| 2026-01-16 | core/orchestrator/handoff/DEFINITION_OF_DONE.md | (new) | Added definition of done checklist. |  |
| 2026-01-16 | core/orchestrator/handoff/TASKS.md | core/orchestrator/handoff/TASKS.md | Added review capture + DoD step. |  |
| 2026-01-16 | core/orchestrator/prompts/SYSTEM.md | core/orchestrator/prompts/SYSTEM.md | Added risk triggers and model-agnostic wording. |  |
| 2026-01-16 | core/orchestrator/prompts/WORKER_RULES.md | core/orchestrator/prompts/WORKER_RULES.md | Model-agnostic worker guidance. |  |
| 2026-01-16 | core/orchestrator/agents/CLAUDE_ORCHESTRATOR_RULES.md | core/orchestrator/agents/CLAUDE_ORCHESTRATOR_RULES.md | Model-agnostic orchestrator rules. |  |
| 2026-01-16 | core/orchestrator/agents/QWEN_WORKER_RULES.md | core/orchestrator/agents/QWEN_WORKER_RULES.md | Model-agnostic worker rules. |  |
| 2026-01-16 | core/orchestrator/agents/GEMINI_REVIEW_RULES.md | core/orchestrator/agents/GEMINI_REVIEW_RULES.md | Model-agnostic reviewer rules. |  |
| 2026-01-16 | core/orchestrator/PROMPT_PACK.md | core/orchestrator/PROMPT_PACK.md | Model-agnostic prompt pack. |  |
| 2026-01-16 | core/orchestrator/handoff/PLAN.md | core/orchestrator/handoff/PLAN.md | Removed model-specific references. |  |
| 2026-01-16 | core/orchestrator/handoff/STATUS.md | core/orchestrator/handoff/STATUS.md | Made status model-agnostic with local runtime example. |  |
| 2026-01-16 | core/workflows/PROMOTION_CRITERIA.md | (new) | Added workflow promotion criteria. |  |
| 2026-01-16 | core/workflows/SOURCES_INDEX.md | (new) | Added workflow sources index. |  |
| 2026-01-16 | core/orchestrator/analysis/README.md | (new) | Added orchestration analysis index. |  |
| 2026-01-16 | core/arch/workflow.md | core/arch/workflow.md | Updated quick links to canonical core paths. |  |
| 2026-01-16 | core/orchestrator/agents/DIRECTOR_RULES.md | (new) | Added model-agnostic Director role. |  |
| 2026-01-16 | core/orchestrator/OPERATOR_MANUAL.md | (new) | Added operator manual tying handoff to AEP workflow. |  |
| 2026-01-16 | core/orchestrator/PROMPT_PACK.md | core/orchestrator/PROMPT_PACK.md | Added Director prompt. |  |
| 2026-01-16 | core/orchestrator/README.md | core/orchestrator/README.md | Linked operator manual and director role. |  |
| 2026-01-16 | core/agents/CLAUDE.md | core/agents/CLAUDE.md | Added context selector table. |  |
| 2026-01-16 | core/orchestrator/handoff/PRIORITIES.md | (new) | Added rolling priorities view. |  |
| 2026-01-16 | core/orchestrator/handoff/REVIEW_CAPTURE.md | (new) | Added review capture template. |  |
| 2026-01-16 | core/orchestrator/handoff/TASKS.md | core/orchestrator/handoff/TASKS.md | Linked review capture template. |  |
| 2026-01-16 | core/orchestrator/AGENT_ROUTING_MAP.md | (new) | Added agent routing map by task type. |  |
| 2026-01-16 | core/orchestrator/README.md | core/orchestrator/README.md | Linked priorities and routing map. |  |
| 2026-01-16 | core/orchestrator/handoff/REVIEW_CHECKLIST.md | (new) | Added model-agnostic review checklist. |  |
| 2026-01-16 | core/ORCHESTRATION_INDEX.md | (new) | Added orchestration index linking core systems. |  |
| 2026-01-16 | core/agents/CLAUDE.md | core/agents/CLAUDE.md | Added quick links to sources and diff report. |  |
| 2026-01-16 | core/README.md | core/README.md | Added orchestration overview links. |  |
| 2026-01-16 | core/orchestrator/GLOSSARY.md | (new) | Added orchestration glossary. |  |
| 2026-01-16 | core/agents/CLAUDE_ADDENDUM.md | (new) | Moved additional project contexts into addendum. |  |
| 2026-01-16 | core/agents/CLAUDE.md | core/agents/CLAUDE.md | Linked addendum and removed project-specific contexts. |  |
| 2026-01-16 | core/orchestrator/README.md | core/orchestrator/README.md | Added orchestration quickstart. |  |
| 2026-01-16 | core/orchestrator/AGENT_ROUTING_MAP.md | core/orchestrator/AGENT_ROUTING_MAP.md | Added role selection checklist. |  |
| 2026-01-16 | core/orchestrator/handoff/ESCALATION_PATHS.md | (new) | Added escalation paths guidance. |  |
| 2026-01-16 | core/orchestrator/handoff/EVIDENCE_CAPTURE.md | (new) | Added evidence capture template. |  |
| 2026-01-16 | core/orchestrator/handoff/SESSION_WRAP.md | (new) | Added session wrap template. |  |
| 2026-01-16 | core/orchestrator/CHEAT_SHEET.md | (new) | Added orchestration cheat sheet. |  |
| 2026-01-16 | core/orchestrator/README.md | core/orchestrator/README.md | Linked cheat sheet and evidence capture in quickstart. |  |
| 2026-01-16 | core/orchestrator/handoff/PLAN.md | core/orchestrator/handoff/PLAN.md | Added minimum required artifacts section. |  |
| 2026-01-16 | core/orchestrator/handoff/STATUS.md | core/orchestrator/handoff/STATUS.md | Added task status glossary. |  |
| 2026-01-16 | core/orchestrator/prompts/SYSTEM.md | core/orchestrator/prompts/SYSTEM.md | Added risk trigger matrix. |  |
| 2026-01-16 | core/orchestrator/handoff/EVIDENCE_CAPTURE.md | core/orchestrator/handoff/EVIDENCE_CAPTURE.md | Added review outcomes section. |  |
| 2026-01-16 | core/orchestrator/CHEAT_SHEET.md | core/orchestrator/CHEAT_SHEET.md | Added task lifecycle diagram. |  |
| 2026-01-16 | core/orchestrator/handoff/REVIEW_CHECKLIST.md | core/orchestrator/handoff/REVIEW_CHECKLIST.md | Added risk trigger checklist. |  |
| 2026-01-16 | core/orchestrator/README.md | core/orchestrator/README.md | Clarified review vs evidence capture. |  |
| 2026-01-16 | core/ORCHESTRATION_INDEX.md | core/ORCHESTRATION_INDEX.md | Added model-agnostic principle note. |  |
| 2026-01-16 | core/orchestrator/handoff/EVIDENCE_CAPTURE.md | core/orchestrator/handoff/EVIDENCE_CAPTURE.md | Added evidence checklist. |  |
| 2026-01-16 | core/workflows/PROMOTION_CRITERIA.md | core/workflows/PROMOTION_CRITERIA.md | Added promotion decision log template. |  |
| 2026-01-16 | core/agents/README.md | core/agents/README.md | Linked CLAUDE addendum usage. |  |
| 2026-01-16 | core/orchestrator/handoff/STATUS.md | core/orchestrator/handoff/STATUS.md | Added handoff file map. |  |
| 2026-01-16 | core/orchestrator/handoff/TASKS.md | core/orchestrator/handoff/TASKS.md | Added minimum task payload. |  |
| 2026-01-16 | core/orchestrator/handoff/ESCALATION_PATHS.md | core/orchestrator/handoff/ESCALATION_PATHS.md | Added review escalation criteria. |  |
| 2026-01-16 | core/orchestrator/handoff/TASKS.md | core/orchestrator/handoff/TASKS.md | Added acceptance criteria examples. |  |
| 2026-01-16 | core/orchestrator/handoff/SESSION_WRAP.md | core/orchestrator/handoff/SESSION_WRAP.md | Added handoff checklist. |  |
| 2026-01-16 | core/arch/verification-log.md | core/arch/verification-log.md | Added usage note for verification log. |  |
| 2026-01-16 | core/research/agentic-orchestration-trends-2025H2.md | docs/research/agentic-orchestration-trends-2025H2.md | Promoted research doc to core for canonical reference. |  |
| 2026-01-16 | core/orchestrator/handoff/EVIDENCE_CAPTURE.md | core/orchestrator/handoff/EVIDENCE_CAPTURE.md | Added evidence example. |  |
| 2026-01-16 | core/orchestrator/handoff/REVIEW_CAPTURE.md | core/orchestrator/handoff/REVIEW_CAPTURE.md | Added risk trigger references. |  |
| 2026-01-16 | core/arch/workflow.md | core/arch/workflow.md | Linked orchestration index. |  |
| 2026-01-16 | core/orchestrator/README.md | core/orchestrator/README.md | Added task evidence quick checklist. |  |
| 2026-01-16 | core/orchestrator/handoff/SESSION_WRAP.md | core/orchestrator/handoff/SESSION_WRAP.md | Added review handoff summary. |  |
| 2026-01-16 | core/workflows/SOURCES_INDEX.md | core/workflows/SOURCES_INDEX.md | Added promotion workflow note. |  |
| 2026-01-16 | core/orchestrator/handoff/TASKS.md | core/orchestrator/handoff/TASKS.md | Added status update template. |  |
| 2026-01-16 | core/orchestrator/GLOSSARY.md | core/orchestrator/GLOSSARY.md | Added role responsibility summary. |  |
| 2026-01-16 | core/orchestrator/OPERATOR_MANUAL.md | core/orchestrator/OPERATOR_MANUAL.md | Added orchestration consistency checklist. |  |
| 2026-01-16 | core/orchestrator/handoff/PRIORITIES.md | core/orchestrator/handoff/PRIORITIES.md | Added handoff cadence note. |  |
| 2026-01-16 | core/orchestrator/handoff/REVIEW_CAPTURE.md | core/orchestrator/handoff/REVIEW_CAPTURE.md | Added review summary example. |  |
| 2026-01-16 | core/orchestrator/handoff/SESSION_WRAP.md | core/orchestrator/handoff/SESSION_WRAP.md | Added verification evidence example. |  |
| 2026-01-16 | core/orchestrator/handoff/STATUS.md | core/orchestrator/handoff/STATUS.md | Added handoff ownership fields. |  |
| 2026-01-16 | core/orchestrator/handoff/DECISIONS.md | core/orchestrator/handoff/DECISIONS.md | Added decision template example. |  |
| 2026-01-16 | core/orchestrator/README.md | core/orchestrator/README.md | Added session logs guidance. |  |
| 2026-01-16 | core/orchestrator/handoff/STATUS.md | core/orchestrator/handoff/STATUS.md | Added runtime assumptions checklist. |  |
| 2026-01-16 | core/orchestrator/handoff/DECISIONS.md | core/orchestrator/handoff/DECISIONS.md | Added decision types list. |  |
| 2026-01-16 | core/ORCHESTRATION_INDEX.md | core/ORCHESTRATION_INDEX.md | Added SESSION_WRAP link. |  |
| 2026-01-16 | core/orchestrator/handoff/SESSION_WRAP.md | core/orchestrator/handoff/SESSION_WRAP.md | Added handoff metadata section. |  |
| 2026-01-16 | core/orchestrator/handoff/TASKS.md | core/orchestrator/handoff/TASKS.md | Added reviewer required field. |  |
| 2026-01-16 | core/orchestrator/handoff/STATUS.md | core/orchestrator/handoff/STATUS.md | Added task status mapping. |  |
| 2026-01-16 | README.md | README.md | Rewrote repo README with model-agnostic specs and usage. |  |
| 2026-01-16 | core/README.md | core/README.md | Added core specifications section. |  |
| 2026-01-16 | docs/README.md | (new) | Added local docs overview and canonical references. |  |

## Release Notes
- 2026-01-16: `RELEASE_NOTES_2026-01-16.md`
