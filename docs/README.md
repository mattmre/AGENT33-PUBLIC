# AGENT-33 Documentation

Last updated: April 17, 2026.

This `docs/` directory is the canonical documentation set for AGENT-33.

## Start Here

1. [Getting Started](getting-started.md)
2. [Operator Onboarding](ONBOARDING.md)
3. [Setup Guide](setup-guide.md)
4. [Walkthroughs](walkthroughs.md)
5. [Release Checklist](RELEASE_CHECKLIST.md)
6. [Operator Guide: Improvement Cycles and Docker Kernels](operator-improvement-cycle-and-jupyter.md)
7. [Production Deployment Runbook](operators/production-deployment-runbook.md)
8. [Operator Verification Runbook](operators/operator-verification-runbook.md)
9. [Process Registry Runbook](operators/process-registry-runbook.md)
10. [Connector Boundary Runbook](operators/connector-boundary-runbook.md)
11. [Horizontal Scaling Architecture](operators/horizontal-scaling-architecture.md)
12. [Incident Response Playbooks](operators/incident-response-playbooks.md)
13. [Pricing And Effort Runbook](operators/pricing-and-effort-runbook.md)
14. [Service Level Objectives](operators/service-level-objectives.md)
15. [Use Cases](use-cases.md)
16. [Functionality and Workflows](functionality-and-workflows.md)
17. [API Surface](api-surface.md)

## Runtime Snapshot

- Runtime entry point: `engine/src/agent33/main.py`
- API prefixes: `/health`, `/v1/*`
- Auth model: middleware-enforced auth + scope checks on selected endpoints (dashboard routes are public for local operator visibility)
- Data stores: PostgreSQL/pgvector, Redis, NATS, plus several in-memory services
- Default deployment: Docker Compose stack in `engine/docker-compose.yml`
- Frontend control plane: `frontend/` (served by compose at `http://localhost:3000`)

## Guide Map

| Document | Purpose |
| --- | --- |
| `getting-started.md` | Fastest path from clone to first successful AGENT-33 demo |
| `ONBOARDING.md` | Operator-oriented introduction to the main surfaces, scopes, and first workflows |
| `setup-guide.md` | End-to-end environment setup, auth bootstrap, and first successful requests |
| `walkthroughs.md` | Task-oriented walkthroughs across agents, workflows, memory, review, release, evaluation, autonomy, and improvement APIs |
| `RELEASE_CHECKLIST.md` | Public-launch and release-readiness checklist for security, verification, and operator posture |
| `operator-improvement-cycle-and-jupyter.md` | Current operator path for the improvement-cycle wizard, canonical presets, and Docker-backed Jupyter execution |
| `operators/production-deployment-runbook.md` | Current Kubernetes production rollout, verification, monitoring, and rollback guidance for the shipped deploy baseline |
| `operators/operator-verification-runbook.md` | Canonical authenticated verification order for operator status, doctor, process inventory, and backup safety checks |
| `operators/process-registry-runbook.md` | Current `/v1/processes` contract, restart-to-`interrupted` recovery path, and bounded cleanup guidance |
| `operators/connector-boundary-runbook.md` | Connector middleware order, breaker cooldown policy, retry semantics, and `/v1/connectors` inspection workflow |
| `operators/pricing-and-effort-runbook.md` | Auditable pricing-catalog provenance, live effort-router thresholds, and fast-path verification steps |
| `operators/horizontal-scaling-architecture.md` | Current replica-safety contract, state-boundary map, blocking globals, and `P1.2` migration sequence for multi-replica rollout |
| `operators/incident-response-playbooks.md` | First incident-response playbooks for API outages, degraded dependencies, evaluation regressions, and webhook backlog incidents |
| `operators/service-level-objectives.md` | Current internal SLO baseline, error-budget policy, guardrail mapping, and deferred-objective inventory |
| `use-cases.md` | Practical implementation patterns with module requirements and tradeoffs |
| `functionality-and-workflows.md` | Current functionality inventory, lifecycle/state flows, and persistence boundaries |
| `api-surface.md` | Complete endpoint map with auth/scope requirements |

## Legacy and Supporting Material

Existing documents under `engine/docs/` and `core/` remain useful as deep reference material. Use this `docs/` set first when you need current runtime behavior and operational guidance.
