# Getting Started

This guide walks you through installing and running the AGENT-33 engine from scratch, verifying the installation, creating your first agent and workflow, and using the CLI.

## Prerequisites

| Tool | Minimum Version | Check Command | Notes |
|---|---|---|---|
| **Docker** | 24.0+ | `docker --version` | Docker Desktop or Docker Engine |
| **Docker Compose** | 2.20+ | `docker compose version` | Included with Docker Desktop; the `docker compose` (v2) plugin is required -- the legacy `docker-compose` binary is not supported |
| **Git** | 2.30+ | `git --version` | Any recent version works |
| **Python** | 3.11+ | `python --version` | Only needed for local development and the CLI; not required when running purely via Docker |
| **pip** | 23.0+ | `pip --version` | Comes with Python; upgrade with `pip install --upgrade pip` |

### Hardware recommendations

- **CPU**: 4+ cores for comfortable parallel workflow execution.
- **RAM**: 16 GB minimum (Ollama alone may consume 4-8 GB depending on the model).
- **GPU**: NVIDIA GPU with CUDA support is strongly recommended for local LLM inference. CPU-only mode works but is significantly slower.
- **Disk**: 20 GB free for Docker images and model weights.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/agent-33/agent-33.git
cd agent-33/engine
```

### 2. Configure environment

```bash
cp .env.example .env
```

The defaults work for local development. For production, edit `.env` and set strong values for:

- `API_SECRET_KEY` -- used for session signing
- `JWT_SECRET` -- used for JWT token signing
- `ENCRYPTION_KEY` -- Fernet key for data-at-rest encryption (generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)

### 3. Start all services

```bash
docker compose up -d
```

This starts five containers:

| Container | Image | Purpose |
|---|---|---|
| `api` | Custom (built from `Dockerfile`) | FastAPI application server |
| `ollama` | `ollama/ollama:latest` | Local LLM inference |
| `postgres` | `pgvector/pgvector:pg16` | PostgreSQL with pgvector extension |
| `redis` | `redis:7-alpine` | Caching and session state |
| `nats` | `nats:2-alpine` | Internal event bus (JetStream) |

Wait about 15-30 seconds for PostgreSQL and Redis health checks to pass before the API becomes available.

### 4. Pull a model

Recommended path:

```bash
python -m agent33.cli.main wizard
```

The wizard can start a local or bundled Ollama service automatically and download the recommended model for your hardware.

Manual fallback:

```bash
docker compose exec ollama ollama pull llama3.2
```

This downloads the Llama 3.2 model (approximately 2 GB). You can substitute any model supported by Ollama (e.g., `mistral`, `codellama`, `phi3`).

To list available models after pulling:

```bash
docker compose exec ollama ollama list
```

## Verifying the Installation

### Health check

```bash
curl http://localhost:8000/health
```

Expected response when all services are healthy:

```json
{
  "status": "healthy",
  "services": {
    "ollama": "ok",
    "redis": "ok",
    "postgres": "ok",
    "nats": "ok"
  }
}
```

If any service shows `"unavailable"` or `"degraded"`, the overall status will be `"degraded"`. Check the relevant container logs:

```bash
docker compose logs <service-name>
```

### API documentation

The auto-generated OpenAPI documentation is available at:

- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

These endpoints are publicly accessible (no authentication required).

## First Agent Invocation

### 1. Create an agent definition

Create the file `agent-definitions/greeter.json`:

```json
{
  "name": "greeter",
  "version": "1.0.0",
  "role": "worker",
  "description": "A simple agent that greets the user",
  "capabilities": [],
  "inputs": {
    "name": {
      "type": "string",
      "description": "Name of the person to greet",
      "required": true
    }
  },
  "outputs": {
    "greeting": {
      "type": "string",
      "description": "The greeting message"
    }
  },
  "prompts": {
    "system": "You are a friendly greeter. Given a name, produce a warm greeting.",
    "user": "Please greet {{ name }}."
  },
  "constraints": {
    "max_tokens": 256,
    "timeout_seconds": 30
  }
}
```

### 2. Restart the API to discover the new agent

```bash
docker compose restart api
```

### 3. Invoke via the chat endpoint

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, Agent-33!"}'
```

Expected response (content will vary based on the model):

```json
{
  "response": "Hello! Welcome to Agent-33. How can I help you today?",
  "model": "llama3.2"
}
```

## First Workflow

### 1. Create a workflow definition

Create the file `workflow-definitions/hello-world.json`:

```json
{
  "name": "hello-world",
  "version": "1.0.0",
  "description": "A minimal workflow that invokes the greeter agent",
  "triggers": {
    "manual": true
  },
  "inputs": {
    "name": {
      "type": "string",
      "description": "Who to greet",
      "required": true,
      "default": "World"
    }
  },
  "steps": [
    {
      "id": "greet",
      "name": "Greet the user",
      "action": "invoke-agent",
      "agent": "greeter",
      "inputs": {
        "name": "{{ name }}"
      }
    }
  ],
  "execution": {
    "mode": "sequential"
  }
}
```

### 2. Execute the workflow

Using the CLI:

```bash
agent33 run hello-world --inputs '{"name": "Alice"}'
```

Or via the API:

```bash
curl -X POST http://localhost:8000/api/v1/workflows/hello-world/execute \
  -H "Content-Type: application/json" \
  -d '{"name": "Alice"}'
```

### 3. Inspect the results

The workflow response includes step-level detail:

```json
{
  "outputs": {
    "greeting": "Hello, Alice! Welcome aboard."
  },
  "steps_executed": ["greet"],
  "step_results": [
    {
      "step_id": "greet",
      "status": "success",
      "outputs": {"greeting": "Hello, Alice! Welcome aboard."},
      "error": null,
      "duration_ms": 1523.45
    }
  ],
  "duration_ms": 1530.12,
  "status": "success"
}
```

## Using the CLI

Install the CLI in development mode:

```bash
cd engine
pip install -e ".[dev]"
```

The `agent33` command provides four subcommands:

### `agent33 status`

Check the health of all engine services.

```bash
$ agent33 status
Engine Status: healthy
  ollama:   ok
  redis:    ok
  postgres: ok
  nats:     ok
```

### `agent33 init <name> --kind <agent|workflow>`

Scaffold a new agent or workflow definition with a template.

```bash
# Create a new agent definition
agent33 init my-researcher --kind agent
# Creates agent-definitions/my-researcher.json

# Create a new workflow definition
agent33 init data-pipeline --kind workflow
# Creates workflow-definitions/data-pipeline.json
```

### `agent33 run <workflow> --inputs '<json>'`

Execute a workflow by name, passing JSON inputs.

```bash
agent33 run hello-world --inputs '{"name": "Bob"}'
```

### `agent33 <other commands>`

Run `agent33 --help` to see all available commands and options.

## Next Steps

- [Architecture Overview](architecture.md) -- component diagram, data flow, extension points
- [API Reference](api-reference.md) -- detailed endpoint documentation
- [Contributing Guide](contributing.md) -- development setup, testing, code style, PR process

## Troubleshooting

### Ollama not responding

**Symptom**: Health check shows `"ollama": "unavailable"`.

**Possible causes and fixes**:

1. The Ollama container has not finished starting. Wait 10-15 seconds and retry.
2. No model has been pulled yet. Run `docker compose exec ollama ollama pull llama3.2`.
3. The container crashed due to insufficient memory. Check logs with `docker compose logs ollama` and ensure you have at least 8 GB of RAM available.
4. On systems without NVIDIA GPUs, the `deploy.resources.reservations.devices` section in `docker-compose.yml` may cause the container to fail. Remove or comment out the GPU reservation block if you are running on CPU only.

### GPU not detected

**Symptom**: Ollama runs but inference is very slow.

**Possible causes and fixes**:

1. NVIDIA Container Toolkit is not installed. Follow the [NVIDIA Container Toolkit installation guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
2. Verify GPU access from inside Docker: `docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi`.
3. On Windows with WSL2, ensure your NVIDIA drivers are up to date and WSL2 GPU support is enabled.

### Port conflicts

**Symptom**: `docker compose up` fails with "port is already allocated".

**Fix**: Change the host port in your `.env` file:

```bash
API_PORT=8001
POSTGRES_PORT=5433
REDIS_PORT=6380
NATS_PORT=4223
OLLAMA_PORT=11435
```

Then restart: `docker compose down && docker compose up -d`.

### Database connection refused

**Symptom**: API logs show `Connection refused` for PostgreSQL.

**Fix**: The API container waits for the PostgreSQL health check, but the check may not pass fast enough on slower machines. Run `docker compose restart api` once PostgreSQL is healthy (`docker compose ps` should show `healthy` for the postgres service).

### Python version mismatch

**Symptom**: `pip install -e ".[dev]"` fails with syntax errors.

**Fix**: AGENT-33 requires Python 3.11 or later. Verify with `python --version`. If you have multiple Python versions, use `python3.11 -m venv .venv` explicitly.
