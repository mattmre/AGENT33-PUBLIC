# DAG-Based Stage Execution Specification

**Status**: Specification
**Sources**: Spinnaker Orca (CA-107 to CA-118), Dagster (CA-119 to CA-130), Kestra (CA-041 to CA-052)

## Related Documents

- [Execution Modes](../parallel/EXECUTION_MODES.md) - Parallel and sequential execution strategies
- [Semaphore Control](../parallel/SEMAPHORE_CONTROL.md) - Concurrency limits for parallel stages
- [Dependency Graph Spec](../dependencies/DEPENDENCY_GRAPH_SPEC.md) - Underlying graph structure
- [Asset-First Workflow Schema](./ASSET_FIRST_WORKFLOW_SCHEMA.md) - Asset-centric workflow definitions
- [Expression Language Spec](./EXPRESSION_LANGUAGE_SPEC.md) - Expressions for conditions and inputs
- [Trigger Catalog](../triggers/TRIGGER_CATALOG.md) - Events that initiate pipeline execution

## Overview

This specification defines how AGENT-33 executes multi-stage workflows as directed acyclic graphs (DAGs). Each stage declares its dependencies, and the execution engine derives a topological ordering that maximizes parallelism while respecting data flow constraints. The engine supports conditional branching, dynamic fork-join patterns, synthetic stage composition, and canary execution.

## Stage Definition Schema

### Core Schema

```yaml
stage:
  id: string                       # Unique stage identifier
  name: string                     # Human-readable label
  type: task | fork | join | conditional | subworkflow
  depends_on: [stage_id]           # Upstream stage dependencies
  condition:
    expression: string             # Evaluated at runtime (see Expression Language Spec)
    on_false: skip | fail | branch_to
    branch_target: string          # Stage ID (when on_false = branch_to)
  execution:
    strategy: sequential | parallel | canary
    timeout: duration              # Max execution time (e.g., "30m", "2h")
    retries:
      max: number
      backoff: exponential | linear
      initial_delay: duration      # e.g., "5s"
    on_failure: fail_fast | continue | compensate
    compensation_stage: string     # Stage ID (when on_failure = compensate)
  inputs: {key: value_or_expression}
  outputs: {key: jsonpath_expression}
  context_variables: {key: value}  # Passed to downstream stages
```

### Python Data Model

```python
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
from datetime import timedelta


class StageType(Enum):
    TASK = "task"                # Single unit of work
    FORK = "fork"                # Fan-out to parallel branches
    JOIN = "join"                # Fan-in from parallel branches
    CONDITIONAL = "conditional"  # Branch based on expression
    SUBWORKFLOW = "subworkflow"  # Nested pipeline


class StageStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELED = "canceled"


class FailureAction(Enum):
    FAIL_FAST = "fail_fast"      # Abort entire pipeline
    CONTINUE = "continue"        # Mark failed, continue others
    COMPENSATE = "compensate"    # Run compensation stage


class BackoffStrategy(Enum):
    EXPONENTIAL = "exponential"
    LINEAR = "linear"


@dataclass
class RetryConfig:
    max_retries: int = 0
    backoff: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    initial_delay: timedelta = timedelta(seconds=5)

    def delay_for_attempt(self, attempt: int) -> timedelta:
        if self.backoff == BackoffStrategy.EXPONENTIAL:
            return self.initial_delay * (2 ** attempt)
        return self.initial_delay * (attempt + 1)


@dataclass
class StageCondition:
    expression: str                     # Runtime expression
    on_false: str = "skip"              # skip | fail | branch_to
    branch_target: Optional[str] = None


@dataclass
class StageExecution:
    strategy: str = "sequential"
    timeout: timedelta = timedelta(minutes=30)
    retries: RetryConfig = field(default_factory=RetryConfig)
    on_failure: FailureAction = FailureAction.FAIL_FAST
    compensation_stage: Optional[str] = None


@dataclass
class Stage:
    """A single stage in a DAG pipeline."""
    id: str
    name: str
    type: StageType = StageType.TASK
    depends_on: List[str] = field(default_factory=list)
    condition: Optional[StageCondition] = None
    execution: StageExecution = field(default_factory=StageExecution)
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, str] = field(default_factory=dict)
    context_variables: Dict[str, Any] = field(default_factory=dict)
    status: StageStatus = StageStatus.PENDING
```

## DAG Construction

The execution engine constructs a DAG from stage dependency declarations and validates it before execution.

```python
@dataclass
class PipelineDAG:
    """Directed acyclic graph of stages."""
    stages: Dict[str, Stage] = field(default_factory=dict)

    def add_stage(self, stage: Stage) -> None:
        if stage.id in self.stages:
            raise ValueError(f"Duplicate stage ID: {stage.id}")
        self.stages[stage.id] = stage

    def validate(self) -> List[str]:
        """Return list of validation errors, empty if valid."""
        errors = []
        # Check all dependency references exist
        for stage in self.stages.values():
            for dep in stage.depends_on:
                if dep not in self.stages:
                    errors.append(f"Stage '{stage.id}' depends on unknown stage '{dep}'")
        # Check for cycles
        if self._has_cycle():
            errors.append("Pipeline contains a dependency cycle")
        # Check join stages have corresponding forks
        for stage in self.stages.values():
            if stage.type == StageType.JOIN:
                if not stage.depends_on:
                    errors.append(f"Join stage '{stage.id}' has no dependencies")
        return errors

    def _has_cycle(self) -> bool:
        visited = set()
        in_progress = set()
        def visit(stage_id: str) -> bool:
            if stage_id in in_progress:
                return True
            if stage_id in visited:
                return False
            in_progress.add(stage_id)
            for dep_id in self._downstream(stage_id):
                if visit(dep_id):
                    return True
            in_progress.discard(stage_id)
            visited.add(stage_id)
            return False
        return any(visit(sid) for sid in self.stages if sid not in visited)

    def _downstream(self, stage_id: str) -> List[str]:
        return [
            s.id for s in self.stages.values() if stage_id in s.depends_on
        ]

    def topological_order(self) -> List[str]:
        """Return stages in valid execution order."""
        in_degree = {sid: 0 for sid in self.stages}
        for stage in self.stages.values():
            for dep in stage.depends_on:
                # dep -> stage (stage has in-degree from dep)
                pass  # in_degree computed from depends_on length
        for stage in self.stages.values():
            in_degree[stage.id] = len(stage.depends_on)
        queue = [sid for sid, d in in_degree.items() if d == 0]
        order = []
        while queue:
            sid = queue.pop(0)
            order.append(sid)
            for downstream in self._downstream(sid):
                in_degree[downstream] -= 1
                if in_degree[downstream] == 0:
                    queue.append(downstream)
        return order

    def parallel_groups(self) -> List[List[str]]:
        """Return stages grouped by execution wave (max parallelism)."""
        remaining = set(self.stages.keys())
        completed = set()
        waves = []
        while remaining:
            wave = [
                sid for sid in remaining
                if all(dep in completed for dep in self.stages[sid].depends_on)
            ]
            if not wave:
                raise ValueError("Cycle detected or unresolvable dependencies")
            waves.append(wave)
            completed.update(wave)
            remaining -= set(wave)
        return waves
```

## Execution Strategies

### Topological Sort Execution

Stages execute in dependency-safe order. Within each wave, independent stages run in parallel up to the semaphore limit.

```python
async def execute_pipeline(
    dag: PipelineDAG,
    executor: "StageExecutor",
    semaphore: "asyncio.Semaphore"
) -> Dict[str, StageStatus]:
    """Execute all stages respecting dependencies and parallelism."""
    context = PipelineContext()
    results = {}

    for wave in dag.parallel_groups():
        tasks = []
        for stage_id in wave:
            stage = dag.stages[stage_id]
            tasks.append(
                _execute_stage(stage, executor, semaphore, context, results)
            )
        wave_results = await asyncio.gather(*tasks, return_exceptions=True)
        for stage_id, result in zip(wave, wave_results):
            if isinstance(result, Exception):
                results[stage_id] = StageStatus.FAILED
                if dag.stages[stage_id].execution.on_failure == FailureAction.FAIL_FAST:
                    # Cancel remaining stages
                    for remaining in dag.stages:
                        if remaining not in results:
                            results[remaining] = StageStatus.CANCELED
                    return results
            else:
                results[stage_id] = result

    return results
```

### Parallel Fan-Out / Fan-In (Join)

Fork stages spawn parallel branches. Join stages wait for all upstream branches to complete.

```yaml
stages:
  - id: prepare
    name: "Prepare data"
    type: task

  - id: fan_out
    name: "Fork into parallel branches"
    type: fork
    depends_on: [prepare]

  - id: branch_security
    name: "Security analysis"
    type: task
    depends_on: [fan_out]

  - id: branch_performance
    name: "Performance analysis"
    type: task
    depends_on: [fan_out]

  - id: branch_usability
    name: "Usability analysis"
    type: task
    depends_on: [fan_out]

  - id: fan_in
    name: "Merge branch results"
    type: join
    depends_on: [branch_security, branch_performance, branch_usability]

  - id: report
    name: "Generate report"
    type: task
    depends_on: [fan_in]
```

### Dynamic Fork-Join

When the number of parallel branches is determined at runtime, a dynamic fork generates branches from a list produced by an upstream stage.

```python
@dataclass
class DynamicFork:
    """Runtime-determined fan-out."""
    source_stage: str              # Stage whose output determines branches
    items_expression: str          # Expression to extract list of items
    branch_template: Stage         # Template stage cloned per item
    join_stage: str                # Stage that collects results

    def resolve(self, context: "PipelineContext") -> List[Stage]:
        items = context.evaluate(self.items_expression)
        branches = []
        for i, item in enumerate(items):
            branch = self._clone_stage(self.branch_template, index=i, item=item)
            branches.append(branch)
        return branches

    def _clone_stage(self, template: Stage, index: int, item: Any) -> Stage:
        return Stage(
            id=f"{template.id}_{index}",
            name=f"{template.name} [{index}]",
            type=template.type,
            depends_on=template.depends_on,
            inputs={**template.inputs, "_item": item, "_index": index},
            execution=template.execution,
        )
```

## Synthetic Stage Composition

Multiple stages can be composed into a macro-stage (synthetic stage) that appears as a single unit in the top-level DAG. This enables reusable workflow fragments.

```python
@dataclass
class SyntheticStage:
    """A composite stage containing a sub-DAG."""
    id: str
    name: str
    sub_dag: PipelineDAG
    depends_on: List[str] = field(default_factory=list)
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, str] = field(default_factory=dict)

    def expand(self) -> List[Stage]:
        """Flatten synthetic stage into individual stages for execution."""
        expanded = []
        for stage in self.sub_dag.stages.values():
            prefixed = Stage(
                id=f"{self.id}.{stage.id}",
                name=f"{self.name} > {stage.name}",
                type=stage.type,
                depends_on=[
                    f"{self.id}.{d}" if d in self.sub_dag.stages else d
                    for d in stage.depends_on
                ],
                condition=stage.condition,
                execution=stage.execution,
                inputs=stage.inputs,
                outputs=stage.outputs,
            )
            expanded.append(prefixed)
        return expanded
```

## Conditional Branching

### If/Else

```yaml
stages:
  - id: check_quality
    name: "Evaluate quality score"
    type: task
    outputs:
      quality_score: "$.result.score"

  - id: fast_path
    name: "Apply fast-track review"
    type: task
    depends_on: [check_quality]
    condition:
      expression: "${check_quality.output.quality_score >= 90}"
      on_false: skip

  - id: full_review
    name: "Full review cycle"
    type: task
    depends_on: [check_quality]
    condition:
      expression: "${check_quality.output.quality_score < 90}"
      on_false: skip
```

### Switch/Case

```yaml
stages:
  - id: classify
    name: "Classify task type"
    type: task
    outputs:
      task_type: "$.result.type"

  - id: handle_bug
    type: task
    depends_on: [classify]
    condition:
      expression: "${classify.output.task_type == 'bug'}"
      on_false: skip

  - id: handle_feature
    type: task
    depends_on: [classify]
    condition:
      expression: "${classify.output.task_type == 'feature'}"
      on_false: skip

  - id: handle_refactor
    type: task
    depends_on: [classify]
    condition:
      expression: "${classify.output.task_type == 'refactor'}"
      on_false: skip
```

## Error Handling

Each stage defines its own error handling behavior through the `on_failure` field.

### Strategies

| Strategy | Behavior |
|----------|----------|
| `fail_fast` | Abort the entire pipeline immediately |
| `continue` | Mark stage as failed, continue with independent stages |
| `compensate` | Run a compensation stage to undo partial work |

### Retry with Backoff

```python
async def _execute_with_retry(
    stage: Stage,
    executor: "StageExecutor",
    context: "PipelineContext"
) -> StageStatus:
    retries = stage.execution.retries
    last_error = None

    for attempt in range(retries.max_retries + 1):
        try:
            result = await asyncio.wait_for(
                executor.run(stage, context),
                timeout=stage.execution.timeout.total_seconds()
            )
            return StageStatus.SUCCEEDED
        except asyncio.TimeoutError:
            last_error = TimeoutError(f"Stage '{stage.id}' timed out")
        except Exception as e:
            last_error = e

        if attempt < retries.max_retries:
            delay = retries.delay_for_attempt(attempt)
            await asyncio.sleep(delay.total_seconds())

    # All retries exhausted
    if stage.execution.on_failure == FailureAction.COMPENSATE:
        comp_id = stage.execution.compensation_stage
        if comp_id:
            await executor.run(context.pipeline.stages[comp_id], context)
    return StageStatus.FAILED
```

### Compensation Example

```yaml
stages:
  - id: provision_resources
    name: "Provision agent resources"
    type: task
    execution:
      on_failure: compensate
      compensation_stage: cleanup_resources

  - id: cleanup_resources
    name: "Release provisioned resources"
    type: task
    # Only runs as compensation; not in normal DAG path
```

## Stage Lifecycle

```
            +---> SUCCEEDED
            |
PENDING ---> RUNNING ---+---> FAILED
                        |
                        +---> CANCELED (external signal)

PENDING ---> SKIPPED (condition evaluated false)
```

### State Transitions

| From | To | Trigger |
|------|----|---------|
| PENDING | RUNNING | All dependencies satisfied, condition true |
| PENDING | SKIPPED | Condition evaluates to false |
| PENDING | CANCELED | Pipeline abort signal |
| RUNNING | SUCCEEDED | Stage completes without error |
| RUNNING | FAILED | Stage errors after all retries exhausted |
| RUNNING | CANCELED | Pipeline abort or timeout |

## Canary Execution

Run a pipeline on a subset of inputs before committing to a full run. The canary verifies that stages succeed before scaling out.

```python
@dataclass
class CanaryConfig:
    """Run a subset before full execution."""
    sample_size: int = 1                 # Number of items in canary batch
    success_threshold: float = 1.0       # Required success rate (0.0 to 1.0)
    auto_promote: bool = False           # Automatically proceed if canary passes
    rollback_on_failure: bool = True     # Revert canary results on failure
```

```yaml
stages:
  - id: process_all_specs
    name: "Process all specifications"
    type: task
    execution:
      strategy: canary
      canary:
        sample_size: 2
        success_threshold: 1.0
        auto_promote: true
```

## Pipeline Templates

Reusable stage compositions that can be instantiated with parameters.

```yaml
templates:
  - name: review_cycle
    description: "Standard three-phase review"
    parameters:
      artifact_type: string
      reviewer_agent: string
    stages:
      - id: lint
        name: "Lint ${artifact_type}"
        type: task
        inputs:
          type: "${artifact_type}"

      - id: review
        name: "Agent review"
        type: task
        depends_on: [lint]
        inputs:
          agent: "${reviewer_agent}"

      - id: approve
        name: "Final approval"
        type: task
        depends_on: [review]

# Instantiation:
pipelines:
  - name: security_review
    template: review_cycle
    parameters:
      artifact_type: "security_policy"
      reviewer_agent: "gemini-review"
```

## Integration with Existing Specs

### Parallel Execution (CA-008)

The DAG engine delegates concurrent stage execution to the parallel execution infrastructure defined in [Execution Modes](../parallel/EXECUTION_MODES.md). Each wave of independent stages is executed using `ParallelMode` with the configured semaphore limit from [Semaphore Control](../parallel/SEMAPHORE_CONTROL.md).

### Dependency Graph

Stage dependencies are projected into the dependency graph as `NodeType.WORKFLOW` nodes with `EdgeType.INVOKES` edges, enabling cross-system dependency tracking.

## Complete Pipeline Example

```yaml
pipeline:
  name: competitive_analysis_pipeline
  description: "End-to-end competitive analysis with conditional deep-dives"

  stages:
    - id: gather
      name: "Gather framework data"
      type: task
      execution:
        timeout: "2h"
        retries: {max: 2, backoff: exponential}
      outputs:
        frameworks: "$.result.frameworks"
        count: "$.result.count"

    - id: should_parallelize
      name: "Decide execution strategy"
      type: conditional
      depends_on: [gather]
      condition:
        expression: "${gather.output.count > 5}"
        on_false: branch_to
        branch_target: sequential_analysis

    - id: parallel_fan_out
      name: "Fork per framework"
      type: fork
      depends_on: [should_parallelize]

    - id: analyze_framework
      name: "Analyze framework"
      type: task
      depends_on: [parallel_fan_out]
      # Dynamic: cloned per framework item

    - id: parallel_fan_in
      name: "Merge analyses"
      type: join
      depends_on: [analyze_framework]

    - id: sequential_analysis
      name: "Analyze all sequentially"
      type: task
      depends_on: [gather]
      condition:
        expression: "${gather.output.count <= 5}"
        on_false: skip

    - id: synthesize
      name: "Synthesize findings"
      type: task
      depends_on: [parallel_fan_in, sequential_analysis]
      execution:
        on_failure: fail_fast

    - id: publish
      name: "Publish report"
      type: task
      depends_on: [synthesize]
      execution:
        retries: {max: 1, backoff: linear}
```
