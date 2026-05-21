# AGENT-33 API Reference

Base URL: `http://localhost:8000`

All endpoints return JSON unless otherwise noted. The API follows OpenAI-compatible conventions where applicable.

---

## Table of Contents

1. [Health](#1-health)
2. [Chat](#2-chat)
3. [Agents](#3-agents)
4. [Workflows](#4-workflows)
5. [Authentication](#5-authentication)
6. [Webhooks](#6-webhooks)
7. [Dashboard](#7-dashboard)

---

## 1. Health

### GET /health

Aggregate health check for all backing services (Ollama, Redis, PostgreSQL, NATS).

**Authentication:** None (public)

#### Response

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

Each service value is one of `"ok"`, `"degraded"`, or `"unavailable"`. The top-level `status` is `"healthy"` only when every service reports `"ok"`; otherwise it is `"degraded"`.

#### curl

```bash
curl http://localhost:8000/health
```

---

## 2. Chat

### POST /v1/chat/completions

Proxy chat completions to the configured LLM backend (Ollama). Returns an OpenAI-compatible response format.

**Authentication:** Required

#### Request Body

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `model` | string | No | Server default | Model name (e.g. `"llama3"`) |
| `messages` | array | Yes | -- | Array of message objects |
| `temperature` | float | No | `0.7` | Sampling temperature |
| `max_tokens` | integer | No | `null` | Maximum tokens to generate |
| `stream` | boolean | No | `false` | Streaming mode (currently always non-streaming) |

Each message object:

| Field | Type | Description |
|-------|------|-------------|
| `role` | string | `"system"`, `"user"`, or `"assistant"` |
| `content` | string | Message content |

```json
{
  "model": "llama3",
  "messages": [
    { "role": "system", "content": "You are a helpful assistant." },
    { "role": "user", "content": "What is AGENT-33?" }
  ],
  "temperature": 0.7,
  "max_tokens": 512
}
```

#### Response

```json
{
  "id": "chatcmpl-140234866512",
  "object": "chat.completion",
  "model": "llama3",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "AGENT-33 is a multi-agent orchestration platform..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 28,
    "completion_tokens": 64,
    "total_tokens": 92
  }
}
```

#### Error Responses

| Status | Detail |
|--------|--------|
| 503 | `"Ollama unavailable"` -- LLM backend is not reachable |
| 4xx/5xx | Upstream Ollama error proxied through |

#### curl

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3",
    "messages": [
      {"role": "user", "content": "Hello"}
    ]
  }'
```

---

## 3. Agents

### GET /v1/agents

List all registered agent definitions.

**Authentication:** Required

#### Response

```json
[
  {
    "name": "code-reviewer",
    "version": "1.0.0",
    "role": "specialist",
    "description": "Reviews code for quality and security issues"
  }
]
```

#### curl

```bash
curl http://localhost:8000/v1/agents \
  -H "Authorization: Bearer <token>"
```

---

### GET /v1/agents/{name}

Return the full definition for a single agent.

**Authentication:** Required

#### Path Parameters

| Name | Type | Description |
|------|------|-------------|
| `name` | string | Agent name (e.g. `"code-reviewer"`) |

#### Response

Returns the complete `AgentDefinition` object:

```json
{
  "name": "code-reviewer",
  "version": "1.0.0",
  "role": "specialist",
  "description": "Reviews code for quality and security issues",
  "capabilities": ["code_analysis"],
  "inputs": {
    "code": { "type": "string", "description": "Source code to review" }
  },
  "outputs": {
    "review": { "type": "string", "description": "Review results" }
  },
  "dependencies": [],
  "prompts": {
    "system": "",
    "template": ""
  },
  "constraints": {},
  "metadata": {}
}
```

#### Error Responses

| Status | Detail |
|--------|--------|
| 404 | `"Agent '{name}' not found"` |

#### curl

```bash
curl http://localhost:8000/v1/agents/code-reviewer \
  -H "Authorization: Bearer <token>"
```

---

### POST /v1/agents

Register a new agent definition.

**Authentication:** Required

#### Request Body

The full `AgentDefinition` schema. Required fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Lowercase alphanumeric with hyphens, 2-64 chars (pattern: `^[a-z][a-z0-9-]*$`) |
| `version` | string | Yes | Semver string (pattern: `^\d+\.\d+\.\d+$`) |
| `role` | string | Yes | Agent role enum value |
| `description` | string | No | Up to 500 characters |
| `capabilities` | array | No | List of capability strings |
| `inputs` | object | No | Input parameter definitions |
| `outputs` | object | No | Output parameter definitions |
| `dependencies` | array | No | Agent dependencies |
| `prompts` | object | No | System/template prompts |
| `constraints` | object | No | Execution constraints |
| `metadata` | object | No | Arbitrary metadata |

```json
{
  "name": "summarizer",
  "version": "1.0.0",
  "role": "specialist",
  "description": "Summarizes long documents",
  "capabilities": ["text_generation"],
  "inputs": {
    "document": { "type": "string", "description": "Text to summarize" }
  },
  "outputs": {
    "summary": { "type": "string", "description": "Generated summary" }
  }
}
```

#### Response (201 Created)

```json
{
  "status": "registered",
  "name": "summarizer"
}
```

#### curl

```bash
curl -X POST http://localhost:8000/v1/agents \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "summarizer",
    "version": "1.0.0",
    "role": "specialist",
    "description": "Summarizes long documents"
  }'
```

---

### POST /v1/agents/{name}/invoke

Invoke a registered agent with the given inputs.

**Authentication:** Required

#### Path Parameters

| Name | Type | Description |
|------|------|-------------|
| `name` | string | Agent name to invoke |

#### Request Body

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `inputs` | object | No | `{}` | Key-value inputs matching the agent's input schema |
| `model` | string | No | `null` | Override the model to use |
| `temperature` | float | No | `0.7` | Sampling temperature |

```json
{
  "inputs": {
    "document": "AGENT-33 is a platform for orchestrating multiple AI agents..."
  },
  "model": "llama3",
  "temperature": 0.5
}
```

#### Response

```json
{
  "agent": "summarizer",
  "output": {
    "summary": "AGENT-33 orchestrates multiple AI agents for complex tasks."
  },
  "tokens_used": 142,
  "model": "llama3"
}
```

#### Error Responses

| Status | Detail |
|--------|--------|
| 404 | `"Agent '{name}' not found"` |
| 422 | Validation error from agent runtime (e.g. missing required input) |
| 502 | Runtime error from the LLM backend |

#### curl

```bash
curl -X POST http://localhost:8000/v1/agents/summarizer/invoke \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {"document": "Long text here..."},
    "temperature": 0.5
  }'
```

---

## 4. Workflows

### GET /v1/workflows

List all registered workflows.

**Authentication:** Required

#### Response

```json
[
  {
    "name": "data-pipeline",
    "version": "1.0.0",
    "description": "Extract, transform, and summarize data",
    "step_count": 3,
    "triggers": {}
  }
]
```

#### curl

```bash
curl http://localhost:8000/v1/workflows \
  -H "Authorization: Bearer <token>"
```

---

### GET /v1/workflows/{name}

Get the full workflow definition by name.

**Authentication:** Required

#### Path Parameters

| Name | Type | Description |
|------|------|-------------|
| `name` | string | Workflow name |

#### Response

Returns the complete `WorkflowDefinition` object serialized as JSON.

```json
{
  "name": "data-pipeline",
  "version": "1.0.0",
  "description": "Extract, transform, and summarize data",
  "triggers": {},
  "inputs": {},
  "outputs": {},
  "steps": [
    {
      "id": "extract",
      "agent": "extractor",
      "inputs": {}
    }
  ],
  "execution": {},
  "metadata": {}
}
```

#### Error Responses

| Status | Detail |
|--------|--------|
| 404 | `"Workflow '{name}' not found"` |

#### curl

```bash
curl http://localhost:8000/v1/workflows/data-pipeline \
  -H "Authorization: Bearer <token>"
```

---

### POST /v1/workflows

Register a new workflow definition.

**Authentication:** Required

#### Request Body

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | -- | Workflow name |
| `version` | string | Yes | -- | Semver version |
| `description` | string | No | `null` | Human-readable description |
| `triggers` | object | No | `{}` | Trigger configuration (cron, webhook, etc.) |
| `inputs` | object | No | `{}` | Input schema |
| `outputs` | object | No | `{}` | Output schema |
| `steps` | array | Yes | -- | Ordered list of workflow steps |
| `execution` | object | No | `{}` | Execution settings (timeout, retry, dry_run) |
| `metadata` | object | No | `{}` | Arbitrary metadata |

```json
{
  "name": "data-pipeline",
  "version": "1.0.0",
  "description": "Extract, transform, and summarize data",
  "steps": [
    {
      "id": "extract",
      "agent": "extractor",
      "inputs": { "url": "{{inputs.source_url}}" }
    },
    {
      "id": "summarize",
      "agent": "summarizer",
      "inputs": { "document": "{{steps.extract.output}}" }
    }
  ]
}
```

#### Response (201 Created)

```json
{
  "name": "data-pipeline",
  "version": "1.0.0",
  "step_count": 2,
  "created": true
}
```

#### Error Responses

| Status | Detail |
|--------|--------|
| 409 | `"Workflow '{name}' already exists"` |
| 422 | Validation error in workflow definition |

#### curl

```bash
curl -X POST http://localhost:8000/v1/workflows \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "data-pipeline",
    "version": "1.0.0",
    "steps": [
      {"id": "step1", "agent": "summarizer", "inputs": {}}
    ]
  }'
```

---

### POST /v1/workflows/{name}/execute

Execute a registered workflow.

**Authentication:** Required

#### Path Parameters

| Name | Type | Description |
|------|------|-------------|
| `name` | string | Workflow name to execute |

#### Request Body

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `inputs` | object | No | `{}` | Runtime inputs for the workflow |
| `dry_run` | boolean | No | `false` | If `true`, simulate execution without side effects |

```json
{
  "inputs": {
    "source_url": "https://example.com/data.json"
  },
  "dry_run": false
}
```

#### Response

Returns a `WorkflowResult` object:

```json
{
  "workflow_name": "data-pipeline",
  "status": "completed",
  "outputs": {
    "summary": "The extracted data contains 150 records..."
  },
  "step_results": [
    {
      "step_id": "extract",
      "status": "completed",
      "output": {}
    },
    {
      "step_id": "summarize",
      "status": "completed",
      "output": {}
    }
  ],
  "duration_ms": 4523,
  "error": null
}
```

#### Error Responses

| Status | Detail |
|--------|--------|
| 404 | `"Workflow '{name}' not found"` |
| 500 | Execution failure (detail contains error message) |

#### curl

```bash
curl -X POST http://localhost:8000/v1/workflows/data-pipeline/execute \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"inputs": {"source_url": "https://example.com/data.json"}}'
```

---

## 5. Authentication

### POST /v1/auth/token

Authenticate with username and password to receive a JWT access token.

**Authentication:** None (public)

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `username` | string | Yes | Account username |
| `password` | string | Yes | Account password |

```json
{
  "username": "<your-username>",
  "password": "<your-password>"
}
```

#### Response

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

#### Error Responses

| Status | Detail |
|--------|--------|
| 401 | `"Invalid credentials"` |

#### curl

```bash
curl -X POST http://localhost:8000/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "<your-username>", "password": "<your-password>"}'
```

---

### POST /v1/auth/api-keys

Generate a new API key for programmatic access.

**Authentication:** Required

#### Request Body

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `subject` | string | Yes | -- | Identifier for the key owner (e.g. service name) |
| `scopes` | array | No | `[]` | Permission scopes for the key |

```json
{
  "subject": "ci-pipeline",
  "scopes": ["agents:read", "workflows:execute"]
}
```

#### Response (201 Created)

```json
{
  "key_id": "ak_1a2b3c4d",
  "key": "a33_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "subject": "ci-pipeline",
  "scopes": ["agents:read", "workflows:execute"]
}
```

> **Important:** The `key` value is only returned once at creation time. Store it securely.

#### curl

```bash
curl -X POST http://localhost:8000/v1/auth/api-keys \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"subject": "ci-pipeline", "scopes": ["agents:read"]}'
```

---

### DELETE /v1/auth/api-keys/{key_id}

Revoke an API key by its identifier.

**Authentication:** Required

#### Path Parameters

| Name | Type | Description |
|------|------|-------------|
| `key_id` | string | The key identifier (e.g. `"ak_1a2b3c4d"`) |

#### Response (204 No Content)

Empty body on success.

#### Error Responses

| Status | Detail |
|--------|--------|
| 404 | `"API key not found"` |

#### curl

```bash
curl -X DELETE http://localhost:8000/v1/auth/api-keys/ak_1a2b3c4d \
  -H "Authorization: Bearer <token>"
```

---

## 6. Webhooks

Webhook endpoints receive inbound messages from external messaging platforms. Each platform adapter must be configured at application startup. If an adapter is not configured, the endpoint returns `503`.

### POST /v1/webhooks/telegram

Receive Telegram Bot API webhook updates.

**Authentication:** None (Telegram delivers updates directly)

#### Request Body

Raw Telegram Update object as defined by the [Telegram Bot API](https://core.telegram.org/bots/api#update).

```json
{
  "update_id": 123456789,
  "message": {
    "message_id": 1,
    "from": { "id": 12345, "first_name": "User" },
    "chat": { "id": 12345, "type": "private" },
    "text": "Hello"
  }
}
```

#### Response

```json
{
  "status": "ok"
}
```

#### Error Responses

| Status | Detail |
|--------|--------|
| 503 | `"Telegram adapter not configured"` |

#### curl

```bash
curl -X POST http://localhost:8000/v1/webhooks/telegram \
  -H "Content-Type: application/json" \
  -d '{"update_id": 123456789, "message": {"message_id": 1, "text": "Hello", "chat": {"id": 12345, "type": "private"}}}'
```

---

### POST /v1/webhooks/discord

Receive Discord interaction webhooks.

**Authentication:** Ed25519 signature verification via headers

#### Headers

| Name | Required | Description |
|------|----------|-------------|
| `X-Signature-Ed25519` | Yes | Ed25519 signature |
| `X-Signature-Timestamp` | Yes | Request timestamp |

#### Request Body

Discord Interaction object. Type `1` (PING) is handled automatically with a PONG response.

```json
{
  "type": 2,
  "data": {
    "name": "ask",
    "options": [
      { "name": "question", "value": "What is AGENT-33?" }
    ]
  }
}
```

#### Response

For PING interactions (type 1):

```json
{
  "type": 1
}
```

For all other interactions:

```json
{
  "status": "ok"
}
```

#### Error Responses

| Status | Detail |
|--------|--------|
| 401 | `"Invalid signature"` |
| 503 | `"Discord adapter not configured"` |

#### curl

```bash
curl -X POST http://localhost:8000/v1/webhooks/discord \
  -H "Content-Type: application/json" \
  -H "X-Signature-Ed25519: <signature>" \
  -H "X-Signature-Timestamp: <timestamp>" \
  -d '{"type": 1}'
```

---

### POST /v1/webhooks/slack

Receive Slack Events API callbacks.

**Authentication:** Slack request signature verification via headers

#### Headers

| Name | Required | Description |
|------|----------|-------------|
| `X-Slack-Request-Timestamp` | Yes | Request timestamp |
| `X-Slack-Signature` | Yes | HMAC-SHA256 signature |

#### Request Body

Slack event payload. The `url_verification` challenge type is handled automatically.

```json
{
  "type": "event_callback",
  "event": {
    "type": "message",
    "text": "Hello agent",
    "channel": "C0123456789"
  }
}
```

#### Response

For URL verification:

```json
{
  "challenge": "<challenge_value>"
}
```

For all other events:

```json
{
  "status": "ok"
}
```

#### Error Responses

| Status | Detail |
|--------|--------|
| 401 | `"Invalid signature"` |
| 503 | `"Slack adapter not configured"` |

#### curl

```bash
curl -X POST http://localhost:8000/v1/webhooks/slack \
  -H "Content-Type: application/json" \
  -H "X-Slack-Request-Timestamp: 1234567890" \
  -H "X-Slack-Signature: v0=<signature>" \
  -d '{"type": "url_verification", "challenge": "abc123"}'
```

---

### GET /v1/webhooks/whatsapp

Handle WhatsApp webhook verification (Meta Hub challenge).

**Authentication:** None (Meta verification handshake)

#### Query Parameters

| Name | Type | Description |
|------|------|-------------|
| `hub.mode` | string | Should be `"subscribe"` |
| `hub.verify_token` | string | Verification token configured in Meta dashboard |
| `hub.challenge` | string | Challenge string to echo back |

#### Response

Returns the `hub.challenge` value as plain text on success.

#### Error Responses

| Status | Detail |
|--------|--------|
| 403 | `"Verification failed"` |
| 503 | `"WhatsApp adapter not configured"` |

#### curl

```bash
curl "http://localhost:8000/v1/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=mytoken&hub.challenge=challenge123"
```

---

### POST /v1/webhooks/whatsapp

Receive WhatsApp Cloud API webhook events.

**Authentication:** HMAC-SHA256 signature verification via header

#### Headers

| Name | Required | Description |
|------|----------|-------------|
| `X-Hub-Signature-256` | Yes | HMAC-SHA256 signature of the request body |

#### Request Body

WhatsApp Cloud API webhook payload.

```json
{
  "object": "whatsapp_business_account",
  "entry": [
    {
      "id": "BUSINESS_ID",
      "changes": [
        {
          "field": "messages",
          "value": {
            "messages": [
              {
                "from": "1234567890",
                "type": "text",
                "text": { "body": "Hello" }
              }
            ]
          }
        }
      ]
    }
  ]
}
```

#### Response

```json
{
  "status": "ok"
}
```

#### Error Responses

| Status | Detail |
|--------|--------|
| 401 | `"Invalid signature"` |
| 503 | `"WhatsApp adapter not configured"` |

#### curl

```bash
curl -X POST http://localhost:8000/v1/webhooks/whatsapp \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=<signature>" \
  -d '{"object": "whatsapp_business_account", "entry": []}'
```

---

## 7. Dashboard

### GET /v1/dashboard

Serve the HTML dashboard page.

**Authentication:** Required

#### Response

Returns `text/html` content. If the dashboard template is not found, a fallback HTML page is returned.

#### curl

```bash
curl http://localhost:8000/v1/dashboard \
  -H "Authorization: Bearer <token>"
```

---

### GET /v1/dashboard/metrics

Return current metrics summary as JSON.

**Authentication:** Required

#### Response

```json
{
  "total_requests": 1542,
  "active_agents": 5,
  "active_workflows": 3,
  "avg_latency_ms": 230,
  "error_rate": 0.02
}
```

> Note: The exact shape of the metrics summary depends on the `MetricsCollector` implementation.

#### curl

```bash
curl http://localhost:8000/v1/dashboard/metrics \
  -H "Authorization: Bearer <token>"
```

---

### GET /v1/dashboard/lineage/{workflow_id}

Return execution lineage records for a specific workflow run.

**Authentication:** Required

#### Path Parameters

| Name | Type | Description |
|------|------|-------------|
| `workflow_id` | string | The workflow execution identifier |

#### Response

```json
[
  {
    "workflow_id": "wf-run-abc123",
    "step_id": "extract",
    "action": "invoke_agent",
    "inputs_hash": "sha256:a1b2c3...",
    "outputs_hash": "sha256:d4e5f6...",
    "parent_id": null,
    "timestamp": "2026-01-30T12:00:00Z"
  },
  {
    "workflow_id": "wf-run-abc123",
    "step_id": "summarize",
    "action": "invoke_agent",
    "inputs_hash": "sha256:f6e5d4...",
    "outputs_hash": "sha256:c3b2a1...",
    "parent_id": "extract",
    "timestamp": "2026-01-30T12:00:02Z"
  }
]
```

#### curl

```bash
curl http://localhost:8000/v1/dashboard/lineage/wf-run-abc123 \
  -H "Authorization: Bearer <token>"
```

---

## Authentication Overview

Most endpoints require a Bearer token in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

Tokens are obtained via `POST /v1/auth/token`. Alternatively, API keys generated via `POST /v1/auth/api-keys` can be used.

**Public endpoints (no auth required):**

- `GET /health`
- `POST /v1/auth/token`
- `POST /v1/webhooks/*` (secured by platform-specific signature verification)
- `GET /v1/webhooks/whatsapp` (Meta verification handshake)
- Auto-generated docs at `/docs` (Swagger UI) and `/redoc`

---

## Common Error Format

All error responses follow this structure:

```json
{
  "detail": "Human-readable error message"
}
```

### Standard HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Resource created |
| 204 | Success with no content |
| 401 | Unauthorized (invalid or missing credentials) |
| 403 | Forbidden (insufficient permissions) |
| 404 | Resource not found |
| 409 | Conflict (resource already exists) |
| 422 | Validation error |
| 500 | Internal server error |
| 502 | Bad gateway (upstream LLM error) |
| 503 | Service unavailable (dependency not configured or reachable) |
