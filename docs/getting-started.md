# Getting Started

This guide is the fastest path from a fresh checkout to a working AGENT-33 demo.

## What you will do

1. Start the runtime with Docker Compose
2. Verify health
3. Sign in to the control plane
4. Mint a JWT for API access
5. List agents
6. Invoke one agent

## Prerequisites

- Docker Desktop or Docker Engine with Compose
- Python 3.11+
- `curl`
- Ollama reachable from the stack, or one of the documented Ollama override modes

## 1. Configure the environment

From repo root:

```bash
cd engine
cp .env.example .env
```

For local-only setup, the defaults are acceptable. For anything beyond local development, change at least:

- `API_SECRET_KEY`
- `JWT_SECRET`
- `ENCRYPTION_KEY`
- `AUTH_BOOTSTRAP_ENABLED`

Docker Compose reads `.env`. The bootstrap/wizard path writes `.env.local` for
local CLI/runtime usage and does not replace the Compose config file.

## 2. Start the stack

```bash
cd engine
docker compose up -d
```

By default, `engine/.env` points `OLLAMA_BASE_URL` at
`http://host.docker.internal:11434` so the stack can reuse a host/shared Ollama
daemon. If you want the repo-managed Ollama container instead, use the bundled
profile below and set `OLLAMA_BASE_URL=http://ollama:11434` in `engine/.env`
first.

Alternative startup modes:

- shared Ollama network:

```bash
docker compose -f docker-compose.yml -f docker-compose.shared-ollama.yml up -d
```

- bundled Ollama profile:

```bash
# set OLLAMA_BASE_URL=http://ollama:11434 in .env first
docker compose --profile local-ollama up -d
```

- dev container with tooling:

```bash
docker compose --profile dev up -d devbox
```

## 3. Verify runtime health

```bash
curl http://localhost:8000/health
```

You should see service health information for the runtime and its dependencies.

## 4. Open the control plane

- Frontend: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`

Default local credentials:

- username: `admin`
- password: `admin`

## 5. Create a local JWT for API calls

```bash
docker compose exec -T api python -c "import os,time,jwt; now=int(time.time()); payload={'sub':'local-admin','scopes':['admin','agents:read','agents:write','agents:invoke','workflows:read','workflows:write','workflows:execute','tools:execute'],'iat':now,'exp':now+3600}; print(jwt.encode(payload, os.getenv('JWT_SECRET','change-me-in-production'), algorithm=os.getenv('JWT_ALGORITHM','HS256')))"
```

Set the token:

```bash
export TOKEN="<paste-token-here>"
```

PowerShell:

```powershell
$env:TOKEN = "<paste-token-here>"
```

## 6. List agents

```bash
curl http://localhost:8000/v1/agents/ \
  -H "Authorization: Bearer $TOKEN"
```

## 7. Invoke the orchestrator

```bash
curl -X POST http://localhost:8000/v1/agents/orchestrator/invoke \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "task": "Create a short checklist for verifying a local AGENT-33 deployment"
    },
    "model": "llama3.2:3b",
    "temperature": 0.2
  }'
```

## 8. Optional next steps

- Continue with [Walkthroughs](walkthroughs.md)
- Read [Operator Onboarding](ONBOARDING.md)
- Review the [API Surface](api-surface.md)
- Use the [Release Checklist](RELEASE_CHECKLIST.md) before any non-local deployment

## Important security note

The bootstrap login and default secrets in `.env.example` are **not** safe for public exposure.

Before shared or production use:

- set `AUTH_BOOTSTRAP_ENABLED=false`
- rotate all default secrets
- read [SECURITY.md](../SECURITY.md)
- follow the [Release Checklist](RELEASE_CHECKLIST.md)
