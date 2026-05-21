# Glossary

Alphabetical definitions for the terms used across AGENT-33's
documentation and source. Each entry includes a one-line definition and
a pointer to where the concept is described in more depth.

## A

**Adapter.** A class that translates between AGENT-33's internal
protocols and an external system. Examples: LLM provider adapters
(Ollama, OpenAI-compatible), messaging adapters (Telegram, Slack), code
execution adapters (CLI subprocess). See
[`docs/architecture/components.md`](architecture/components.md).

**Agent.** A configured behavior — system prompt, allowed tools, model
assignment, iteration policy — defined as a JSON file under
`engine/agent-definitions/`. See [`docs/concepts.md`](concepts.md).

**Agent registry.** The startup-time index of all loaded agent
definitions. Routes resolve agent names through the registry. See
[`docs/architecture/agents.md`](architecture/agents.md).

**Agent runtime.** The iterative or streaming loop that turns an agent
plus an input into an output. See [`docs/concepts.md`](concepts.md).

**Alembic.** The database migration tool used for the PostgreSQL schema.
Migrations live in `engine/alembic/versions/`.

**APScheduler.** The cron-style scheduler that drives knowledge
ingestion jobs.

**Autonomy budget.** A runtime envelope describing the file, command,
and network scope an agent is allowed to use, plus stop conditions. See
[`docs/concepts.md`](concepts.md).

## B

**BM25.** A lexical ranking function used as one half of the hybrid
retrieval pipeline. The other half is vector similarity; they are
combined through reciprocal rank fusion.

**Browser agent.** The reference agent that drives the headless browser
tool. Useful for tasks that require navigating live web pages.

## C

**Candidate asset.** An external resource (skill, agent, pack, knowledge
item) submitted to the platform but not yet published. Lives in a
governed lifecycle. See [`docs/concepts.md`](concepts.md).

**Checkpoint.** A persisted record of a workflow's state after a step
completes. Lets a crashed workflow resume from the last good point.

**CLI.** The `agent33` command-line tool. Installable via
`pip install -e ".[dev]"`. See [`docs/cli-reference.md`](cli-reference.md).

**Code execution.** The subsystem (`engine/src/agent33/execution/`) that
runs code under a sandbox contract. Used by workflow steps that need to
execute generated code.

**Conditional branch.** A workflow step that selects one of several next
steps based on an expression. See
[`docs/architecture/workflows.md`](architecture/workflows.md).

**Confidence label.** A tag on a candidate asset indicating how confident
the submitter or the validator is in its quality. Values: low, medium,
high.

## D

**DAG.** Directed acyclic graph. The shape of every workflow.

**DLQ.** Dead-letter queue. Where messages go when a downstream handler
repeatedly fails to process them. See
[`engine/src/agent33/automation/`](../engine/src/agent33/automation/).

## E

**Embedding.** A vector representation of text used by the long-term
memory and the hybrid retrieval pipeline.

**Embedding provider.** The adapter that produces embeddings. The active
provider is chosen at startup by configuration.

**Engine.** The Python/FastAPI runtime. Lives under `engine/`.

**Evaluation.** The subsystem that runs golden tasks and golden cases,
computes metrics, and detects regressions.

**Expression evaluator.** The small language used in workflow step
references — for example `${step.output.field}`. See
[`docs/architecture/workflows.md`](architecture/workflows.md).

## F

**Failure taxonomy.** The 10-category classification applied to trace
failures so they can be grouped and reasoned about. See
[`docs/architecture/observability.md`](architecture/observability.md).

**FastAPI.** The Python web framework AGENT-33's engine is built on.

**Frontend.** The React/TypeScript operator console under `frontend/`.

## G

**Golden case.** A specific test scenario used by the evaluation suite
with known inputs and expected outputs.

**Golden task.** A high-level evaluation target made up of one or more
golden cases.

**Governance.** The tool-policy layer that decides which tenants can
call which tools under which conditions.

## H

**Headless browser.** The browser automation tool that drives Chromium
without a visible window.

**Health check.** A liveness probe on a subsystem. Each messaging
adapter, each model provider, and each subsystem in the lifespan
exposes a health check.

**HPA.** Horizontal Pod Autoscaler. The production Kubernetes overlay
wires the engine deployment to one.

**Hybrid search.** Retrieval that combines BM25 (lexical) with vector
similarity (semantic) via reciprocal rank fusion.

## I

**Ingestion.** The candidate-asset lifecycle: submitted → triaged →
validating → published → revoked. See
[`engine/src/agent33/ingestion/`](../engine/src/agent33/ingestion/).

**Iterative invocation.** Agent runtime mode where each step returns
when the loop completes. The other mode is streaming.

## J

**JWT.** JSON Web Token. One of the two supported authentication
mechanisms. The other is API key.

## K

**Kernel container.** A sandboxed Jupyter-style execution context.
Documented in
[`docs/runbooks/jupyter-kernel-containers.md`](runbooks/jupyter-kernel-containers.md).

**Knowledge ingestion.** The subsystem that pulls in external content
from RSS, GitHub, web pages, and folders on a schedule.

## L

**L0 / L1 / L2.** The three levels of progressive disclosure for skills:
summary, outline, full body.

**Lifespan.** The FastAPI lifespan handler that initializes subsystems
in order at startup and unwinds them at shutdown.

**Lineage.** Parent-child relationships between traces. Lets a single
workflow's events be assembled into a tree.

**LLM router.** The layer that picks a provider + model for a given
agent call. See [`docs/architecture/components.md`](architecture/components.md).

**Long-term memory.** The pgvector-backed store that holds embedded
context across sessions, scoped to the tenant.

## M

**Manifest.** A pack's declaration of its name, version, contents, and
dependencies.

**MCP.** Model Context Protocol. AGENT-33 integrates as both a server
(exposing its surface) and a client (consuming external MCP servers).
See [`docs/architecture/mcp-integration.md`](architecture/mcp-integration.md).

**Messaging adapter.** A driver for a chat platform (Telegram, Discord,
Slack, WhatsApp).

**Metric.** A measurable value emitted by the engine. Metric names
follow the `agent33_*` prefix.

**Model router.** Same as LLM router.

**mypy.** The static type checker. Runs in strict mode in CI.

## N

**NATS.** The lightweight event bus used for asynchronous communication
between subsystems.

## O

**Ollama.** A local LLM runtime. The default provider in the Docker
Compose stack.

**Outcome.** A recorded result of an agent or workflow run, used by the
impact dashboard and regression detection. See
[`docs/concepts.md`](concepts.md).

**Override.** An explicit, audited deviation from a policy. Overrides
leave a record in the audit trail.

## P

**Pack.** A distributable bundle of skills, agents, tools, and policy
with a manifest and an integrity hash. See [`docs/concepts.md`](concepts.md).

**PackHub.** The optional remote registry for packs.

**Parallel group.** A workflow step that runs multiple child steps in
parallel and joins their results.

**pgvector.** The PostgreSQL extension that backs long-term memory.

**Preflight check.** An autonomy budget check applied before the agent
runs, as opposed to the runtime enforcement that happens during
execution.

**Progressive disclosure.** The L0/L1/L2 mechanism for showing the agent
only as much skill content as it needs.

**Provider catalog.** The auto-registered list of available LLM
providers, populated from environment variables at startup.

## Q

**QA agent.** The reference agent that reviews output for correctness.

## R

**RAG.** Retrieval-augmented generation. The pipeline that pulls
relevant memory into the agent's prompt before the LLM call.

**Redis.** The in-memory store used for ephemeral state.

**Registry.** A startup-time index. Multiple registries exist: agent
registry, skill registry, tool registry, pack registry, provider
registry.

**Release lifecycle.** The state machine that governs release artifacts:
planned → frozen → rc → validating → released → rolled_back.

**Replay.** The ability to re-execute a past run from its trace stream.

**Reciprocal rank fusion (RRF).** The algorithm that combines BM25 and
vector similarity scores into a single ranking.

**Retention policy.** A rule that decides how long traces and outcomes
are kept before being summarized and eventually purged.

**Rollback.** The release lifecycle transition that returns the system
to a previous release artifact.

**ruff.** The Python linter and formatter. Replaces black, isort, and
flake8 for this project.

## S

**Sandbox contract.** The structured input to the code-execution
subsystem describing what the executed code is allowed to do.

**Session.** A conversational unit of state — tenant, model, short-term
memory, long-term memory scope, trace stream.

**Session summarizer.** The component that compresses short-term memory
when it grows past a threshold.

**Skill.** A documented capability (Markdown or YAML) with frontmatter
and a body. Participates in progressive disclosure.

**Skill injector.** The component that resolves which skills to include
in a given agent invocation and at which level (L0/L1/L2).

**SkillsBench.** The third-party benchmark AGENT-33 runs to measure
skill-driven capability. Smoke tier runs in CI; full tier runs weekly.

**SSE.** Server-sent events. The streaming transport for agent
transcripts.

**Stop condition.** An autonomy-budget rule that ends an agent run when
hit (max steps, max wall clock, max cost).

**Streaming invocation.** Agent runtime mode where events are yielded
as they happen. Used by the operator console for live transcripts.

**structlog.** The Python structured logging library used throughout
the engine.

## T

**Tenant.** An isolated namespace. Every piece of state is scoped to a
tenant. See [`docs/concepts.md`](concepts.md).

**Tool.** A function an agent can call. Validated by JSON Schema at
registration and at invocation. See [`docs/concepts.md`](concepts.md).

**Tool governance.** The policy layer that decides which tenants can
call which tools.

**Topological sort.** The algorithm used to order workflow steps for
execution.

**Trace.** An audit record of an execution. See
[`docs/concepts.md`](concepts.md).

**Trust label.** A tag on a candidate asset indicating its source:
untrusted, community, maintainer, first-party.

## U

**Upsert.** Insert-or-replace. The persistence pattern used by the
ingestion subsystem and several others.

## V

**Vector store.** The pgvector table that holds embedded long-term
memory.

## W

**Workflow.** A DAG of steps. See [`docs/concepts.md`](concepts.md).

**Workflow bridge.** The component that lets a workflow step invoke an
agent through the registry.

## See also

- [`docs/concepts.md`](concepts.md) — extended explanations of these terms
- [`ARCHITECTURE.md`](../ARCHITECTURE.md) — system overview
