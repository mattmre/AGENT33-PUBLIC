# AGENT-33 Documentation

Welcome to the AGENT-33 documentation set. This index is the canonical entry point for operators, integrators, and contributors. Start with the quick-navigation links if you already know what you need; otherwise work through the numbered sections in order — they progress from first-time setup to advanced architecture and reference material.

## Quick navigation

- [Installation](../INSTALL.md)
- [Architecture overview](../ARCHITECTURE.md)
- [Quick start](../README.md#quick-start)
- [API reference](api-reference.md)
- [Changelog](../CHANGELOG.md)

## 1. Getting started

New to AGENT-33? Read these in order to get a working deployment and your first authenticated request.

- [Getting started](getting-started.md) — Fastest path from a fresh checkout to a running demo, including health checks and JWT minting.
- [Setup guide](setup-guide.md) — End-to-end local setup with prerequisites, environment variables, and Ollama startup modes.
- [Operator onboarding](ONBOARDING.md) — Operator-oriented tour of the four primary surfaces (control plane, runtime API, CLI, traces).
- [Walkthroughs](walkthroughs.md) — Task-oriented walkthroughs across agents, workflows, memory, review, release, evaluation, autonomy, and improvement.
- [Examples](examples.md) — Realistic end-to-end scenarios with commands, expected output, and verification steps.
- [Use cases](use-cases.md) — Implementation patterns mapped to the current runtime surface, with module requirements and tradeoffs.

## 2. Core concepts

Mental models for the abstractions that compose into the platform.

- [Concepts](concepts.md) — Tenants, agents, workflows, skills, packs, tools, memory, and how they relate.
- [Glossary](glossary.md) — Alphabetical definitions of terms used across documentation and source.
- [Conventions](CONVENTIONS.md) — Repository layout, change-flow expectations, and contribution standards.
- [Functionality and workflows](functionality-and-workflows.md) — Current behavior map: runtime architecture, lifecycle/state flows, and persistence boundaries.

## 3. Architecture

Deep dives into the design of each subsystem.

- [Architecture directory](architecture/) — Full architecture catalog covering system overview, components, data flow, agents, workflows, packs and skills, security model, multi-tenancy, observability, storage, messaging, MCP integration, deployment topologies, help assistant, API surface, and architecture decision records.

## 4. Operator runbooks

Day-2 operations and incident response. These runbooks describe surfaces that are already shipped and verified on `main`.

- [Operator manual](operator-manual.md) — Reference for starting and stopping the engine, watching agents and workflows, managing tenants, governing tools, and handling common operational tasks.
- [Operators directory](operators/) — Production-focused runbooks covering deployment, verification, scaling, incident response, SLOs, and more (production deployment, agent OS runtime, operator verification, process registry, connector boundary, horizontal scaling, incident response playbooks, pricing and effort, service level objectives, security audit checklist, voice daemon).
- [Runbooks directory](runbooks/) — Targeted runbooks for Jupyter kernel containers and Kubernetes secret rotation.
- [Operator improvement cycle and Jupyter](operator-improvement-cycle-and-jupyter.md) — Operator path for the improvement-cycle wizard, canonical workflow presets, and Docker-backed Jupyter execution.
- [Troubleshooting](troubleshooting.md) — Indexed failure modes with pointers to `/health`, container logs, `/v1/traces`, and `var/` artifacts.
- [Upgrade guide](upgrade-guide.md) — Version-agnostic upgrade process: backup, upgrade, migrate, smoke, and rollback.

## 5. Workflows, skills, and packs

How to compose, extend, and distribute capability.

- [Default policy packs](default-policy-packs.md) — Connector-boundary policy-pack presets and how they combine with explicit blocklists.
- [Plugins directory](plugins/) — Plugin SDK: how to create, package, and register plugins that contribute tools, skills, agents, and hooks.

## 6. Observability and governance

Inspection, evaluation, and self-improvement.

- [Self-improvement directory](self-improvement/) — Continuous-improvement loop: intake protocol, testing protocol, offline-mode behavior, and community-improvement model.
- [Benchmarks directory](benchmarks/) — Benchmark run metadata and pointers to the `benchmarks` branch for full result sets.
- [Competitive analysis directory](competitive-analysis/) — Autonomous competitive-analysis protocol: how the engine generates competitor dossiers on demand.

## 7. Integration and APIs

External-facing contracts and developer integration. The operator-facing REST API index is the API reference linked from Quick navigation at the top of this page.

- [API surface](api-surface.md) — Source-of-truth map of route modules, public endpoints, and scope checks.
- [CLI reference](cli-reference.md) — Complete `agent33` command reference with arguments and examples.
- [Configuration](configuration.md) — Every environment variable, grouped by subsystem, with type, default, purpose, and example.

## 8. Advanced

Release engineering, contribution workflow, and quality gates.

- [Testing](testing.md) — Test-suite layout, layers, and how to run tests locally.
- [Releasing](releasing.md) — Versioning scheme, release lifecycle, pre-release checklist, and rollback process.
- [Release checklist](RELEASE_CHECKLIST.md) — Public-launch and release-readiness checklist for security, verification, and operator posture.

## 9. Reference

Authoritative lookup material lives in the sections above. The glossary, configuration, API reference, API surface, and CLI reference are the primary lookup surfaces (listed under sections 2 and 7). The architecture directory additionally contains the architecture decision record (ADR) series for load-bearing design decisions.

## Support

- [Discussions](https://github.com/mattmre/AGENT33-PUBLIC/discussions)
- [Security policy](../SECURITY.md)
- [Contributing](../CONTRIBUTING.md)
