# Code Execution Contract

Purpose: Define the runtime contract for code execution, including inputs, outputs, sandbox limits, and adapter patterns.

Related docs:
- `core/orchestrator/TOOLS_AS_CODE.md` (progressive disclosure and folder structure)
- `core/orchestrator/TOOL_GOVERNANCE.md` (allowlist policy)
- `core/orchestrator/TOOL_REGISTRY_CHANGE_CONTROL.md` (change control)
- `core/packs/policy-pack-v1/RISK_TRIGGERS.md` (security risk triggers)

---

## Execution Contract Schema

Every code execution must conform to this contract:

```yaml
execution_id: <unique-run-identifier>
tool_id: <registered-tool-id>
adapter_id: <adapter-identifier>

# Inputs
inputs:
  command: <command-or-function>
  arguments: [<arg1>, <arg2>, ...]
  environment:
    <ENV_VAR>: <value>
  working_directory: <path>
  input_files: [<path1>, <path2>, ...]
  stdin: <optional-stdin-content>

# Sandbox Limits
sandbox:
  timeout_ms: <max-execution-time>
  memory_mb: <max-memory>
  cpu_cores: <max-cores>
  filesystem:
    read: [<allowed-read-paths>]
    write: [<allowed-write-paths>]
    deny: [<blocked-paths>]
  network:
    enabled: <true|false>
    allow: [<allowed-hosts>]
    deny: [<blocked-hosts>]
  processes:
    max_children: <count>
    allow_fork: <true|false>

# Expected Outputs
outputs:
  stdout: <expected|captured>
  stderr: <expected|captured>
  exit_code: <expected-code>
  output_files: [<path1>, <path2>, ...]
  artifacts: [<artifact-spec>]

# Metadata
metadata:
  requested_by: <agent-or-user>
  requested_at: <ISO8601-timestamp>
  purpose: <brief-description>
  evidence_ref: <link-to-evidence-capture>
```

---

## Sandbox Limits

### Default Limits

| Limit | Default | Min | Max | Notes |
|-------|---------|-----|-----|-------|
| `timeout_ms` | 30000 | 1000 | 600000 | 30s default, 10min max |
| `memory_mb` | 512 | 64 | 4096 | Per execution |
| `cpu_cores` | 1 | 1 | 4 | Logical cores |
| `max_children` | 10 | 0 | 100 | Child processes |

### Filesystem Access Levels

| Level | Read | Write | Use Case |
|-------|------|-------|----------|
| **Minimal** | Working dir only | None | Read-only analysis |
| **Standard** | Repo root | Working dir | Typical development |
| **Extended** | Repo + deps | Working dir + output | Build tasks |
| **Elevated** | System paths | Specific paths | System tools (requires approval) |

### Network Access Levels

| Level | Allowed | Use Case |
|-------|---------|----------|
| **Offline** | None | Most tasks (default) |
| **Registry** | Package registries only | Dependency install |
| **API** | Allowlisted APIs | External integrations |
| **Open** | Any (logged) | Research (requires approval) |

---

## Input Validation

### Required Checks

| Check | Description | Enforcement |
|-------|-------------|-------------|
| **IV-01: Command allowlist** | Command must be in tool allowlist | Block if not listed |
| **IV-02: Argument sanitization** | No shell injection patterns | Escape or block |
| **IV-03: Path traversal** | No `../` in file paths | Normalize and validate |
| **IV-04: Environment filtering** | Only approved env vars | Strip unapproved |
| **IV-05: Input size** | Stdin and files within limits | Truncate or reject |

### Sanitization Rules

```
# Shell injection patterns to block or escape
; | & $ ` ( ) { } [ ] < > \ " ' ! # * ?

# Path traversal patterns to normalize
../ ..\\ /etc/ /var/ C:\Windows\

# Dangerous environment variables to strip
LD_PRELOAD LD_LIBRARY_PATH PATH (unless scoped)
```

---

## Output Handling

### Output Capture

| Output Type | Capture Method | Size Limit | Retention |
|-------------|---------------|------------|-----------|
| `stdout` | Stream capture | 1MB | Session |
| `stderr` | Stream capture | 256KB | Session |
| `exit_code` | Process return | N/A | Session |
| `output_files` | File collection | 10MB total | Evidence |
| `artifacts` | Structured capture | 10MB total | Evidence |

### Exit Code Interpretation

| Code | Meaning | Action |
|------|---------|--------|
| 0 | Success | Continue workflow |
| 1-125 | Tool-specific error | Log and handle |
| 126 | Permission denied | Escalate |
| 127 | Command not found | Check allowlist |
| 128+ | Signal termination | Log signal number |
| 137 | OOM killed | Increase memory or fail |
| 143 | SIGTERM (timeout) | Extend timeout or fail |

---

## Adapter Template

### Adapter Schema

```yaml
adapter_id: <unique-identifier>
name: <adapter-name>
version: <semver>
tool_id: <target-tool-id>

# Adapter Type
type: cli | api | sdk | mcp

# Interface Definition
interface:
  # For CLI adapters
  cli:
    executable: <path-or-command>
    base_args: [<default-args>]
    arg_mapping:
      <param-name>: <arg-template>
    env_mapping:
      <param-name>: <env-var>

  # For API adapters
  api:
    base_url: <api-endpoint>
    auth_method: <none|api_key|oauth|bearer>
    headers:
      <header-name>: <value>
    endpoint_mapping:
      <operation>: <path-template>

  # For SDK adapters
  sdk:
    language: <python|node|go|rust>
    package: <package-name>
    import_path: <module.path>
    function_mapping:
      <operation>: <function-name>

  # For MCP adapters
  mcp:
    server: <server-identifier>
    transport: <stdio|http|websocket>
    tool_mapping:
      <operation>: <mcp-tool-name>

# Input/Output Transformation
transforms:
  input:
    - type: <rename|map|default|validate>
      spec: <transformation-spec>
  output:
    - type: <parse|extract|format>
      spec: <transformation-spec>

# Error Handling
errors:
  retry:
    max_attempts: <count>
    backoff_ms: <initial-backoff>
    retryable_codes: [<exit-codes>]
  fallback:
    adapter_id: <fallback-adapter>
    condition: <when-to-fallback>

# Sandbox Override
sandbox_override:
  timeout_ms: <custom-timeout>
  memory_mb: <custom-memory>
  network:
    enabled: <true|false>
    allow: [<hosts>]

# Metadata
metadata:
  author: <creator>
  created: <ISO8601>
  updated: <ISO8601>
  status: <active|deprecated|experimental>
```

---

## Example Adapters

### Example 1: CLI Adapter (ripgrep)

```yaml
adapter_id: ADP-001
name: ripgrep-search
version: "1.0.0"
tool_id: TL-003

type: cli

interface:
  cli:
    executable: rg
    base_args: ["--json", "--no-heading"]
    arg_mapping:
      pattern: "{pattern}"
      path: "{path}"
      ignore_case: "-i"
      max_count: "-m {value}"
    env_mapping: {}

transforms:
  input: []
  output:
    - type: parse
      spec: json_lines

errors:
  retry:
    max_attempts: 1
    backoff_ms: 0
    retryable_codes: []
  fallback: null

sandbox_override:
  timeout_ms: 60000
  memory_mb: 256
  network:
    enabled: false

metadata:
  author: Runtime Agent
  created: "2026-01-16"
  updated: "2026-01-16"
  status: active
```

### Example 2: API Adapter (generic REST)

```yaml
adapter_id: ADP-002
name: rest-api-client
version: "1.0.0"
tool_id: TL-100

type: api

interface:
  api:
    base_url: "https://api.example.com/v1"
    auth_method: bearer
    headers:
      Content-Type: application/json
      Accept: application/json
    endpoint_mapping:
      get_resource: "GET /resources/{id}"
      list_resources: "GET /resources"
      create_resource: "POST /resources"

transforms:
  input:
    - type: validate
      spec: json_schema
  output:
    - type: extract
      spec: "$.data"

errors:
  retry:
    max_attempts: 3
    backoff_ms: 1000
    retryable_codes: [429, 500, 502, 503]
  fallback: null

sandbox_override:
  timeout_ms: 30000
  network:
    enabled: true
    allow: ["api.example.com"]

metadata:
  author: Runtime Agent
  created: "2026-01-16"
  updated: "2026-01-16"
  status: experimental
```

### Example 3: MCP Adapter

```yaml
adapter_id: ADP-003
name: mcp-filesystem
version: "1.0.0"
tool_id: TL-200

type: mcp

interface:
  mcp:
    server: filesystem-server
    transport: stdio
    tool_mapping:
      read_file: read_file
      write_file: write_file
      list_directory: list_directory

transforms:
  input: []
  output:
    - type: extract
      spec: "$.content"

errors:
  retry:
    max_attempts: 2
    backoff_ms: 500
    retryable_codes: []
  fallback: null

sandbox_override:
  timeout_ms: 10000
  memory_mb: 128
  network:
    enabled: false

metadata:
  author: Runtime Agent
  created: "2026-01-16"
  updated: "2026-01-16"
  status: active
```

---

## Progressive Disclosure Integration

### Loading Levels

| Level | What's Loaded | When to Use |
|-------|--------------|-------------|
| **L0** | adapter_id, name, tool_id, type | Listing available adapters |
| **L1** | L0 + interface summary | Selecting adapter for task |
| **L2** | L0 + L1 + full interface + transforms | Executing adapter |
| **L3** | Full schema + examples + fixtures | Debugging or documentation |

### Loading Workflow

```
1. Request adapter for tool_id
2. Load L0 metadata (fast, cached)
3. If multiple adapters, load L1 to compare
4. Select adapter based on task requirements
5. Load L2 for execution
6. Load L3 only for debugging or new adapter development
```

---

## Deterministic Execution

### Requirements for Determinism

| Requirement | Implementation |
|-------------|----------------|
| **Version pinning** | Exact tool and adapter versions |
| **Fixed inputs** | Same command, args, env, files |
| **Controlled randomness** | Seed random generators |
| **Stable filesystem** | Consistent file ordering |
| **No network variance** | Mock or cache external calls |
| **Timestamp handling** | Use fixed or mocked timestamps |

### Caching Strategy

| Cache Level | Scope | TTL | Invalidation |
|-------------|-------|-----|--------------|
| **Adapter schema** | Global | 24h | Version change |
| **Tool metadata** | Global | 1h | Manual refresh |
| **Execution results** | Session | Session end | Input change |
| **Golden outputs** | Permanent | Never | Manual update |

---

## Execution Checklist

### Pre-Execution

- [ ] Tool is in registry and active
- [ ] Adapter exists and matches tool version
- [ ] Inputs validated and sanitized
- [ ] Sandbox limits set appropriately
- [ ] Allowlist permits the operation
- [ ] Evidence capture initialized

### During Execution

- [ ] Timeout enforced
- [ ] Resource limits monitored
- [ ] Output streams captured
- [ ] Errors logged with context

### Post-Execution

- [ ] Exit code interpreted
- [ ] Outputs collected and validated
- [ ] Artifacts stored
- [ ] Evidence captured
- [ ] Cleanup performed

---

## References

- Tools-as-code guidance: `core/orchestrator/TOOLS_AS_CODE.md`
- Tool governance: `core/orchestrator/TOOL_GOVERNANCE.md`
- Tool registry: `core/orchestrator/TOOL_REGISTRY_CHANGE_CONTROL.md`
- Risk triggers: `core/packs/policy-pack-v1/RISK_TRIGGERS.md`
- Evidence capture: `core/orchestrator/handoff/EVIDENCE_CAPTURE.md`
