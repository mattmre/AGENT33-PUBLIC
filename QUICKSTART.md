# AGENT-33 Quickstart

This is the five-minute path from a clean checkout to a running AGENT-33 stack and
a successful health check. It uses Docker Compose and the bundled `.env.example`
defaults. For full installation options (bare metal, Kubernetes, lite mode,
profiles), see [INSTALL.md](./INSTALL.md).

## Prerequisites

You need:

- **Docker** 24+ with the **Compose** plugin (`docker compose version` works).
- About **4 GB of free RAM** and **10 GB of disk**.
- Outbound HTTPS to pull container images (`postgres`, `redis`, `nats`,
  `searxng`, and the AGENT-33 image).

A local LLM is optional. The defaults expect Ollama on the host at port 11434. If
you do not have Ollama, you can run AGENT-33 against OpenAI, OpenRouter, or any
other OpenAI-compatible endpoint; see step 4.

## 1. Clone the repository

```bash
git clone https://github.com/mattmre/AGENT33-PUBLIC.git agent33
cd agent33
```

The runtime lives under `engine/`. All Docker Compose commands run from there.

## 2. Copy the example environment

```bash
cd engine
cp .env.example .env
```

This writes the bundled defaults to `.env`. The file is git-ignored. Edit it
before any non-local use; the bootstrap admin password defaults to `admin` and
the JWT secret is a placeholder.

At minimum, change these three lines in `.env` before you expose the API to
anyone else:

```bash
JWT_SECRET=<paste a random 64-char string>
AUTH_BOOTSTRAP_ADMIN_PASSWORD=<your own admin password>
API_SECRET_KEY=<another random string>
```

You can generate suitable values with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

If you prefer, run `agent33 bootstrap --output .env.local` after step 6 instead.
That command generates a `.env.local` with secure random secrets.

## 3. Bring up the stack

```bash
docker compose up -d
```

Compose starts these services:

| Service  | Port  | Purpose                                  |
|----------|-------|------------------------------------------|
| api      | 8000  | AGENT-33 FastAPI engine                  |
| frontend | 3000  | Control-plane React UI                   |
| postgres | 5432  | Application data + pgvector              |
| redis    | 6379  | Cache and rate-limit window              |
| nats     | 4222  | Messaging bus                            |
| searxng  | 8888  | Privacy-respecting web search backend    |

The first build takes a few minutes while images are pulled and the engine layer
is built. Subsequent starts are quick.

## 4. (Optional) Wire up an LLM

The default configuration looks for Ollama on the Docker host. If you already
have Ollama running with at least one model:

```bash
ollama pull llama3.2:3b
```

If you would rather use a cloud provider, set one or more of the following in
`.env` and restart with `docker compose up -d`:

```bash
# OpenAI-compatible
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
DEFAULT_MODEL=gpt-4o-mini

# OpenRouter
OPENROUTER_API_KEY=sk-or-...
DEFAULT_MODEL=openrouter/auto
```

A single working provider is enough. AGENT-33 will route to whichever one is
configured.

## 5. Check health

```bash
curl http://localhost:8000/health
```

A successful response looks roughly like:

```json
{
  "status": "healthy",
  "services": {
    "postgres": "ok",
    "redis": "ok",
    "nats": "ok",
    "ollama": "ok"
  },
  "required_services": {
    "postgres": "ok",
    "redis": "ok",
    "nats": "ok",
    "ollama": "ok"
  }
}
```

If `status` is `"degraded"`, inspect the `services` map. The most common cause is
that Ollama is unreachable or has no model installed; see
[docs/troubleshooting.md](docs/troubleshooting.md).

## 6. Get a token and try the API

Use the bootstrap admin account to mint a JWT:

```bash
curl -X POST http://localhost:8000/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}'
```

Export the returned `access_token`:

```bash
export TOKEN="<paste access_token>"
```

List available agents:

```bash
curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:8000/v1/agents/search
```

Invoke the bundled `researcher` agent:

```bash
curl -X POST http://localhost:8000/v1/agents/researcher/invoke \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"inputs":{"query":"What is AGENT-33?"}}'
```

## 7. Try the control plane UI

Open `http://localhost:3000` in a browser. Log in with the bootstrap admin
credentials. You should see dashboards for agents, workflows, packs, traces, and
the improvement queue.

## 8. Run a built-in workflow

Eight workflow templates ship in `core/templates/`. The control plane lets you
import them, or you can submit one through the CLI once it is installed:

```bash
pip install -e ".[dev]"           # installs the agent33 CLI
agent33 run research-assistant \
  --inputs '{"topic":"agent control planes","depth":"brief"}'
```

## 9. Tear down

```bash
docker compose down            # keeps your data
docker compose down -v         # also wipes Postgres / Redis volumes
```

## Where to next?

- A guided narrative walk-through is in
  [docs/getting-started.md](docs/getting-started.md).
- The full operator manual is in [docs/operator-manual.md](docs/operator-manual.md).
- Configuration reference: [docs/configuration.md](docs/configuration.md).
- All install paths: [INSTALL.md](INSTALL.md).

If anything fails during these steps, jump straight to
[docs/troubleshooting.md](docs/troubleshooting.md).
