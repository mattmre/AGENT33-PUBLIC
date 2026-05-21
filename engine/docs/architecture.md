# Architecture Overview

## Component Diagram

```
                              +-------------------+
                              |    CLI (typer)    |
                              +--------+----------+
                                       |
            +--------------+  +--------+----------+  +-------------------+
            |  Webhooks /  |->|   FastAPI Server  |->|   Auth Middleware  |
            |  Scheduler   |  |   (api/)          |  |   (security/)     |
            +--------------+  +--------+----------+  +-------------------+
                                       |
                 +---------------------+---------------------+
                 |                     |                     |
        +--------+--------+  +--------+--------+  +--------+--------+
        | Agent Runtime   |  | Workflow Engine  |  |   Memory / RAG  |
        | (agents/)       |  | (workflows/)     |  |   (memory/)     |
        +--------+--------+  +--------+--------+  +--------+--------+
                 |                     |                     |
        +--------+--------+  +--------+--------+  +--------+--------+
        |   LLM Router    |  |   DAG Builder   |  |   Embeddings    |
        |   (llm/)        |  |   + Actions     |  |   + pgvector    |
        +--------+--------+  +--------+--------+  +--------+--------+
                 |                     |                     |
        +--------+--------+  +--------+--------+  +--------+--------+
        | Ollama | OpenAI |  | Checkpoint      |  | Long-term Store |
        +--------+--------+  | (PostgreSQL)    |  | (PostgreSQL)    |
                              +--------+--------+  +-----------------+
                                       |
        +------------------------------+------------------------------+
        |                              |                              |
+-------+--------+            +--------+--------+           +--------+--------+
|   Tools        |            |   Messaging     |           |  Observability  |
|   (tools/)     |            |   (messaging/)  |           |  (observability)|
+-------+--------+            +--------+--------+           +--------+--------+
        |                              |                             |
+-------+--------+     +----+----+----+----+----+      +----+----+----+----+
| shell, file_ops|     |NATS|Tele|Disc|Slack|WA |      |logs|trace|metrics|
| web_fetch,     |     |Bus |gram|ord |     |   |      |    |     |alerts |
| browser        |     +----+----+----+----+----+      +----+----+--------+
+----------------+
                              +-------------------+
                              |  Automation       |
                              |  (automation/)    |
                              +--------+----------+
                              |                   |
                       +------+------+   +--------+--------+
                       | Scheduler   |   | Sensors         |
                       | (APSched)   |   | file_change,    |
                       +-------------+   | freshness,event |
                                         +-----------------+

                         +------------------+
                         | Infrastructure   |
                         +--+------+-----+--+
                            |      |     |
                     +------++ +---+--+ +-+------+
                     |Postgres| |Redis | | NATS  |
                     |pgvector| |      | |JetStr.|
                     +--------+ +------+ +-------+
```

## Module Dependency Graph

The following shows the import dependencies between top-level modules. Arrows point from the importing module to the module it depends on.

```
api  -----> agents, workflows, security, memory, config
agents ---> llm, memory, config
workflows -> agents, tools, config
llm ------> config
memory ---> config (embeddings, pgvector, redis)
security --> config
messaging -> config
automation > workflows, messaging, config
observability -> config
tools -----> security (allowlists, governance)
cli -------> api (HTTP client)
```

Key design constraints:

- **No circular imports**: The dependency graph is a DAG. Lower-level modules (config, llm, security) never import higher-level modules (api, workflows).
- **Protocol-based decoupling**: `llm.base.LLMProvider`, `tools.base.Tool`, and `messaging.base` define `Protocol` classes so that concrete implementations can be swapped without changing callers.
- **Config is leaf-level**: `config.py` depends only on `pydantic_settings` and is imported by every other module.

## Data Flow

1. **Request arrives** via the API, CLI, webhook, or scheduler trigger.
2. **Auth middleware** intercepts the request. Public paths (`/health`, `/docs`, `/redoc`, `/openapi.json`) pass through. All other paths require either a `Bearer <jwt>` token or an `X-API-Key` header. On success, the decoded `TokenPayload` is attached to `request.state.user`.
3. **Route handler** validates the request body using Pydantic models and dispatches to the appropriate service layer.
4. **Workflow engine** (if triggered) loads the workflow definition (JSON/YAML), builds a DAG of steps via `DAGBuilder`, and resolves the topological execution order into parallel groups.
5. **Steps execute** according to the execution mode:
   - **Sequential**: Steps run one at a time in definition order.
   - **Parallel**: Steps run concurrently up to `parallel_limit` using `asyncio.Semaphore`.
   - **Dependency-aware**: The DAG is partitioned into parallel groups where all dependencies are satisfied before a group starts.
6. Each `invoke-agent` step delegates to the **Agent Runtime**, which:
   - Loads the `AgentDefinition` from the registry.
   - Constructs the prompt from templates, resolving `{{ expressions }}` against the workflow state.
   - Optionally queries the **RAG pipeline** to augment the prompt with relevant context from long-term memory.
   - Sends the prompt to the **LLM Router**.
7. **LLM Router** selects the configured provider (Ollama for local inference, OpenAI for cloud) and forwards the request. The response includes token usage metrics.
8. **Results flow back** through the workflow engine, which merges step outputs into the workflow state (`state[step.id] = result.outputs`) for use by downstream steps via expressions.
9. **Checkpoints** are persisted to PostgreSQL so workflows can resume after failures.
10. **Events** are published to the NATS JetStream bus for cross-module communication (e.g., `workflow.completed`, `agent.invoked`).
11. **Observability** captures structured logs (structlog), distributed traces, metrics, and data lineage at each stage.

## Request Lifecycle

A detailed trace of an HTTP request from client to response:

```
Client
  |
  | POST /api/v1/workflows/my-flow/execute  {"query": "..."}
  v
FastAPI (uvicorn)
  |
  | 1. ASGI middleware chain
  v
AuthMiddleware.dispatch()
  |
  | 2. Extract Bearer token or X-API-Key header
  | 3. verify_token() or validate_api_key()
  | 4. Attach TokenPayload to request.state.user
  v
workflows.router (route handler)
  |
  | 5. Validate request body (Pydantic)
  | 6. Load WorkflowDefinition from file
  v
WorkflowExecutor.execute(inputs)
  |
  | 7. Build DAG, compute parallel groups
  | 8. For each group, for each step:
  v
WorkflowExecutor._execute_step(step, state)
  |
  | 9. Evaluate condition (ExpressionEvaluator)
  | 10. Resolve input expressions against state
  | 11. Dispatch to action handler
  v
invoke_agent.execute(agent="greeter", inputs={...})
  |
  | 12. AgentRegistry.get("greeter") -> AgentDefinition
  | 13. Build ChatMessage list (system + user prompts)
  | 14. (Optional) RAGPipeline.query() -> augmented prompt
  v
ModelRouter.complete(messages, model="llama3.2")
  |
  | 15. Select OllamaProvider or OpenAIProvider
  | 16. HTTP POST to Ollama/OpenAI API
  | 17. Parse LLMResponse (content, token counts)
  v
  ... (results bubble back up through each layer)
  v
JSON Response -> Client
```

## Data Model Overview

### Agent Models (`agents/definition.py`)

```
AgentDefinition
  ├── name: str                    # Unique identifier (kebab-case)
  ├── version: str                 # Semantic version
  ├── role: AgentRole              # orchestrator | director | worker | reviewer | researcher | validator
  ├── description: str
  ├── capabilities: [AgentCapability]  # file-read, code-execution, web-search, etc.
  ├── inputs: {name: AgentParameter}
  ├── outputs: {name: AgentParameter}
  ├── dependencies: [AgentDependency]
  ├── prompts: AgentPrompts        # system, user, examples
  ├── constraints: AgentConstraints # max_tokens, timeout, retries, parallel_allowed
  └── metadata: AgentMetadata      # author, created, updated, tags
```

### Workflow Models (`workflows/definition.py`)

```
WorkflowDefinition
  ├── name: str
  ├── version: str
  ├── description: str
  ├── triggers: WorkflowTriggers   # manual, on_change, schedule (cron), on_event
  ├── inputs: {name: ParameterDef}
  ├── outputs: {name: ParameterDef}
  ├── steps: [WorkflowStep]       # At least one step required
  │     ├── id: str
  │     ├── action: StepAction     # invoke-agent | run-command | validate | transform |
  │     │                          # conditional | parallel-group | wait
  │     ├── agent: str?            # For invoke-agent
  │     ├── command: str?          # For run-command
  │     ├── inputs / outputs: dict
  │     ├── condition: str?        # Jinja expression for conditional execution
  │     ├── depends_on: [str]      # Step IDs this step depends on
  │     ├── retry: StepRetry       # max_attempts, delay_seconds
  │     ├── steps: [WorkflowStep]  # Sub-steps for parallel-group
  │     └── then / else: [WorkflowStep]  # Branches for conditional
  ├── execution: WorkflowExecution # mode, parallel_limit, continue_on_error, fail_fast, timeout, dry_run
  └── metadata: WorkflowMetadata
```

### Execution Models (`workflows/executor.py`)

```
StepResult
  ├── step_id: str
  ├── status: str          # "success" | "failed" | "skipped"
  ├── outputs: dict
  ├── error: str?
  └── duration_ms: float

WorkflowResult
  ├── outputs: dict         # Merged outputs from all successful steps
  ├── steps_executed: [str]
  ├── step_results: [StepResult]
  ├── duration_ms: float
  └── status: WorkflowStatus  # success | failed | partial | skipped
```

### LLM Models (`llm/base.py`)

```
ChatMessage(role: str, content: str)
LLMResponse(content: str, model: str, prompt_tokens: int, completion_tokens: int)
LLMProvider (Protocol): complete(), list_models()
```

### Tool Models (`tools/base.py`)

```
ToolContext(user_scopes, command_allowlist, path_allowlist, domain_allowlist, working_dir)
ToolResult(success: bool, output: str, error: str)
Tool (Protocol): name, description, execute()
```

### Security Models (`security/auth.py`)

```
TokenPayload(sub: str, scopes: [str], exp: int)
```

## Concurrency Model

AGENT-33 is built on Python's `asyncio` event loop, running inside Uvicorn's async workers.

### Request handling

FastAPI handles each HTTP request as an async coroutine on the event loop. There is no thread pool for request handling; all I/O (database queries, HTTP calls to Ollama, NATS publish) is non-blocking.

### Workflow parallelism

The `WorkflowExecutor` supports three execution modes:

- **Sequential**: Steps execute one at a time using `await`.
- **Parallel / Dependency-aware**: The DAG is partitioned into groups. Within each group, steps run concurrently using `asyncio.gather()`, gated by an `asyncio.Semaphore(parallel_limit)` (default 4, max 32). Groups execute sequentially -- the next group starts only after all tasks in the current group finish.

### NATS messaging

The `NATSMessageBus` uses the `nats-py` async client. Subscriptions register async callbacks that run on the event loop. JetStream provides at-least-once delivery for durable subscriptions.

### Key constraints

- All LLM calls are I/O-bound (HTTP to Ollama/OpenAI), so async concurrency is effective.
- CPU-bound work (e.g., embedding computation) should be offloaded to a thread pool using `asyncio.to_thread()`.
- The `parallel_limit` setting prevents overwhelming external services with too many concurrent requests.

## Storage Architecture

### PostgreSQL

| Table / Concept | Purpose |
|---|---|
| **workflow_checkpoints** | Persisted workflow state for resumption after failures. Managed by custom checkpoint manager in `workflows/checkpoint.py`. |
| **embeddings** (pgvector) | Vector embeddings for long-term memory and RAG. Uses the `pgvector` extension with `vector` column type for cosine similarity search. |
| **sessions** | Session metadata and state for multi-turn conversations. |
| **data_lineage** | Tracks the provenance of data through workflow steps (`observability/lineage.py`). |

Migrations are managed by Alembic:

```bash
cd engine
alembic revision --autogenerate -m "description"
alembic upgrade head
```

### Redis

| Key Pattern | Purpose |
|---|---|
| `session:{id}` | Short-term memory and conversation context (`memory/short_term.py`, `memory/session.py`) |
| `cache:*` | Response caching and deduplication |
| `rate_limit:*` | Per-user/per-endpoint rate limiting |

### NATS Subjects

| Subject | Purpose |
|---|---|
| `agent33.workflow.started` | Published when a workflow execution begins |
| `agent33.workflow.completed` | Published when a workflow finishes (success or failure) |
| `agent33.agent.invoked` | Published when an agent is invoked within a workflow |
| `agent33.sensor.*` | Sensor events (file changes, freshness checks) |
| `agent33.alert.*` | Alert notifications from the observability module |

JetStream is enabled for durable streams, ensuring events are not lost if a subscriber is temporarily unavailable.

## Security Architecture

### Authentication flow

```
Client Request
  |
  +-- Authorization: Bearer <jwt>  -->  verify_token(jwt)
  |                                       |
  |                                       +-- jwt.decode() with JWT_SECRET + HS256
  |                                       +-- Returns TokenPayload(sub, scopes, exp)
  |
  +-- X-API-Key: a33_xxxxx  --------->  validate_api_key(key)
  |                                       |
  |                                       +-- SHA-256 hash lookup in memory store
  |                                       +-- Returns TokenPayload or None
  |
  +-- (neither) ---------------------->  401 Missing authentication credentials
```

### Public paths (no auth required)

- `/health`
- `/docs`, `/redoc`, `/openapi.json`

### Encryption at rest

Sensitive session data is encrypted using Fernet symmetric encryption (`security/encryption.py`). The encryption key is configured via `ENCRYPTION_KEY`. If the key is empty, encryption is disabled (suitable for development only).

### Secret management

The `security/vault.py` module provides a unified interface for accessing secrets that may come from environment variables, encrypted files, or external vault services.

### Tool governance

When agents invoke tools (shell commands, file operations, web fetches, browser actions), the `tools/governance.py` module enforces allowlists:

- **Command allowlist**: Only explicitly allowed shell commands can execute.
- **Path allowlist**: File operations are restricted to allowed directories.
- **Domain allowlist**: Web fetch and browser tools can only access allowed domains.

These allowlists are configured per-agent via `ToolContext` and enforced before any tool execution.

### Prompt injection detection

The `security/injection.py` module scans user inputs for known prompt injection patterns before they reach the LLM.

## Extension Points

### Adding a new LLM provider

1. Create a module in `engine/src/agent33/llm/` implementing the `LLMProvider` protocol (see `base.py`).
2. Implement `async def complete(messages, *, model, temperature, max_tokens) -> LLMResponse`.
3. Implement `async def list_models() -> list[str]`.
4. Register it in `ModelRouter` with a provider name.

### Adding a new agent

1. Create a JSON file in `engine/agent-definitions/` matching the `AgentDefinition` schema.
2. The `AgentRegistry` discovers it on startup.
3. Use roles: `orchestrator`, `director`, `worker`, `reviewer`, `researcher`, `validator`.
4. Declare capabilities to control which tools the agent can use.

### Adding a new workflow

1. Create a JSON or YAML file in `engine/workflow-definitions/`.
2. Define steps using available actions: `invoke-agent`, `run-command`, `validate`, `transform`, `conditional`, `parallel-group`, `wait`.
3. Use `depends_on` to express step dependencies for DAG-based execution.
4. Use `{{ step_id.output_field }}` expressions to reference outputs from previous steps.

### Adding a new tool

1. Create a module in `engine/src/agent33/tools/builtin/` implementing the `Tool` protocol.
2. Implement the `name`, `description` properties and `async def execute(params, context) -> ToolResult`.
3. Register it in `tools/registry.py`.
4. Add governance rules if the tool accesses external resources.

### Adding a new sensor

1. Implement the sensor in `engine/src/agent33/automation/sensors/`.
2. Register it with the `SensorRegistry` at application startup.

### Adding a new messaging integration

1. Create a module in `engine/src/agent33/messaging/` following the pattern of `telegram.py`, `discord.py`, or `slack.py`.
2. If the integration requires additional dependencies, add them to the `[project.optional-dependencies]` section in `pyproject.toml`.

### Database migrations

Managed by Alembic. To create a new migration:

```bash
cd engine
alembic revision --autogenerate -m "description"
alembic upgrade head
```
