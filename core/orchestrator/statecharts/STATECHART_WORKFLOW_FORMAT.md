# Statechart Workflow Format Specification

**Status**: Specification
**Source**: CA-065 to CA-076 (XState competitive analysis)

## Overview

This document defines a statechart-based workflow representation for AGENT-33 using hierarchical state machines with parallel regions, guards, and actions. Statecharts extend finite state machines with hierarchy (nested states), concurrency (parallel regions), and communication (events and actions), enabling complex orchestration workflows to be modeled as formal, verifiable, and visualizable state diagrams.

## State Types

AGENT-33 statecharts support five state node types, each serving a distinct role in workflow composition.

### Atomic State

A leaf state with no child states. Represents a concrete step in a workflow.

```yaml
states:
  reviewing:
    type: atomic
    entry: [start_review_timer]
    on:
      APPROVE:
        target: approved
      REJECT:
        target: rejected
```

### Compound State (Nested)

A state containing child states, exactly one of which is active at any time. Enables hierarchical decomposition of complex behavior.

```yaml
states:
  processing:
    type: compound
    initial: validating
    states:
      validating:
        type: atomic
        on:
          VALID:
            target: executing
          INVALID:
            target: failed
      executing:
        type: atomic
        on:
          COMPLETE:
            target: done
      failed:
        type: final
      done:
        type: final
```

### Parallel State

A state containing multiple regions that execute concurrently. All regions are active simultaneously and evolve independently until a synchronization point.

```yaml
states:
  analysis:
    type: parallel
    regions:
      - id: code_review
        initial: pending
        states:
          pending:
            on:
              START_REVIEW:
                target: in_progress
          in_progress:
            on:
              REVIEW_DONE:
                target: complete
          complete:
            type: final
      - id: security_scan
        initial: pending
        states:
          pending:
            on:
              START_SCAN:
                target: scanning
          scanning:
            on:
              SCAN_DONE:
                target: complete
          complete:
            type: final
    onAllDone:
      target: merged
```

### Final State

A terminal state indicating that the enclosing compound or parallel region has completed. When all parallel regions reach a final state, the parent parallel state itself completes.

```yaml
states:
  completed:
    type: final
    entry: [record_completion]
```

### History State

A pseudo-state that remembers the last active child state of its parent compound state, enabling resumption after interruption.

| Variant | Behavior |
|---------|----------|
| Shallow | Remembers the immediate child state only |
| Deep    | Remembers the full nested state hierarchy |

```yaml
states:
  workflow:
    type: compound
    initial: drafting
    states:
      drafting:
        on:
          SUBMIT:
            target: review
      review:
        on:
          REVISE:
            target: drafting
      interrupted:
        type: atomic
        on:
          RESUME:
            target: history_node
      history_node:
        type: history
        variant: deep
```

## Transitions

Transitions define how the machine moves between states in response to events.

### Event-Driven Transitions

```yaml
on:
  EVENT_NAME:
    target: next_state
    guard: expression
    actions: [action_list]
```

### Guarded Transitions

Guards are boolean expressions evaluated against the machine context. A transition fires only when its guard evaluates to true. Multiple transitions for the same event are evaluated in order; the first whose guard passes wins.

```yaml
on:
  SUBMIT:
    - target: auto_approved
      guard: "context.risk_level == 'low' and context.score >= 90"
      actions: [log_auto_approve]
    - target: manual_review
      guard: "context.risk_level == 'medium'"
      actions: [assign_reviewer]
    - target: escalation
      guard: "context.risk_level == 'high'"
      actions: [notify_admin, assign_senior_reviewer]
```

Guard expressions use the AGENT-33 expression language (see integration section below).

### Null Events (Always / Eventless Transitions)

Transitions that fire immediately when their guard condition is met, without an explicit event.

```yaml
states:
  checking:
    always:
      - target: approved
        guard: "context.all_checks_passed"
      - target: rejected
        guard: "context.has_critical_failure"
```

### Wildcard Transitions

Catch-all transitions that fire for any event not explicitly handled by the current state.

```yaml
on:
  "*":
    actions: [log_unhandled_event]
```

## Actions

Actions are side effects executed at specific points in the state machine lifecycle.

### Action Types

| Trigger | When Executed |
|---------|---------------|
| Entry actions | When a state is entered |
| Exit actions | When a state is exited |
| Transition actions | During a transition, after exit and before entry |

### Action Definition

```yaml
actions:
  start_review_timer:
    type: invoke
    handler: timers.start
    params:
      name: review_deadline
      duration: 24h

  assign_reviewer:
    type: assign
    context_updates:
      reviewer: "agents.select('reviewer', context.task_type)"
      assigned_at: "now()"

  log_auto_approve:
    type: emit
    event: AUDIT_LOG
    data:
      action: auto_approve
      reason: "Low risk, high score"

  notify_admin:
    type: send
    target: admin_channel
    event: ESCALATION_REQUIRED
    data:
      workflow_id: "context.id"
      risk_level: "context.risk_level"
```

### Built-in Action Types

| Type | Purpose |
|------|---------|
| `assign` | Update machine context |
| `emit` | Emit an event to parent or external listeners |
| `send` | Send an event to another machine or service |
| `invoke` | Call an external handler |
| `log` | Write to execution trace |
| `raise` | Send an event to self (processed in current step) |

## Context (Extended State)

Context is the mutable data carried by the machine, separate from the finite state. Context enables data-driven decisions without state explosion.

```yaml
statechart:
  id: code_review_workflow
  context:
    pull_request_id: null
    author: null
    reviewer: null
    risk_level: low
    score: 0
    checks_passed: []
    all_checks_passed: false
    has_critical_failure: false
    retry_count: 0
    max_retries: 3
```

Context is updated exclusively through `assign` actions to maintain traceability.

## Invocations

Invocations spawn child machines or external services. The parent state remains active until the invoked service completes or fails.

### Service Invocation

```yaml
states:
  running_agent:
    invoke:
      id: agent_task
      src: agent_executor
      input:
        agent: "context.assigned_agent"
        task: "context.current_task"
        tools: "context.allowed_tools"
      onDone:
        target: evaluating_result
        actions:
          - type: assign
            context_updates:
              result: "event.data.output"
      onError:
        target: handling_failure
        actions:
          - type: assign
            context_updates:
              error: "event.data.message"
              retry_count: "context.retry_count + 1"
```

### Child Machine Invocation

```yaml
states:
  sub_workflow:
    invoke:
      id: review_sub
      src: statechart:review_workflow
      input:
        artifact: "context.artifact"
      onDone:
        target: next_step
      onError:
        target: error_handling
```

### Agent Handoff Invocation

Statechart invocations integrate with the AGENT-33 agent handoff protocol. When `src` references an agent identifier, the orchestrator dispatches to that agent and awaits completion.

```yaml
states:
  code_generation:
    invoke:
      id: implementer_task
      src: agent:implementer
      input:
        task: "context.task_description"
        files: "context.target_files"
      onDone:
        target: code_review
      onError:
        target: escalation
```

## Delayed Transitions

Transitions that fire after a specified timeout, enabling deadline enforcement and polling patterns.

```yaml
states:
  waiting_for_approval:
    on:
      APPROVED:
        target: approved
      REJECTED:
        target: rejected
    after:
      86400000:  # 24 hours in ms
        target: auto_rejected
        actions: [notify_timeout]

      # Named delays resolved from context
      "context.sla_deadline_ms":
        target: sla_breach
        actions: [escalate_sla]
```

Delayed transitions are cancelled when the state is exited before the timeout elapses.

## Parallel Regions

Parallel regions model concurrent activities within a single state. Each region is an independent state machine.

### Synchronization

All regions must reach a final state for the parent parallel state to complete. The `onAllDone` transition fires when this condition is met.

### Inter-Region Communication

Regions communicate via shared context (read-only access to sibling region data) and events (raised events are broadcast to all regions).

```yaml
states:
  pipeline:
    type: parallel
    regions:
      - id: build
        initial: compiling
        states:
          compiling:
            invoke:
              src: agent:builder
              onDone:
                target: built
                actions:
                  - type: assign
                    context_updates:
                      build_artifact: "event.data.artifact"
            on:
              BUILD_FAILED:
                target: build_error
          built:
            type: final
          build_error:
            type: final
            entry:
              - type: raise
                event: REGION_FAILED
                data:
                  region: build
      - id: lint
        initial: linting
        states:
          linting:
            invoke:
              src: agent:linter
              onDone:
                target: linted
          linted:
            type: final
    on:
      REGION_FAILED:
        target: pipeline_failed
    onAllDone:
      target: deploy
```

## Machine Composition

### Nested Machines

A statechart can invoke another statechart as a child. The child runs independently with its own context, communicating with the parent through done/error events and optional output data.

### Parallel Machines

Multiple independent machines can run concurrently, coordinated by a parent parallel state or by an external supervisor machine.

### Machine Registry

Machines are registered by ID and version, enabling reuse across workflows.

```yaml
machine_registry:
  - id: code_review_workflow
    version: "1.2.0"
    src: statecharts/code_review.yaml
  - id: deploy_workflow
    version: "2.0.0"
    src: statecharts/deploy.yaml
```

## Serialization Format

All statecharts are serialized as YAML (primary) or JSON (interchange). The canonical format is:

```yaml
statechart:
  id: string                    # unique machine identifier
  version: semver               # machine version
  initial: state_id             # initial state
  context: {key: value}         # extended state data

  states:
    state_id:
      type: atomic | compound | parallel | final | history

      # History-specific
      variant: shallow | deep   # only for type: history

      # Entry/exit actions
      entry: [action]
      exit: [action]

      # Event-driven transitions
      on:
        EVENT_NAME:
          target: state_id
          guard: expression
          actions: [action]

      # Eventless transitions
      always:
        - target: state_id
          guard: expression
          actions: [action]

      # Delayed transitions
      after:
        delay_ms_or_expression:
          target: state_id
          actions: [action]

      # Service invocation
      invoke:
        id: string
        src: service_ref | statechart:id | agent:id
        input: {key: expression}
        onDone:
          target: state_id
          actions: [action]
        onError:
          target: state_id
          actions: [action]

      # Nested states (compound)
      initial: state_id
      states: {}

      # Parallel regions
      regions: []
      onAllDone:
        target: state_id

  # Top-level action definitions
  actions:
    action_name:
      type: assign | emit | send | invoke | log | raise
      # type-specific parameters
```

### JSON Interchange

The YAML format maps directly to JSON for programmatic consumption, API exchange, and storage in document databases.

```json
{
  "statechart": {
    "id": "example",
    "version": "1.0.0",
    "initial": "idle",
    "context": {},
    "states": {
      "idle": {
        "type": "atomic",
        "on": {
          "START": {
            "target": "running"
          }
        }
      },
      "running": {
        "type": "atomic",
        "on": {
          "DONE": {
            "target": "complete"
          }
        }
      },
      "complete": {
        "type": "final"
      }
    }
  }
}
```

## Visualization Support

Statecharts export to standard diagram formats for documentation and debugging.

### Export Formats

| Format | Use Case |
|--------|----------|
| Mermaid stateDiagram | Inline in Markdown documentation |
| PlantUML | CI-generated diagrams |
| DOT (Graphviz) | Detailed layout control |
| SVG | Standalone visual artifacts |

### Mermaid Export Example

A statechart is convertible to Mermaid syntax:

```
stateDiagram-v2
    [*] --> idle
    idle --> running : START
    running --> evaluating : STEP_COMPLETE
    evaluating --> running : CONTINUE [has_more_steps]
    evaluating --> complete : FINISH [all_steps_done]
    complete --> [*]

    state running {
        [*] --> executing
        executing --> waiting : INVOKE
        waiting --> executing : RESULT
    }
```

### Visualization Metadata

States and transitions may carry optional display hints.

```yaml
states:
  review:
    meta:
      label: "Code Review"
      description: "Agent reviews code changes"
      color: "#4A90D9"
      position: {x: 200, y: 100}
```

## AGENT-33 Integration

### Statechart Execution Mode

Statechart mode is a new execution mode alongside sequential, parallel, and pipeline modes defined in `core/orchestrator/parallel/EXECUTION_MODES.md`.

```python
@dataclass
class StatechartMode:
    """Execute workflow as a statechart."""
    name: str = "statechart"
    machine_id: str = ""
    machine_version: str = "latest"

    async def execute(
        self,
        machine: StatechartDefinition,
        initial_context: Dict[str, Any],
        executor: TaskExecutor
    ) -> ExecutionResults:
        """
        Interpret the statechart, processing events
        and invoking services until a final state is reached.
        """
        interpreter = StatechartInterpreter(machine, executor)
        return await interpreter.run(initial_context)
```

### Expression Language Integration

Guard expressions and context update expressions use the AGENT-33 expression language. Available bindings:

| Binding | Description |
|---------|-------------|
| `context` | Current machine context |
| `event` | Current event being processed (including `event.data`) |
| `now()` | Current timestamp |
| `agents` | Agent registry for dynamic agent selection |
| `env` | Environment configuration |

### Agent Handoff Integration

Service invocations with `src: agent:<agent_id>` dispatch to the AGENT-33 agent handoff protocol. The invocation input maps to the agent task payload, and the done/error events map to the agent completion or failure signals.

### Tool Governance Integration

Actions of type `invoke` that call external tools are subject to the provenance checklist defined in `core/orchestrator/TOOL_GOVERNANCE.md`. The statechart executor validates tool permissions before dispatching.

## Validation Rules

A valid statechart must satisfy:

1. Exactly one `initial` state declared for the machine and each compound state
2. All `target` references resolve to existing state IDs within scope
3. No orphan states (every non-initial state is reachable via at least one transition)
4. Parallel states have at least two regions
5. Each region in a parallel state has at least one final state (unless the parallel state itself handles termination via event)
6. Guard expressions parse without errors
7. Action references resolve to defined actions or built-in types
8. Invocation `src` references resolve to registered services, machines, or agents
9. No circular eventless (always) transitions that would cause infinite loops
10. Context schema is consistent with all assign action updates
