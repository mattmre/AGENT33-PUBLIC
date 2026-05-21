# Qwen Code Tool Protocol

Purpose: Integration protocol for Qwen Code tool usage within the orchestration framework.

Related docs:
- `core/orchestrator/CODE_EXECUTION_CONTRACT.md` (execution contract)
- `core/orchestrator/agents/QWEN_WORKER_RULES.md` (worker rules)
- `core/orchestrator/TOOL_GOVERNANCE.md` (tool governance)

---

## Overview

This protocol defines how to invoke, validate, and integrate Qwen Code tool outputs within the agent orchestration system.

---

## Invocation Schema

### Request Format

```yaml
invocation_id: <unique-request-identifier>
tool: qwen-code
model: <model-version>
mode: <code-generation|code-review|code-completion|refactor>

# Input Specification
input:
  prompt: <task-description>
  context:
    files: [<file-path>, ...]
    language: <programming-language>
    framework: <optional-framework>
  constraints:
    max_tokens: <token-limit>
    temperature: <0.0-1.0>
    style_guide: <reference>
  
# Execution Context
execution:
  timeout_ms: 60000
  retry_attempts: 2
  warmup_required: <true|false>

# Metadata
metadata:
  requested_by: <agent-id>
  task_ref: <task-id>
  evidence_ref: <evidence-capture-link>
```

### Response Format

```yaml
invocation_id: <matching-request-id>
status: <success|error|timeout|partial>

# Output
output:
  code: <generated-code>
  language: <detected-language>
  tokens_used: <count>
  completion_time_ms: <duration>

# Validation Results
validation:
  syntax_valid: <true|false>
  lint_passed: <true|false|skipped>
  tests_passed: <true|false|skipped>
  security_scan: <pass|warn|fail|skipped>

# Error Information (if applicable)
error:
  code: <error-code>
  message: <error-description>
  recoverable: <true|false>
```

---

## Error Handling

### Error Codes

| Code | Description | Recovery Action |
|------|-------------|-----------------|
| **QC-001** | Model unavailable | Retry with warmup or escalate |
| **QC-002** | Context too large | Reduce context scope |
| **QC-003** | Generation timeout | Increase timeout or simplify prompt |
| **QC-004** | Invalid prompt | Validate and reformat prompt |
| **QC-005** | Rate limited | Backoff and retry |
| **QC-006** | Output validation failed | Review and regenerate |
| **QC-007** | Security violation | Block and escalate |

### Retry Strategy

```yaml
retry:
  max_attempts: 3
  backoff_strategy: exponential
  initial_delay_ms: 1000
  max_delay_ms: 30000
  retryable_codes: [QC-001, QC-003, QC-005]
```

### Escalation Triggers

- 3 consecutive failures on same task
- Security violation detected (QC-007)
- Output fails validation after retry
- Model consistently unavailable

---

## Validation Checklist

### Pre-Invocation Checks

- [ ] **VC-01**: Prompt is clear and task-scoped
- [ ] **VC-02**: Context files exist and are accessible
- [ ] **VC-03**: Language/framework is supported
- [ ] **VC-04**: Constraints are within allowed limits
- [ ] **VC-05**: Model is warmed up (if warmup_required)

### Output Validation Checks

- [ ] **VC-06**: Code is syntactically valid
- [ ] **VC-07**: Code follows style guide
- [ ] **VC-08**: No security vulnerabilities introduced
- [ ] **VC-09**: Code is scoped to task (no unrelated changes)
- [ ] **VC-10**: Dependencies are approved
- [ ] **VC-11**: Tests pass (if applicable)
- [ ] **VC-12**: Documentation updated (if applicable)

### Post-Integration Checks

- [ ] **VC-13**: Build succeeds with new code
- [ ] **VC-14**: Existing tests still pass
- [ ] **VC-15**: No regressions in functionality
- [ ] **VC-16**: Evidence captured

---

## Integration with Code Execution Contract

This protocol extends `CODE_EXECUTION_CONTRACT.md` for Qwen Code:

### Adapter Definition

```yaml
adapter_id: ADP-QWEN-001
name: qwen-code-adapter
version: "1.0.0"
tool_id: TL-QWEN

type: sdk

interface:
  sdk:
    language: python
    package: qwen-agent
    import_path: qwen_agent.code
    function_mapping:
      generate: generate_code
      review: review_code
      complete: complete_code
      refactor: refactor_code

sandbox_override:
  timeout_ms: 120000
  memory_mb: 2048
  network:
    enabled: true
    allow: ["api.qwen.ai", "models.qwen.ai"]

metadata:
  author: Orchestration Team
  created: "2026-01-16"
  status: active
```

### Execution Contract Extension

| Field | Qwen-Specific Value |
|-------|---------------------|
| `tool_id` | TL-QWEN |
| `adapter_id` | ADP-QWEN-001 |
| `sandbox.timeout_ms` | 120000 (extended for generation) |
| `sandbox.network.allow` | Qwen API endpoints |

---

## Model Pinning and Warmup

### Pinning Requirements

```yaml
model_config:
  id: qwen-coder-<version>
  pin_version: true
  version_lock_file: .qwen-version
  
  # Pinning ensures deterministic outputs
  deterministic: true
  seed: <optional-fixed-seed>
```

### Warmup Protocol

```yaml
warmup:
  enabled: true
  trigger: session_start
  timeout_ms: 30000
  health_check:
    endpoint: /health
    expected_status: 200
  
  # Keep model hot
  keepalive:
    interval_ms: 300000  # 5 minutes
    max_duration_ms: 1800000  # 30 minutes
```

### Warmup Verification

1. Send lightweight health check request
2. Verify response within timeout
3. Log warmup status to evidence
4. If warmup fails, retry up to 3 times with exponential backoff
5. Escalate if warmup consistently fails

---

## Usage Guidelines

### Best Practices

1. **Scope prompts tightly** - One task per invocation
2. **Provide sufficient context** - Include relevant files and constraints
3. **Validate early** - Run syntax checks before integration
4. **Capture evidence** - Log all invocations and outputs
5. **Review security** - Scan generated code before execution

### Anti-Patterns

- ❌ Generating entire files without review
- ❌ Skipping validation steps
- ❌ Ignoring security scan results
- ❌ Bypassing warmup for cold models
- ❌ Over-relying on generated code without human review

---

## Evidence Capture

All Qwen Code invocations must capture:

```yaml
evidence:
  invocation_log:
    path: core/logs/qwen-invocations/<date>/<invocation_id>.yaml
    retention: 30d
  
  generated_code:
    path: core/logs/qwen-outputs/<date>/<invocation_id>/
    retention: 7d
  
  validation_results:
    path: core/logs/qwen-validation/<date>/<invocation_id>.yaml
    retention: 30d
```

---

## References

- Code Execution Contract: `core/orchestrator/CODE_EXECUTION_CONTRACT.md`
- Worker Rules: `core/orchestrator/agents/QWEN_WORKER_RULES.md`
- Tool Governance: `core/orchestrator/TOOL_GOVERNANCE.md`
- Evidence Capture: `core/orchestrator/handoff/EVIDENCE_CAPTURE.md`
