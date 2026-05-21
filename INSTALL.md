# Installing AGENT-33

This guide covers every supported installation path and the configuration you
need afterwards. If you just want a stack running fast, read
[QUICKSTART.md](./QUICKSTART.md) first.

- [System requirements](#system-requirements)
- [Path A: Docker Compose](#path-a-docker-compose-recommended)
- [Path B: Bare-metal Python](#path-b-bare-metal-python)
- [Path C: Kubernetes](#path-c-kubernetes)
- [Path D: Lite mode (single binary)](#path-d-lite-mode-single-binary)
- [Post-install configuration](#post-install-configuration)
- [Verifying the install](#verifying-the-install)
- [Troubleshooting installs](#troubleshooting-installs)

## System requirements

| Component   | Minimum                                | Recommended           |
|-------------|----------------------------------------|-----------------------|
| OS          | Linux, macOS, or Windows 11 + WSL2     | Linux                 |
| Python      | 3.11                                   | 3.11 or 3.12          |
| Docker      | 24.x with the Compose plugin           | latest                |
| RAM         | 4 GB                                   | 8 GB+                 |
| Disk        | 10 GB                                  | 30 GB+ (for models)   |
| Postgres    | 16 (with `pgvector` extension)         | bundled by Compose    |
| Redis       | 7                                      | bundled by Compose    |
| NATS        | 2.x with JetStream                     | bundled by Compose    |
| LLM backend | Ollama, llama.cpp, or an API provider  | local Ollama + cloud  |

The Docker Compose path bundles all infrastructure dependencies; you only need
the Docker engine itself. The bare-metal path expects you to provide Postgres,
Redis, NATS, and a model backend yourself.

Optional features have additional requirements:

- **GPU inference** (AirLLM): NVIDIA GPU with CUDA 12+ and `nvidia-container-toolkit`.
- **PDF ingestion**: PyMuPDF + pdfplumber (install via `pip install -e ".[pdf]"`).
- **OCR**: Tesseract installed on the host (`apt-get install tesseract-ocr`).
- **Browser automation**: Playwright (`pip install -e ".[browser]"` then
  `playwright install`).

## Path A: Docker Compose (recommended)

This is the fastest, most reproducible install for individuals and teams.

```bash
git clone https://github.com/mattmre/AGENT33-PUBLIC.git
cd AGENT33-PUBLIC/engine
cp .env.example .env

# Bring up the whole stack
docker compose up -d
```

By default, Compose starts:

- `api` (the FastAPI engine, port 8000)
- `frontend` (control-plane UI, port 3000)
- `postgres` (with `pgvector`)
- `redis`
- `nats` (with JetStream enabled)
- `searxng` (used by the bundled web-search tool)

### Profiles

Several services are gated behind Compose profiles so they only run when you ask
for them. Activate them with the `--profile` flag:

| Profile         | Adds                                                | Use case                          |
|-----------------|-----------------------------------------------------|-----------------------------------|
| `local-ollama`  | `ollama` container (GPU required)                   | Self-host LLMs in-cluster         |
| `dev`           | `devbox` interactive sidecar                        | Editing inside the container      |
| `agent-os`      | `agent-os` headless agent runner                    | Multi-agent OS sessions           |
| `integrations`  | `n8n` workflow automation                           | Connect external SaaS             |
| `gpu`           | `airllm` layer-sharded large-model worker           | Run 70B+ models locally           |

Example:

```bash
docker compose --profile local-ollama up -d
```

### Production Compose overlay

`engine/docker-compose.prod.yml` adds resource limits, restart policies, and
read-only volume mounts suitable for a single-host production deployment. Layer
it on top of the default file:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

See [docs/operators/production-deployment-runbook.md](docs/operators/production-deployment-runbook.md)
for hardening guidance.

## Path B: Bare-metal Python

Use this when you already run Postgres / Redis / NATS, or want the engine in a
process supervisor without Docker.

### 1. Install Python 3.11+

The engine refuses to start on older interpreters.

```bash
python --version       # must be >= 3.11
```

### 2. Create a virtual environment

From the repository root:

```bash
cd engine
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\Activate.ps1
```

### 3. Install the package

For a development install (editable, with test/lint tooling):

```bash
pip install -e ".[dev]"
```

For a production install with optional extras:

```bash
pip install -e ".[standard,messaging,reader,tokenizer]"
```

Available extras:

| Extra         | Pulls in                                                          |
|---------------|-------------------------------------------------------------------|
| `lite`        | SQLite, fakeredis, rank-bm25 (single-process mode)                |
| `standard`    | Postgres + Redis + NATS clients, sentence-transformers            |
| `enterprise`  | Kubernetes client, Prometheus client, OpenTelemetry               |
| `messaging`   | Telegram, Discord, Slack adapters                                 |
| `browser`     | Playwright                                                        |
| `reader`      | Trafilatura (HTML to text)                                        |
| `gpu`         | AirLLM, Torch, Transformers, Accelerate                           |
| `pdf`         | PyMuPDF, pdfplumber                                               |
| `ocr`         | Pillow, pytesseract                                               |
| `tokenizer`   | tiktoken                                                          |
| `telemetry`   | OpenTelemetry API                                                 |
| `jupyter`     | jupyter_client, jupyter_core, ipykernel                           |
| `dev`         | pytest, ruff, mypy, and friends                                   |

### 4. Provide infrastructure

Set `DATABASE_URL`, `REDIS_URL`, and `NATS_URL` in your environment so the
engine can find them. The default values in `.env.example` assume the Compose
stack; on bare metal you typically point at your own services:

```bash
export DATABASE_URL="postgresql+asyncpg://agent33:CHANGE_ME@db.example.com:5432/agent33"
export REDIS_URL="redis://redis.example.com:6379/0"
export NATS_URL="nats://nats.example.com:4222"
```

Postgres requires the `pgvector` extension. The engine creates the schema and
extension on first startup if your role has `CREATE EXTENSION` rights. If it
does not, apply migrations manually:

```bash
alembic upgrade head
```

### 5. Run the server

```bash
agent33 start --host 0.0.0.0 --port 8000
```

Or, for development with auto-reload:

```bash
uvicorn agent33.main:app --reload --host 0.0.0.0 --port 8000
```

## Path C: Kubernetes

Production Kubernetes manifests ship in `deploy/k8s/`. They use Kustomize and
include base resources plus a `production` overlay.

```bash
cd deploy/k8s
kubectl apply -k base                  # baseline deployment
kubectl apply -k overlays/production   # production-hardened overlay
```

The base manifests deploy:

- `api` Deployment with HPA, PDB, and Ingress
- `postgres` StatefulSet with `pgvector`
- `redis` Deployment
- `nats` Deployment
- `ollama` Deployment with a PersistentVolumeClaim
- `searxng` Deployment
- All required Services and a Namespace

Before you `apply`, copy the example Secrets and ConfigMap and edit them to suit
your cluster:

```bash
cp base/api-secret.example.yaml base/api-secret.yaml
cp base/postgres-secret.example.yaml base/postgres-secret.yaml
# Edit each file: replace placeholder values with real secrets
```

Add the two new files to `base/kustomization.yaml` if they are not already
listed. See [deploy/k8s/base/README.md](deploy/k8s/base/README.md) and
[deploy/k8s/overlays/production/README.md](deploy/k8s/overlays/production/README.md)
for the full topology and hardening notes.

### Helm

A Helm chart is not yet shipped. Use Kustomize for now or wrap the manifests in
your own chart.

## Path D: Lite mode (single binary)

For single-user, laptop, or CI scenarios where you do not want Postgres /
Redis / NATS, AGENT-33 supports a "lite" mode that swaps the production stack
for SQLite + in-process fakes.

```bash
pip install "agent33[lite]"
export AGENT33_MODE=lite
export AGENT33_PROFILE=minimal       # optional, applies a curated lite preset
agent33 start
```

In lite mode:

- Long-term memory uses SQLite at `var/agent33_memory.db` (configurable via
  `SQLITE_MEMORY_DB_PATH`).
- Redis is replaced by `fakeredis` in-process.
- NATS is optional; messaging adapters that need it become no-ops.
- JWT secrets are auto-generated and logged with a warning.

Lite mode is appropriate for evaluation, demos, and CI; do not run untrusted
multi-tenant traffic against it.

## Post-install configuration

After any path above, edit your `.env` (or your Kubernetes Secret) to lock down
defaults that are insecure on purpose:

```bash
JWT_SECRET=<random 64+ char string>
API_SECRET_KEY=<another random string>
AUTH_BOOTSTRAP_ADMIN_PASSWORD=<your own admin password>
ENVIRONMENT=production
```

The full reference is in [docs/configuration.md](docs/configuration.md). The
high-impact knobs are:

- **`AGENT33_MODE`** — `lite`, `standard`, or `enterprise`.
- **`AGENT33_PROFILE`** — applies a curated preset (`minimal`, `developer`,
  `production`, `enterprise`, `airgapped`).
- **`DEFAULT_MODEL`** — the model the chat surface and most agents will use.
- **`CORS_ALLOWED_ORIGINS`** — comma-separated list; empty by default means no
  browser can talk to the API.
- **`TOOL_USE_MODE`** — `audit` (default), `dry-run`, or `approved`.

For multi-environment setups, run `agent33 start --profile production` (or
similar) so a single env file can serve dev and prod with one variable flip.

## Verifying the install

```bash
# Health check
curl http://localhost:8000/health

# Authenticated CLI status
TOKEN=$(curl -s -X POST http://localhost:8000/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | jq -r .access_token)

agent33 status --base-url http://localhost:8000

# Diagnostic checks (Python, ports, infra, models)
agent33 diagnose
```

`agent33 diagnose --fix` will auto-remediate safe issues (creating missing
directories, regenerating placeholder secrets in lite mode, etc.).

## Troubleshooting installs

Common install-time failures and where to look:

| Symptom                                            | Likely cause                                             | Fix                                                                                          |
|----------------------------------------------------|----------------------------------------------------------|----------------------------------------------------------------------------------------------|
| `docker compose up` hangs at `frontend` build      | Pulling Node dependencies on slow link                   | Wait, or `docker compose build --pull api` separately                                        |
| `/health` shows `postgres: unavailable`            | Postgres role lacks `CREATE EXTENSION` for `pgvector`    | Run `CREATE EXTENSION vector;` as a superuser                                                |
| Engine logs `database_init_failed`                 | `DATABASE_URL` wrong driver or wrong host                | Must start with `postgresql+asyncpg://`                                                      |
| `agent33` not found after `pip install -e .`       | Virtualenv not active                                    | `source .venv/bin/activate`                                                                  |
| `JWT_SECRET` warning: "FATAL: Refusing to start"   | Production env with the default secret                   | Set `JWT_SECRET` to a random 64-char value                                                   |
| `ollama: degraded`                                 | Model declared in `OLLAMA_DEFAULT_MODEL` not pulled      | `ollama pull llama3.2:3b`                                                                    |
| Windows: `agent33 wizard` cannot find `python`     | Python is not on PATH                                    | Reinstall Python and tick "Add to PATH"                                                      |

The longer reference is in [docs/troubleshooting.md](docs/troubleshooting.md).

## See also

- [QUICKSTART.md](QUICKSTART.md) — five-minute Docker path
- [docs/getting-started.md](docs/getting-started.md) — narrative tutorial
- [docs/configuration.md](docs/configuration.md) — every env var
- [docs/operator-manual.md](docs/operator-manual.md) — day-2 operations
- [docs/upgrade-guide.md](docs/upgrade-guide.md) — moving between versions
