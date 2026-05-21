# Decision Routing Specification

**Status**: Specification
**Sources**: Osmedeus (CA-089 to CA-106), Netflix Conductor (CA-017 to CA-028), Camunda (CA-053 to CA-064)

## Overview

This document specifies the decision routing system for AGENT-33. Decision routing enables conditional execution paths within workflows, supporting binary branching, multi-way switches, weighted probabilistic routing, and rule-table evaluation. All decisions are logged for auditability and can be cached for performance.

## Decision Schema

```yaml
decision:
  id: string
  name: string
  type: binary | switch | weighted | rule_table
  input: expression (value to evaluate)
  cases:
    - condition: expression
      target: stage_id | workflow_id
      weight: number (for weighted type)
      label: string
  default:
    target: stage_id
  logging:
    log_decision: true
    include_inputs: true
    include_evaluation: true
  cache:
    enabled: boolean
    ttl: duration
```

## Decision Types

### Binary (if/else)

Routes execution to one of two branches based on a boolean condition.

```yaml
decision:
  id: decision-quality-gate
  name: "Quality Gate"
  type: binary
  input: "{{ artifact.quality_score }}"
  cases:
    - condition: "input >= 0.8"
      target: stage-deploy
      label: "Pass"
    - condition: "input < 0.8"
      target: stage-rework
      label: "Fail"
  default:
    target: stage-rework
  logging:
    log_decision: true
    include_inputs: true
    include_evaluation: true
```

### Switch (multi-way)

Routes to one of several branches based on a value match, analogous to a switch/case statement.

```yaml
decision:
  id: decision-artifact-type-router
  name: "Artifact Type Router"
  type: switch
  input: "{{ artifact.type }}"
  cases:
    - condition: "input == 'prompt'"
      target: stage-prompt-validation
      label: "Prompt"
    - condition: "input == 'workflow'"
      target: stage-workflow-validation
      label: "Workflow"
    - condition: "input == 'schema'"
      target: stage-schema-validation
      label: "Schema"
    - condition: "input == 'agent'"
      target: stage-agent-validation
      label: "Agent Config"
  default:
    target: stage-generic-validation
  logging:
    log_decision: true
    include_inputs: true
    include_evaluation: true
```

### Weighted (probabilistic)

Routes execution probabilistically across branches. Used for A/B testing, canary deployments, and gradual rollouts.

```yaml
decision:
  id: decision-ab-prompt-variant
  name: "A/B Prompt Variant Test"
  type: weighted
  input: "{{ request.id }}"
  cases:
    - condition: ""
      target: stage-prompt-v1
      weight: 70
      label: "Control (v1)"
    - condition: ""
      target: stage-prompt-v2
      weight: 20
      label: "Variant A (v2)"
    - condition: ""
      target: stage-prompt-v3
      weight: 10
      label: "Variant B (v3)"
  default:
    target: stage-prompt-v1
  logging:
    log_decision: true
    include_inputs: true
    include_evaluation: true
  cache:
    enabled: true
    ttl: "24h"
```

### Rule Table (DMN-style)

Evaluates a table of rules in order, firing the first match or collecting all matches. Inspired by DMN (Decision Model and Notation) from Camunda.

```yaml
decision:
  id: decision-escalation-rules
  name: "Escalation Rules"
  type: rule_table
  input: "{{ context }}"
  hit_policy: first  # first | collect | priority
  rules:
    - condition: "input.severity == 'critical' and input.attempts > 2"
      target: stage-human-escalation
      label: "Critical + Retried"
      priority: 1
    - condition: "input.severity == 'critical'"
      target: stage-senior-agent
      label: "Critical"
      priority: 2
    - condition: "input.quality_score < 0.5"
      target: stage-full-rework
      label: "Low Quality"
      priority: 3
    - condition: "input.quality_score < 0.8"
      target: stage-minor-rework
      label: "Needs Polish"
      priority: 4
  default:
    target: stage-continue
  logging:
    log_decision: true
    include_inputs: true
    include_evaluation: true
```

## Data Model

```python
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
from datetime import datetime, timedelta
import hashlib
import json
import random


class DecisionType(Enum):
    BINARY = "binary"
    SWITCH = "switch"
    WEIGHTED = "weighted"
    RULE_TABLE = "rule_table"


class HitPolicy(Enum):
    FIRST = "first"       # First matching rule wins
    COLLECT = "collect"   # All matching rules fire
    PRIORITY = "priority" # Highest priority match wins


@dataclass
class DecisionCase:
    """A single case/branch in a decision."""
    condition: str             # Expression to evaluate
    target: str                # Stage or workflow to route to
    weight: float = 0.0        # For weighted routing
    label: str = ""            # Human-readable label
    priority: int = 0          # For rule_table with priority hit policy


@dataclass
class DecisionDefault:
    """Fallback route when no case matches."""
    target: str


@dataclass
class LoggingConfig:
    """Controls what gets logged for each decision."""
    log_decision: bool = True
    include_inputs: bool = True
    include_evaluation: bool = True


@dataclass
class CacheConfig:
    """Controls decision result caching."""
    enabled: bool = False
    ttl: timedelta = field(default_factory=lambda: timedelta(hours=1))


@dataclass
class Decision:
    """A fully defined decision node."""
    id: str
    name: str
    type: DecisionType
    input_expression: str
    cases: List[DecisionCase]
    default: DecisionDefault
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    hit_policy: HitPolicy = HitPolicy.FIRST  # For rule_table type
```

## Decision Evaluation

```python
@dataclass
class DecisionResult:
    """The outcome of evaluating a decision."""
    decision_id: str
    selected_targets: List[str]       # One or more targets
    selected_labels: List[str]        # Labels of selected branches
    input_value: Any                  # Resolved input
    evaluation_details: Dict[str, Any]  # Per-case evaluation results
    timestamp: str                    # ISO-8601
    cached: bool = False              # Whether result came from cache


class DecisionEvaluator:
    """Evaluates decision nodes and returns routing results."""

    def __init__(self, expression_engine: Any):
        """
        Args:
            expression_engine: Engine for evaluating condition expressions.
                Must support evaluate(expression, context) -> Any.
        """
        self.expression_engine = expression_engine

    def evaluate(
        self,
        decision: Decision,
        context: Dict[str, Any]
    ) -> DecisionResult:
        """
        Evaluate a decision and return the selected route(s).

        Args:
            decision: The decision definition.
            context: Variables available to expressions.

        Returns:
            DecisionResult with selected targets and metadata.
        """
        input_value = self.expression_engine.evaluate(
            decision.input_expression, context
        )

        eval_context = {**context, "input": input_value}

        if decision.type == DecisionType.BINARY:
            return self._evaluate_binary(decision, eval_context, input_value)
        elif decision.type == DecisionType.SWITCH:
            return self._evaluate_switch(decision, eval_context, input_value)
        elif decision.type == DecisionType.WEIGHTED:
            return self._evaluate_weighted(decision, eval_context, input_value)
        elif decision.type == DecisionType.RULE_TABLE:
            return self._evaluate_rule_table(decision, eval_context, input_value)
        else:
            raise ValueError(f"Unknown decision type: {decision.type}")

    def _evaluate_binary(
        self, decision: Decision, context: Dict, input_value: Any
    ) -> DecisionResult:
        """Evaluate binary if/else decision."""
        details = {}
        for case in decision.cases:
            result = self.expression_engine.evaluate(case.condition, context)
            details[case.label] = {"condition": case.condition, "result": result}
            if result:
                return DecisionResult(
                    decision_id=decision.id,
                    selected_targets=[case.target],
                    selected_labels=[case.label],
                    input_value=input_value,
                    evaluation_details=details,
                    timestamp=datetime.utcnow().isoformat() + "Z",
                )

        return self._default_result(decision, input_value, details)

    def _evaluate_switch(
        self, decision: Decision, context: Dict, input_value: Any
    ) -> DecisionResult:
        """Evaluate switch/case decision."""
        details = {}
        for case in decision.cases:
            result = self.expression_engine.evaluate(case.condition, context)
            details[case.label] = {"condition": case.condition, "result": result}
            if result:
                return DecisionResult(
                    decision_id=decision.id,
                    selected_targets=[case.target],
                    selected_labels=[case.label],
                    input_value=input_value,
                    evaluation_details=details,
                    timestamp=datetime.utcnow().isoformat() + "Z",
                )

        return self._default_result(decision, input_value, details)

    def _evaluate_weighted(
        self, decision: Decision, context: Dict, input_value: Any
    ) -> DecisionResult:
        """
        Evaluate weighted probabilistic decision.

        Uses the input value as a seed for deterministic routing when
        caching is enabled (same input always routes to same target).
        """
        total_weight = sum(c.weight for c in decision.cases)
        if total_weight == 0:
            return self._default_result(decision, input_value, {})

        # Deterministic selection based on input hash
        seed = int(hashlib.sha256(str(input_value).encode()).hexdigest(), 16)
        rng = random.Random(seed)
        roll = rng.uniform(0, total_weight)

        cumulative = 0.0
        for case in decision.cases:
            cumulative += case.weight
            if roll <= cumulative:
                return DecisionResult(
                    decision_id=decision.id,
                    selected_targets=[case.target],
                    selected_labels=[case.label],
                    input_value=input_value,
                    evaluation_details={
                        "roll": roll,
                        "total_weight": total_weight,
                        "weights": {c.label: c.weight for c in decision.cases},
                    },
                    timestamp=datetime.utcnow().isoformat() + "Z",
                )

        return self._default_result(decision, input_value, {})

    def _evaluate_rule_table(
        self, decision: Decision, context: Dict, input_value: Any
    ) -> DecisionResult:
        """
        Evaluate rule table decision according to hit policy.

        - first: Return the first matching rule.
        - collect: Return all matching rules.
        - priority: Return the highest-priority matching rule.
        """
        matches = []
        details = {}

        for case in decision.cases:
            result = self.expression_engine.evaluate(case.condition, context)
            details[case.label] = {
                "condition": case.condition,
                "result": result,
                "priority": case.priority,
            }
            if result:
                matches.append(case)

        if not matches:
            return self._default_result(decision, input_value, details)

        if decision.hit_policy == HitPolicy.FIRST:
            selected = [matches[0]]
        elif decision.hit_policy == HitPolicy.PRIORITY:
            selected = [min(matches, key=lambda c: c.priority)]
        elif decision.hit_policy == HitPolicy.COLLECT:
            selected = matches
        else:
            selected = [matches[0]]

        return DecisionResult(
            decision_id=decision.id,
            selected_targets=[c.target for c in selected],
            selected_labels=[c.label for c in selected],
            input_value=input_value,
            evaluation_details=details,
            timestamp=datetime.utcnow().isoformat() + "Z",
        )

    def _default_result(
        self, decision: Decision, input_value: Any, details: Dict
    ) -> DecisionResult:
        """Return the default/fallback route."""
        return DecisionResult(
            decision_id=decision.id,
            selected_targets=[decision.default.target],
            selected_labels=["default"],
            input_value=input_value,
            evaluation_details=details,
            timestamp=datetime.utcnow().isoformat() + "Z",
        )
```

## Decision Caching

```python
@dataclass
class CacheEntry:
    """A cached decision result."""
    result: DecisionResult
    expires_at: datetime


class DecisionCache:
    """Cache for decision results to avoid redundant evaluation."""

    def __init__(self):
        self.entries: Dict[str, CacheEntry] = {}

    def _cache_key(self, decision_id: str, input_value: Any) -> str:
        """Generate a deterministic cache key."""
        raw = f"{decision_id}:{json.dumps(input_value, sort_keys=True, default=str)}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(
        self, decision_id: str, input_value: Any
    ) -> Optional[DecisionResult]:
        """
        Retrieve a cached result if it exists and has not expired.

        Returns:
            DecisionResult if cache hit, None if miss or expired.
        """
        key = self._cache_key(decision_id, input_value)
        entry = self.entries.get(key)
        if entry and datetime.utcnow() < entry.expires_at:
            result = entry.result
            result.cached = True
            return result
        if entry:
            del self.entries[key]
        return None

    def put(
        self,
        decision_id: str,
        input_value: Any,
        result: DecisionResult,
        ttl: timedelta
    ) -> None:
        """Store a decision result in the cache."""
        key = self._cache_key(decision_id, input_value)
        self.entries[key] = CacheEntry(
            result=result,
            expires_at=datetime.utcnow() + ttl,
        )

    def invalidate(self, decision_id: str) -> int:
        """
        Remove all cached results for a decision.

        Returns:
            Number of entries removed.
        """
        to_remove = [
            k for k in self.entries
            if k.startswith(hashlib.sha256(
                f"{decision_id}:".encode()
            ).hexdigest()[:16])
        ]
        # Full scan fallback since keys are hashed
        to_remove = []
        for key, entry in list(self.entries.items()):
            if entry.result.decision_id == decision_id:
                to_remove.append(key)
        for key in to_remove:
            del self.entries[key]
        return len(to_remove)
```

## Decision Logging

```python
@dataclass
class DecisionLogEntry:
    """A logged decision for audit trail."""
    decision_id: str
    decision_name: str
    timestamp: str                    # ISO-8601
    input_value: Any
    selected_targets: List[str]
    selected_labels: List[str]
    evaluation_details: Dict[str, Any]
    cached: bool
    workflow_id: str
    stage_id: str


class DecisionLogger:
    """Records all decision outcomes for auditability."""

    def __init__(self):
        self.log: List[DecisionLogEntry] = []

    def record(
        self,
        decision: Decision,
        result: DecisionResult,
        workflow_id: str,
        stage_id: str
    ) -> None:
        """Log a decision result."""
        if not decision.logging.log_decision:
            return

        entry = DecisionLogEntry(
            decision_id=decision.id,
            decision_name=decision.name,
            timestamp=result.timestamp,
            input_value=result.input_value if decision.logging.include_inputs else None,
            selected_targets=result.selected_targets,
            selected_labels=result.selected_labels,
            evaluation_details=(
                result.evaluation_details
                if decision.logging.include_evaluation
                else {}
            ),
            cached=result.cached,
            workflow_id=workflow_id,
            stage_id=stage_id,
        )
        self.log.append(entry)

    def query(
        self,
        decision_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        since: Optional[str] = None
    ) -> List[DecisionLogEntry]:
        """
        Query decision log entries with optional filters.

        Args:
            decision_id: Filter by decision ID.
            workflow_id: Filter by workflow ID.
            since: ISO-8601 timestamp, return only entries after this time.

        Returns:
            Matching log entries in chronological order.
        """
        results = self.log

        if decision_id:
            results = [e for e in results if e.decision_id == decision_id]
        if workflow_id:
            results = [e for e in results if e.workflow_id == workflow_id]
        if since:
            results = [e for e in results if e.timestamp >= since]

        return results

    def get_branch_distribution(
        self, decision_id: str
    ) -> Dict[str, int]:
        """
        Get the distribution of branches taken for a decision.

        Useful for validating A/B test weight distributions.

        Returns:
            Dictionary mapping label to count.
        """
        dist: Dict[str, int] = {}
        for entry in self.log:
            if entry.decision_id == decision_id:
                for label in entry.selected_labels:
                    dist[label] = dist.get(label, 0) + 1
        return dist
```

## Guardrail Integration

Decisions can be validated before execution to ensure they comply with guardrails.

```python
@dataclass
class GuardrailCheck:
    """A guardrail validation for a decision result."""
    decision_id: str
    check_name: str
    passed: bool
    message: str


def validate_decision(
    decision: Decision,
    result: DecisionResult,
    guardrails: List[Dict[str, Any]]
) -> List[GuardrailCheck]:
    """
    Validate a decision result against configured guardrails.

    Example guardrails:
    - No routing to disabled stages.
    - Weighted decisions must have reasonable distributions.
    - Critical workflows require explicit approval routing.

    Args:
        decision: The decision definition.
        result: The evaluation result.
        guardrails: List of guardrail configurations.

    Returns:
        List of guardrail check results.
    """
    checks = []

    for guardrail in guardrails:
        check_type = guardrail.get("type")

        if check_type == "no_disabled_targets":
            disabled = guardrail.get("disabled_stages", [])
            for target in result.selected_targets:
                passed = target not in disabled
                checks.append(GuardrailCheck(
                    decision_id=decision.id,
                    check_name="no_disabled_targets",
                    passed=passed,
                    message=(
                        f"Target '{target}' is allowed"
                        if passed
                        else f"Target '{target}' is disabled"
                    ),
                ))

        elif check_type == "weight_bounds":
            min_weight = guardrail.get("min_weight", 0)
            for case in decision.cases:
                passed = case.weight >= min_weight
                checks.append(GuardrailCheck(
                    decision_id=decision.id,
                    check_name="weight_bounds",
                    passed=passed,
                    message=(
                        f"Weight {case.weight} for '{case.label}' is within bounds"
                        if passed
                        else f"Weight {case.weight} for '{case.label}' below minimum {min_weight}"
                    ),
                ))

    return checks
```

## CLI Commands

```bash
# Decision management
agent-33 decision list
agent-33 decision show <decision-id>

# Evaluation
agent-33 decision evaluate <decision-id> --input '{"key": "value"}'
agent-33 decision dry-run <decision-id> --input '{"key": "value"}'

# Logging and audit
agent-33 decision log [--decision-id <id>] [--workflow-id <id>] [--since <timestamp>]
agent-33 decision distribution <decision-id>

# Cache management
agent-33 decision cache status
agent-33 decision cache invalidate <decision-id>
agent-33 decision cache clear
```

## Integration Points

### Expression Language

Decision conditions use the shared expression language. The expression engine must support comparison operators, boolean logic, string matching, and access to nested context variables.

### Guardrails

Before executing a decision result, the system validates it against active guardrails. A failed guardrail check can block execution and route to an escalation path instead.

### Lineage Tracking

Every decision evaluation is recorded in the lineage graph, linking the decision to its input artifacts and the chosen output branch. This enables full traceability of why a particular execution path was taken.

### Sensors

Sensor output events are commonly routed through decisions. For example, a `file_change` sensor may trigger a decision that routes to different validation workflows based on the file type.

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| uses | `../lineage/LINEAGE_TRACKING_SPEC.md` | Decisions recorded in lineage |
| uses | `../sensors/ARTIFACT_SENSOR_SPEC.md` | Sensor events feed decisions |
| uses | `../dependencies/DEPENDENCY_GRAPH_SPEC.md` | Resolve target stages |
| integrates | `../modes/DRY_RUN_SPEC.md` | Dry-run evaluates without executing |
| sources | Osmedeus CA-089 to CA-106 | Module routing patterns |
| sources | Netflix Conductor CA-017 to CA-028 | Switch/case task patterns |
| sources | Camunda CA-053 to CA-064 | DMN decision table patterns |
