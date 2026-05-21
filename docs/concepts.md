# Concepts

This document explains the mental models behind AGENT-33. If you have
read `ARCHITECTURE.md`, this is the conceptual layer underneath: what each
abstraction is, why it exists, and how it relates to the others.

The platform is built from a small set of core concepts that compose. Once
you understand them, everything else in the codebase is a refinement.

## Tenant

A **tenant** is an isolated namespace. Two tenants on the same engine
instance cannot see each other's data, sessions, agents, packs, traces,
or memory.

Tenancy is propagated from the authentication layer down through every
service. An API key or JWT resolves to a tenant on every request, and
`tenant_id` flows into the persistence layer as a column, into the
in-memory caches as a key prefix, and into the trace pipeline as a tag.

The point of having tenants is that one engine can serve many independent
users or teams without their work bleeding together. Even on a
single-operator install where there is only one real tenant, the model
holds: code that scopes by `tenant_id` is the same code that scales to a
hundred tenants.

## Agent

An **agent** is a configured behavior: a system prompt, a set of allowed
tools, a model assignment, and an iteration policy. Agents are defined
in JSON files under `engine/agent-definitions/` and auto-loaded at
startup.

The reference agents that ship in the box are:

- `orchestrator` — decomposes a goal into a plan
- `director` — picks the next step from a plan
- `code-worker` — writes or edits code
- `qa` — reviews output for correctness
- `researcher` — searches and synthesizes
- `browser-agent` — drives the headless browser

You can author your own agents by adding a JSON file in the definitions
directory or by pushing one through the agent registry API. An agent is a
small piece of configuration — what makes it powerful is the runtime that
loads it.

## Agent runtime

The **agent runtime** is the loop that turns an agent definition plus an
input into an output. Each iteration:

1. Constructs a prompt from the agent's system message, the conversation
   so far, the relevant skill context (progressive disclosure), and the
   tools the agent is allowed to call.
2. Calls the LLM through the model router.
3. Parses the response. If the response calls a tool, the runtime
   validates the call against the tool's JSON Schema, executes it under
   the tool's policy, and feeds the result back into the next iteration.
4. Stops when the agent emits a final answer, hits its iteration cap, or
   trips an autonomy budget.

The runtime supports two modes: iterative (each step returns when the
loop completes) and streaming (each step yields events as they happen).
Streaming is what the operator console uses for live transcripts.

## Workflow

A **workflow** is a directed acyclic graph of steps. Each step is one of
a handful of action types: invoke an agent, run a command, validate a
result, transform data, branch on a condition, fan out in parallel,
wait, or execute code in a sandbox.

The workflow engine:

- Validates the DAG (no cycles, all dependencies reachable).
- Topologically sorts the steps and starts the ones with no unresolved
  dependencies.
- Runs steps in parallel where the DAG allows.
- Applies per-step retry and timeout policies.
- Persists a checkpoint after each step so a crashed workflow can resume.
- Carries state through an expression evaluator: later steps can
  reference earlier steps' outputs by name.

Workflows are how AGENT-33 makes multi-agent behavior reproducible.
Instead of an open-ended conversation with one model, a workflow declares
the steps, the order, and the success conditions up front.

## Skill

A **skill** is a piece of documented capability. It is a Markdown or YAML
file with a frontmatter header that describes when the skill applies and
a body that explains how to use it.

Skills exist because LLMs are better when they are told what to do than
when they are asked to figure it out. Instead of stuffing every possible
instruction into every system prompt, AGENT-33 keeps skills as separate
documents and injects only the ones an agent needs.

Skills participate in **progressive disclosure** at three levels:

- **L0 (summary)** — one-line description. Cheap to include. The agent
  sees a list of L0 summaries and picks which skills to expand.
- **L1 (outline)** — structured outline of the skill. Included when the
  agent expresses interest.
- **L2 (full body)** — complete instructions. Included only when the
  agent commits to using the skill.

The point is that the agent sees only as much skill content as it needs
for the current step, which keeps the prompt small and the LLM focused.

## Pack

A **pack** is a distributable bundle of skills, agents, tools, and policy.
Packs are how AGENT-33 ships capability between installations.

A pack has:

- A manifest declaring its name, version, dependencies, and contents.
- One or more skills, agents, or tools.
- An integrity hash (SHA-256) that the local registry verifies on load.
- Optional policy: tool allowlists, autonomy budgets, prompt addenda.

You can install a pack from a local file, from the optional PackHub
registry, or by importing one another agent shares with you over a
workflow. Packs are the unit of capability exchange in the ecosystem.

## Tool

A **tool** is a function an agent can call. Each tool has:

- A name.
- A JSON Schema describing its input.
- A handler that performs the work.
- A policy: which tenants can call it, under what budget, and what
  audit record to produce.

Tools are validated at registration (the schema must parse) and again at
invocation (the LLM's tool call must match the schema). A tool call that
does not match its schema is rejected before it reaches the handler. A
tool that is not on the active allowlist is rejected before it is even
offered to the LLM.

Built-in tools cover shell, file operations, HTTP fetch, and headless
browser control. Custom tools are added either by registering them
through the API or by shipping them in a pack.

## Trace

A **trace** is the audit record of a single execution. Every agent run,
every tool call, every workflow step produces trace events with:

- Timestamp.
- Tenant.
- Subject (which agent, which workflow, which tool).
- Inputs and outputs.
- Status and, on failure, a category from the failure taxonomy.
- Lineage: a parent trace ID so events can be assembled into a tree.

Traces are how operators answer questions after the fact. "Why did this
workflow fail?" — read the trace. "What did agent X do last Tuesday at
14:00?" — read the trace. The trace pipeline applies retention policies
so old traces are summarized and eventually purged according to your
configuration.

## Autonomy budget

An **autonomy budget** is a runtime envelope for what an agent is allowed
to do. A budget has:

- A file scope (which paths the agent can read or write).
- A command scope (which shell commands the agent can run).
- A network scope (which hosts the agent can reach).
- A lifecycle state (draft → active → completed).
- Stop conditions (max steps, max wall clock, max cost).

Budgets are checked twice. **Preflight** checks the budget when the agent
is launched, before any step runs, and rejects requests that the budget
cannot satisfy. **Runtime enforcement** checks each tool call against
the active budget and refuses calls that step outside it.

The point of budgets is that an operator can give an agent latitude to
work without giving it unbounded access. The budget is the social
contract: "you have this much authority for this much work."

## Outcome

An **outcome** is the recorded result of an agent or workflow run from
the operator's perspective: did it accomplish the goal, partially
accomplish it, or fail. Outcomes are tagged with the agent, the pack,
the workflow, and the tenant, and they accumulate over time.

Outcomes feed two surfaces:

- **The impact dashboard**, which aggregates outcomes into estimates of
  what each pack and agent is contributing.
- **Evaluation regression detection**, which compares outcome rates over
  rolling windows so a sudden drop in success rate is visible.

Outcomes are how AGENT-33 closes the loop between "we shipped this
capability" and "this capability is actually working."

## Candidate asset

A **candidate asset** is an external resource — a skill, an agent, a
pack, a piece of knowledge — that has been submitted to the platform but
has not yet been published. Candidates live in a governed lifecycle:

```
submitted → triaged → validating → published
                                  → revoked
```

The lifecycle exists because external contributions need a review path
before they are visible to running agents. Candidates carry a confidence
label (low / medium / high) and a trust label (untrusted / community /
maintainer / first-party) so reviewers can see the provenance at a
glance.

The candidate ingestion mailbox is the deposit point: external operators
post events, the mailbox routes them, and the intake pipeline drives
them through the lifecycle.

## Session

A **session** is a unit of conversational state. A session has:

- A tenant.
- A model assignment.
- A short-term memory buffer.
- A long-term memory store (pgvector-backed, scoped to the session and
  the tenant).
- A trace stream.

Sessions are how the operator console keeps a coherent transcript across
multiple agent invocations. They are also how the memory subsystem keeps
context relevant: a session-scoped memory means an agent does not pollute
its short-term context with unrelated history from another conversation.

## Model router

The **model router** is the layer that picks which LLM handles a given
call. It reads:

- The agent's preferred model assignment.
- The provider catalog (which providers are configured and healthy).
- The effort-routing parameters resolved from the input.

It returns a concrete provider + model, and the agent runtime makes the
call through that provider's adapter.

The router exists so that swapping providers — Ollama for OpenAI for
Anthropic for a self-hosted llama.cpp instance — does not require
rewriting agents. The agent declares what it needs; the router decides
where to send it.

## Memory

**Memory** in AGENT-33 is two layers.

**Short-term memory** is a per-session buffer. It holds the last N turns
of conversation in raw form and is summarized by the session
summarizer when it grows past a threshold.

**Long-term memory** is a pgvector-backed store, scoped to the tenant and
the session. Embeddings are computed by the active embedding provider,
cached in an LRU, and chunked with a token-aware chunker (1200 tokens
by default).

Retrieval combines a BM25 lexical index with the vector store through
reciprocal rank fusion. The hybrid result feeds the RAG pipeline, which
feeds the agent runtime's prompt construction.

## Putting it together

A typical operator workflow:

1. The operator opens the console and starts a **session**.
2. The console calls an **agent** through the engine.
3. The engine runs the **agent runtime** loop. Each iteration consults
   **memory**, picks **skills** through progressive disclosure, and calls
   **tools** that pass the **autonomy budget** check.
4. When the agent kicks off a multi-step plan, a **workflow** is
   created. Each step is itself an agent invocation or another action.
5. Every step emits **traces**. When the workflow finishes, an
   **outcome** is recorded.
6. The operator looks at the **trace** tree to understand what happened
   and at the **impact dashboard** to see how the system is performing
   over time.

Every one of these concepts is scoped to a **tenant**, and every change
that touches them flows through the conventions described in
[`CONVENTIONS.md`](CONVENTIONS.md).

## See also

- [`ARCHITECTURE.md`](../ARCHITECTURE.md) — high-level system shape
- [`docs/architecture/`](architecture/) — per-subsystem deep dives
- [`docs/glossary.md`](glossary.md) — short definitions of all terms
- [`docs/examples.md`](examples.md) — worked scenarios
