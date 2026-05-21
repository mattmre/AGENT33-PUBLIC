# AGENT-33 Engine

Runtime implementation for AGENT-33.

This package provides:

- FastAPI API server (`agent33.main:app`)
- Agent registry and runtime invocation
- Workflow execution engine
- Memory/RAG stack (pgvector + BM25 hybrid)
- Review, trace, evaluation, autonomy, release, and improvement services
- Tool and code-execution framework

## Start the Runtime

```bash
cd engine
cp .env.example .env
docker compose up -d
curl http://localhost:8000/health
```

`/health` reports the dependencies required by the current runtime configuration.
Inactive providers stay visible as `configured`/`unconfigured`, while `/readyz`
only gates on the services the running stack actually needs.

By default, AGENT-33 expects Ollama to be available at `http://host.docker.internal:11434`
so one shared Ollama instance can be reused across repos.

If you want a bundled Ollama service for this stack instead:

```bash
docker compose --profile local-ollama up -d ollama
docker compose exec ollama ollama pull llama3.2:3b
```

If your Ollama is running in another compose project/network (for example upstream agent OS),
run with the shared-network override:

```bash
docker compose -f docker-compose.yml -f docker-compose.shared-ollama.yml up -d
```

This points API calls at `shared-ollama:11434` on `shared_ollama_default` by default.

If `EMBEDDING_PROVIDER=ollama`, make sure the configured embedding model is
available in Ollama (for example `ollama pull nomic-embed-text`) or `/health`
and `/readyz` will stay degraded.

## Frontend (Control Plane UI)

The compose stack includes the AGENT-33 frontend at:

- `http://localhost:3000`

First-run local login (from `.env.example` defaults):

- username: `admin`
- password: `admin`

**⚠️ Security Warning:** The bootstrap authentication (`admin/admin`) is for local development only. **Do not use these credentials in production or on public-facing deployments.** For production or VPS environments, disable bootstrap auth by setting `AUTH_BOOTSTRAP_ENABLED=false` in your `.env` file and configure a proper identity provider or secure token issuing mechanism.

After login, use the UI domain workspace to run all API features (agents, workflows, memory,
reviews, traces, evaluations, autonomy, releases, improvements, dashboard, training, webhooks).

## Local Development

```bash
cd engine
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
uvicorn agent33.main:app --reload --host 0.0.0.0 --port 8000
```

## Devbox (Containerized Tooling)

```bash
cd engine
docker compose --profile dev up -d devbox
docker compose exec devbox bash
```

The `devbox` container mounts the repository at `/workspace` and includes multi-language tooling
(Python, Node.js, Go, Rust), service CLIs, and Docker CLI access via the host Docker socket.

## Test and Lint

```bash
cd engine
pytest
ruff check src/ tests/
```

## Documentation

Canonical docs are in the repository root `docs/` directory:

- `../docs/setup-guide.md`
- `../docs/walkthroughs.md`
- `../docs/use-cases.md`
- `../docs/functionality-and-workflows.md`
- `../docs/api-surface.md`

## Operational Notes

- Most `/v1/*` routes require auth; only health/docs/login routes are public.
- Several services are in-memory and reset on restart (workflow/review/evaluation/release/autonomy/improvement/traces).
- Webhook adapters must be registered in-process before `/v1/webhooks/*` endpoints are usable.
- Training routes exist, but full runtime wiring for `training_runner` and `agent_optimizer` is partial by default.
