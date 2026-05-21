# Operator Onboarding

This guide is for a new operator who needs to understand what AGENT-33 does, how to get value quickly, and what surfaces matter first.

## 1. Understand the core surfaces

AGENT-33 has four primary operator surfaces:

1. **Control plane UI** at `http://localhost:3000`
2. **Runtime API** at `http://localhost:8000`
3. **Workflow and agent execution** through `/v1/agents/*` and `/v1/workflows/*`
4. **Operational controls** for reviews, evaluations, releases, autonomy, and memory

## 2. Know the first endpoints to verify

Start with these:

- `GET /health`
- `GET /v1/agents/`
- `POST /v1/agents/{name}/invoke`
- `GET /v1/workflows/`
- `POST /v1/workflows/{name}/execute`

See [API Surface](api-surface.md) for the complete auth and scope map.

## 3. Know the main scope families

The most visible scopes are:

- `admin`
- `agents:read`
- `agents:write`
- `agents:invoke`
- `workflows:read`
- `workflows:write`
- `workflows:execute`
- `tools:execute`
- `operator:read`
- `operator:write`

If you receive `403 Missing required scope`, check [API Surface](api-surface.md) before debugging anything else.

## 4. First operator workflow

Recommended first-run sequence:

1. Start the stack with Docker Compose
2. Verify `/health`
3. Sign in to the UI
4. Mint or obtain a JWT
5. List registered agents
6. Invoke the orchestrator
7. Register and execute a minimal workflow
8. Inspect dashboard and trace surfaces

Detailed commands are in:

- [Getting Started](getting-started.md)
- [Setup Guide](setup-guide.md)
- [Walkthroughs](walkthroughs.md)

## 5. Product areas to explore after first run

### Agents

Use when you want direct, bounded execution against a named capability.

- discovery: `GET /v1/agents/`
- invoke: `POST /v1/agents/{name}/invoke`

### Workflows

Use when you want repeatable multi-step execution.

- register: `POST /v1/workflows/`
- execute: `POST /v1/workflows/{name}/execute`

### Reviews and releases

Use when you need explicit signoff and gatekeeping.

- [Walkthroughs](walkthroughs.md)
- [Production Deployment Runbook](operators/production-deployment-runbook.md)

### Evaluations and regression handling

Use when you need measured quality gates and baseline comparisons.

- [Walkthroughs](walkthroughs.md)
- [Use Cases](use-cases.md)

### Memory and recall

Use when you need long-horizon context and retrieval-backed sessions.

- [Walkthroughs](walkthroughs.md)
- [Use Cases](use-cases.md)

## 6. What is local-only vs production-ready

### Local-only defaults

- bootstrap login with `admin/admin`
- default secrets from `.env.example`
- convenience JWT minting from the API container

### Production expectations

- disable bootstrap auth
- rotate secrets
- define your real identity and token issuing path
- use the production deployment and verification runbooks
- complete the [Release Checklist](RELEASE_CHECKLIST.md)

## 7. Operational guardrails to remember

- Most `/v1/*` routes require authentication
- Several services are still in-memory and reset on process restart
- Webhook endpoints remain unavailable until adapters are registered in-process
- Training surfaces exist, but some runtime wiring is partial by default

## 8. Recommended reading order

1. [Getting Started](getting-started.md)
2. [Setup Guide](setup-guide.md)
3. [Walkthroughs](walkthroughs.md)
4. [Use Cases](use-cases.md)
5. [API Surface](api-surface.md)
6. [Release Checklist](RELEASE_CHECKLIST.md)
7. [Documentation Index](README.md)
