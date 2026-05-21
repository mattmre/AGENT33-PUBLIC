# Expression Language Specification

**Status**: Specification
**Sources**: Netflix Conductor JSONPath (CA-017 to CA-028), Spinnaker SpEL (CA-107 to CA-118), Camunda FEEL (CA-053 to CA-064)

## Related Documents

- [DAG Execution Engine](./DAG_EXECUTION_ENGINE.md) - Uses expressions for stage conditions and inputs
- [Asset-First Workflow Schema](./ASSET_FIRST_WORKFLOW_SCHEMA.md) - Uses expressions in sensors and dynamic partitions
- [Trigger Catalog](../triggers/TRIGGER_CATALOG.md) - Trigger conditions use this expression language
- [Execution Modes](../parallel/EXECUTION_MODES.md) - Runtime configuration via expressions

## Overview

AGENT-33 uses a safe, sandboxed expression language for dynamic workflow behavior. Expressions appear in stage conditions, input/output mappings, asset sensor triggers, and template parameters. The language is intentionally limited: it supports value extraction, transformation, and conditional logic but prohibits arbitrary code execution or side effects.

## Expression Syntax

### Variable References

Expressions are enclosed in `${ }` delimiters. Variables reference values from the pipeline context, stage outputs, and system state.

```
${context.variable_name}           # Pipeline context variable
${stage_id.output.key}             # Stage output value
${stage_id.status}                 # Stage status (SUCCEEDED, FAILED, etc.)
${inputs.parameter_name}           # Pipeline input parameter
${system.timestamp}                # Current UTC timestamp
${system.pipeline_id}              # Running pipeline ID
${partition.key}                   # Current partition key (if partitioned)
```

### Nested Access

Dot notation navigates nested objects. Bracket notation accesses array elements and dynamic keys.

```
${stage.output.result.items[0].name}     # First item's name
${stage.output.data["key-with-dashes"]}  # Bracket key access
${stage.output.matrix[1][2]}             # Nested array access
```

### Literal Values

```
${"hello"}          # String literal
${42}               # Integer literal
${3.14}             # Float literal
${true}             # Boolean literal
${null}             # Null literal
${[1, 2, 3]}        # Array literal
${{"a": 1}}         # Object literal
```

## Configuration Schema

```yaml
expression_language:
  syntax: jsonpath_extended
  variable_prefix: "${"
  variable_suffix: "}"
  allowed_functions:
    string: [concat, substring, replace, trim, upper, lower, split, join]
    math: [add, subtract, multiply, divide, mod, min, max, abs, round]
    date: [now, format, parse, diff, add_days, add_hours]
    collection: [size, first, last, filter, map, reduce, contains, flatten]
    logic: [if, switch, coalesce, default]
  security:
    sandbox: true
    no_side_effects: true
    max_depth: 10
    max_execution_ms: 100
    blocked_patterns: [import, require, eval, exec, process]
```

## Operators

### Arithmetic

| Operator | Symbol | Example | Result |
|----------|--------|---------|--------|
| Add | `+` | `${3 + 2}` | `5` |
| Subtract | `-` | `${10 - 4}` | `6` |
| Multiply | `*` | `${3 * 7}` | `21` |
| Divide | `/` | `${10 / 3}` | `3.333...` |
| Modulo | `%` | `${10 % 3}` | `1` |
| Negate | `-` (unary) | `${-score}` | negated value |

### Comparison

| Operator | Symbol | Example | Result |
|----------|--------|---------|--------|
| Equal | `==` | `${status == "ready"}` | `true`/`false` |
| Not equal | `!=` | `${count != 0}` | `true`/`false` |
| Greater than | `>` | `${score > 90}` | `true`/`false` |
| Greater or equal | `>=` | `${score >= 90}` | `true`/`false` |
| Less than | `<` | `${score < 50}` | `true`/`false` |
| Less or equal | `<=` | `${score <= 50}` | `true`/`false` |

### Logical

| Operator | Symbol | Example |
|----------|--------|---------|
| And | `&&` | `${a > 0 && b > 0}` |
| Or | `\|\|` | `${a > 0 \|\| b > 0}` |
| Not | `!` | `${!is_stale}` |

### String

| Operator | Symbol | Example | Result |
|----------|--------|---------|--------|
| Concatenation | `+` | `${"hello" + " " + "world"}` | `"hello world"` |
| Contains | `contains` | `${name contains "test"}` | `true`/`false` |
| Matches | `matches` | `${name matches "^v[0-9]+"}` | `true`/`false` |

### Collection

| Operator | Symbol | Example | Result |
|----------|--------|---------|--------|
| In | `in` | `${"a" in tags}` | `true`/`false` |
| Not in | `not in` | `${"x" not in tags}` | `true`/`false` |

## Built-in Functions

### String Functions

| Function | Signature | Example | Result |
|----------|-----------|---------|--------|
| `concat` | `concat(s1, s2, ...)` | `${concat("a", "b", "c")}` | `"abc"` |
| `substring` | `substring(s, start, end?)` | `${substring("hello", 0, 3)}` | `"hel"` |
| `replace` | `replace(s, old, new)` | `${replace("foo-bar", "-", "_")}` | `"foo_bar"` |
| `trim` | `trim(s)` | `${trim("  hi  ")}` | `"hi"` |
| `upper` | `upper(s)` | `${upper("hello")}` | `"HELLO"` |
| `lower` | `lower(s)` | `${lower("HELLO")}` | `"hello"` |
| `split` | `split(s, delimiter)` | `${split("a,b,c", ",")}` | `["a","b","c"]` |
| `join` | `join(arr, delimiter)` | `${join(["a","b"], "-")}` | `"a-b"` |
| `length` | `length(s)` | `${length("hello")}` | `5` |
| `starts_with` | `starts_with(s, prefix)` | `${starts_with("hello", "he")}` | `true` |
| `ends_with` | `ends_with(s, suffix)` | `${ends_with("hello", "lo")}` | `true` |

### Math Functions

| Function | Signature | Example | Result |
|----------|-----------|---------|--------|
| `add` | `add(a, b)` | `${add(3, 4)}` | `7` |
| `subtract` | `subtract(a, b)` | `${subtract(10, 3)}` | `7` |
| `multiply` | `multiply(a, b)` | `${multiply(3, 4)}` | `12` |
| `divide` | `divide(a, b)` | `${divide(10, 3)}` | `3.333` |
| `mod` | `mod(a, b)` | `${mod(10, 3)}` | `1` |
| `min` | `min(a, b, ...)` | `${min(3, 1, 4)}` | `1` |
| `max` | `max(a, b, ...)` | `${max(3, 1, 4)}` | `4` |
| `abs` | `abs(n)` | `${abs(-5)}` | `5` |
| `round` | `round(n, decimals?)` | `${round(3.456, 2)}` | `3.46` |
| `ceil` | `ceil(n)` | `${ceil(3.2)}` | `4` |
| `floor` | `floor(n)` | `${floor(3.8)}` | `3` |

### Date/Time Functions

| Function | Signature | Example |
|----------|-----------|---------|
| `now` | `now()` | `${now()}` returns current UTC datetime |
| `format` | `format(dt, pattern)` | `${format(now(), "YYYY-MM-DD")}` |
| `parse` | `parse(s, pattern)` | `${parse("2025-06-15", "YYYY-MM-DD")}` |
| `diff` | `diff(dt1, dt2, unit)` | `${diff(now(), created_at, "hours")}` |
| `add_days` | `add_days(dt, n)` | `${add_days(now(), 7)}` |
| `add_hours` | `add_hours(dt, n)` | `${add_hours(now(), -2)}` |

### Collection Functions

| Function | Signature | Example | Result |
|----------|-----------|---------|--------|
| `size` | `size(collection)` | `${size([1,2,3])}` | `3` |
| `first` | `first(collection)` | `${first([10,20])}` | `10` |
| `last` | `last(collection)` | `${last([10,20])}` | `20` |
| `filter` | `filter(arr, predicate)` | `${filter(items, x -> x.score > 80)}` | filtered array |
| `map` | `map(arr, transform)` | `${map(items, x -> x.name)}` | mapped array |
| `reduce` | `reduce(arr, fn, init)` | `${reduce([1,2,3], (a,b) -> a+b, 0)}` | `6` |
| `contains` | `contains(arr, value)` | `${contains(tags, "urgent")}` | `true`/`false` |
| `flatten` | `flatten(arr)` | `${flatten([[1,2],[3]])}` | `[1,2,3]` |
| `sort` | `sort(arr, key?)` | `${sort(items, x -> x.priority)}` | sorted array |
| `distinct` | `distinct(arr)` | `${distinct([1,1,2,3])}` | `[1,2,3]` |

### Logic Functions

| Function | Signature | Example | Result |
|----------|-----------|---------|--------|
| `if` | `if(cond, then, else)` | `${if(score > 90, "pass", "fail")}` | `"pass"` or `"fail"` |
| `switch` | `switch(val, cases)` | `${switch(type, {"bug":"fix", "feat":"build"})}` | matched value |
| `coalesce` | `coalesce(v1, v2, ...)` | `${coalesce(name, alias, "unknown")}` | first non-null |
| `default` | `default(value, fallback)` | `${default(config.timeout, "30m")}` | value or fallback |

## Conditional Expressions

Ternary syntax for inline conditionals:

```
${condition ? value_if_true : value_if_false}
```

Examples:

```
${score >= 90 ? "excellent" : "needs_work"}
${items.length > 0 ? first(items) : null}
${is_production ? "strict" : "permissive"}
```

Nested conditionals:

```
${score >= 90 ? "A" : score >= 80 ? "B" : score >= 70 ? "C" : "F"}
```

## Pipeline Expressions

Transform values through a chain of functions using the pipe operator `|`:

```
${input | transform1 | transform2 | transform3}
```

The output of each step becomes the input of the next. The implicit variable `_` refers to the piped value.

Examples:

```
${stage.output.name | trim | upper}
# Equivalent to: upper(trim(stage.output.name))

${stage.output.items | filter(x -> x.active) | map(x -> x.name) | sort | join(", ")}
# Filter, extract names, sort, join into comma-separated string

${stage.output.raw_text | split("\n") | filter(x -> length(x) > 0) | size}
# Count non-empty lines
```

## Type System

The expression language uses a simple type system with implicit coercion.

### Types

| Type | Description | Literals |
|------|-------------|----------|
| `string` | Unicode text | `"hello"`, `'hello'` |
| `number` | 64-bit float | `42`, `3.14`, `-7` |
| `boolean` | True or false | `true`, `false` |
| `array` | Ordered collection | `[1, 2, 3]` |
| `object` | Key-value map | `{"key": "value"}` |
| `null` | Absence of value | `null` |

### Type Coercion Rules

| From | To | Rule |
|------|----|------|
| `number` | `string` | Automatic (e.g., `42` becomes `"42"` in concatenation) |
| `string` | `number` | Automatic in arithmetic if parseable; error otherwise |
| `boolean` | `string` | `"true"` / `"false"` |
| `null` | `string` | `"null"` |
| `null` | `number` | Error |
| `null` | `boolean` | `false` |
| Any | `boolean` | Truthy: non-null, non-zero, non-empty; Falsy: null, 0, "", [] |

## Security Model

The expression language is sandboxed to prevent misuse.

### Constraints

| Constraint | Value | Purpose |
|------------|-------|---------|
| Sandbox | Enabled | Expressions run in isolated evaluation context |
| Side effects | Prohibited | No file I/O, network calls, or state mutation |
| Max depth | 10 | Nested expression / recursion limit |
| Max execution | 100ms | Hard timeout per expression evaluation |
| Blocked patterns | `import`, `require`, `eval`, `exec`, `process` | Prevent code injection |

### Evaluation Context

```python
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable, List
import time


class ExpressionSecurityError(Exception):
    """Raised when an expression violates security constraints."""
    pass


class ExpressionTimeoutError(Exception):
    """Raised when expression evaluation exceeds the time limit."""
    pass


BLOCKED_PATTERNS = ["import", "require", "eval", "exec", "process", "__"]


@dataclass
class ExpressionContext:
    """Sandboxed evaluation context for expressions."""
    variables: Dict[str, Any] = field(default_factory=dict)
    functions: Dict[str, Callable] = field(default_factory=dict)
    max_depth: int = 10
    max_execution_ms: int = 100

    def evaluate(self, expression: str) -> Any:
        """Evaluate an expression string in this context."""
        self._security_check(expression)
        start = time.monotonic()
        try:
            result = self._eval_recursive(expression, depth=0, start_time=start)
            return result
        except ExpressionSecurityError:
            raise
        except ExpressionTimeoutError:
            raise
        except Exception as e:
            raise ExpressionEvaluationError(
                f"Failed to evaluate '{expression}': {e}"
            ) from e

    def _security_check(self, expression: str) -> None:
        lowered = expression.lower()
        for pattern in BLOCKED_PATTERNS:
            if pattern in lowered:
                raise ExpressionSecurityError(
                    f"Blocked pattern '{pattern}' found in expression"
                )

    def _eval_recursive(self, expr: str, depth: int, start_time: float) -> Any:
        if depth > self.max_depth:
            raise ExpressionSecurityError(
                f"Expression depth {depth} exceeds maximum {self.max_depth}"
            )
        elapsed_ms = (time.monotonic() - start_time) * 1000
        if elapsed_ms > self.max_execution_ms:
            raise ExpressionTimeoutError(
                f"Expression exceeded {self.max_execution_ms}ms limit"
            )
        # Parser and evaluator implementation
        return self._parse_and_evaluate(expr, depth, start_time)

    def _parse_and_evaluate(self, expr: str, depth: int, start_time: float) -> Any:
        """Parse expression into AST and evaluate. Implementation detail."""
        ...


class ExpressionEvaluationError(Exception):
    """Raised when expression evaluation fails for non-security reasons."""
    pass
```

### Function Allowlist

Only explicitly registered functions are callable. The evaluator rejects any function call not in the allowlist.

```python
def build_default_functions() -> Dict[str, Callable]:
    """Build the standard function library."""
    return {
        # String
        "concat": lambda *args: "".join(str(a) for a in args),
        "substring": lambda s, start, end=None: s[start:end],
        "replace": lambda s, old, new: s.replace(old, new),
        "trim": lambda s: s.strip(),
        "upper": lambda s: s.upper(),
        "lower": lambda s: s.lower(),
        "split": lambda s, d: s.split(d),
        "join": lambda arr, d: d.join(str(x) for x in arr),
        "length": lambda s: len(s),
        "starts_with": lambda s, p: s.startswith(p),
        "ends_with": lambda s, p: s.endswith(p),
        # Math
        "add": lambda a, b: a + b,
        "subtract": lambda a, b: a - b,
        "multiply": lambda a, b: a * b,
        "divide": lambda a, b: a / b if b != 0 else None,
        "mod": lambda a, b: a % b,
        "min": lambda *args: min(args),
        "max": lambda *args: max(args),
        "abs": lambda n: abs(n),
        "round": lambda n, d=0: round(n, d),
        # Collection
        "size": lambda c: len(c),
        "first": lambda c: c[0] if c else None,
        "last": lambda c: c[-1] if c else None,
        "contains": lambda c, v: v in c,
        "flatten": lambda arr: [x for sub in arr for x in sub],
        "distinct": lambda arr: list(dict.fromkeys(arr)),
        "sort": lambda arr, key=None: sorted(arr, key=key),
        # Logic
        "coalesce": lambda *args: next((a for a in args if a is not None), None),
        "default": lambda v, d: v if v is not None else d,
    }
```

## Error Handling

### Evaluation Failures

When an expression fails to evaluate, the system applies a configurable error strategy:

```yaml
expression_error_handling:
  strategy: default_value | propagate_error | skip_stage
  default_value: null           # Used when strategy is default_value
  log_level: warn               # Log level for expression failures
```

### Common Error Cases

| Error | Cause | Default Behavior |
|-------|-------|-----------------|
| `VariableNotFound` | Referenced variable does not exist | Return `null` |
| `TypeMismatch` | Incompatible types in operation | Propagate error |
| `DivisionByZero` | Division or modulo by zero | Return `null` |
| `IndexOutOfBounds` | Array index exceeds length | Return `null` |
| `SecurityViolation` | Blocked pattern detected | Propagate error (always) |
| `Timeout` | Exceeded `max_execution_ms` | Propagate error (always) |
| `DepthExceeded` | Nested beyond `max_depth` | Propagate error (always) |

### Error Handling in Context

```python
@dataclass
class ExpressionErrorPolicy:
    strategy: str = "default_value"  # default_value | propagate_error | skip_stage
    default_value: Any = None
    log_level: str = "warn"

    def handle(self, error: Exception, expression: str) -> Any:
        if isinstance(error, (ExpressionSecurityError, ExpressionTimeoutError)):
            raise error  # Always propagate security/timeout errors
        if self.strategy == "default_value":
            return self.default_value
        elif self.strategy == "propagate_error":
            raise error
        elif self.strategy == "skip_stage":
            raise StageSkipSignal(f"Expression failed: {expression}")
```

## Common Pattern Examples

### Routing by Agent Output

```yaml
# Route to different handlers based on classification
condition:
  expression: "${classify.output.category == 'security'}"
```

### Value Extraction from Nested Output

```yaml
# Extract specific field from JSON output
inputs:
  framework_name: "${gather.output.results[0].metadata.name}"
  total_count: "${size(gather.output.results)}"
```

### Conditional Input Formatting

```yaml
# Format output differently based on context
inputs:
  summary: "${if(context.verbose, stage.output.full_report, stage.output.summary)}"
  label: "${upper(replace(context.project_name, '-', '_'))}"
```

### Aggregation Across Branches

```yaml
# After a fan-in, aggregate results from parallel branches
inputs:
  all_scores: "${map(fan_in.output.branch_results, r -> r.score)}"
  average: "${reduce(map(fan_in.output.branch_results, r -> r.score), (a,b) -> a+b, 0) / size(fan_in.output.branch_results)}"
  passed: "${filter(fan_in.output.branch_results, r -> r.score >= 80)}"
```

### Pipeline Transform Chain

```yaml
# Clean and normalize text through a pipeline
inputs:
  normalized: "${stage.output.raw_text | trim | lower | replace(' ', '_')}"
  tags: "${stage.output.tag_string | split(',') | map(t -> trim(t)) | filter(t -> length(t) > 0) | distinct}"
```

### Default Values and Null Safety

```yaml
# Provide defaults for optional values
inputs:
  timeout: "${default(config.timeout, '30m')}"
  owner: "${coalesce(stage.output.owner, context.default_owner, 'unassigned')}"
  items: "${default(stage.output.items, [])}"
```

### Date-Based Conditions

```yaml
# Check if asset is recent enough
condition:
  expression: "${diff(now(), asset.last_materialized, 'hours') < 24}"
```

### Switch-Based Routing

```yaml
inputs:
  handler: "${switch(task.type, {'bug': 'fix-agent', 'feature': 'build-agent', 'docs': 'writer-agent'})}"
  priority: "${switch(severity, {'critical': 0, 'high': 1, 'medium': 2, 'low': 3})}"
```
