# Workflow Testing Framework

Purpose: Define patterns for testing workflows, task types, and agent behavior in isolation and integration.

Sources: Dagster (CA-119 to CA-130), XState model-based testing (CA-065 to CA-076)

Related docs:
- `core/orchestrator/TRACE_SCHEMA.md` (trace schema for test result recording)
- `core/orchestrator/handoff/DEFINITION_OF_DONE.md` (quality gates)
- `core/orchestrator/TOOLS_AS_CODE.md` (task type definitions)
- `core/orchestrator/analytics/METRICS_CATALOG.md` (coverage and quality metrics)
- `core/orchestrator/modes/DRY_RUN_SPEC.md` (dry run execution for test scenarios)
- `core/orchestrator/plugins/PLUGIN_REGISTRY_SPEC.md` (plugin testing requirements)

---

## Overview

The workflow testing framework provides structured patterns for verifying orchestration behavior at every level: individual tasks, multi-stage pipelines, full end-to-end workflows, and statechart model conformance. Tests are first-class artifacts that live alongside workflow definitions and are executed as part of the CI pipeline.

## Test Types

### Unit Tests

Test a single task type or agent action in isolation. All dependencies are mocked.

| Aspect | Detail |
|--------|--------|
| **Scope** | One task, one agent action, or one transform |
| **Dependencies** | All mocked (agents, tools, context, assets) |
| **Speed** | Fast (under 5 seconds per test) |
| **Purpose** | Verify input-output contracts and error handling |

### Integration Tests

Test multi-stage interactions where two or more components collaborate.

| Aspect | Detail |
|--------|--------|
| **Scope** | Two or more stages, handoff sequences, or plugin interactions |
| **Dependencies** | Real orchestrator, mocked external services |
| **Speed** | Medium (under 60 seconds per test) |
| **Purpose** | Verify stage sequencing, data flow, and handoff correctness |

### End-to-End Tests

Test a complete workflow from trigger to final output.

| Aspect | Detail |
|--------|--------|
| **Scope** | Full workflow definition executed top to bottom |
| **Dependencies** | Real orchestrator, real or sandboxed external services |
| **Speed** | Slow (minutes, budget-constrained) |
| **Purpose** | Verify the workflow produces correct final outcomes |

### Property-Based Tests

Generate randomized inputs and verify that invariants hold across all executions.

| Aspect | Detail |
|--------|--------|
| **Scope** | Any component with definable invariants |
| **Dependencies** | Configurable (mock or real) |
| **Speed** | Variable (depends on iteration count, default: 100 runs) |
| **Purpose** | Discover edge cases that example-based tests miss |

**Common properties to test:**
- Idempotency: running a task twice with the same input produces the same output.
- Monotonicity: adding more context never reduces output quality score.
- Bounded duration: no task exceeds its declared timeout.
- Schema conformance: all outputs match their declared schema.

### Model-Based Tests

Generate test cases automatically from a statechart model of the workflow.

| Aspect | Detail |
|--------|--------|
| **Scope** | Statechart-defined workflows |
| **Dependencies** | Model definition plus orchestrator |
| **Speed** | Variable (depends on state space size) |
| **Purpose** | Achieve transition and path coverage systematically |

**Process:**
1. Define the workflow as a statechart (states, transitions, guards, actions).
2. The test generator walks the statechart to produce test paths.
3. Each path becomes a test case with concrete inputs derived from guard conditions.
4. Execute each path and verify that the system reaches the expected final state.

## Test Definition Schema

```yaml
test:
  # Identity
  name: string                        # unique test name
  description: string                 # what this test verifies
  type: unit | integration | e2e | property | model
  target: workflow_id | task_type | agent_role

  # Tags and filtering
  tags: [string]                      # e.g. [smoke, regression, nightly]
  priority: critical | high | medium | low

  # Fixtures
  fixtures:
    agents:
      - name: string                  # mock agent identifier
        role: string                  # agent role to mock
        behavior: static | scripted | passthrough
        responses:                    # for static/scripted behavior
          - trigger: string           # input pattern to match
            response: value           # canned response
    tools:
      - name: string                  # mock tool identifier
        type: string                  # tool type
        behavior: static | scripted | passthrough
        responses:
          - trigger: string
            response: value
    context:
      key: value                      # initial context entries
    assets:
      - name: string                  # mock asset identifier
        type: string                  # asset type (file, url, etc.)
        content: string | filepath    # inline content or path to fixture file

  # Test steps
  steps:
    - action: trigger | assert | wait | inject_fault | set_context | send_event
      target: stage_id | expression | agent_name
      params:
        key: value                    # action-specific parameters
      description: string             # human-readable step description

  # Assertions
  assertions:
    - type: stage_completed | output_matches | no_errors | within_timeout | within_budget | state_equals | transition_occurred
      target: string                  # stage ID, output path, or metric name
      expected: value                 # expected value or pattern
      tolerance: number               # optional tolerance for numeric comparisons
      message: string                 # custom failure message

  # Coverage requirements
  coverage:
    required_minimum: percentage      # e.g. 80
    types:
      - stage                         # every stage executed at least once
      - transition                    # every transition traversed at least once
      - path                          # every distinct path through the workflow
      - expression                    # every guard expression evaluated both true and false

  # Execution constraints
  constraints:
    timeout: duration                 # max test duration (e.g. 30s, 5m)
    budget: number                    # max cost in tokens or API calls
    retries: number                   # retry count on transient failure (default: 0)
    environment: local | sandbox | ci # required execution environment
```

## Test Fixtures

### Mock Agents

Mock agents simulate agent behavior without invoking real LLM calls.

| Behavior | Description |
|----------|-------------|
| **static** | Always returns the same response regardless of input |
| **scripted** | Returns responses from an ordered list, matched by trigger pattern |
| **passthrough** | Forwards to the real agent (used in integration and e2e tests) |

```yaml
mock_agent:
  name: mock_reviewer
  role: reviewer
  behavior: scripted
  responses:
    - trigger: "review.*code"
      response:
        verdict: approved
        comments: ["Looks good"]
    - trigger: "review.*security"
      response:
        verdict: needs_changes
        comments: ["Missing input validation"]
  default_response:
    verdict: approved
    comments: []
```

### Mock Tools

Mock tools simulate external tool invocations.

```yaml
mock_tool:
  name: mock_git
  type: shell_command
  behavior: scripted
  responses:
    - trigger: "git status"
      response:
        exit_code: 0
        stdout: "On branch main\nnothing to commit"
    - trigger: "git diff"
      response:
        exit_code: 0
        stdout: ""
  default_response:
    exit_code: 1
    stderr: "unknown command"
```

### Mock Context

Pre-populated context entries for deterministic testing.

```yaml
mock_context:
  session_id: "test-session-001"
  workflow_id: "wf-unit-test"
  user: "test-operator"
  environment: "test"
  timestamp: "2026-01-30T00:00:00Z"
  custom:
    project_name: "test-project"
    branch: "feature/test"
```

### Mock Assets

File fixtures and synthetic data for test inputs.

```yaml
mock_asset:
  name: sample_input
  type: file
  content_path: fixtures/sample_input.json    # relative to test directory
  checksum: sha256:abc123...
```

## Assertion Library

### Built-in Assertion Types

| Assertion | Description | Parameters |
|-----------|-------------|------------|
| `stage_completed` | Verify a stage reached `completed` status | `target`: stage ID |
| `stage_failed` | Verify a stage reached `failed` status | `target`: stage ID |
| `output_matches` | Verify output matches expected value or pattern | `target`: output path, `expected`: value or regex |
| `output_schema` | Verify output conforms to a JSON Schema | `target`: output path, `expected`: schema ref |
| `no_errors` | Verify no errors were recorded during execution | (none) |
| `error_contains` | Verify a specific error message was produced | `expected`: substring or regex |
| `within_timeout` | Verify execution completed within a duration | `expected`: duration string |
| `within_budget` | Verify execution cost stayed within budget | `expected`: numeric limit |
| `state_equals` | Verify the workflow is in a specific state | `target`: state name |
| `transition_occurred` | Verify a specific state transition happened | `target`: "from_state -> to_state" |
| `context_contains` | Verify context has a specific key-value | `target`: key path, `expected`: value |
| `trace_contains` | Verify the execution trace includes a specific action | `expected`: action type or pattern |

### Custom Assertions

Tests can define inline custom assertions using expressions.

```yaml
assertions:
  - type: custom
    expression: "output.score >= 0.8 and output.score <= 1.0"
    message: "Score must be between 0.8 and 1.0"
```

## Snapshot Testing

Snapshot tests capture the full workflow state at a checkpoint and compare it against a stored golden reference.

### How Snapshots Work

1. **Capture**: During a baseline run, the framework serializes workflow state at declared checkpoints.
2. **Store**: The serialized state is saved as a `.snapshot.yaml` file alongside the test.
3. **Compare**: On subsequent runs, the framework captures state at the same checkpoints and diffs against the stored snapshot.
4. **Update**: When intentional changes are made, the operator runs `--update-snapshots` to regenerate golden files.

### Snapshot Schema

```yaml
snapshot:
  test_name: string
  captured_at: ISO-8601
  checkpoints:
    - name: string                    # checkpoint identifier
      stage_id: string               # stage at which state was captured
      state:
        status: string
        context: {key: value}
        outputs: {key: value}
        active_stages: [string]
```

### Snapshot Diff Rules

- Keys listed in `ignore_keys` are excluded from comparison (e.g., timestamps, trace IDs).
- Numeric values can specify a tolerance (e.g., `duration_ms` within 10%).
- New keys in the actual output produce a warning, not a failure.
- Missing keys in the actual output produce a failure.

```yaml
snapshot_config:
  ignore_keys: [trace_id, session_id, timestamp, captured_at]
  numeric_tolerance:
    duration_ms: 0.10               # 10% tolerance
  fail_on_new_keys: false
  fail_on_missing_keys: true
```

## Model-Based Testing

Model-based testing generates test cases from a statechart model, ensuring systematic coverage of states and transitions.

### Statechart Model Definition

```yaml
model:
  name: string
  initial_state: string
  states:
    - name: string
      type: normal | final | parallel
      on_enter: [action]
      on_exit: [action]
  transitions:
    - from: string
      to: string
      event: string
      guard: expression              # boolean condition
      actions: [action]
```

### Test Generation Strategies

| Strategy | Description | Coverage Target |
|----------|-------------|-----------------|
| **All states** | Generate paths that visit every state at least once | Stage coverage |
| **All transitions** | Generate paths that traverse every transition at least once | Transition coverage |
| **All paths** | Generate paths covering every unique path (up to a depth limit) | Path coverage |
| **All guards** | Generate inputs that evaluate every guard both true and false | Expression coverage |
| **Random walk** | Random traversal for stress testing (configurable iterations) | Statistical coverage |

### Generated Test Output

The generator produces concrete test cases in the standard test definition schema, which can be run like any other test.

```yaml
# Auto-generated from model "review_workflow", strategy: all_transitions
test:
  name: auto_review_workflow_transition_001
  description: "Path: idle -> reviewing -> approved -> complete"
  type: model
  target: review_workflow
  steps:
    - action: send_event
      target: review_workflow
      params: {event: submit_review, input: {code: "print('hello')"}}
    - action: assert
      target: state
      params: {expected: reviewing}
    - action: send_event
      target: review_workflow
      params: {event: approve}
    - action: assert
      target: state
      params: {expected: complete}
```

## Coverage Metrics

### Coverage Types

| Metric | Definition | Calculation |
|--------|-----------|-------------|
| **Stage coverage** | Percentage of workflow stages executed by test suite | `executed_stages / total_stages * 100` |
| **Transition coverage** | Percentage of state transitions traversed | `traversed_transitions / total_transitions * 100` |
| **Path coverage** | Percentage of distinct execution paths tested (bounded by depth) | `tested_paths / enumerated_paths * 100` |
| **Expression coverage** | Percentage of guard/condition expressions evaluated both true and false | `fully_evaluated / total_expressions * 100` |

### Coverage Thresholds

| Level | Stage | Transition | Path | Expression |
|-------|-------|-----------|------|------------|
| **Minimum** | 80% | 70% | 50% | 60% |
| **Target** | 95% | 90% | 75% | 80% |
| **Required for release** | 90% | 80% | 60% | 70% |

### Coverage Reporting

```yaml
coverage_report:
  test_suite: string
  generated_at: ISO-8601
  summary:
    stage_coverage: percentage
    transition_coverage: percentage
    path_coverage: percentage
    expression_coverage: percentage
  uncovered:
    stages: [stage_id]
    transitions: [{from: string, to: string, event: string}]
    expressions: [expression_string]
```

## Test Execution Environments

### Local

- Runs on the developer's machine.
- All external dependencies are mocked.
- Fast feedback loop (seconds).
- Used during development and before committing.

### Sandbox

- Runs in an isolated environment with controlled external access.
- Real orchestrator, sandboxed external services (stubs or containers).
- Medium speed (seconds to minutes).
- Used for integration testing and plugin validation.

### CI

- Runs automatically on every push or pull request.
- Full test suite execution with coverage reporting.
- Results are recorded in the trace schema and published to the analytics dashboard.
- Failures block merge.

### Execution Configuration

```yaml
execution:
  environment: local | sandbox | ci
  parallelism: number               # max concurrent tests (default: 4)
  fail_fast: boolean                 # stop on first failure (default: false in CI)
  timeout_multiplier: number         # scale all timeouts (e.g., 2.0 for slow CI)
  report_format: yaml | json | junit # output format
  report_path: string                # output file path
  coverage_output: string            # coverage report path
```

## Regression Test Management

### Golden Tests

Golden tests are high-value tests that represent critical workflow behaviors. They are tagged and receive special treatment.

- Golden tests are never skipped in CI.
- Golden test failures block release.
- Changes to golden test expectations require explicit operator approval.
- Golden tests are versioned alongside the workflow definitions they protect.

```yaml
test:
  name: critical_review_flow
  tags: [golden, regression]
  # ... standard test definition
```

### Flaky Test Detection

A test is marked flaky if it produces inconsistent results across runs with identical inputs.

**Detection criteria:**
- A test that fails and then passes on retry without code changes.
- A test that has a failure rate between 1% and 50% over the last 20 runs.

**Handling:**
1. Flaky tests are automatically tagged `flaky` in the test registry.
2. Flaky tests produce warnings instead of failures in CI (unless they are golden tests).
3. A flaky test report is generated weekly listing all flaky tests and their failure rates.
4. Flaky tests that remain unresolved for 14 days are escalated to the operator.

### Test Quarantine

Tests that are known-broken but not yet fixed can be quarantined.

```yaml
quarantine:
  test_name: string
  reason: string
  quarantined_at: ISO-8601
  quarantined_by: string
  expected_fix_date: ISO-8601
  ticket: string                     # tracking issue reference
```

- Quarantined tests are skipped in CI but logged.
- A quarantine report is published daily listing all quarantined tests.
- Tests quarantined for more than 30 days are escalated.

## Integration Points

### Evaluation Harness

The testing framework feeds results into the evaluation harness for quality tracking.

- Test pass/fail rates are recorded as quality metrics.
- Coverage metrics are tracked over time to detect regression.
- Test duration trends are monitored for performance regression.

### Regression Gates

Tests integrate with the regression gate system to block deployments on failure.

| Gate | Condition | Action on failure |
|------|-----------|-------------------|
| **Pre-merge** | All unit and integration tests pass | Block merge |
| **Pre-deploy** | All golden and e2e tests pass | Block deployment |
| **Post-deploy** | Smoke tests pass in production | Trigger rollback |

### Trace Schema

Test executions are recorded in the trace schema for audit and analysis.

```yaml
trace:
  type: test_execution
  test_name: string
  test_type: string
  result: pass | fail | skip | error
  duration_ms: number
  coverage: {stage: pct, transition: pct, path: pct, expression: pct}
  assertions_total: number
  assertions_passed: number
  failure_details: string            # populated on failure
```

---

## Appendix: Example Test Suite

```yaml
# tests/review_workflow_test.yaml
suite:
  name: review_workflow_tests
  target: review_workflow

tests:
  - name: test_happy_path_approval
    type: unit
    fixtures:
      agents:
        - name: mock_reviewer
          role: reviewer
          behavior: static
          responses:
            - trigger: ".*"
              response: {verdict: approved, comments: ["LGTM"]}
      context:
        code_path: "src/main.py"
    steps:
      - action: trigger
        target: review_stage
        params: {input: {file: "src/main.py", diff: "+print('hello')"}}
      - action: assert
        target: review_stage
        params: {type: stage_completed}
    assertions:
      - type: stage_completed
        target: review_stage
      - type: output_matches
        target: review_stage.verdict
        expected: approved
      - type: no_errors
      - type: within_timeout
        expected: 10s

  - name: test_rejection_triggers_rework
    type: integration
    fixtures:
      agents:
        - name: mock_reviewer
          role: reviewer
          behavior: scripted
          responses:
            - trigger: ".*"
              response: {verdict: needs_changes, comments: ["Fix naming"]}
      context:
        code_path: "src/main.py"
    steps:
      - action: trigger
        target: review_stage
        params: {input: {file: "src/main.py", diff: "+x=1"}}
      - action: assert
        target: review_stage
        params: {type: stage_completed}
      - action: assert
        target: rework_stage
        params: {type: stage_completed}
    assertions:
      - type: stage_completed
        target: review_stage
      - type: transition_occurred
        target: "review_stage -> rework_stage"
      - type: output_matches
        target: review_stage.verdict
        expected: needs_changes
```
