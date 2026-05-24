# AGENT-33

AGENT-33 is a local-first AI agent orchestration platform for teams that want **real workflows, explicit governance, and a usable control plane** instead of a pile of disconnected scripts.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## Why AGENT-33

AGENT-33 combines an API runtime, workflow engine, memory stack, review/release controls, and a first-party frontend so you can run guarded automation from one system.

- **Local-first runtime**: FastAPI backend, Docker Compose bootstrap, Ollama-friendly model routing
- **Contained Agent OS**: optional Linux operator workspace with first-party tools, state, and stack connectivity
- **Guardrailed automation**: scopes, approvals, autonomy budgets, and review/release workflows
- **Agent + workflow orchestration**: invoke agents directly or compose repeatable workflows
- **Operational visibility**: health, dashboard surfaces, traces, evaluations, and rollout telemetry
- **Extensible platform**: packs, tools, memory, webhook intake, and improvement loops

## Repository Layout

- `engine/`: FastAPI runtime, orchestration services, API routes, tests, Docker Compose stack
- `frontend/`: AGENT-33 control plane UI served at `http://localhost:3000`
- `core/`: orchestration specs, policy packs, protocol references, workflow materials
- `docs/`: canonical operator, setup, onboarding, and release-readiness documentation

## Quick Start

### Prerequisites

- Docker Desktop or Docker Engine with Compose
- Python 3.11+
- `curl`
- Ollama reachable from the stack (`http://host.docker.internal:11434` by default), or use the bundled/local override paths documented in the setup guides

### 1. Start the stack

```bash
cd engine
cp .env.example .env
docker compose up -d
curl http://localhost:8000/health
```

If you reuse an Ollama container from another Compose project:

```bash
docker compose -f docker-compose.yml -f docker-compose.shared-ollama.yml up -d
```

### 2. Open the control plane

- Frontend: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`

Default local credentials from `.env.example`:

- username: `admin`
- password: `admin`

### 3. Mint a local JWT for API access

```bash
docker compose exec -T api python -c "import os,time,jwt; now=int(time.time()); payload={'sub':'local-admin','scopes':['admin','agents:read','agents:write','agents:invoke','workflows:read','workflows:write','workflows:execute','tools:execute'],'iat':now,'exp':now+3600}; print(jwt.encode(payload, os.getenv('JWT_SECRET','change-me-in-production'), algorithm=os.getenv('JWT_ALGORITHM','HS256')))"
```

Set the token in your shell:

```bash
export TOKEN="<paste-token-here>"
```

PowerShell:

```powershell
$env:TOKEN = "<paste-token-here>"
```

### 4. Verify the first agent flow

List agents:

```bash
curl http://localhost:8000/v1/agents/ \
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

## First 5-Minute Operator Path

1. Start the stack and confirm `/health`
2. Sign in to `http://localhost:3000`
3. Mint a local JWT or use the UI token flow
4. List agents with `GET /v1/agents/`
5. Invoke an agent or execute a minimal workflow
6. Explore the dashboard, traces, reviews, evaluations, and autonomy surfaces from the UI

For a fuller beginner path, use:

- [Getting Started](docs/getting-started.md)
- [Operator Onboarding](docs/ONBOARDING.md)
- [Walkthroughs](docs/walkthroughs.md)

## Security and Production Warning

**Bootstrap auth is for local development only. Do not expose AGENT-33 publicly with default credentials or default secrets.**

Before any shared, VPS, or production deployment:

- set `AUTH_BOOTSTRAP_ENABLED=false`
- rotate `API_SECRET_KEY`
- rotate `JWT_SECRET`
- rotate `ENCRYPTION_KEY`
- review [SECURITY.md](SECURITY.md)
- work through the [Release Checklist](docs/RELEASE_CHECKLIST.md)

## Documentation Map

### Start here

- [Getting Started](docs/getting-started.md)
- [Operator Onboarding](docs/ONBOARDING.md)
- [Setup Guide](docs/setup-guide.md)
- [Walkthroughs](docs/walkthroughs.md)
- [Use Cases](docs/use-cases.md)
- [Agent OS Runtime](docs/operators/agent-os-runtime.md)
- [API Surface](docs/api-surface.md)
- [Release Checklist](docs/RELEASE_CHECKLIST.md)
- [Documentation Index](docs/README.md)

### Deep references

- [Functionality and Workflows](docs/functionality-and-workflows.md)
- [Production Deployment Runbook](docs/operators/production-deployment-runbook.md)
- [Operator Verification Runbook](docs/operators/operator-verification-runbook.md)
- [Horizontal Scaling Architecture](docs/operators/horizontal-scaling-architecture.md)
- [Incident Response Playbooks](docs/operators/incident-response-playbooks.md)

## Who this is for

- **Operators** who need a guarded local or self-hosted AI control plane
- **Platform teams** building approval-aware automation and workflow execution
- **Engineering teams** running review, release, evaluation, and autonomy gates in one runtime
- **Researchers and builders** experimenting with packs, memory, training, and improvement loops

## Current Status

The POST-4 roadmap is complete through `POST-4.5`, including the P-PACK v3 A/B harness and behavior rollout. The next roadmap wave is public launch preparation and broader ecosystem work under `POST-CLUSTER`.

Latest merged implementation PR:

- `#406` — `POST-4.5: apply P-PACK v3 behavior rollout`

## License

MIT. See [LICENSE](LICENSE).
