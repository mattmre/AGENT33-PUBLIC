# AGENT-33 Workflow Guide

This guide covers the workflow engine: how to define, execute, test, and debug workflows in the AGENT-33 orchestration framework.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Workflow Definition Format](#2-workflow-definition-format)
3. [Step Types](#3-step-types)
4. [Execution Modes](#4-execution-modes)
5. [Expressions](#5-expressions)
6. [Parallel Execution](#6-parallel-execution)
7. [Error Handling](#7-error-handling)
8. [Checkpointing](#8-checkpointing)
9. [State Machine Integration](#9-state-machine-integration)
10. [Triggers](#10-triggers)
11. [Use Cases](#11-use-cases)
12. [Best Practices](#12-best-practices)
13. [Testing Workflows](#13-testing-workflows)

---

## 1. Overview

A **workflow** is a declarative JSON (or YAML) document that describes a sequence of steps to execute. The engine parses the definition into a directed acyclic graph (DAG), resolves dependencies between steps, and executes them according to the chosen execution mode.

### Core Concepts

- **DAG-based execution.** Steps declare dependencies via `depends_on`. The engine builds a DAG using Kahn's algorithm, detects cycles at load time, and groups independent steps for concurrent execution.
- **State passing.** Each step receives inputs and produces outputs. Outputs are stored in a shared state dict keyed by step ID, making them available to downstream steps through Jinja2 expressions.
- **Execution modes.** Choose between sequential, parallel, or dependency-aware execution depending on the nature of the pipeline.
- **Resilience.** Built-in retry, timeout, continue-on-error, and checkpoint/resume capabilities.

### Architecture at a Glance

```
WorkflowDefinition (JSON/YAML)
        |
   DAGBuilder.build()        -- topological sort, cycle detection
        |
   WorkflowExecutor.execute()  -- dispatches steps to action handlers
        |
   Action modules             -- invoke-agent, run-command, validate, ...
        |
   CheckpointManager          -- persists state between steps
```

**Key source files:**

| File | Purpose |
|------|---------|
| `engine/src/agent33/workflows/definition.py` | Pydantic models for workflow JSON |
| `engine/src/agent33/workflows/dag.py` | DAG builder, topological sort, parallel groups |
| `engine/src/agent33/workflows/executor.py` | Step dispatcher with retry/timeout logic |
| `engine/src/agent33/workflows/expressions.py` | Jinja2 sandboxed expression evaluator |
| `engine/src/agent33/workflows/checkpoint.py` | SQLAlchemy-based state persistence |
| `engine/src/agent33/workflows/state_machine.py` | XState-inspired statechart engine |
| `engine/src/agent33/workflows/actions/` | Individual action implementations |

---

## 2. Workflow Definition Format

A workflow is a JSON object conforming to the schema at `core/schemas/workflow.schema.json`. The three required top-level fields are `name`, `version`, and `steps`.

### Full Annotated Example

```json
{
  "$schema": "../core/schemas/workflow.schema.json",

  "name": "code-review-pipeline",
  "version": "1.0.0",
  "description": "Automated code review with parallel analysis",

  "triggers": {
    "manual": true,
    "on_event": ["artifact-created"],
    "on_change": ["src/**/*.py"],
    "schedule": "0 2 * * 1"
  },

  "inputs": {
    "repository": {
      "type": "string",
      "description": "Repository path to analyze",
      "required": true
    },
    "branch": {
      "type": "string",
      "description": "Branch to review",
      "default": "main"
    }
  },

  "outputs": {
    "review_summary": {
      "type": "object",
      "description": "Combined review results"
    }
  },

  "steps": [
    {
      "id": "fetch-code",
      "name": "Fetch Source Code",
      "action": "run-command",
      "command": "git diff --stat HEAD~1",
      "inputs": {},
      "outputs": { "diff_output": "stdout" },
      "timeout_seconds": 30
    },
    {
      "id": "lint-check",
      "name": "Run Linter",
      "action": "run-command",
      "command": "echo lint-passed",
      "depends_on": ["fetch-code"],
      "timeout_seconds": 60
    }
  ],

  "execution": {
    "mode": "dependency-aware",
    "parallel_limit": 4,
    "continue_on_error": false,
    "fail_fast": true,
    "timeout_seconds": 300,
    "dry_run": false
  },

  "metadata": {
    "author": "agent-33",
    "created": "2025-01-30",
    "tags": ["code-review", "ci-cd"]
  }
}
```

### Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique identifier. Pattern: `^[a-z][a-z0-9-]*$`, 2-64 chars. |
| `version` | string | Yes | Semver string, e.g. `"1.0.0"`. |
| `description` | string | No | Up to 500 characters. |
| `triggers` | object | No | How the workflow is started. See [Triggers](#10-triggers). |
| `inputs` | object | No | Named parameters the workflow accepts. Each value is a `ParameterDef`. |
| `outputs` | object | No | Named parameters the workflow produces. |
| `steps` | array | Yes | One or more `WorkflowStep` objects. At least one required. |
| `execution` | object | No | Execution mode, concurrency, timeouts. |
| `metadata` | object | No | Author, dates, tags. |

### ParameterDef

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | One of `string`, `number`, `boolean`, `array`, `object`, `path`. |
| `description` | string | Human-readable description. |
| `required` | boolean | Whether this parameter must be provided. Default: `false`. |
| `default` | any | Default value when not supplied. |

### WorkflowStep Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique step identifier. Pattern: `^[a-z][a-z0-9-]*$`. |
| `name` | string | Human-readable label. |
| `action` | string | One of the seven action types. See [Step Types](#3-step-types). |
| `agent` | string | Agent name (for `invoke-agent`). |
| `command` | string | Shell command (for `run-command`). |
| `inputs` | object | Input mapping. String values are evaluated as Jinja2 expressions. |
| `outputs` | object | Output mapping for documentation and downstream reference. |
| `condition` | string | Jinja2 expression. Step is skipped if it evaluates to falsy. |
| `depends_on` | array | List of step IDs that must complete before this step runs. |
| `retry` | object | `{ "max_attempts": 1..10, "delay_seconds": >=1 }` |
| `timeout_seconds` | integer | Per-step timeout. Minimum 10. |
| `steps` | array | Sub-steps for `parallel-group` action. |
| `then` / `else` | array | Branch sub-steps for `conditional` action. |
| `duration_seconds` | integer | Fixed wait time for `wait` action. |
| `wait_condition` | string | Polling expression for `wait` action. |

---

## 3. Step Types

### 3.1 invoke-agent

Delegates work to a registered agent handler. The agent must be registered in the in-process agent registry before workflow execution.

**Required fields:** `agent`

**Outputs:** Whatever the agent handler returns (must be a dict, or is wrapped as `{"result": value}`).

```json
{
  "id": "security-scan",
  "action": "invoke-agent",
  "agent": "security-scanner",
  "inputs": {
    "source": "{{ steps['fetch-code'].diff_output }}"
  },
  "retry": { "max_attempts": 2, "delay_seconds": 5 }
}
```

**Agent registration (Python):**

```python
from agent33.workflows.actions.invoke_agent import register_agent

async def my_scanner(inputs: dict) -> dict:
    return {"findings": [], "score": 100}

register_agent("security-scanner", my_scanner)
```

### 3.2 run-command

Executes a shell command via `asyncio.create_subprocess_exec` (Unix) or `asyncio.create_subprocess_shell` (Windows). Input values are passed as environment variables.

**Required fields:** `command`

**Outputs:** `{ "stdout": "...", "stderr": "...", "return_code": 0 }`

A non-zero exit code raises `RuntimeError`, triggering retry or failure.

```json
{
  "id": "run-tests",
  "action": "run-command",
  "command": "pytest tests/ -v",
  "inputs": { "CI": "true" },
  "timeout_seconds": 120,
  "retry": { "max_attempts": 2, "delay_seconds": 3 }
}
```

### 3.3 validate

Validates data against a JSON Schema, a Jinja2 expression, or both.

**Required inputs (in `inputs`):**
- `data` -- the value to validate.
- `schema` (optional) -- a JSON Schema dict.
- `expression` (optional) -- a Jinja2 expression that must evaluate to truthy.

At least one of `schema` or `expression` is required. Raises `ValueError` on failure.

**Outputs:** `{ "valid": true, "errors": [] }`

```json
{
  "id": "validate-config",
  "action": "validate",
  "inputs": {
    "data": "{{ steps['load-config'].result }}",
    "schema": {
      "type": "object",
      "required": ["name", "version"],
      "properties": {
        "name": { "type": "string" },
        "version": { "type": "string" }
      }
    }
  }
}
```

Expression-based validation:

```json
{
  "id": "check-score",
  "action": "validate",
  "inputs": {
    "data": "{{ steps['analyze'].score }}",
    "expression": "data > 80"
  }
}
```

### 3.4 transform

Transforms data using Jinja2 template expressions. Accepts either a `template` dict (each string value is a Jinja2 expression) or a single `expression`.

**Outputs:**
- Template mode: returns the resolved dict directly.
- Expression mode: returns `{ "result": evaluated_value }`.
- Passthrough: if only `data` is provided, returns `{ "result": data }`.

```json
{
  "id": "build-report",
  "action": "transform",
  "inputs": {
    "template": {
      "summary": "{{ 'PASS' if score > 80 else 'FAIL' }}",
      "details": "{{ findings | tojson }}"
    }
  }
}
```

Single expression:

```json
{
  "id": "extract-count",
  "action": "transform",
  "inputs": {
    "expression": "len(items)",
    "items": "{{ steps['fetch'].result }}"
  }
}
```

### 3.5 conditional

Evaluates a Jinja2 condition and branches into `then` or `else` sub-steps.

**Required fields:** `condition`

**Outputs:** `{ "branch": "then"|"else", "condition_result": true|false }`. Sub-step outputs are also merged in.

```json
{
  "id": "deploy-gate",
  "action": "conditional",
  "condition": "steps['run-tests'].return_code == 0 and steps['lint'].stdout == 'ok'",
  "then": [
    {
      "id": "deploy",
      "action": "run-command",
      "command": "make deploy"
    }
  ],
  "else": [
    {
      "id": "notify-failure",
      "action": "invoke-agent",
      "agent": "notifier",
      "inputs": { "message": "Deployment blocked" }
    }
  ]
}
```

### 3.6 parallel-group

Explicitly runs a set of sub-steps concurrently within a single logical step. This is useful when you want to group related parallel work without expressing it through top-level `depends_on`.

**Required fields:** `steps` (array of sub-steps)

**Outputs:** `{ "results": { "<step-id>": {...}, ... }, "errors": [...] }`

```json
{
  "id": "parallel-analysis",
  "action": "parallel-group",
  "steps": [
    {
      "id": "lint",
      "action": "run-command",
      "command": "ruff check src/"
    },
    {
      "id": "typecheck",
      "action": "run-command",
      "command": "mypy src/"
    },
    {
      "id": "security",
      "action": "invoke-agent",
      "agent": "security-scanner",
      "inputs": { "path": "src/" }
    }
  ]
}
```

### 3.7 wait

Pauses execution for a fixed duration or polls a condition until it becomes truthy.

**Fields:**
- `duration_seconds` -- sleep for a fixed time.
- `wait_condition` -- a Jinja2 expression polled every 2 seconds.
- `timeout_seconds` -- max wait time when polling (default: 300s).

**Outputs:** `{ "waited_seconds": N, "condition_met": true|false }`

Fixed delay:

```json
{
  "id": "cooldown",
  "action": "wait",
  "duration_seconds": 30
}
```

Condition polling:

```json
{
  "id": "wait-for-deploy",
  "action": "wait",
  "wait_condition": "deployment_status == 'ready'",
  "timeout_seconds": 120
}
```

---

## 4. Execution Modes

Configure the mode under the `execution` block.

### sequential

Steps execute one at a time in the order they appear in the `steps` array. Dependencies (`depends_on`) are not used for ordering -- list order is the execution order.

**When to use:** Simple linear pipelines, debugging, or when steps must run in strict declaration order.

```json
{ "execution": { "mode": "sequential" } }
```

### parallel

All steps in the same DAG group run concurrently. The DAG is still built from `depends_on` declarations. Steps with no dependencies start together; once all finish, the next group begins.

**When to use:** Maximizing throughput when steps are I/O-bound (API calls, agent invocations).

```json
{ "execution": { "mode": "parallel", "parallel_limit": 8 } }
```

### dependency-aware

Same DAG grouping as `parallel` mode. Single-step groups run sequentially; multi-step groups run concurrently up to `parallel_limit`. This is the recommended mode for most workflows.

**When to use:** Production pipelines with a mix of sequential and parallelizable work.

```json
{ "execution": { "mode": "dependency-aware", "parallel_limit": 4 } }
```

### Comparison

| Mode | Respects `depends_on` | Parallelism | Best for |
|------|----------------------|-------------|----------|
| `sequential` | No (uses list order) | None | Simple chains |
| `parallel` | Yes | Full | I/O-heavy work |
| `dependency-aware` | Yes | Bounded | General use |

---

## 5. Expressions

The workflow engine uses **Jinja2** in a sandboxed environment for all dynamic values. Expressions appear in three places:

1. **Step `inputs`** -- string values are evaluated against the current state.
2. **Step `condition`** -- must evaluate to a truthy value or the step is skipped.
3. **`wait_condition`** -- polled repeatedly until truthy.

### Available Context

Inside any expression, the following variables are available:

- **Workflow inputs** -- top-level input values are available by name.
- **Step outputs** -- each completed step's outputs are stored under the step ID. Access them as `steps['step-id'].field` or directly as `step_id` (with hyphens replaced).

### Built-in Functions and Filters

| Name | Type | Description |
|------|------|-------------|
| `range` | function | Python `range()` |
| `len` | function | Python `len()` |
| `str`, `int`, `float`, `bool` | function | Type conversions |
| `list`, `dict` | function | Container constructors |
| `tojson` | filter | `json.dumps()` |
| `fromjson` | filter | `json.loads()` |

### Examples

**Accessing step outputs:**

```
{{ steps['fetch-code'].stdout }}
```

**Conditional logic in inputs:**

```
{{ 'production' if branch == 'main' else 'staging' }}
```

**Condition expression (no delimiters needed):**

```
steps['lint-check'].return_code == 0 and len(steps['security-scan'].findings) == 0
```

**Template rendering:**

```
Review for {{ repository }} on branch {{ branch }}: {{ 'PASS' if score > 80 else 'FAIL' }}
```

**Using filters:**

```
{{ results | tojson }}
{{ raw_json | fromjson }}
```

### How Resolution Works

The `ExpressionEvaluator.resolve_inputs()` method walks the `inputs` dict recursively:
- String values are evaluated as Jinja2 expressions.
- Nested dicts are resolved recursively.
- Lists have their string elements evaluated individually.
- Non-string values pass through unchanged.

---

## 6. Parallel Execution

### DAG-Based Grouping

The `DAGBuilder` uses Kahn's algorithm to compute parallel groups. Each group contains steps whose dependencies are all in prior groups. Within a group, all steps can run simultaneously.

Example dependency graph:

```
fetch-code
   |       \
lint-check  security-scan
   \       /
 quality-gate
      |
 generate-report
```

This produces three parallel groups:

| Group | Steps |
|-------|-------|
| 0 | `fetch-code` |
| 1 | `lint-check`, `security-scan` |
| 2 | `quality-gate` |
| 3 | `generate-report` |

Group 1 runs both steps concurrently.

### Concurrency Limits

The `parallel_limit` field (1-32, default 4) controls the maximum number of concurrent tasks within a group. An `asyncio.Semaphore` enforces this limit.

```json
{ "execution": { "mode": "dependency-aware", "parallel_limit": 2 } }
```

With `parallel_limit: 2` and a group of 5 steps, at most 2 run at any given time.

### Fan-Out / Fan-In Pattern

A common pattern is one step producing data consumed by multiple parallel steps, whose outputs are then aggregated:

```json
{
  "steps": [
    { "id": "split-data", "action": "transform", "inputs": { "expression": "partition(data, 4)" } },

    { "id": "process-a", "action": "invoke-agent", "agent": "processor", "depends_on": ["split-data"],
      "inputs": { "chunk": "{{ steps['split-data'].result[0] }}" } },
    { "id": "process-b", "action": "invoke-agent", "agent": "processor", "depends_on": ["split-data"],
      "inputs": { "chunk": "{{ steps['split-data'].result[1] }}" } },
    { "id": "process-c", "action": "invoke-agent", "agent": "processor", "depends_on": ["split-data"],
      "inputs": { "chunk": "{{ steps['split-data'].result[2] }}" } },
    { "id": "process-d", "action": "invoke-agent", "agent": "processor", "depends_on": ["split-data"],
      "inputs": { "chunk": "{{ steps['split-data'].result[3] }}" } },

    { "id": "aggregate", "action": "transform", "depends_on": ["process-a", "process-b", "process-c", "process-d"],
      "inputs": { "expression": "[steps['process-a'].result, steps['process-b'].result, steps['process-c'].result, steps['process-d'].result]" } }
  ],
  "execution": { "mode": "dependency-aware", "parallel_limit": 4 }
}
```

### Explicit Parallel Groups

For tightly coupled parallel work, use the `parallel-group` action instead of relying on the DAG:

```json
{
  "id": "all-checks",
  "action": "parallel-group",
  "steps": [
    { "id": "lint", "action": "run-command", "command": "ruff check ." },
    { "id": "types", "action": "run-command", "command": "mypy ." },
    { "id": "tests", "action": "run-command", "command": "pytest" }
  ]
}
```

---

## 7. Error Handling

### Retry Configuration

Each step can specify retry behavior:

```json
{
  "retry": {
    "max_attempts": 3,
    "delay_seconds": 5
  }
}
```

- `max_attempts` (1-10, default 1): Total attempts including the first try.
- `delay_seconds` (>=1, default 1): Seconds to sleep between retries.

The executor catches any exception (including `TimeoutError`) and retries up to `max_attempts`. If all attempts fail, the step result status is `"failed"`.

### Workflow-Level Controls

| Field | Default | Description |
|-------|---------|-------------|
| `fail_fast` | `true` | Stop the entire workflow on the first step failure. |
| `continue_on_error` | `false` | Continue executing subsequent steps even after a failure. |
| `timeout_seconds` | none | Overall workflow timeout (60-86400 seconds). |

**Behavior matrix:**

| `fail_fast` | `continue_on_error` | Behavior |
|-------------|---------------------|----------|
| true | false | Stop at first failure (default). |
| false | false | Stop at first failure in group, but complete current group. |
| false | true | Continue all remaining steps regardless of failures. |

### Step Timeouts

```json
{ "timeout_seconds": 60 }
```

Minimum 10 seconds. Enforced via `asyncio.wait_for()`. On timeout, the step is retried (if retries remain) or marked as failed.

### Workflow Status

The final `WorkflowResult.status` is one of:

| Status | Meaning |
|--------|---------|
| `success` | All executed steps succeeded. |
| `failed` | At least one step failed and no steps succeeded. |
| `partial` | Some steps succeeded, some failed. |
| `skipped` | No steps executed (e.g., all conditions were false). |

### Step Conditions as Guards

A step with a `condition` that evaluates to false is skipped (not failed):

```json
{
  "id": "deploy",
  "action": "run-command",
  "command": "make deploy",
  "condition": "branch == 'main' and steps['test'].return_code == 0"
}
```

Skipped steps produce `{ "skipped": true, "reason": "condition_false" }`.

---

## 8. Checkpointing

The `CheckpointManager` persists workflow state to a database (PostgreSQL or any SQLAlchemy-async-compatible store) so that workflows can resume after failure.

### How It Works

1. After each step completes, the executor can save a checkpoint containing the full state dict.
2. On restart, `load_checkpoint(workflow_id)` retrieves the most recent state.
3. The executor skips already-completed steps and resumes from the next one.

### Database Schema

The `workflow_checkpoints` table:

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) | UUID primary key |
| `workflow_id` | VARCHAR(128) | Identifies the workflow run |
| `step_id` | VARCHAR(128) | The step that was just completed |
| `state_json` | TEXT | JSON-serialized state dict |
| `created_at` | TIMESTAMP | When the checkpoint was saved |

### API

```python
from agent33.workflows.checkpoint import CheckpointManager

mgr = CheckpointManager(database_url="postgresql+asyncpg://...")

# Initialize table
await mgr.initialize()

# Save after a step completes
checkpoint_id = await mgr.save_checkpoint(
    workflow_id="run-abc-123",
    step_id="lint-check",
    state={"lint-check": {"stdout": "ok", "return_code": 0}},
)

# Resume from last checkpoint
state = await mgr.load_checkpoint("run-abc-123")

# List all checkpoints for a workflow
checkpoints = await mgr.list_checkpoints(workflow_id="run-abc-123")

# Clean up
await mgr.close()
```

---

## 9. State Machine Integration

For workflows that are better modeled as reactive state transitions rather than linear pipelines, the engine provides an XState-inspired `StateMachine`.

### When to Use Statecharts vs DAGs

| Use Case | Model |
|----------|-------|
| Linear or fan-out/fan-in pipelines | DAG workflow |
| Long-running processes with external events | Statechart |
| Approval gates waiting on human input | Statechart |
| Simple automation chains | DAG workflow |
| Complex multi-phase processes with loops | Statechart |

### StatechartDefinition

```python
from agent33.workflows.state_machine import (
    StatechartDefinition,
    StateNode,
    Transition,
    StateMachine,
)

definition = StatechartDefinition(
    id="review-flow",
    initial="draft",
    context={"revisions": 0, "approved": False},
    states={
        "draft": StateNode(
            entry=["init_draft"],
            on={
                "SUBMIT": Transition(target="reviewing", actions=["log_submit"]),
            },
        ),
        "reviewing": StateNode(
            on={
                "APPROVE": Transition(
                    target="approved",
                    guard="has_no_issues",
                    actions=["mark_approved"],
                ),
                "REJECT": Transition(
                    target="draft",
                    actions=["increment_revisions"],
                ),
            },
        ),
        "approved": StateNode(
            on={"PUBLISH": "published"},
        ),
        "published": StateNode(final=True),
    },
)
```

### Running a State Machine

```python
def has_no_issues(ctx: dict) -> bool:
    return ctx.get("issues", 0) == 0

def mark_approved(ctx: dict) -> None:
    ctx["approved"] = True

def increment_revisions(ctx: dict) -> None:
    ctx["revisions"] = ctx.get("revisions", 0) + 1

machine = StateMachine(
    definition,
    guards={"has_no_issues": has_no_issues},
    actions={
        "mark_approved": mark_approved,
        "increment_revisions": increment_revisions,
        "init_draft": lambda ctx: None,
        "log_submit": lambda ctx: None,
    },
)

machine.send("SUBMIT")       # -> "reviewing"
machine.send("REJECT")       # -> "draft" (revisions incremented)
machine.send("SUBMIT")       # -> "reviewing"
machine.send("APPROVE")      # -> "approved" (if guard passes)
machine.send("PUBLISH")      # -> "published" (final)

result = machine.result()
# result.final_state == "published"
# result.history == ["draft", "reviewing", "draft", "reviewing", "approved", "published"]
# result.context == {"revisions": 1, "approved": True}
```

### Key Features

- **Guards** -- callable predicates that can block a transition.
- **Entry/Exit actions** -- run automatically when entering or leaving a state.
- **Transition actions** -- run during the transition itself.
- **Final states** -- no further events are accepted.
- **Batch execution** -- `machine.execute(["SUBMIT", "APPROVE", "PUBLISH"])` sends a sequence of events, stopping at any final state.

---

## 10. Triggers

The `triggers` block controls how a workflow is started.

### manual

```json
{ "triggers": { "manual": true } }
```

The workflow can be started explicitly via the CLI or API. Default: `true`.

### schedule (cron)

```json
{ "triggers": { "schedule": "0 2 * * 1" } }
```

A standard cron expression. The example above runs every Monday at 2:00 AM.

### on_change (file change)

```json
{ "triggers": { "on_change": ["src/**/*.py", "tests/**/*.py"] } }
```

Glob patterns. The workflow triggers when matching files are modified.

### on_event (system event)

```json
{ "triggers": { "on_event": ["artifact-created", "review-complete"] } }
```

Available system events:

| Event | Description |
|-------|-------------|
| `session-start` | A new agent session begins. |
| `session-end` | An agent session ends. |
| `artifact-created` | A new artifact (file, document) is created. |
| `review-complete` | A review process finishes. |

### Combining Triggers

All trigger types can be combined. A workflow starts whenever any trigger fires:

```json
{
  "triggers": {
    "manual": true,
    "schedule": "0 9 * * *",
    "on_change": ["docs/**/*.md"],
    "on_event": ["review-complete"]
  }
}
```

---

## 11. Use Cases

### 11.1 CI/CD Pipeline

Lint, test, and deploy with a conditional gate.

```json
{
  "name": "ci-cd-pipeline",
  "version": "1.0.0",
  "description": "Build, test, and deploy on merge to main",
  "triggers": {
    "on_change": ["src/**/*"],
    "on_event": ["artifact-created"]
  },
  "inputs": {
    "branch": { "type": "string", "default": "main" }
  },
  "steps": [
    {
      "id": "lint",
      "action": "run-command",
      "command": "ruff check src/",
      "timeout_seconds": 60
    },
    {
      "id": "typecheck",
      "action": "run-command",
      "command": "mypy src/",
      "depends_on": ["lint"],
      "timeout_seconds": 120
    },
    {
      "id": "test",
      "action": "run-command",
      "command": "pytest tests/ --tb=short",
      "depends_on": ["lint"],
      "timeout_seconds": 300,
      "retry": { "max_attempts": 2, "delay_seconds": 5 }
    },
    {
      "id": "deploy-check",
      "action": "conditional",
      "depends_on": ["typecheck", "test"],
      "condition": "branch == 'main'"
    },
    {
      "id": "deploy",
      "action": "run-command",
      "command": "make deploy-production",
      "depends_on": ["deploy-check"],
      "condition": "steps['deploy-check'].condition_result == true",
      "timeout_seconds": 600
    }
  ],
  "execution": {
    "mode": "dependency-aware",
    "parallel_limit": 4,
    "fail_fast": true
  }
}
```

### 11.2 Content Generation Pipeline

Research a topic, draft content, review it, and publish.

```json
{
  "name": "content-pipeline",
  "version": "1.0.0",
  "description": "End-to-end content creation with AI agents",
  "inputs": {
    "topic": { "type": "string", "required": true },
    "tone": { "type": "string", "default": "professional" }
  },
  "steps": [
    {
      "id": "research",
      "action": "invoke-agent",
      "agent": "researcher",
      "inputs": { "topic": "{{ topic }}", "depth": "detailed" }
    },
    {
      "id": "draft",
      "action": "invoke-agent",
      "agent": "writer",
      "depends_on": ["research"],
      "inputs": {
        "research": "{{ steps['research'].findings }}",
        "tone": "{{ tone }}"
      }
    },
    {
      "id": "review",
      "action": "invoke-agent",
      "agent": "editor",
      "depends_on": ["draft"],
      "inputs": { "draft": "{{ steps['draft'].content }}" },
      "retry": { "max_attempts": 2, "delay_seconds": 3 }
    },
    {
      "id": "quality-check",
      "action": "validate",
      "depends_on": ["review"],
      "inputs": {
        "data": "{{ steps['review'] }}",
        "expression": "data.score >= 7"
      }
    },
    {
      "id": "publish",
      "action": "invoke-agent",
      "agent": "publisher",
      "depends_on": ["quality-check"],
      "inputs": {
        "content": "{{ steps['review'].final_content }}",
        "metadata": "{{ steps['research'].sources | tojson }}"
      }
    }
  ],
  "execution": { "mode": "sequential" }
}
```

### 11.3 Data Processing Pipeline

Ingest, transform, validate, and store data.

```json
{
  "name": "data-processing",
  "version": "1.0.0",
  "description": "ETL pipeline with validation",
  "triggers": { "schedule": "0 1 * * *" },
  "steps": [
    {
      "id": "ingest",
      "action": "run-command",
      "command": "python scripts/fetch_data.py --source api",
      "timeout_seconds": 120
    },
    {
      "id": "normalize",
      "action": "transform",
      "depends_on": ["ingest"],
      "inputs": {
        "template": {
          "records": "{{ steps['ingest'].stdout | fromjson }}",
          "count": "{{ len(steps['ingest'].stdout | fromjson) }}"
        }
      }
    },
    {
      "id": "validate-schema",
      "action": "validate",
      "depends_on": ["normalize"],
      "inputs": {
        "data": "{{ steps['normalize'].records }}",
        "schema": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["id", "value"],
            "properties": {
              "id": { "type": "string" },
              "value": { "type": "number" }
            }
          }
        }
      }
    },
    {
      "id": "store",
      "action": "run-command",
      "depends_on": ["validate-schema"],
      "command": "python scripts/store_data.py",
      "inputs": { "DATA": "{{ steps['normalize'].records | tojson }}" },
      "timeout_seconds": 60
    }
  ],
  "execution": { "mode": "dependency-aware" }
}
```

### 11.4 Multi-Agent Collaboration

An orchestrator delegates subtasks to specialized worker agents and aggregates results.

```json
{
  "name": "multi-agent-collab",
  "version": "1.0.0",
  "description": "Orchestrator delegates to specialist agents",
  "inputs": {
    "project_spec": { "type": "string", "required": true }
  },
  "steps": [
    {
      "id": "plan",
      "action": "invoke-agent",
      "agent": "architect",
      "inputs": { "spec": "{{ project_spec }}" }
    },
    {
      "id": "implement-backend",
      "action": "invoke-agent",
      "agent": "backend-dev",
      "depends_on": ["plan"],
      "inputs": { "design": "{{ steps['plan'].backend_design }}" },
      "timeout_seconds": 600
    },
    {
      "id": "implement-frontend",
      "action": "invoke-agent",
      "agent": "frontend-dev",
      "depends_on": ["plan"],
      "inputs": { "design": "{{ steps['plan'].frontend_design }}" },
      "timeout_seconds": 600
    },
    {
      "id": "write-tests",
      "action": "invoke-agent",
      "agent": "test-engineer",
      "depends_on": ["plan"],
      "inputs": { "requirements": "{{ steps['plan'].test_plan }}" },
      "timeout_seconds": 300
    },
    {
      "id": "integration",
      "action": "invoke-agent",
      "agent": "integrator",
      "depends_on": ["implement-backend", "implement-frontend", "write-tests"],
      "inputs": {
        "backend": "{{ steps['implement-backend'].code }}",
        "frontend": "{{ steps['implement-frontend'].code }}",
        "tests": "{{ steps['write-tests'].test_suite }}"
      }
    },
    {
      "id": "review",
      "action": "invoke-agent",
      "agent": "code-reviewer",
      "depends_on": ["integration"],
      "inputs": { "codebase": "{{ steps['integration'].merged_code }}" }
    }
  ],
  "execution": {
    "mode": "dependency-aware",
    "parallel_limit": 3,
    "timeout_seconds": 1800
  }
}
```

---

## 12. Best Practices

### Naming Conventions

- **Workflow names:** lowercase kebab-case, descriptive. Example: `code-review-pipeline`, `nightly-data-sync`.
- **Step IDs:** lowercase kebab-case, verb-noun. Example: `fetch-code`, `run-tests`, `validate-config`.
- **Agent names:** match the registered handler name exactly.

### Step Granularity

- Each step should do **one thing**. Prefer `run-tests` + `run-lint` over a single `run-all-checks`.
- Use `parallel-group` to bundle related checks that have no dependencies on each other.
- Keep steps small enough that a retry is cheap.

### Error Handling Patterns

1. **Critical path with fail-fast.** Default behavior. Any failure stops the workflow.

2. **Best-effort with continue-on-error.** Use for reporting or monitoring pipelines where partial results are still valuable.
   ```json
   { "execution": { "continue_on_error": true, "fail_fast": false } }
   ```

3. **Retry flaky steps.** Network calls, agent invocations, and external commands benefit from retries.
   ```json
   { "retry": { "max_attempts": 3, "delay_seconds": 10 } }
   ```

4. **Guard with conditions.** Skip expensive steps when prerequisites are not met rather than letting them fail.
   ```json
   { "condition": "steps['preflight'].status == 'ready'" }
   ```

### Dependency Management

- Always use `depends_on` rather than relying on array order, unless using `sequential` mode.
- Keep the DAG shallow. Deep chains reduce parallelism opportunities.
- Avoid unnecessary dependencies. If step B does not actually need step A's output, do not add the dependency.

### Timeouts

- Always set `timeout_seconds` on `run-command` steps. Shell commands can hang indefinitely.
- Set a workflow-level `timeout_seconds` as a safety net.
- Use generous timeouts for agent invocations (LLM calls are variable).

### Version Control

- Store workflow definitions in `engine/workflow-definitions/`.
- Use semantic versioning. Bump the version when changing step structure.
- Include the `$schema` field for IDE autocompletion and validation.

---

## 13. Testing Workflows

The `WorkflowTestHarness` class (in `engine/src/agent33/testing/workflow_harness.py`) provides two testing modes: dry runs and mock execution.

### Dry Runs

A dry run analyzes the DAG and returns the execution plan without running any steps.

```python
from agent33.testing.workflow_harness import WorkflowTestHarness

harness = WorkflowTestHarness()
harness.load_workflow("engine/workflow-definitions/example-pipeline.json")

plan = harness.dry_run(inputs={"repository": "/app", "branch": "main"})

print(f"Workflow: {plan.workflow_name}")
print(f"Total steps: {plan.total_steps}")
print(f"Execution order: {plan.execution_order}")
print(f"Parallel groups: {plan.parallel_groups}")

for step in plan.steps:
    print(f"  [{step.group_index}] {step.step_id} ({step.action})")
```

**Output:**

```
Workflow: code-review-pipeline
Total steps: 5
Execution order: ['fetch-code', 'lint-check', 'security-scan', 'quality-gate', 'generate-report']
Parallel groups: [['fetch-code'], ['lint-check', 'security-scan'], ['quality-gate'], ['generate-report']]
  [0] fetch-code (run-command)
  [1] lint-check (run-command)
  [1] security-scan (invoke-agent)
  [2] quality-gate (conditional)
  [3] generate-report (transform)
```

### Mock Execution

Run the workflow with mock agent outputs to test the full pipeline logic without calling real agents or external services.

```python
import asyncio
from agent33.testing.workflow_harness import WorkflowTestHarness

harness = WorkflowTestHarness()
harness.load_workflow("engine/workflow-definitions/example-pipeline.json")

result = asyncio.run(harness.run_with_mocks(
    inputs={"repository": "/app", "branch": "main"},
    mock_agents={
        "security-scanner": {
            "findings": [],
            "score": 100,
        },
    },
))

assert result.success
print(f"Steps executed: {[s.step_id for s in result.step_results]}")
for step in result.step_results:
    print(f"  {step.step_id}: {step.output}")
```

### Using in pytest

```python
import pytest
from agent33.testing.workflow_harness import WorkflowTestHarness

@pytest.fixture
def harness():
    h = WorkflowTestHarness()
    h.load_workflow("engine/workflow-definitions/example-pipeline.json")
    return h

def test_workflow_has_no_cycles(harness):
    plan = harness.dry_run()
    assert plan.total_steps == 5

def test_parallel_groups(harness):
    plan = harness.dry_run()
    # lint-check and security-scan should be in the same group
    assert ["lint-check", "security-scan"] in plan.parallel_groups

@pytest.mark.asyncio
async def test_mock_execution(harness):
    result = await harness.run_with_mocks(
        mock_agents={"security-scanner": {"findings": [], "score": 95}},
    )
    assert result.success
```

### Validating a Definition Programmatically

```python
from agent33.workflows.definition import WorkflowDefinition

# Raises ValidationError on invalid JSON
defn = WorkflowDefinition.load_from_file("my-workflow.json")

# Check for cycles
from agent33.workflows.dag import DAGBuilder, CycleDetectedError

try:
    DAGBuilder(defn.steps).build()
except CycleDetectedError as e:
    print(f"Cycle found: {e.cycle}")
```

---

## Further Reading

- Schema definition: `core/schemas/workflow.schema.json`
- Example pipeline: `engine/workflow-definitions/example-pipeline.json`
- Action source code: `engine/src/agent33/workflows/actions/`
- Test harness: `engine/src/agent33/testing/workflow_harness.py`
