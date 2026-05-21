# AGENT-33 Integration Guide

This guide covers how to connect AGENT-33 to LLM providers, messaging platforms, external systems, and how to extend the platform with plugins and custom tools.

---

## Table of Contents

- [Connecting to LLM Providers](#connecting-to-llm-providers)
- [Messaging Platform Integration](#messaging-platform-integration)
- [NATS Message Bus](#nats-message-bus)
- [Plugin Development](#plugin-development)
- [Tool Development](#tool-development)
- [Database Integration](#database-integration)
- [External System Integration](#external-system-integration)
- [Using AGENT-33 from Other Projects](#using-agent-33-from-other-projects)
- [CI/CD Integration](#cicd-integration)

---

## Connecting to LLM Providers

AGENT-33 supports multiple LLM providers through a unified protocol and a model router that dispatches requests based on model name prefixes.

**Source files:** `llm/base.py`, `llm/ollama.py`, `llm/openai.py`, `llm/router.py`

### Ollama Setup (Default Provider)

Ollama is the default and primary LLM provider. It runs as a container in the Docker Compose stack.

**Environment variables:**

| Variable              | Default                    | Description                  |
|-----------------------|----------------------------|------------------------------|
| `OLLAMA_BASE_URL`     | `http://ollama:11434`      | Ollama API base URL          |
| `OLLAMA_DEFAULT_MODEL`| `llama3.2`                 | Default model for completions|

**Usage:**

```python
from agent33.llm.ollama import OllamaProvider
from agent33.llm.base import ChatMessage

provider = OllamaProvider(
    base_url="http://localhost:11434",
    default_model="llama3.2",
    timeout=120.0,
)

response = await provider.complete(
    messages=[ChatMessage(role="user", content="Hello")],
    model="llama3.2",       # Optional, falls back to default_model
    temperature=0.7,
    max_tokens=500,         # Maps to Ollama's num_predict
)
print(response.content)
print(response.prompt_tokens, response.completion_tokens)

# List available models
models = await provider.list_models()
```

Both `complete` and `list_models` use exponential-backoff retry (3 attempts, delays of 1s, 2s, 4s).

### OpenAI-Compatible APIs

The `OpenAIProvider` works with OpenAI and any OpenAI-compatible API (LiteLLM, vLLM, Azure OpenAI, etc.).

**Environment variables:**

| Variable           | Default                     | Description               |
|--------------------|-----------------------------|---------------------------|
| `OPENAI_API_KEY`   | (empty)                     | API key for authentication|
| `OPENAI_BASE_URL`  | `https://api.openai.com/v1` | API base URL              |

**Usage:**

```python
from agent33.llm.openai import OpenAIProvider
from agent33.llm.base import ChatMessage

provider = OpenAIProvider(
    api_key="sk-...",
    base_url="https://api.openai.com/v1",  # Or any compatible endpoint
    default_model="gpt-4o",
    timeout=120.0,
)

response = await provider.complete(
    messages=[ChatMessage(role="user", content="Hello")],
    model="gpt-4o",
    temperature=0.7,
    max_tokens=1000,
)
```

**Examples of compatible endpoints:**

- OpenAI: `https://api.openai.com/v1`
- Azure OpenAI: `https://{resource}.openai.azure.com/openai/deployments/{deployment}`
- LiteLLM proxy: `http://localhost:4000/v1`
- vLLM: `http://localhost:8000/v1`

### Adding a Custom Provider

Implement the `LLMProvider` protocol:

```python
from agent33.llm.base import LLMProvider, LLMResponse, ChatMessage

class MyCustomProvider:
    """Custom LLM provider."""

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        # Call your LLM API here
        content = await self._call_api(messages, model, temperature, max_tokens)
        return LLMResponse(
            content=content,
            model=model,
            prompt_tokens=0,
            completion_tokens=0,
        )

    async def list_models(self) -> list[str]:
        return ["my-model-v1", "my-model-v2"]
```

The protocol is `@runtime_checkable`, so `isinstance(obj, LLMProvider)` works at runtime.

### Model Router

The `ModelRouter` dispatches completion requests to the correct provider based on model name prefixes.

```python
from agent33.llm.router import ModelRouter
from agent33.llm.ollama import OllamaProvider
from agent33.llm.openai import OpenAIProvider

router = ModelRouter()
router.register("ollama", OllamaProvider(base_url="http://ollama:11434"))
router.register("openai", OpenAIProvider(api_key="sk-..."))

# Automatic routing based on model name prefix
response = await router.complete(
    messages=[ChatMessage(role="user", content="Hello")],
    model="gpt-4o",       # Routed to "openai" (prefix "gpt-")
)

response = await router.complete(
    messages=[ChatMessage(role="user", content="Hello")],
    model="llama3.2",     # Routed to "ollama" (default provider)
)
```

**Default prefix routing rules:**

| Model Prefix | Provider  | Notes                              |
|--------------|-----------|------------------------------------|
| `gpt-`       | `openai`  | OpenAI GPT models                  |
| `o1`         | `openai`  | OpenAI o1 reasoning models         |
| `o3`         | `openai`  | OpenAI o3 reasoning models         |
| `claude-`    | `openai`  | Anthropic via OpenAI-compatible proxy |
| `ft:gpt-`    | `openai`  | Fine-tuned GPT models              |
| (no match)   | `ollama`  | Default fallback provider          |

Custom prefix rules can be passed to the `ModelRouter` constructor:

```python
router = ModelRouter(
    prefix_map=[
        ("mistral-", "my_provider"),
        ("gpt-", "openai"),
    ],
    default_provider="ollama",
)
```

---

## Messaging Platform Integration

AGENT-33 provides adapters for Telegram, Discord, Slack, and WhatsApp. All adapters implement the `MessagingAdapter` protocol with a unified interface.

**Source files:** `messaging/base.py`, `messaging/models.py`, `messaging/telegram.py`, `messaging/discord.py`, `messaging/slack.py`, `messaging/whatsapp.py`, `messaging/pairing.py`

### MessagingAdapter Protocol

Every adapter implements:

```python
class MessagingAdapter(Protocol):
    @property
    def platform(self) -> str: ...           # e.g. "telegram"
    async def send(self, channel_id: str, text: str) -> None: ...
    async def receive(self) -> Message: ...  # Blocks until next message
    async def start(self) -> None: ...       # Open connections
    async def stop(self) -> None: ...        # Graceful shutdown
```

### Message Model

All inbound messages are normalized to a common `Message` model:

```python
class Message(BaseModel):
    platform: str                    # "telegram", "discord", "slack", "whatsapp"
    channel_id: str                  # Platform-specific channel/chat ID
    user_id: str                     # Platform-specific user ID
    text: str                        # Message text content
    timestamp: datetime              # UTC timestamp
    metadata: dict[str, Any] = {}    # Raw platform payload under "raw" key
```

### Telegram

**Requirements:** A Telegram Bot Token from [@BotFather](https://t.me/BotFather).

```python
from agent33.messaging.telegram import TelegramAdapter

adapter = TelegramAdapter(token="123456:ABC-DEF...")
await adapter.start()    # Begins long-polling for updates

# Send a message
await adapter.send(channel_id="123456789", text="Hello from AGENT-33")

# Receive messages (blocks until available)
msg = await adapter.receive()
print(msg.text, msg.user_id, msg.channel_id)

await adapter.stop()
```

**Webhook mode:** Instead of long-polling, you can push updates via webhook:

```python
adapter.enqueue_webhook_update(payload)  # Raw Telegram update JSON
```

Messages are sent with Markdown parse mode enabled.

### Discord

**Requirements:** A Discord Bot Token and Application Public Key from the [Discord Developer Portal](https://discord.com/developers/applications).

```python
from agent33.messaging.discord import DiscordAdapter

adapter = DiscordAdapter(
    bot_token="MTIz...",
    public_key="abc123...",
)
await adapter.start()

await adapter.send(channel_id="1234567890", text="Hello from AGENT-33")

# Enqueue interactions from webhook
adapter.enqueue_interaction(payload)  # Discord interaction JSON

# Verify webhook signature (Ed25519, requires PyNaCl)
is_valid = adapter.verify_signature(signature, timestamp, body)

await adapter.stop()
```

The adapter uses the Discord REST API v10. It processes `APPLICATION_COMMAND` (type 2) and `MESSAGE_COMPONENT` (type 3) interactions. Slash command options are joined as `name=value` pairs in the message text.

### Slack

**Requirements:** A Slack Bot Token (`xoxb-...`) and Signing Secret from [api.slack.com/apps](https://api.slack.com/apps).

```python
from agent33.messaging.slack import SlackAdapter

adapter = SlackAdapter(
    bot_token="xoxb-...",
    signing_secret="abc123...",
)
await adapter.start()

await adapter.send(channel_id="C01ABCDEF", text="Hello from AGENT-33")

# Enqueue Events API payloads
adapter.enqueue_event(payload)  # Slack event JSON

# Verify request signature (HMAC-SHA256)
is_valid = adapter.verify_signature(timestamp, body, signature)

await adapter.stop()
```

The adapter processes `message` events from the Slack Events API. Bot messages are automatically filtered to prevent feedback loops. Signature verification rejects requests older than 5 minutes.

### WhatsApp

**Requirements:** WhatsApp Business API credentials from the [Meta Developer Portal](https://developers.facebook.com/):
- Access Token
- Phone Number ID
- Verify Token (for webhook setup)
- App Secret (for signature verification)

```python
from agent33.messaging.whatsapp import WhatsAppAdapter

adapter = WhatsAppAdapter(
    access_token="EAAG...",
    phone_number_id="123456789",
    verify_token="my-verify-token",
    app_secret="abc123...",
)
await adapter.start()

# Send to a phone number
await adapter.send(channel_id="+1234567890", text="Hello from AGENT-33")

# Enqueue webhook payloads
adapter.enqueue_webhook_payload(payload)

# Verify webhook signature (X-Hub-Signature-256)
is_valid = adapter.verify_signature(signature_header, body)

# Handle webhook verification challenge
challenge = adapter.verify_webhook_challenge(mode, token, challenge)

await adapter.stop()
```

Uses the Meta Graph API v18.0. Only text messages are processed; media messages are skipped.

### User Pairing

The `PairingManager` links platform users to AGENT-33 accounts using six-digit codes with a 15-minute TTL.

```python
from agent33.messaging.pairing import PairingManager

pairing = PairingManager()
await pairing.start()  # Begins periodic cleanup of expired codes

code = pairing.generate_code(platform="telegram", user_id="123456")
# code -> "482901"

is_valid = pairing.verify_code("482901", user_id="123456")
# True (code is consumed and removed)

await pairing.stop()
```

---

## NATS Message Bus

AGENT-33 uses NATS for internal event routing and cross-service communication.

**Source file:** `messaging/bus.py`

**Environment variable:**

| Variable   | Default              | Description     |
|------------|----------------------|-----------------|
| `NATS_URL` | `nats://nats:4222`   | NATS server URL |

### Basic Usage

```python
from agent33.messaging.bus import NATSMessageBus

bus = NATSMessageBus(url="nats://localhost:4222")
await bus.connect()

# Publish a message
await bus.publish("agent.events.completed", {
    "agent_id": "agent-001",
    "result": "success",
})

# Subscribe to a subject
async def handler(data: dict) -> None:
    print(f"Received: {data}")

await bus.subscribe("agent.events.*", handler)

# Request/reply (5-second default timeout)
reply = await bus.request("agent.status", {"agent_id": "agent-001"}, timeout=5.0)

await bus.close()  # Drains subscriptions first
```

### Subject Naming Convention

Use dot-separated hierarchical subjects:

| Subject Pattern               | Purpose                           |
|-------------------------------|-----------------------------------|
| `agent.events.{event_type}`   | Agent lifecycle events            |
| `workflow.events.{event_type}`| Workflow execution events         |
| `tool.events.{event_type}`    | Tool execution events             |
| `messaging.{platform}.inbound`| Inbound messages from platforms   |
| `messaging.{platform}.outbound`| Outbound messages to platforms  |

NATS wildcards: `*` matches a single token, `>` matches one or more tokens.

### Cross-Service Communication Patterns

**Fan-out (publish/subscribe):**
```python
# Service A publishes
await bus.publish("workflow.events.completed", {"workflow_id": "wf-001"})

# Services B, C, D all receive independently
await bus.subscribe("workflow.events.*", handle_workflow_event)
```

**Request/reply:**
```python
# Service A requests
result = await bus.request("agent.status", {"agent_id": "agent-001"})

# Service B responds (NATS handles reply routing)
async def status_handler(data):
    return {"status": "running"}
```

All messages are JSON-encoded. Errors in handlers are caught and logged without crashing the subscription.

---

## Plugin Development

AGENT-33 discovers plugins via Python setuptools entry points under the `agent33.plugins` group.

**Source file:** `plugins/loader.py`

### Creating a Plugin

1. Create a Python package with a `register` function:

```python
# my_plugin/__init__.py
from agent33.tools.registry import ToolRegistry

def register(registry: ToolRegistry, adapters: dict) -> None:
    """Called by AGENT-33 during plugin discovery."""
    # Register custom tools
    registry.register(MyCustomTool())

    # Optionally register messaging adapters
    adapters["my_platform"] = MyAdapter()
```

2. Declare the entry point in `pyproject.toml`:

```toml
[project.entry-points."agent33.plugins"]
my_plugin = "my_plugin:register"
```

Or in `setup.cfg`:

```ini
[options.entry_points]
agent33.plugins =
    my_plugin = my_plugin:register
```

3. Install the plugin package into the same environment as AGENT-33.

### Plugin Loading

The `PluginLoader` scans entry points and invokes each plugin's `register` function:

```python
from agent33.plugins.loader import PluginLoader
from agent33.tools.registry import ToolRegistry

registry = ToolRegistry()
loader = PluginLoader(tool_registry=registry, adapter_registry={})

count = loader.discover_and_load()
print(f"Loaded {count} plugins: {loader.loaded_plugins}")
```

Plugins that fail to load are logged and skipped without affecting other plugins.

---

## Tool Development

Tools are the primary way AGENT-33 interacts with external systems. All tools implement the `Tool` protocol.

**Source files:** `tools/base.py`, `tools/registry.py`, `tools/governance.py`

### The Tool Protocol

```python
from typing import Any, Protocol

class Tool(Protocol):
    @property
    def name(self) -> str: ...           # Unique identifier

    @property
    def description(self) -> str: ...    # Human-readable description

    async def execute(
        self,
        params: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult: ...
```

### Creating a Custom Tool

```python
from typing import Any
from agent33.tools.base import Tool, ToolContext, ToolResult

class WeatherTool:
    @property
    def name(self) -> str:
        return "weather"

    @property
    def description(self) -> str:
        return "Get current weather for a city."

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        city = params.get("city", "").strip()
        if not city:
            return ToolResult.fail("No city provided")

        # Check domain allowlist if configured
        if context.domain_allowlist:
            if "api.weather.com" not in context.domain_allowlist:
                return ToolResult.fail("Weather API domain not in allowlist")

        try:
            # Your API call here
            weather_data = await fetch_weather(city)
            return ToolResult.ok(f"Weather in {city}: {weather_data}")
        except Exception as exc:
            return ToolResult.fail(f"Weather lookup failed: {exc}")
```

### Registering Tools

```python
from agent33.tools.registry import ToolRegistry

registry = ToolRegistry()

# Manual registration
registry.register(WeatherTool())

# Entry-point discovery (looks for "agent33.tools" group)
count = registry.discover_from_entrypoints()

# Access tools
tool = registry.get("weather")
all_tools = registry.list_all()
```

Entry-point registration in `pyproject.toml`:

```toml
[project.entry-points."agent33.tools"]
weather = "my_package.tools:WeatherTool"
```

### Governance Integration

Wrap tool execution with governance checks for permission enforcement and audit logging:

```python
from agent33.tools.governance import ToolGovernance
from agent33.tools.base import ToolContext

governance = ToolGovernance()

# Optional: map tools to custom scopes
governance.TOOL_SCOPE_MAP["weather"] = "tools:execute"

context = ToolContext(
    user_scopes=["tools:execute"],
    domain_allowlist=["api.weather.com"],
)

# Pre-execution check
if not governance.pre_execute_check("weather", {"city": "London"}, context):
    print("Permission denied")
else:
    result = await tool.execute({"city": "London"}, context)
    governance.log_execution("weather", {"city": "London"}, result)
```

### Built-in Tools

| Tool        | Module                     | Description                              |
|-------------|----------------------------|------------------------------------------|
| `file_ops`  | `tools/builtin/file_ops.py`| Read, write, list files (path allowlist) |
| `web_fetch` | `tools/builtin/web_fetch.py`| HTTP GET/POST (domain allowlist, 5 MB limit) |
| `shell`     | `tools/builtin/shell.py`   | Shell command execution (command allowlist) |
| `browser`   | `tools/builtin/browser.py` | Browser automation                       |

---

## Database Integration

### PostgreSQL with pgvector

AGENT-33 uses PostgreSQL with the pgvector extension for relational data and vector embeddings.

**Environment variable:**

| Variable       | Default                                                    |
|----------------|------------------------------------------------------------|
| `DATABASE_URL` | `postgresql+asyncpg://agent33:agent33@postgres:5432/agent33` |

The Docker Compose stack uses the `pgvector/pgvector:pg16` image, which includes the vector extension pre-installed.

**Connection pattern (async SQLAlchemy):**

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from agent33.config import settings

engine = create_async_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async with SessionLocal() as session:
    result = await session.execute(...)
```

**Using pgvector for embeddings:**

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE embeddings (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    embedding vector(1536)
);

-- Similarity search
SELECT content, embedding <=> '[0.1, 0.2, ...]' AS distance
FROM embeddings
ORDER BY distance
LIMIT 10;
```

### Redis

Redis is used for caching, rate limiting, and ephemeral state.

**Environment variable:**

| Variable    | Default               |
|-------------|-----------------------|
| `REDIS_URL` | `redis://redis:6379/0`|

### Alembic Migrations

For schema migrations, use Alembic with the async SQLAlchemy engine:

```bash
# Initialize (one-time)
cd engine
alembic init -t async alembic

# Create a migration
alembic revision --autogenerate -m "add agents table"

# Apply migrations
alembic upgrade head
```

Configure `alembic.ini` to read `DATABASE_URL` from the environment:

```ini
sqlalchemy.url = %(DATABASE_URL)s
```

---

## External System Integration

### Webhook Triggers with HMAC Verification

All messaging adapters include signature verification. For custom webhooks, follow the same HMAC-SHA256 pattern:

```python
import hashlib
import hmac

def verify_webhook(secret: str, body: bytes, signature: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

### REST API Consumption

Use the `web_fetch` tool or direct `httpx` calls for REST API integration:

```python
import httpx

async with httpx.AsyncClient() as client:
    resp = await client.get("https://api.example.com/data", headers={
        "Authorization": "Bearer token",
    })
    data = resp.json()
```

### Event-Driven Patterns

Combine NATS subscriptions with webhook endpoints for event-driven workflows:

```python
# Receive external webhook -> publish to NATS
@app.post("/webhooks/github")
async def github_webhook(request: Request):
    payload = await request.json()
    await bus.publish("external.github.push", payload)
    return {"ok": True}

# Subscribe to NATS -> trigger agent workflow
await bus.subscribe("external.github.push", async def handler(data):
    await invoke_agent("code-reviewer", data)
)
```

---

## Using AGENT-33 from Other Projects

### REST API Access

AGENT-33 exposes a FastAPI application on port 8000 (configurable via `API_PORT`).

**Authentication:**

```python
import httpx

# Using JWT
headers = {"Authorization": "Bearer eyJhbG..."}

# Using API key
headers = {"X-API-Key": "a33_abc123..."}
```

**Example: Invoking an agent from an external script:**

```python
import httpx

async def invoke_agent(agent_id: str, message: str) -> str:
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        resp = await client.post(
            f"/api/agents/{agent_id}/invoke",
            json={"message": message},
            headers={"X-API-Key": "a33_your_key_here"},
        )
        resp.raise_for_status()
        return resp.json()
```

**Example: Listing agents:**

```python
async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
    resp = await client.get(
        "/api/agents",
        headers={"X-API-Key": "a33_your_key_here"},
    )
    agents = resp.json()
```

### Docker Network Integration

To call AGENT-33 from another Docker Compose project, connect both to a shared network:

```yaml
# In your project's docker-compose.yml
services:
  my-app:
    image: my-app:latest
    networks:
      - agent33_network

networks:
  agent33_network:
    external: true
    name: engine_default  # Default network name from AGENT-33's compose
```

Then call the API at `http://api:8000` (using the service name from AGENT-33's compose file).

---

## CI/CD Integration

AGENT-33 includes a GitHub Actions workflow at `.github/workflows/ci.yml` with three jobs.

### GitHub Actions Workflow

The CI pipeline runs on every push and pull request to `main`:

**Lint job:**
```yaml
- pip install -e ".[dev]"
- ruff check src/ tests/
- mypy src/
```

**Test job:**
```yaml
- pip install -e ".[dev]"
- pytest --cov=agent33 --cov-report=term-missing -x -q
```

**Build job:**
```yaml
- docker compose build
```

### Running Tests in Pipelines

```bash
cd engine
pip install -e ".[dev]"
pytest --cov=agent33 --cov-report=term-missing -x -q
```

The `-x` flag stops on the first failure. Remove it for full test runs. Add `--cov-report=xml` for coverage upload to services like Codecov.

### Docker Build Patterns

The `Dockerfile` uses a multi-stage build:

1. **Builder stage** (`python:3.11-slim`): Installs build dependencies and the package.
2. **Runtime stage** (`python:3.11-slim`): Copies installed packages, runs as non-root `agent33` user.

```bash
# Build the image
cd engine
docker compose build

# Build only the API service
docker compose build api

# Production build
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
```

The runtime container exposes port 8000 and runs `uvicorn agent33.main:app`.

### Adding Custom CI Steps

Example additions to the workflow:

```yaml
# Security audit
- name: Safety check
  run: pip-audit

# Build and push Docker image
- name: Build and push
  uses: docker/build-push-action@v5
  with:
    context: engine
    push: true
    tags: ghcr.io/${{ github.repository }}/agent33:${{ github.sha }}
```
