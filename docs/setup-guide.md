# Setup Guide

This guide gets AGENT-33 running locally and verifies protected API access.

## Prerequisites

- Docker Desktop (or Docker Engine + Compose)
- Python 3.11+
- `curl`
- Ollama reachable from the stack, or one of the documented Ollama startup modes below

Optional:

- NVIDIA GPU (for local Ollama acceleration)
- Playwright dependencies (if you plan to use the browser tool)

## 1. Configure Environment

From repo root:

```bash
cd engine
cp .env.example .env
```

Review and update at least these values for non-local environments:

- `API_SECRET_KEY`
- `JWT_SECRET`
- `ENCRYPTION_KEY`
- `DATABASE_URL`

Docker Compose reads `.env`. The wizard/bootstrap path writes `.env.local` for
local CLI/runtime usage (for example `agent33 start`) and does **not** replace
the Compose `.env` contract.

## 2. Start the Stack

```bash
cd engine
docker compose up -d
```

This starts AGENT-33 and uses your existing Ollama instance via `OLLAMA_BASE_URL`.
The stack also exposes the frontend control plane on `http://localhost:3000`.

If your Ollama runs in another Docker compose project without host port mapping
(for example `shared-ollama` on `shared_ollama_default`), use the shared-network override:

```bash
cd engine
docker compose -f docker-compose.yml -f docker-compose.shared-ollama.yml up -d
```

Optional network/env overrides:

- `SHARED_OLLAMA_NETWORK` (default: `shared_ollama_default`)
- `SHARED_OLLAMA_BASE_URL` (default: `http://shared-ollama:11434`)

Optional profiles:

- Integrations profile (includes `n8n`):

```bash
docker compose --profile integrations up -d
```

- GPU profile (includes `airllm` service):

```bash
docker compose --profile gpu up -d
```

- Dev profile (includes Ubuntu `devbox` with CLI tooling and repo mount):

```bash
docker compose --profile dev up -d devbox
docker compose exec devbox bash
```

- Local Ollama profile (starts the bundled Ollama service **and** the rest of the stack):

```bash
cd engine
# set OLLAMA_BASE_URL=http://ollama:11434 in .env first
docker compose --profile local-ollama up -d
```

`devbox` includes common tooling for coding and automation:

- Shell/build: `bash`, `make`, `build-essential`, `cmake`, `tmux`
- Python: `python3`, `pip`, `venv`, `uv`, `poetry`
- JavaScript/TypeScript: Node.js 22 + `npm`, `pnpm`, `yarn` (via corepack)
- Systems: `go`, `rustc`, `cargo`
- Dev ops + diagnostics: `git`, `gh`, `docker` + `docker compose`, `curl`, `jq`, `ripgrep`, `fd`, `tree`
- Data/service CLIs: `psql`, `redis-cli`, `sqlite3`

The container also mounts Docker Desktop's socket (`/var/run/docker.sock`) so tools running inside
`devbox` can manage host containers.

## 3. Open the Frontend

Open:

- `http://localhost:3000`

Default local credentials (from `.env.example`):

- username: `admin`
- password: `admin`

**⚠️ Security Warning:** The bootstrap authentication (`admin/admin`) is for local development only. **Do not use these credentials in production or on public-facing deployments.**

For production/VPS deployments, you **must**:

- Set `AUTH_BOOTSTRAP_ENABLED=false` in your `.env` file
- Configure a proper identity provider or secure token issuing mechanism
- Change all default secrets (`API_SECRET_KEY`, `JWT_SECRET`, `ENCRYPTION_KEY`)

## 4. Verify Health

```bash
curl http://localhost:8000/health
```

You should receive a JSON payload with service statuses (`ollama`, `redis`, `postgres`, `nats`, and channel health entries).

## 5. Configure Ollama and Pull a Model

Recommended path:

```bash
cd engine
python -m agent33.cli.main wizard
```

The wizard now:

- refreshes your environment profile
- recommends the best local Ollama model for your hardware
- starts `ollama serve` automatically when possible
- falls back to the bundled `docker compose --profile local-ollama` Ollama service when available
- downloads the recommended model if it is missing

The wizard only bootstraps the Ollama service. If you want the full AGENT-33
stack plus bundled Ollama through Docker Compose, use the `docker compose
--profile local-ollama up -d` flow above.

For local Python/CLI usage instead of Docker Compose:

```bash
cd engine
python -m agent33.cli.main bootstrap
python -m agent33.cli.main wizard
agent33 start
```

Manual fallback:

```bash
ollama pull llama3.2:3b
```

Recommended coding model for a 24GB GPU (RTX 3090):

```bash
ollama pull qwen2.5-coder:32b
```

If you are using the bundled Ollama profile instead of host Ollama:

```bash
docker compose exec ollama ollama pull qwen2.5-coder:32b
```

## 6. Create a Local Development JWT (Optional)

Most `/v1/*` endpoints require authentication. You can sign in from the UI, or mint a JWT directly using the same `JWT_SECRET` used by the API.

```bash
docker compose exec -T api python -c "import os,time,jwt; now=int(time.time()); payload={'sub':'local-admin','scopes':['admin','agents:read','agents:write','agents:invoke','workflows:read','workflows:write','workflows:execute','tools:execute'],'iat':now,'exp':now+3600}; print(jwt.encode(payload, os.getenv('JWT_SECRET','change-me-in-production'), algorithm=os.getenv('JWT_ALGORITHM','HS256')))"
```

Set it in your shell:

```bash
export TOKEN="<paste-token-here>"
```

PowerShell:

```powershell
$env:TOKEN = "<paste-token-here>"
```

## 7. Verify Protected Access

```bash
curl http://localhost:8000/v1/agents/ \
  -H "Authorization: Bearer $TOKEN"
```

## 8. First Chat Completion

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3.2:3b",
    "messages": [
      {"role": "user", "content": "Say hello from AGENT-33"}
    ]
  }'
```

## Local Python Development (Without Full Compose)

Run infrastructure containers only:

```bash
cd engine
docker compose up -d postgres redis nats
```

Install runtime locally:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
```

Point the app at localhost services:

```bash
export OLLAMA_BASE_URL=http://localhost:11434
export DATABASE_URL=postgresql+asyncpg://agent33:agent33@localhost:5432/agent33
export REDIS_URL=redis://localhost:6379/0
export NATS_URL=nats://localhost:4222
```

Run API:

```bash
uvicorn agent33.main:app --reload --host 0.0.0.0 --port 8000
```

## Known Setup Constraints

- **Default bootstrap auth (`admin/admin`) is for local setup convenience only; you must disable it in production and non-local environments.** Leaving bootstrap auth enabled with default credentials on a public-facing deployment is a critical security risk.
- Several services are in-memory by design (workflow registry, review/release/evaluation/autonomy/improvement/traces) and reset on process restart.
- Webhook endpoints return `503` until adapters are registered in-process.

## Troubleshooting

- `401 Missing authentication credentials`:
  - Ensure `Authorization: Bearer <token>` is present.
- `403 Missing required scope`:
  - Mint a token with the required scope (see `docs/api-surface.md`).
- `503 Ollama unavailable` on chat/agent calls:
  - Verify your Ollama endpoint in `.env` is reachable and the model is pulled.
- `503 Memory system not initialized`:
  - Check startup logs for Postgres/embedding initialization errors.
- `409` state transition errors (review/release/autonomy flows):
  - Transition only through supported lifecycle states.

Continue with [Walkthroughs](walkthroughs.md).
