# Walkthroughs

These walkthroughs assume:

- API is running at `http://localhost:8000`
- `TOKEN` is set (see `setup-guide.md`)

Example header used below:

```bash
-H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json"
```

## 1. Agent Discovery and Invocation

List registered agents:

```bash
curl http://localhost:8000/v1/agents/ \
  -H "Authorization: Bearer $TOKEN"
```

Search by role:

```bash
curl "http://localhost:8000/v1/agents/search?role=orchestrator" \
  -H "Authorization: Bearer $TOKEN"
```

Invoke the orchestrator:

```bash
curl -X POST http://localhost:8000/v1/agents/orchestrator/invoke \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "task": "Create a short rollout plan for adding cache metrics"
    },
    "model": "llama3.2",
    "temperature": 0.2
  }'
```

## 2. Workflow Registration and Execution

Register a minimal workflow:

```bash
curl -X POST http://localhost:8000/v1/workflows/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "hello-flow",
    "version": "1.0.0",
    "description": "simple workflow",
    "triggers": {"manual": true},
    "inputs": {
      "name": {"type": "string", "required": true}
    },
    "outputs": {
      "message": {"type": "string"}
    },
    "steps": [
      {
        "id": "build-message",
        "action": "transform",
        "inputs": {
          "template": {
            "message": "Hello {{ name }}"
          }
        }
      }
    ],
    "execution": {"mode": "sequential"}
  }'
```

Execute it:

```bash
curl -X POST http://localhost:8000/v1/workflows/hello-flow/execute \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {"name": "AGENT-33"}
  }'
```

For the improvement-cycle wizard and Docker-backed Jupyter execution surfaces, see:

- [`operator-improvement-cycle-and-jupyter.md`](operator-improvement-cycle-and-jupyter.md)

## 3. Memory Search and Session Queries

Search progressive recall index:

```bash
curl -X POST http://localhost:8000/v1/memory/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"release checklist", "level":"index", "top_k":5}'
```

List buffered observations for a session:

```bash
curl http://localhost:8000/v1/memory/sessions/session-123/observations \
  -H "Authorization: Bearer $TOKEN"
```

Summarize a session:

```bash
curl -X POST http://localhost:8000/v1/memory/sessions/session-123/summarize \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

## 4. Review Lifecycle (Two-Layer Signoff)

Create review:

```bash
curl -X POST http://localhost:8000/v1/reviews/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"task_id":"TASK-101","branch":"feat/docs-refresh","pr_number":12}'
```

Assess risk:

```bash
curl -X POST http://localhost:8000/v1/reviews/<review_id>/assess \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"triggers":["api-public","security"]}'
```

Move to ready and assign L1:

```bash
curl -X POST http://localhost:8000/v1/reviews/<review_id>/ready -H "Authorization: Bearer $TOKEN"
curl -X POST http://localhost:8000/v1/reviews/<review_id>/assign-l1 -H "Authorization: Bearer $TOKEN"
```

Submit L1 decision:

```bash
curl -X POST http://localhost:8000/v1/reviews/<review_id>/l1 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"decision":"approved","issues":[],"comments":"L1 pass"}'
```

If L2 required, continue:

```bash
curl -X POST http://localhost:8000/v1/reviews/<review_id>/assign-l2 -H "Authorization: Bearer $TOKEN"
curl -X POST http://localhost:8000/v1/reviews/<review_id>/l2 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"decision":"approved","issues":[],"comments":"L2 pass"}'
```

Finalize:

```bash
curl -X POST http://localhost:8000/v1/reviews/<review_id>/approve \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"approver_id":"release-manager","conditions":[]}'

curl -X POST http://localhost:8000/v1/reviews/<review_id>/merge \
  -H "Authorization: Bearer $TOKEN"
```

## 5. Evaluation Run and Regression Handling

Create run:

```bash
curl -X POST http://localhost:8000/v1/evaluations/runs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"gate":"G-PR","commit_hash":"abc123","branch":"main"}'
```

Submit task results:

```bash
curl -X POST http://localhost:8000/v1/evaluations/runs/<run_id>/results \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "task_results": [
      {"item_id":"GT-01","result":"pass","checks_passed":3,"checks_total":3,"duration_ms":1200}
    ],
    "rework_count": 0,
    "scope_violations": 0
  }'
```

Save baseline from completed run:

```bash
curl -X POST http://localhost:8000/v1/evaluations/runs/<run_id>/baseline \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"commit_hash":"abc123","branch":"main"}'
```

List regressions:

```bash
curl http://localhost:8000/v1/evaluations/regressions \
  -H "Authorization: Bearer $TOKEN"
```

## 6. Autonomy Budget Lifecycle

Create budget:

```bash
curl -X POST http://localhost:8000/v1/autonomy/budgets \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "task_id":"TASK-201",
    "agent_id":"AGT-003",
    "in_scope":["engine/src/**"],
    "out_of_scope":["infra/**"],
    "default_escalation_target":"orchestrator"
  }'
```

Activate and create runtime enforcer:

```bash
curl -X POST http://localhost:8000/v1/autonomy/budgets/<budget_id>/activate \
  -H "Authorization: Bearer $TOKEN"

curl -X POST http://localhost:8000/v1/autonomy/budgets/<budget_id>/enforcer \
  -H "Authorization: Bearer $TOKEN"
```

Run sample enforcement checks:

```bash
curl -X POST http://localhost:8000/v1/autonomy/budgets/<budget_id>/enforce/command \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command":"pytest -q"}'

curl -X POST http://localhost:8000/v1/autonomy/budgets/<budget_id>/escalate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"description":"Manual escalation for policy review","target":"director","urgency":"normal"}'
```

## 7. Release Lifecycle, Sync, and Rollback

Create release:

```bash
curl -X POST http://localhost:8000/v1/releases \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"version":"1.4.0","release_type":"minor","description":"Feature bundle"}'
```

Move through lifecycle:

```bash
curl -X POST http://localhost:8000/v1/releases/<release_id>/freeze -H "Authorization: Bearer $TOKEN"
curl -X POST http://localhost:8000/v1/releases/<release_id>/rc -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"rc_version":"1.4.0-rc1"}'
curl -X POST http://localhost:8000/v1/releases/<release_id>/validate -H "Authorization: Bearer $TOKEN"
```

If publish fails checklist validation, inspect checklist:

```bash
curl http://localhost:8000/v1/releases/<release_id>/checklist \
  -H "Authorization: Bearer $TOKEN"
```

Create sync rule and dry-run:

```bash
curl -X POST http://localhost:8000/v1/releases/sync/rules \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_pattern":"core/**/*.md",
    "target_repo":"example/downstream",
    "target_path":"docs",
    "strategy":"copy",
    "frequency":"manual"
  }'

curl -X POST http://localhost:8000/v1/releases/sync/rules/<rule_id>/dry-run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"available_files":["core/README.md"],"release_version":"1.4.0"}'
```

## 8. Improvement Intake and Lessons

Submit intake:

```bash
curl -X POST http://localhost:8000/v1/improvements/intakes \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title":"Need workflow action routing",
    "summary":"Route action should dispatch by model capability",
    "source":"internal-review",
    "submitted_by":"platform-team",
    "research_type":"technical",
    "urgency":"high",
    "priority_score":8
  }'
```

Transition intake:

```bash
curl -X POST http://localhost:8000/v1/improvements/intakes/<intake_id>/transition \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"new_status":"triaged","decision_by":"director"}'
```

Record lesson:

```bash
curl -X POST http://localhost:8000/v1/improvements/lessons \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "recorded_by":"qa-agent",
    "phase":"phase-18",
    "event_type":"observation",
    "what_happened":"auth scopes were missing in one route",
    "insight":"scope checks must be enforced in every route",
    "recommendation":"add route-level scope checklist"
  }'
```

## 9. Trace and Failure Capture

Start trace:

```bash
curl -X POST http://localhost:8000/v1/traces/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"task_id":"TASK-301","session_id":"session-301","agent_id":"AGT-001","agent_role":"orchestrator"}'
```

Add action:

```bash
curl -X POST http://localhost:8000/v1/traces/<trace_id>/actions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"step_id":"step-1","action_id":"act-1","tool":"shell","input_data":"pytest -q","output_data":"ok","duration_ms":850,"status":"success"}'
```

Complete trace:

```bash
curl -X POST http://localhost:8000/v1/traces/<trace_id>/complete \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"completed"}'
```

## 10. Visual Explanations (Phase 26)

Generate and retrieve persistent visual explanation pages for diffs, plans,
and project recaps.  All endpoints require `workflows:write` to create and
`workflows:read` to retrieve.

### Generate a diff review page

```bash
curl -X POST http://localhost:8000/v1/explanations/diff-review \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "entity_type": "workflow",
    "entity_id": "hello-flow",
    "diff_text": "diff --git a/engine/src/agent33/main.py b/engine/src/agent33/main.py\n--- a/engine/src/agent33/main.py\n+++ b/engine/src/agent33/main.py\n@@ -1,3 +1,4 @@\n+import structlog\n import sys\n-# old comment\n+# new comment",
    "metadata": {"branch": "feat/perf", "pr": 42}
  }'
```

The response includes the rendered HTML page and a persisted explanation ID:

```json
{
  "id": "expl-a1b2c3d4e5f6",
  "entity_type": "workflow",
  "entity_id": "hello-flow",
  "mode": "diff_review",
  "content": "<!DOCTYPE html>...",
  "fact_check_status": "skipped",
  "claims": [],
  "created_at": "2026-05-16T12:00:00Z",
  "metadata": {"branch": "feat/perf", "pr": 42}
}
```

### Generate a plan review page

```bash
curl -X POST http://localhost:8000/v1/explanations/plan-review \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "entity_type": "workflow",
    "entity_id": "phase-27-plan",
    "plan_text": "## Phase 27: Streaming\n\nAdd server-sent events.\n\n## Phase 28: Auth refresh\n\nRotate signing keys.",
    "metadata": {}
  }'
```

### Retrieve a stored explanation

Explanations are persisted to SQLite and survive server restarts:

```bash
curl http://localhost:8000/v1/explanations/expl-a1b2c3d4e5f6 \
  -H "Authorization: Bearer $TOKEN"
```

List all explanations (optionally filtered):

```bash
# All explanations
curl "http://localhost:8000/v1/explanations/" \
  -H "Authorization: Bearer $TOKEN"

# Filtered by entity_type
curl "http://localhost:8000/v1/explanations/?entity_type=workflow" \
  -H "Authorization: Bearer $TOKEN"
```

### Run or re-run fact-check on an explanation

```bash
curl -X POST http://localhost:8000/v1/explanations/expl-a1b2c3d4e5f6/fact-check \
  -H "Authorization: Bearer $TOKEN"
```

The fact-check engine evaluates any attached deterministic claims
(`file_exists`, `metadata_equals`, `content_contains`) and updates
`fact_check_status` to `verified`, `flagged`, or `skipped`.

## 11. Workflow Graph Visualization (Phase 25)

Get visual graph representation of a workflow:

```bash
curl http://localhost:8000/v1/visualizations/workflows/hello-flow/graph \
  -H "Authorization: Bearer $TOKEN"
```

Response includes nodes, edges, layout coordinates, and execution status overlay:

```json
{
  "workflow_id": "hello-flow",
  "workflow_version": "1.0.0",
  "nodes": [
    {
      "id": "build-message",
      "name": "build-message",
      "action": "transform",
      "x": 80,
      "y": 80,
      "position": {"x": 80, "y": 80},
      "metadata": {
        "inputs": {...},
        "outputs": {...}
      },
      "status": "success"
    }
  ],
  "edges": [],
  "layout": {
    "type": "layered",
    "width": 280,
    "height": 280,
    "layer_spacing": 200,
    "node_spacing": 150
  },
  "metadata": {
    "generated_at": "2026-02-17T...",
    "step_count": 1,
    "execution_mode": "sequential"
  }
}
```

### Using the Frontend Workflow Graph View

1. Navigate to `http://localhost:3000` and login with bootstrap credentials
2. Select the **Workflows** domain from the sidebar
3. Choose **Workflow Graph** operation
4. Enter the workflow ID (e.g., `hello-flow`) in the path parameter field
5. Click **Run** to fetch and render the graph
6. Use the interactive controls:
   - **Zoom**: Mouse wheel or zoom controls
   - **Pan**: Click and drag on the canvas
   - **Node details**: Click any node to view inputs, outputs, status, and metadata
   - **Deselect**: Click on empty canvas to hide detail sidebar

The graph view is useful for:
- Debugging workflow execution paths and dependencies
- Identifying failed steps visually with status indicators
- Understanding complex workflow structures without manual trace correlation
- Sharing workflow architecture diagrams with non-technical stakeholders

## 11. Enterprise Security Scanning (Phase 28)

### Prerequisites
- API key with `component-security:read` and `component-security:write` scopes
- Component security service initialized (check `GET /v1/component-security/health`)

### 11.1 Check security scan service health

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/component-security/health
# → {"status": "ready", "service": "component-security", "initialized": true, "store_enabled": true}
```

### 11.2 Launch a security scan

The `target` object requires a `repository_path`. The scan is created and executed immediately when `execute_now` is `true` (the default).

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "target": {"repository_path": "engine/src/agent33"},
    "profile": "standard",
    "requested_by": "ops-team"
  }' \
  http://localhost:8000/v1/component-security/runs
# → {"id": "secrun-...", "status": "running", "profile": "standard",
#    "target": {"repository_path": "engine/src/agent33", ...}, ...}
```

Supported profiles: `quick`, `standard`, `deep`.

### 11.3 Poll scan status

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/component-security/runs/{run_id}/status
# → {"run_id": "secrun-...", "status": "completed"}
```

### 11.4 Get full run details and findings summary

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/component-security/runs/{run_id}
# → {"id": "secrun-...", "status": "completed", "findings_count": 3,
#    "findings_summary": {"critical": 0, "high": 1, "medium": 2, "low": 0, "info": 0}, ...}
```

### 11.5 Fetch detailed findings

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/v1/component-security/runs/{run_id}/findings?min_severity=medium"
# → {"findings": [{...}, ...], "total_count": 3}
```

### 11.6 Export findings as SARIF

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/component-security/runs/{run_id}/sarif
# → SARIF 2.1.0 JSON document suitable for GitHub Code Scanning upload
```

### 11.7 List recent scan runs

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/v1/component-security/runs?limit=10"
# → [{"id": "secrun-...", "status": "completed", ...}, ...]
```

Filter by status or profile:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/v1/component-security/runs?status=completed&profile=standard&limit=5"
```

### 11.8 Release security gate auto-evaluation

When a release enters the `validating` phase (via `POST /v1/releases/{release_id}/validate`), the engine automatically evaluates the security gate by looking up the most recent completed scan. Scans tagged with a matching `release_candidate_id` are preferred. If no completed scan exists or findings exceed the policy threshold, checklist item RL-06 is marked FAIL and the release is blocked.

```bash
# Trigger validation (runs _auto_evaluate_security_gate internally):
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/releases/{release_id}/validate
# → {"release_id": "...", "status": "validating", ...}

# Inspect the RL-06 checklist item to see the gate decision:
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/releases/{release_id}/checklist
# → [{"check_id": "RL-06", "name": "Security Gate", "status": "pass|fail", "message": "..."}, ...]
```

### 11.9 Register an MCP security server

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "bandit-mcp", "transport": "stdio", "config": {}}' \
  http://localhost:8000/v1/component-security/mcp-servers
# → {"name": "bandit-mcp", "transport": "stdio", ...}
```

## 12. Operations Hub (Phase 27)

The operations hub surfaces all concurrent active work — traces, autonomy budgets,
workflow executions, and pending improvements — in a single authenticated view.

### View the hub summary

```bash
curl http://localhost:8000/v1/operations/hub \
  -H "Authorization: Bearer $TOKEN"
```

Response shape:

```json
{
  "timestamp": "2026-05-16T10:00:00Z",
  "active_count": 3,
  "processes": [
    {
      "id": "trace-abc123",
      "type": "trace",
      "status": "running",
      "started_at": "2026-05-16T09:55:00Z",
      "name": "Research intake workflow"
    }
  ]
}
```

### Inspect a specific process

```bash
curl http://localhost:8000/v1/operations/processes/<process_id> \
  -H "Authorization: Bearer $TOKEN"
```

The detail response adds an `actions` array — one entry per workflow step with
`step_id`, `action_count`, and `completed_at`. This is the delegation lineage
data used to populate the process lineage view in the frontend.

### Lifecycle controls

```bash
# Pause a running process
curl -X POST http://localhost:8000/v1/operations/processes/<process_id>/control \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "pause"}'

# Resume a paused process
curl -X POST http://localhost:8000/v1/operations/processes/<process_id>/control \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "resume"}'

# Cancel a process
curl -X POST http://localhost:8000/v1/operations/processes/<process_id>/control \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "cancel"}'
```

Valid actions: `pause`, `resume`, `cancel`. Autonomy-budget processes honour the
budget policy; cancel on a budget with `ACTIVE` state transitions it to `CANCELLED`.

### Live SSE stream

For real-time status updates without polling, subscribe to the SSE stream:

```bash
curl -N http://localhost:8000/v1/operations/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: text/event-stream"
```

Each event is a JSON-encoded process summary. The frontend `OperationsHubPanel`
uses a 1.5-second polling interval as a fallback when SSE is not in use.

### Using the Frontend Operations Hub

1. Navigate to `http://localhost:3000` and log in.
2. Select the **Operations Hub** panel from the sidebar.
3. The **Run Timeline** overview shows total, active, needs-attention, and done counts.
4. Use the **Status** filter and **Search** field to narrow the process list.
5. Click any process row to load the detail view on the right side. The detail view shows:
   - Type, status, and start time
   - Metadata block
   - Reviewable output plan (when the process has pending review gates)
   - **Delegation lineage**: ordered list of steps with action counts and completion times
   - Pause / Resume / Cancel control buttons
6. The **Session recovery** panel (below the timeline) lists crashed or suspended sessions.
   Use **Resume session** to re-attach to an incomplete run or **Save checkpoint** to
   snapshot its current state without continuing.

Required auth scope: `workflows:read` for read operations, `workflows:execute` for control actions.

## 13. Improvement Cycle Wizard (Phase 27)

The improvement cycle wizard guides operators through the full
`observe → research → decide → execute → review → improve` loop backed by
AGENT-33's improvement intake, lessons-learned, and checklist subsystems.

### Start an improvement cycle (frontend)

1. From the Operations Hub panel, click **Start Improvement Cycle**.
2. The wizard opens a multi-step form:
   - **Step 1 — Observe**: choose signal sources and observe period.
   - **Step 2 — Research**: link or submit a research intake item via the intake API.
   - **Step 3 — Decide**: triage signals, pick an action, record rationale.
   - **Step 4 — Execute**: apply the action (or mark dry-run to preview only).
   - **Step 5 — Review**: capture a lesson-learned entry and collect reviewer signoff.
   - **Step 6 — Improve**: mark checklist items complete and optionally refresh the roadmap.
3. Each step links to the relevant API route (see below).

### Trigger via workflow templates

Two reusable templates implement the cycle phases. Before executing a workflow
by name, it must be registered with the engine (one-time per server restart):

**Step 1 — Register the templates** (required before first execute call):

```bash
# Register observe-decide-execute
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(python -c "import json, pathlib; d=__import__('yaml').safe_load(pathlib.Path('core/workflows/improvement-cycle/observe-decide-execute.workflow.yaml').read_text()); print(json.dumps(d))")" \
  http://localhost:8000/v1/workflows/

# Register review-improve
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(python -c "import json, pathlib; d=__import__('yaml').safe_load(pathlib.Path('core/workflows/improvement-cycle/review-improve.workflow.yaml').read_text()); print(json.dumps(d))")" \
  http://localhost:8000/v1/workflows/
```

**Step 2 — Execute the templates**:

**observe-decide-execute** — covers signal collection through execution and verification:

```bash
curl -X POST http://localhost:8000/v1/workflows/observe-decide-execute/execute \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "cycle_id": "cycle-2026-q2-01",
      "observe_period": "last-14d",
      "signal_sources": ["traces", "evaluations"],
      "decision_threshold": "high",
      "dry_run": false
    }
  }'
```

**review-improve** — closes the cycle with lesson capture and roadmap update:

```bash
curl -X POST http://localhost:8000/v1/workflows/review-improve/execute \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "cycle_id": "cycle-2026-q2-01",
      "execution_outcome": "Reduced trace failure rate by 12% via timeout config fix.",
      "reviewers": ["director", "qa"],
      "checklist_ids": ["CI-03", "CI-07"],
      "roadmap_update_needed": true
    }
  }'
```

### Review and approve / reject intake items from the cycle

List items pending triage:

```bash
curl http://localhost:8000/v1/improvements/intakes?status=triaged \
  -H "Authorization: Bearer $TOKEN"
```

Approve an intake item for tracking:

```bash
curl -X POST http://localhost:8000/v1/improvements/intakes/<intake_id>/transition \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"new_status": "accepted", "decision_by": "director"}'
```

Reject an intake item:

```bash
curl -X POST http://localhost:8000/v1/improvements/intakes/<intake_id>/transition \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"new_status": "rejected", "decision_by": "director"}'
```

### Improvement metrics widget

The operations hub dashboard includes an improvement metrics widget. It pulls
live data from:

```bash
curl http://localhost:8000/v1/improvements/metrics \
  -H "Authorization: Bearer $TOKEN"
```

Metrics include cycle completion rate (IM-01), mean time to triage (IM-02),
adoption rate (IM-03), regression prevention rate (IM-04), and lesson reuse
rate (IM-05).

For the full operator guide including Jupyter notebook integration, see
[`operator-improvement-cycle-and-jupyter.md`](operator-improvement-cycle-and-jupyter.md).
