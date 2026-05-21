# Task Definition Registry Specification

**Status**: Specification
**Source**: CA-017 to CA-028 (Netflix Conductor), CA-041 to CA-052 (Kestra)

## Overview

The Task Definition Registry is a centralized catalog of reusable task types that can be instantiated in workflows. Each task type defines its interface (input/output schemas), execution behavior (handler, timeout, retry), and governance metadata (risk level, approval requirements). Workflows reference task types by name and version, enabling composition, reuse, and independent evolution of task implementations.

## Task Type Definition

A task type is the blueprint from which task instances are created during workflow execution.

```yaml
task_type:
  name: string                  # unique identifier (snake_case)
  version: semver               # semantic version
  description: string           # human-readable purpose
  category: string              # classification (see categories below)
  tags: [string]                # free-form labels for discovery

  input_schema:
    type: object
    properties:
      # defined per task type
    required: [list]

  output_schema:
    type: object
    properties:
      # defined per task type

  execution:
    handler: string             # reference to execution handler
    timeout: duration           # maximum execution time
    retry_policy:
      max_retries: number
      backoff: exponential | linear | fixed
      initial_delay: duration
      max_delay: duration       # cap for exponential backoff
      retryable_errors: [string] # error codes eligible for retry

  governance:
    provenance_checked: boolean
    risk_level: low | medium | high
    approval_required: boolean
    audit_log: boolean

  deprecation:
    deprecated: boolean
    replacement: task_type_name
    removal_date: ISO-8601
    migration_guide: string     # URL or inline instructions
```

## Built-in Task Types

AGENT-33 ships with the following task types. All built-in types have `provenance_checked: true` and are maintained as part of the core distribution.

### HTTP

Execute an HTTP request to an external service.

```yaml
task_type:
  name: http
  version: "1.0.0"
  description: "Execute an HTTP request and capture the response."
  category: integration
  tags: [api, rest, webhook]

  input_schema:
    type: object
    properties:
      method:
        type: string
        enum: [GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS]
      url:
        type: string
        format: uri
      headers:
        type: object
        additionalProperties:
          type: string
      body:
        type: [object, string, null]
      timeout_ms:
        type: integer
        default: 30000
      follow_redirects:
        type: boolean
        default: true
    required: [method, url]

  output_schema:
    type: object
    properties:
      status_code:
        type: integer
      headers:
        type: object
      body:
        type: [object, string, null]
      duration_ms:
        type: integer

  execution:
    handler: builtin.http_executor
    timeout: 60s
    retry_policy:
      max_retries: 3
      backoff: exponential
      initial_delay: 1s
      max_delay: 30s
      retryable_errors: [TIMEOUT, CONNECTION_REFUSED, HTTP_502, HTTP_503, HTTP_504]

  governance:
    provenance_checked: true
    risk_level: medium
    approval_required: false
    audit_log: true
```

### SHELL

Execute a shell command on the orchestrator host or a designated runner.

```yaml
task_type:
  name: shell
  version: "1.0.0"
  description: "Execute a shell command and capture stdout/stderr."
  category: integration
  tags: [command, script, cli]

  input_schema:
    type: object
    properties:
      command:
        type: string
      args:
        type: array
        items:
          type: string
      working_directory:
        type: string
      environment:
        type: object
        additionalProperties:
          type: string
      stdin:
        type: string
    required: [command]

  output_schema:
    type: object
    properties:
      exit_code:
        type: integer
      stdout:
        type: string
      stderr:
        type: string
      duration_ms:
        type: integer

  execution:
    handler: builtin.shell_executor
    timeout: 300s
    retry_policy:
      max_retries: 0
      backoff: fixed
      initial_delay: 0s

  governance:
    provenance_checked: true
    risk_level: high
    approval_required: true
    audit_log: true
```

### TRANSFORM

Apply a data transformation using the expression language or a registered transform function.

```yaml
task_type:
  name: transform
  version: "1.0.0"
  description: "Transform input data using expressions or registered functions."
  category: transformation
  tags: [data, mapping, jq, expression]

  input_schema:
    type: object
    properties:
      data:
        type: [object, array, string, number, boolean, null]
      expression:
        type: string
      function:
        type: string
      params:
        type: object
    required: [data]

  output_schema:
    type: object
    properties:
      result:
        type: [object, array, string, number, boolean, null]

  execution:
    handler: builtin.transform_executor
    timeout: 30s
    retry_policy:
      max_retries: 0
      backoff: fixed
      initial_delay: 0s

  governance:
    provenance_checked: true
    risk_level: low
    approval_required: false
    audit_log: false
```

### DECISION

Evaluate a condition and route execution to one of several branches.

```yaml
task_type:
  name: decision
  version: "1.0.0"
  description: "Evaluate conditions and select an execution branch."
  category: decision
  tags: [branch, conditional, routing]

  input_schema:
    type: object
    properties:
      cases:
        type: array
        items:
          type: object
          properties:
            condition:
              type: string
            branch:
              type: string
          required: [condition, branch]
      default_branch:
        type: string
    required: [cases]

  output_schema:
    type: object
    properties:
      selected_branch:
        type: string
      condition_results:
        type: object

  execution:
    handler: builtin.decision_executor
    timeout: 10s
    retry_policy:
      max_retries: 0
      backoff: fixed
      initial_delay: 0s

  governance:
    provenance_checked: true
    risk_level: low
    approval_required: false
    audit_log: true
```

### FORK_JOIN

Execute multiple task branches in parallel and wait for all (or a subset) to complete.

```yaml
task_type:
  name: fork_join
  version: "1.0.0"
  description: "Execute parallel branches and join on completion."
  category: orchestration
  tags: [parallel, fan-out, fan-in, concurrency]

  input_schema:
    type: object
    properties:
      branches:
        type: array
        items:
          type: object
          properties:
            id:
              type: string
            tasks:
              type: array
          required: [id, tasks]
      join_strategy:
        type: string
        enum: [all, any, n_of]
        default: all
      join_count:
        type: integer
        description: "Required when join_strategy is n_of"
    required: [branches]

  output_schema:
    type: object
    properties:
      branch_results:
        type: object
        additionalProperties:
          type: object
      completed_branches:
        type: array
        items:
          type: string

  execution:
    handler: builtin.fork_join_executor
    timeout: 3600s
    retry_policy:
      max_retries: 0
      backoff: fixed
      initial_delay: 0s

  governance:
    provenance_checked: true
    risk_level: low
    approval_required: false
    audit_log: true
```

### WAIT

Pause execution until a signal is received, a timer expires, or a condition is met.

```yaml
task_type:
  name: wait
  version: "1.0.0"
  description: "Pause execution until a condition, signal, or timeout."
  category: orchestration
  tags: [pause, timer, signal, delay]

  input_schema:
    type: object
    properties:
      wait_type:
        type: string
        enum: [duration, until, signal]
      duration:
        type: string
        description: "ISO-8601 duration (for wait_type: duration)"
      until:
        type: string
        format: date-time
        description: "Timestamp (for wait_type: until)"
      signal_name:
        type: string
        description: "Signal to wait for (for wait_type: signal)"
      timeout:
        type: string
        description: "Maximum wait time before timeout error"
    required: [wait_type]

  output_schema:
    type: object
    properties:
      waited_ms:
        type: integer
      signal_data:
        type: [object, null]
      timed_out:
        type: boolean

  execution:
    handler: builtin.wait_executor
    timeout: 86400s
    retry_policy:
      max_retries: 0
      backoff: fixed
      initial_delay: 0s

  governance:
    provenance_checked: true
    risk_level: low
    approval_required: false
    audit_log: true
```

### HUMAN

Pause execution and wait for human input or approval.

```yaml
task_type:
  name: human
  version: "1.0.0"
  description: "Request human input, review, or approval."
  category: human
  tags: [approval, review, manual, input]

  input_schema:
    type: object
    properties:
      prompt:
        type: string
      assignee:
        type: string
      form_schema:
        type: object
        description: "JSON Schema for the input form"
      timeout:
        type: string
        default: "P7D"
      escalation_policy:
        type: object
        properties:
          after:
            type: string
          escalate_to:
            type: string
    required: [prompt]

  output_schema:
    type: object
    properties:
      response:
        type: [object, string]
      respondent:
        type: string
      responded_at:
        type: string
        format: date-time

  execution:
    handler: builtin.human_executor
    timeout: 604800s
    retry_policy:
      max_retries: 0
      backoff: fixed
      initial_delay: 0s

  governance:
    provenance_checked: true
    risk_level: low
    approval_required: false
    audit_log: true
```

### SUB_WORKFLOW

Invoke another workflow as a child, passing input and receiving output on completion.

```yaml
task_type:
  name: sub_workflow
  version: "1.0.0"
  description: "Invoke a child workflow and await its completion."
  category: orchestration
  tags: [composition, nested, child]

  input_schema:
    type: object
    properties:
      workflow_id:
        type: string
      workflow_version:
        type: string
        default: "latest"
      input:
        type: object
      correlation_id:
        type: string
    required: [workflow_id]

  output_schema:
    type: object
    properties:
      workflow_output:
        type: object
      workflow_status:
        type: string
        enum: [completed, failed, timed_out]
      duration_ms:
        type: integer

  execution:
    handler: builtin.sub_workflow_executor
    timeout: 86400s
    retry_policy:
      max_retries: 1
      backoff: exponential
      initial_delay: 10s
      max_delay: 300s

  governance:
    provenance_checked: true
    risk_level: medium
    approval_required: false
    audit_log: true
```

### EVENT

Publish or consume an event from the event bus.

```yaml
task_type:
  name: event
  version: "1.0.0"
  description: "Publish or wait for an event on the event bus."
  category: integration
  tags: [event, publish, subscribe, message]

  input_schema:
    type: object
    properties:
      action:
        type: string
        enum: [publish, wait]
      event_name:
        type: string
      event_data:
        type: object
      timeout:
        type: string
        description: "For wait action only"
    required: [action, event_name]

  output_schema:
    type: object
    properties:
      published:
        type: boolean
      received_event:
        type: [object, null]
      waited_ms:
        type: integer

  execution:
    handler: builtin.event_executor
    timeout: 3600s
    retry_policy:
      max_retries: 1
      backoff: fixed
      initial_delay: 5s

  governance:
    provenance_checked: true
    risk_level: low
    approval_required: false
    audit_log: true
```

## Custom Task Type Registration

Teams can register custom task types through a plugin mechanism.

### Plugin Interface

```python
from abc import ABC, abstractmethod
from typing import Any, Dict

class TaskTypePlugin(ABC):
    """Interface for custom task type implementations."""

    @abstractmethod
    def metadata(self) -> TaskTypeMetadata:
        """Return task type metadata (name, version, schemas, governance)."""
        ...

    @abstractmethod
    async def execute(
        self,
        input_data: Dict[str, Any],
        context: ExecutionContext
    ) -> Dict[str, Any]:
        """Execute the task and return output data."""
        ...

    def validate_input(self, input_data: Dict[str, Any]) -> ValidationResult:
        """Validate input against schema. Default uses JSON Schema."""
        return validate_json_schema(input_data, self.metadata().input_schema)

    def validate_output(self, output_data: Dict[str, Any]) -> ValidationResult:
        """Validate output against schema. Default uses JSON Schema."""
        return validate_json_schema(output_data, self.metadata().output_schema)
```

### Registration

```yaml
# registry/custom_tasks.yaml
custom_tasks:
  - name: slack_notify
    version: "1.0.0"
    plugin: plugins.slack.SlackNotifyTask
    category: integration
    governance:
      provenance_checked: true
      risk_level: low
      approval_required: false

  - name: llm_generate
    version: "2.1.0"
    plugin: plugins.llm.LLMGenerateTask
    category: transformation
    governance:
      provenance_checked: true
      risk_level: medium
      approval_required: false
```

### Registration Validation

On registration, the registry validates:

1. Name uniqueness (no conflict with built-in or existing custom types)
2. Schema validity (input and output schemas are valid JSON Schema)
3. Plugin loads and implements the required interface
4. Governance fields are populated
5. Version follows semver format

## Task Versioning

### Semantic Versioning

Task types follow semantic versioning:

| Change Type | Version Bump | Compatibility |
|------------|-------------|---------------|
| Bug fix in handler | Patch (1.0.x) | Fully backward compatible |
| New optional input field | Minor (1.x.0) | Backward compatible |
| Required input field added | Major (x.0.0) | Breaking change |
| Output schema field removed | Major (x.0.0) | Breaking change |
| Handler behavior change | Major (x.0.0) | Breaking change |

### Version Resolution

Workflows reference task types with version constraints:

```yaml
tasks:
  - type: http
    version: ">=1.0.0 <2.0.0"   # range constraint
  - type: transform
    version: "1.2.3"             # exact version
  - type: decision
    version: "latest"            # latest stable
```

### Backward Compatibility

When a major version is released, the previous major version remains available for a deprecation period. Workflows pinned to the old version continue to function until the removal date.

## Task Deprecation and Migration

### Deprecation Lifecycle

```
Active --> Deprecated --> Removed
           (warning)     (error)
```

1. **Active**: Task type is fully supported.
2. **Deprecated**: Task type works but emits warnings. A replacement is available. The `deprecation` field is populated with `replacement` and `removal_date`.
3. **Removed**: Task type is no longer available. Workflows referencing it fail at validation time.

### Migration Support

```yaml
task_type:
  name: http_legacy
  version: "1.0.0"
  deprecation:
    deprecated: true
    replacement: http
    removal_date: "2026-06-01"
    migration_guide: |
      Replace task type 'http_legacy' with 'http'.
      The 'uri' field has been renamed to 'url'.
      The 'method' field is now required (was optional, defaulted to GET).
```

The registry provides a migration check command:

```
agent33 registry check-deprecations --workflow my_workflow.yaml
```

## Input/Output Schema Validation

All task inputs and outputs are validated against JSON Schema at runtime.

### Validation Points

| Point | Behavior on Failure |
|-------|---------------------|
| Before execution | Task fails with `VALIDATION_ERROR`, no retry |
| After execution | Task fails with `OUTPUT_VALIDATION_ERROR`, no retry |
| At registration | Registration rejected |

### Schema Features

Supported JSON Schema features:

- Types: object, array, string, number, integer, boolean, null
- Formats: uri, date-time, email, duration, uuid
- Constraints: required, enum, minimum, maximum, pattern, minLength, maxLength
- Composition: oneOf, anyOf, allOf
- References: $ref for shared schema definitions

## Task Timeout and Retry Policies

### Timeout Behavior

When a task exceeds its timeout:

1. The executor sends a cancellation signal to the handler
2. The handler has a grace period (default 5s) to clean up
3. If the handler does not respond, the task is forcibly terminated
4. The task status is set to `TIMED_OUT`
5. Retry policy is consulted (timeout may or may not be retryable)

### Retry Backoff Strategies

| Strategy | Delay Calculation |
|----------|-------------------|
| `fixed` | `initial_delay` for every retry |
| `linear` | `initial_delay * attempt_number` |
| `exponential` | `min(initial_delay * 2^attempt, max_delay)` |

### Retry Example

```python
@dataclass
class RetryPolicy:
    max_retries: int = 3
    backoff: str = "exponential"
    initial_delay: timedelta = timedelta(seconds=1)
    max_delay: timedelta = timedelta(seconds=60)
    retryable_errors: List[str] = field(default_factory=lambda: ["TIMEOUT", "TRANSIENT"])

    def delay_for_attempt(self, attempt: int) -> timedelta:
        if self.backoff == "fixed":
            return self.initial_delay
        elif self.backoff == "linear":
            return self.initial_delay * attempt
        elif self.backoff == "exponential":
            delay = self.initial_delay * (2 ** (attempt - 1))
            return min(delay, self.max_delay)
```

## Task Categories and Tagging

### Categories

| Category | Description |
|----------|-------------|
| `orchestration` | Control flow tasks (fork_join, sub_workflow, wait) |
| `integration` | External system interaction (http, shell, event) |
| `transformation` | Data manipulation (transform) |
| `decision` | Conditional routing (decision) |
| `human` | Human-in-the-loop tasks (human) |

### Tags

Tags are free-form strings for discovery and filtering. Conventions:

- Lowercase, hyphen-separated
- Describe capability, not implementation
- Examples: `api`, `file-io`, `notification`, `llm`, `database`

## Discovery and Search

The registry supports querying task types by multiple criteria.

```python
class TaskRegistry:
    """Central registry for task type definitions."""

    def search(
        self,
        name: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        version_range: Optional[str] = None,
        include_deprecated: bool = False
    ) -> List[TaskTypeDefinition]:
        """Search task types by criteria."""
        ...

    def get(self, name: str, version: str = "latest") -> TaskTypeDefinition:
        """Get a specific task type by name and version."""
        ...

    def register(self, definition: TaskTypeDefinition) -> None:
        """Register a new task type or version."""
        ...

    def deprecate(self, name: str, version: str, replacement: str, removal_date: str) -> None:
        """Mark a task type version as deprecated."""
        ...

    def list_categories(self) -> List[str]:
        """List all categories with task counts."""
        ...
```

### CLI Access

```
agent33 registry list                          # list all task types
agent33 registry list --category integration   # filter by category
agent33 registry search --tag llm              # search by tag
agent33 registry show http                     # show task type details
agent33 registry show http --version 1.0.0     # show specific version
```

## Tool Governance Integration

Each task type carries governance metadata that integrates with the AGENT-33 tool governance framework defined in `core/orchestrator/TOOL_GOVERNANCE.md`.

### Provenance Checklist

Before a task type is registered, the following provenance checks are required:

| Check | Description |
|-------|-------------|
| Source identified | Handler code source is documented |
| Security reviewed | Handler reviewed for injection, data leaks |
| Schema validated | Input/output schemas are correct and complete |
| Risk assessed | Risk level assigned based on capabilities |
| Approval chain | High-risk tasks require explicit approval |

### Runtime Enforcement

At execution time, the orchestrator verifies:

1. Task type is registered and not removed
2. Input validates against schema
3. Governance approval is satisfied (for approval-required tasks)
4. Audit log entry is created (for audit-enabled tasks)
5. Output validates against schema on completion

### Risk Level Guidelines

| Risk Level | Criteria | Examples |
|------------|----------|----------|
| Low | No external side effects, read-only | transform, decision |
| Medium | External calls, reversible side effects | http (GET), event (publish) |
| High | System commands, irreversible side effects | shell, http (DELETE), file writes |
