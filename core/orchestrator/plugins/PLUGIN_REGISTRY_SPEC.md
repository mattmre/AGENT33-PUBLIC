# Plugin Registry Specification

Purpose: Define a plugin system for extending AGENT-33 with custom task types, agents, validators, integrations, transforms, and sensors.

Sources: Osmedeus (CA-089 to CA-106), Kestra (CA-041 to CA-052)

Related docs:
- `core/orchestrator/TOOL_GOVERNANCE.md` (allowlist and provenance requirements)
- `core/orchestrator/TOOL_REGISTRY_CHANGE_CONTROL.md` (change control checklists)
- `core/orchestrator/TOOLS_AS_CODE.md` (tools-as-code guidance)
- `core/orchestrator/CODE_EXECUTION_CONTRACT.md` (sandbox limits, adapters)
- `core/orchestrator/SECURITY_HARDENING.md` (prompt injection defense, secrets handling)
- `core/orchestrator/community/GOVERNANCE_COMMUNITY_SPEC.md` (community governance)

---

## Overview

The plugin system allows AGENT-33 to be extended without modifying core orchestration code. Plugins register new capabilities that the orchestrator discovers and activates at runtime. All plugins are subject to governance controls, sandboxing, and provenance verification before activation.

## Plugin Types

| Type | Description | Example |
|------|-------------|---------|
| **task_type** | New task execution strategy | `shell_command`, `api_call`, `llm_prompt` |
| **agent_role** | New agent behavior or persona | `security_auditor`, `data_analyst` |
| **validator** | Output validation logic | `json_schema_check`, `regression_gate` |
| **integration** | External service connector | `slack_notify`, `jira_sync`, `github_pr` |
| **transform** | Data transformation pipeline | `csv_to_json`, `log_parser`, `report_gen` |
| **sensor** | Event detection and triggering | `file_watcher`, `webhook_listener`, `cron` |

## Plugin Manifest Schema

Every plugin must include a manifest file (`plugin.yaml`) at its root.

```yaml
plugin:
  # Identity
  name: string                    # unique identifier, lowercase with hyphens
  version: semver                 # e.g. 1.2.0
  type: task_type | agent_role | validator | integration | transform | sensor
  description: string             # one-line summary of purpose
  author: string                  # maintainer name or organization
  license: string                 # SPDX identifier (e.g. MIT, Apache-2.0)

  # Entry point
  entry_point: string             # relative path to main module (e.g. src/main.py)
  exports:
    - name: string                # exported function or class name
      kind: handler | factory | hook

  # Dependencies
  dependencies:
    plugins:
      - name: string              # required plugin name
        version: semver_range     # e.g. ">=1.0.0 <2.0.0"
    runtime:
      min_version: string         # minimum AGENT-33 version required
    system:
      - name: string              # system-level dependency (e.g. ffmpeg, node)
        version: semver_range     # optional version constraint

  # Configuration
  config_schema:
    type: object
    properties: {}                # plugin-specific configuration properties
    required: []                  # list of required config keys
    defaults: {}                  # default values for optional config keys

  # Governance
  governance:
    provenance_checklist: completed | pending
    risk_level: low | medium | high
    review_date: ISO-8601         # date of last governance review
    reviewer: string              # who performed the review
    approval_status: approved | conditional | rejected | pending

  # Metadata
  tags: [string]                  # searchable tags
  documentation_url: string       # link to full documentation
  repository_url: string          # source repository
  checksum: sha256                # integrity hash of plugin package
```

## Plugin Lifecycle

Plugins move through a well-defined lifecycle with explicit state transitions.

```
  discover --> validate --> register --> activate
                  |                        |
                  v                        v
               [reject]              deactivate --> remove
```

### 1. Discover

The orchestrator scans configured plugin directories and registries for plugin manifests.

- **Local discovery**: scan `plugins/` directory for `plugin.yaml` files.
- **Registry discovery**: query the plugin registry API for available plugins.
- **Manual discovery**: operator provides a plugin package path or URL.

Discovery produces a candidate list. No code is loaded at this stage.

### 2. Validate

Each candidate plugin undergoes validation before it can be registered.

| Check | Description | Failure action |
|-------|-------------|----------------|
| **Manifest integrity** | `plugin.yaml` parses correctly and all required fields present | Reject with parse error |
| **Checksum verification** | Package checksum matches declared `checksum` field | Reject with integrity error |
| **Dependency resolution** | All plugin and system dependencies are satisfiable | Reject with dependency error |
| **Version compatibility** | Plugin `runtime.min_version` is met by current AGENT-33 version | Reject with version error |
| **Governance status** | `provenance_checklist` is `completed` and `approval_status` is `approved` | Block until governance passes |
| **Name uniqueness** | No other registered plugin shares the same name | Reject with conflict error |
| **Config schema validity** | `config_schema` is a valid JSON Schema document | Reject with schema error |

### 3. Register

Validated plugins are added to the plugin registry, a persistent catalog of all known plugins.

```yaml
registry_entry:
  plugin_name: string
  plugin_version: semver
  plugin_type: string
  status: registered | active | inactive | deprecated
  registered_at: ISO-8601
  registered_by: string
  manifest_hash: sha256
  config: {}                      # operator-supplied configuration
```

Registration does not execute any plugin code. The plugin is known but not active.

### 4. Activate

Activation loads the plugin into the orchestrator runtime.

- The orchestrator creates an isolated sandbox for the plugin (see Plugin Isolation).
- The entry point module is loaded within the sandbox.
- Exported handlers are bound to the orchestrator's dispatch table.
- An activation health check runs: the plugin must respond to a `ping` within 5 seconds.
- On success, status moves to `active`. On failure, status remains `registered` and an error is logged.

### 5. Deactivate

Deactivation removes the plugin from active dispatch without deleting its registration.

- In-flight tasks using the plugin are allowed to complete (grace period: configurable, default 60 seconds).
- After grace period, the sandbox is torn down.
- Status moves to `inactive`.
- Deactivation can be triggered manually or by the orchestrator (e.g., on repeated failures).

### 6. Remove

Removal deletes the plugin from the registry entirely.

- Plugin must be in `inactive` or `registered` status. Active plugins must be deactivated first.
- All configuration and cached artifacts for the plugin are purged.
- Registry entry is archived (not hard-deleted) for audit trail.

## Plugin Isolation

Each plugin runs in its own sandbox to prevent interference with the core orchestrator or other plugins.

| Boundary | Enforcement |
|----------|------------|
| **Process isolation** | Plugin executes in a child process or container |
| **Filesystem** | Plugin can only access its own data directory and declared inputs |
| **Network** | Plugin network access is governed by the tool allowlist |
| **Memory** | Configurable memory limit per plugin (default: 256 MB) |
| **CPU** | Configurable CPU time limit per invocation (default: 30 seconds) |
| **Secrets** | Plugins receive only secrets explicitly mapped to them in config |
| **Inter-plugin** | Plugins communicate only through the orchestrator message bus, never directly |

### Sandbox Configuration

```yaml
sandbox:
  memory_limit_mb: 256
  cpu_timeout_seconds: 30
  network_policy: allowlist_only    # inherits from TOOL_GOVERNANCE
  filesystem_policy: plugin_dir_only
  secret_bindings:
    - secret_name: string
      env_var: string               # environment variable name inside sandbox
```

## Plugin Configuration

Operators configure plugins through the orchestrator configuration file. Each plugin's configuration must conform to the plugin's declared `config_schema`.

```yaml
# In orchestrator config
plugins:
  slack_notify:
    enabled: true
    config:
      webhook_url: "${SLACK_WEBHOOK_URL}"
      channel: "#agent-alerts"
      mention_on_failure: "@oncall"
  jira_sync:
    enabled: false
    config:
      project_key: "AG33"
      base_url: "https://company.atlassian.net"
```

### Configuration Precedence

1. Plugin `config_schema.defaults` (lowest priority)
2. Orchestrator config file (`plugins.<name>.config`)
3. Environment variable overrides (`PLUGIN_<NAME>_<KEY>`)
4. Runtime overrides via API (highest priority)

### Configuration Validation

- On activation, the orchestrator validates the merged configuration against `config_schema`.
- Missing required fields produce a clear error and block activation.
- Unknown fields produce a warning but do not block activation.

## Plugin Dependency Resolution

Plugins may depend on other plugins. The orchestrator resolves dependencies using the following algorithm.

### Resolution Algorithm

1. Build a directed dependency graph from all registered plugins.
2. Detect cycles. If any cycle exists, reject all plugins in the cycle.
3. Topologically sort the graph.
4. Activate plugins in topological order (dependencies first).
5. Deactivate plugins in reverse topological order (dependents first).

### Version Constraints

- Dependency version ranges follow the semver range specification (e.g., `>=1.0.0 <2.0.0`).
- If multiple versions of the same plugin are needed, the orchestrator rejects the configuration (no multi-version support in v1).
- The resolver selects the highest version that satisfies all constraints.

### Conflict Resolution

| Scenario | Resolution |
|----------|-----------|
| Two plugins require incompatible versions of a third | Reject both dependents with a clear error |
| Plugin depends on a plugin not in the registry | Reject with missing dependency error |
| Circular dependency detected | Reject all plugins in the cycle |

## Plugin Marketplace and Registry

The plugin registry supports both local and remote sources.

### Local Registry

- A directory on the filesystem containing plugin packages.
- Default path: `plugins/` relative to the orchestrator root.
- Each plugin is a subdirectory containing `plugin.yaml` and source files.

### Remote Registry

- An HTTP API that serves plugin metadata and packages.
- Plugins are identified by `name@version`.
- The registry enforces signature verification on all packages.

### Registry API (Future)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/plugins` | GET | List all available plugins (paginated) |
| `/plugins/{name}` | GET | Get metadata for a specific plugin |
| `/plugins/{name}/{version}` | GET | Get a specific version |
| `/plugins/{name}/{version}/download` | GET | Download plugin package |
| `/plugins/search?q={query}` | GET | Search plugins by name, tag, or type |
| `/plugins` | POST | Publish a new plugin (authenticated) |

### Publishing Requirements

- Plugin must pass all validation checks.
- Author must have a verified publisher identity.
- Plugin package must include a signed checksum.
- Governance review must be completed for risk levels `medium` and `high`.

## Governance Integration

All plugins are subject to the same governance standards as tools.

### Provenance Checklist (Required)

The following items must be verified and documented before a plugin can be approved.

- [ ] **Ownership**: maintainer or organization is identified
- [ ] **Source integrity**: repository URL, version tag, and checksum are recorded
- [ ] **License**: SPDX identifier recorded and compatible with project usage
- [ ] **Security review**: code reviewed for injection, data exfiltration, and privilege escalation
- [ ] **Dependency audit**: all transitive dependencies reviewed for known vulnerabilities
- [ ] **Sandbox compliance**: plugin operates correctly within sandbox constraints
- [ ] **Documentation**: plugin purpose, configuration, and usage are documented
- [ ] **Testing**: plugin includes tests and passes the workflow testing framework

### Risk Classification

| Risk Level | Criteria | Approval Required |
|------------|----------|-------------------|
| **Low** | Read-only, no network, no secrets | Single reviewer |
| **Medium** | Write access, network access, or secret binding | Two reviewers |
| **High** | Arbitrary code execution, external API calls with credentials | Two reviewers + operator sign-off |

### Continuous Governance

- Plugins are re-reviewed when updated to a new major version.
- The orchestrator periodically checks plugin dependencies against vulnerability databases.
- Plugins with unresolved critical vulnerabilities are automatically deactivated.

## Integration Points

### Task Definition Registry

Plugins of type `task_type` register new task type handlers. The task definition registry (see `TOOLS_AS_CODE.md`) is extended to include plugin-provided task types.

```yaml
task:
  type: plugin:slack_notify         # "plugin:" prefix indicates a plugin-provided type
  config:
    channel: "#builds"
    message: "Build ${build_id} completed"
```

### Tool Governance

Plugin activation is gated by the same allowlist and provenance system used for tools. A plugin that requires network access must have its endpoints listed in the tool allowlist.

### Trace Schema

Plugin executions are recorded in the trace schema under the `plugin` action type.

```yaml
action:
  type: plugin
  plugin_name: slack_notify
  plugin_version: 1.2.0
  input: {channel: "#builds", message: "Build 42 completed"}
  output: {status: "sent", ts: "1706000000.000001"}
  duration_ms: 230
  sandbox_id: "sbx-abc123"
```

### Analytics

Plugin usage metrics feed into the analytics system (see `analytics/METRICS_CATALOG.md`).

- Activation count, invocation count, error rate, and latency per plugin.
- Plugin dependency graph visualization.

---

## Appendix: Example Plugin

```
plugins/
  slack-notify/
    plugin.yaml
    src/
      main.py
      templates/
        default.jinja2
    tests/
      test_main.py
    README.md
```

**plugin.yaml**:

```yaml
plugin:
  name: slack-notify
  version: 1.0.0
  type: integration
  description: Send notifications to Slack channels on workflow events
  author: agent-33-team
  license: MIT
  entry_point: src/main.py
  exports:
    - name: send_notification
      kind: handler
  dependencies:
    plugins: []
    runtime:
      min_version: "0.5.0"
    system: []
  config_schema:
    type: object
    properties:
      webhook_url:
        type: string
        description: Slack incoming webhook URL
      channel:
        type: string
        description: Default channel to post to
      mention_on_failure:
        type: string
        description: User or group to mention on failure events
    required: [webhook_url]
    defaults:
      channel: "#general"
  governance:
    provenance_checklist: completed
    risk_level: medium
    review_date: "2026-01-30"
    reviewer: operator
    approval_status: approved
  tags: [notification, slack, integration]
  documentation_url: https://github.com/agent-33/agent-33/blob/main/docs/plugins/slack-notify.md
  repository_url: https://github.com/agent-33/plugin-slack-notify
  checksum: sha256:abc123def456...
```
