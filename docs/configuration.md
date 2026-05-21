# Configuration reference

Every AGENT-33 setting is exposed as an environment variable. They are loaded by
`agent33.config.Settings` (pydantic-settings), so the variable name is the
uppercased version of the field name in `engine/src/agent33/config.py`.

This page lists every setting, grouped by subsystem, with type, default,
purpose, and an example. For *how to organize* configuration across
environments, see [setup-guide.md](setup-guide.md).

## Loading priority

1. Values passed directly to `Settings(...)`.
2. Environment variables.
3. `.env` then `.env.local` in the working directory.
4. Profile preset (`AGENT33_PROFILE` env var).
5. File secrets (mounted Kubernetes secrets).
6. Defaults baked into `Settings`.

## Profiles

`AGENT33_PROFILE` selects a curated preset:

| Profile      | Intent                                  |
|--------------|-----------------------------------------|
| `minimal`    | smoke tests, demos, CI                  |
| `developer`  | local development                       |
| `production` | real deployments                        |
| `enterprise` | multi-tenant production with telemetry  |
| `airgapped`  | disconnected environments               |

Settings below show the default for `agent33_mode=standard`; a profile may
change them.

## API

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `API_PORT` | int | `8000` | TCP port the FastAPI server binds. |
| `API_LOG_LEVEL` | str | `info` | Uvicorn log level (`critical`, `error`, `warning`, `info`, `debug`, `trace`). |
| `API_SECRET_KEY` | secret | `change-me-in-production` | Internal HMAC / signing key; rotate in prod. |
| `CORS_ALLOWED_ORIGINS` | csv | `""` (deny all) | Comma-separated allowed origins. Empty means the browser cannot call the API. |
| `MAX_REQUEST_SIZE_BYTES` | int | `10485760` | Per-request body cap (10 MB). |
| `ENVIRONMENT` | str | `development` | One of `development`, `test`, `production`. Drives strict validators. |

Example:

```bash
API_PORT=8000
API_LOG_LEVEL=info
API_SECRET_KEY=base64-random
CORS_ALLOWED_ORIGINS=https://control.example.com,https://agent33.example.com
ENVIRONMENT=production
```

## Deployment mode

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AGENT33_MODE` | enum | `standard` | One of `lite`, `standard`, `enterprise`. |
| `AGENT33_PROFILE` | str | (unset) | Loads a curated preset on top of env vars. |
| `OFFLINE_MODE` | bool | `false` | Disables outbound calls (pack registry, telemetry, remote LLMs). |

## Authentication and authorization

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `JWT_SECRET` | secret | `change-me-in-production` | HMAC secret for JWT signing. **Required** in production. |
| `JWT_ALGORITHM` | str | `HS256` | Token algorithm. |
| `JWT_EXPIRE_MINUTES` | int | `60` | Token lifetime. |
| `ENCRYPTION_KEY` | secret | `""` | Fernet key for encrypted persistence; required in `enterprise` mode. |
| `AUTH_BOOTSTRAP_ENABLED` | bool | `false` | Create a seed admin user on first start. |
| `AUTH_BOOTSTRAP_ADMIN_USERNAME` | str | `admin` | Bootstrap username. |
| `AUTH_BOOTSTRAP_ADMIN_PASSWORD` | secret | `""` | Bootstrap password (set to something strong). |
| `AUTH_BOOTSTRAP_ADMIN_SCOPES` | csv | (admin + base scopes) | Scopes granted to the bootstrap admin. |

The startup validator refuses to boot in `environment=production` if
`JWT_SECRET` is at the default. In `development` / `lite` mode, a random secret
is generated and a warning logged.

## Database (Postgres + pgvector)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DATABASE_URL` | str | `postgresql+asyncpg://agent33:agent33@postgres:5432/agent33` | Async SQLAlchemy URL. |
| `DB_POOL_SIZE` | int | `10` | Connection pool size per process. |
| `DB_MAX_OVERFLOW` | int | `20` | Overflow connections. |
| `DB_POOL_PRE_PING` | bool | `true` | Validate connections before use. |
| `DB_POOL_RECYCLE` | int | `1800` | Recycle connections after N seconds. |

Postgres must be 14+ with the `pgvector` extension. The engine creates the
extension on startup when it has rights.

## Redis

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `REDIS_URL` | str | `redis://redis:6379/0` | Connection string. |
| `REDIS_MAX_CONNECTIONS` | int | `50` | Pool ceiling. |

## NATS

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `NATS_URL` | str | `nats://nats:4222` | Connection string. |

JetStream must be enabled on the server.

## LLM providers

### Ollama (default local)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `OLLAMA_BASE_URL` | str | `http://ollama:11434` | Base URL. |
| `OLLAMA_DEFAULT_MODEL` | str | `llama3.2:3b` | Model used when no model is requested. |

### LM Studio

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `LM_STUDIO_BASE_URL` | str | `http://localhost:1234/v1` | OpenAI-compatible LM Studio URL. |
| `LM_STUDIO_DEFAULT_MODEL` | str | `local-model` | Model identifier. |

### Local orchestration (llama.cpp tensor-offload)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `LOCAL_ORCHESTRATION_MODEL` | str | `qwen3-coder-next` | Headline model. |
| `LOCAL_ORCHESTRATION_FORMAT` | str | `gguf_q4_k_m` | GGUF quantization. |
| `LOCAL_ORCHESTRATION_ENGINE` | str | `llama.cpp` | Engine name. |
| `LOCAL_ORCHESTRATION_BASE_URL` | str | `http://host.docker.internal:8033/v1` | OpenAI-compatible endpoint. |

### Cloud / OpenAI-compatible

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DEFAULT_MODEL` | str | `""` | Override the default model. Use a provider prefix (e.g., `openai/gpt-4o-mini`, `openrouter/auto`). |
| `OPENAI_API_KEY` | secret | `""` | Enable OpenAI / compatible. |
| `OPENAI_BASE_URL` | str | `""` (defaults to OpenAI) | Custom base URL. |
| `OPENROUTER_API_KEY` | secret | `""` | OpenRouter key. |
| `OPENROUTER_BASE_URL` | str | `https://openrouter.ai/api/v1` |  |
| `OPENROUTER_SITE_URL` | str | `http://localhost` | Identifier for OpenRouter. |
| `OPENROUTER_APP_NAME` | str | `AGENT-33` |  |
| `OPENROUTER_APP_CATEGORY` | str | `cli-agent` |  |
| `OPENROUTER_DEFAULT_FALLBACK_MODELS` | csv | `""` | Comma-separated fallback chain. |

### AirLLM (GPU layer-sharded inference)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AIRLLM_ENABLED` | bool | `false` | Enable AirLLM provider. |
| `AIRLLM_MODEL_PATH` | str | `""` | Path or HF identifier. |
| `AIRLLM_DEVICE` | str | `cuda:0` | Device. |
| `AIRLLM_COMPRESSION` | str | `""` | `4bit` / `8bit` / empty. |
| `AIRLLM_MAX_SEQ_LEN` | int | `2048` |  |
| `AIRLLM_PREFETCH` | bool | `true` |  |

## Embeddings and retrieval

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `EMBEDDING_PROVIDER` | str | `ollama` | `ollama` or `jina`. |
| `EMBEDDING_DIM` | int | `768` | Must match the model output. |
| `EMBEDDING_BATCH_SIZE` | int | `100` |  |
| `EMBEDDING_CACHE_ENABLED` | bool | `true` |  |
| `EMBEDDING_CACHE_MAX_SIZE` | int | `1024` |  |
| `EMBEDDING_HOT_SWAP_ENABLED` | bool | `false` |  |
| `EMBEDDING_DEFAULT_MODEL` | str | `nomic-embed-text` |  |
| `EMBEDDING_DEFAULT_DIMENSIONS` | int | `768` |  |
| `EMBEDDING_QUANTIZATION_ENABLED` | bool | `false` | TurboQuant-style compression. |
| `EMBEDDING_QUANTIZATION_BITS` | int | `4` |  |
| `EMBEDDING_QUANTIZATION_SEED` | int | `42` |  |
| `RAG_TOP_K` | int | `5` |  |
| `RAG_SIMILARITY_THRESHOLD` | float | `0.3` |  |
| `RAG_HYBRID_ENABLED` | bool | `true` | BM25 + dense via RRF. |
| `RAG_VECTOR_WEIGHT` | float | `0.7` | BM25 weight = `1 - vector_weight`. |
| `RAG_RRF_K` | int | `60` | Reciprocal rank fusion constant. |
| `CHUNK_TOKENS` | int | `1200` |  |
| `CHUNK_OVERLAP_TOKENS` | int | `100` |  |
| `BM25_WARMUP_ENABLED` | bool | `true` |  |
| `BM25_WARMUP_MAX_RECORDS` | int | `10000` |  |
| `BM25_WARMUP_PAGE_SIZE` | int | `200` |  |
| `JINA_API_KEY` | secret | `""` |  |
| `JINA_READER_URL` | str | `https://r.jina.ai` |  |

## HTTP and runtime

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `HTTP_MAX_CONNECTIONS` | int | `20` | Per-client HTTP pool. |
| `HTTP_MAX_KEEPALIVE` | int | `10` |  |

## Policy / governance

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `TOOL_USE_MODE` | enum | `audit` | `audit`, `dry-run`, `approved`. |
| `EVIDENCE_REQUIRED` | bool | `true` | Reject runs without evidence capture. |
| `REVIEW_AUTHORITY` | enum | `user` | `user`, `automation`, `disabled`. |
| `REDACT_SECRETS_ENABLED` | bool | `true` | Redact API keys / tokens in logs and tool output. |

## Rate limiting

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `RATE_LIMIT_ENABLED` | bool | `true` |  |
| `RATE_LIMIT_DEFAULT_TIER` | str | `standard` |  |
| `RATE_LIMIT_PER_MINUTE` | int | `60` |  |
| `RATE_LIMIT_BURST` | int | `10` |  |

## Web search

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SEARXNG_URL` | str | `http://searxng:8080` |  |
| `TAVILY_API_KEY` | secret | `""` |  |
| `BRAVE_API_KEY` | secret | `""` |  |
| `WEB_SEARCH_MAX_RESULTS` | int | `10` |  |
| `WEB_SEARCH_DEFAULT_PROVIDER` | str | (unset) | Force a provider; empty auto-selects. |

## Voice

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `VOICE_DAEMON_ENABLED` | bool | `true` |  |
| `VOICE_DAEMON_TRANSPORT` | enum | `stub` | `stub`, `sidecar`, `livekit`. |
| `VOICE_DAEMON_URL` | str | `""` | Sidecar URL. |
| `VOICE_DAEMON_API_KEY` | secret | `""` |  |
| `VOICE_DAEMON_API_SECRET` | secret | `""` |  |
| `VOICE_DAEMON_ROOM_PREFIX` | str | `agent33-voice` |  |
| `VOICE_DAEMON_MAX_SESSIONS` | int | `25` |  |
| `VOICE_TTS_PROVIDER` | enum | `stub` | `stub`, `elevenlabs`, `piper`. |
| `VOICE_STT_PROVIDER` | enum | `stub` | `stub`, `whisper`, `openai_whisper`. |
| `VOICE_STT_WHISPER_MODEL_SIZE` | str | `base` | tiny/base/small/medium/large. |
| `VOICE_STT_WHISPER_DEVICE` | str | `cpu` | `cpu` / `cuda`. |
| `VOICE_TTS_PIPER_MODEL_PATH` | str | `""` |  |
| `VOICE_TTS_PIPER_VOICE_ID` | str | `en_US-lessac-medium` |  |
| `ELEVENLABS_API_KEY` | secret | `""` |  |
| `ELEVENLABS_VOICE_ID` | str | `21m00Tcm4TlvDq8ikWAM` |  |
| `VOICE_ELEVENLABS_ENABLED` | bool | `false` |  |
| `VOICE_ELEVENLABS_API_KEY` | secret | `""` |  |
| `VOICE_ELEVENLABS_DEFAULT_VOICE_ID` | str | `""` |  |
| `VOICE_ELEVENLABS_MODEL_ID` | str | `eleven_multilingual_v2` |  |
| `VOICE_LIVEKIT_ENABLED` | bool | `false` |  |
| `VOICE_LIVEKIT_API_KEY` | secret | `""` |  |
| `VOICE_LIVEKIT_API_SECRET` | secret | `""` |  |
| `VOICE_LIVEKIT_WS_URL` | str | `""` |  |

## Knowledge ingestion

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `KNOWLEDGE_DEFAULT_TENANT_ID` | str | `system` |  |
| `INGESTION_DB_PATH` | str | `var/ingestion.db` |  |
| `INGESTION_MAILBOX_DB_PATH` | str | `var/ingestion_mailbox.db` |  |
| `INGESTION_JOURNAL_DB_PATH` | str | `var/ingestion_journal.db` |  |
| `INGESTION_JOURNAL_RETENTION_DAYS` | int | `90` | 0 disables expiry. |
| `INGESTION_TASK_METRICS_DB_PATH` | str | `var/ingestion_task_metrics.db` |  |
| `INGESTION_TASK_METRICS_RETENTION_DAYS` | int | `30` |  |
| `INGESTION_NOTIFICATION_HOOKS_DB_PATH` | str | `var/ingestion_notification_hooks.db` |  |
| `INGESTION_NOTIFICATION_TIMEOUT_SECONDS` | float | `5.0` |  |

## Packs

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PACK_DEFINITIONS_DIR` | str | `packs` |  |
| `PACK_MARKETPLACE_DIR` | str | `pack-marketplace` |  |
| `PACK_MARKETPLACE_REMOTE_SOURCES` | json | `""` | JSON array of remote source configs. |
| `PACK_MARKETPLACE_CACHE_DIR` | str | `var/pack-marketplace-cache` |  |
| `PACK_AUTO_ENABLE` | bool | `false` |  |
| `PACK_MAX_SIZE_MB` | int | `50` |  |
| `PACK_CHECKSUMS_REQUIRED` | bool | `false` |  |
| `PACK_ROLLBACK_ARCHIVE_DIR` | str | `var/pack-rollback-archive` |  |
| `PACK_CURATION_ENABLED` | bool | `false` |  |
| `PACK_MIN_QUALITY_SCORE` | float | `0.5` |  |
| `PACK_REQUIRE_REVIEW_FOR_LISTING` | bool | `true` |  |
| `PACK_DEFAULT_CATEGORIES` | csv | (automation, data-analysis, ...) |  |
| `PACK_SIGNING_KEY` | str | `""` |  |

## Skills

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SKILL_DEFINITIONS_DIR` | str | `skills` |  |
| `SKILL_MAX_INSTRUCTIONS_CHARS` | int | `16000` |  |
| `SKILL_LINEAGE_STORE_PATH` | str | `var/skill_lineage_events.json` |  |
| `SKILLSBENCH_SKILL_MATCHER_ENABLED` | bool | `false` |  |
| `SKILLSBENCH_SKILL_MATCHER_MODEL` | str | `llama3.2` |  |
| `SKILLSBENCH_SKILL_MATCHER_TOP_K` | int | `20` |  |
| `SKILLSBENCH_SKILL_MATCHER_SKIP_LLM_BELOW` | int | `3` |  |
| `SKILLSBENCH_CONTEXT_MANAGER_ENABLED` | bool | `true` |  |
| `SKILLSBENCH_STORAGE_PATH` | str | `var/skillsbench_runs` |  |
| `SKILL_MATCH_FUZZY_THRESHOLD` | float | `0.7` |  |
| `SKILL_MATCH_SEMANTIC_THRESHOLD` | float | `0.5` |  |
| `SKILL_MATCH_CONTEXTUAL_THRESHOLD` | float | `0.4` |  |
| `SKILL_MATCH_MAX_CANDIDATES` | int | `10` |  |

## Plugins

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PLUGIN_DEFINITIONS_DIR` | str | `plugins` |  |
| `PLUGIN_AUTO_ENABLE` | bool | `true` |  |
| `PLUGIN_STATE_STORE_PATH` | str | `var/plugin_lifecycle_state.json` |  |
| `PLUGIN_ALLOWLIST` | csv | `""` (allow all) |  |
| `PLUGIN_DISCOVERY_PATHS` | csv | `""` |  |

## Agents

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AGENT_DEFINITIONS_DIR` | str | `agent-definitions` |  |
| `AGENT_EFFORT_ROUTING_ENABLED` | bool | `false` | Enable effort-based model routing. |
| `AGENT_EFFORT_DEFAULT` | str | `medium` |  |
| `AGENT_EFFORT_LOW_MODEL` | str | `""` | Model for low effort. |
| `AGENT_EFFORT_MEDIUM_MODEL` | str | `""` |  |
| `AGENT_EFFORT_HIGH_MODEL` | str | `""` |  |
| `AGENT_EFFORT_LOW_TOKEN_MULTIPLIER` | float | `1.0` |  |
| `AGENT_EFFORT_MEDIUM_TOKEN_MULTIPLIER` | float | `1.0` |  |
| `AGENT_EFFORT_HIGH_TOKEN_MULTIPLIER` | float | `1.0` |  |
| `AGENT_EFFORT_HEURISTIC_ENABLED` | bool | `true` |  |
| `AGENT_EFFORT_POLICY_TENANT` | json | `""` | `{"tenant-id": "low|medium|high"}` |
| `AGENT_EFFORT_POLICY_DOMAIN` | json | `""` |  |
| `AGENT_EFFORT_POLICY_TENANT_DOMAIN` | json | `""` |  |
| `AGENT_EFFORT_COST_PER_1K_TOKENS` | float | `0.0` | Cost basis for estimates. |
| `AGENT_DEFAULT_CONTEXT_WINDOW` | int | `128000` |  |
| `AGENT_CONTEXT_WARN_THRESHOLD` | float | `0.8` |  |
| `AGENT_TOOL_LOOP_MAX_RETRIES` | int | `3` |  |
| `AGENT_TOOL_LOOP_BACKOFF_BASE_MS` | float | `100` |  |
| `AGENT_PROFILER_MAX_PROFILES` | int | `1000` |  |

## Autonomy

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AUTONOMY_DEFAULT_LEVEL` | int | `1` | `0=supervised`, `1=read-auto`, `2=auto-no-destructive`, `3=full`. |
| `AUTONOMY_MAX_STRETCH_HOURS` | int | `24` |  |
| `AUTONOMY_ALLOW_SECURITY_RECON` | bool | `true` |  |

## Code execution

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `EXECUTION_GPU_ENABLED` | bool | `false` |  |
| `EXECUTION_DEFAULT_DOCKER_IMAGE` | str | `python:3.11-slim` |  |
| `EXECUTION_GPU_RUNTIME` | enum | `nvidia` | `nvidia` or `amd`. |

## Jupyter kernel

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `JUPYTER_KERNEL_ENABLED` | bool | `false` |  |
| `JUPYTER_KERNEL_ADAPTER_ID` | str | `jupyter-kernel` |  |
| `JUPYTER_KERNEL_TOOL_ID` | str | `code-interpreter` |  |
| `JUPYTER_KERNEL_MODE` | enum | `local` | `local` or `docker`. |
| `JUPYTER_KERNEL_NAME` | str | `python3` |  |
| `JUPYTER_KERNEL_MAX_SESSIONS` | int | `10` |  |
| `JUPYTER_KERNEL_IDLE_TIMEOUT_SECONDS` | float | `300.0` |  |
| `JUPYTER_KERNEL_STARTUP_TIMEOUT_SECONDS` | float | `30.0` |  |
| `JUPYTER_KERNEL_EXECUTION_TIMEOUT_SECONDS` | float | `60.0` |  |
| `JUPYTER_KERNEL_DOCKER_IMAGE` | str | `quay.io/jupyter/minimal-notebook:python-3.11` |  |
| `JUPYTER_KERNEL_ALLOWED_IMAGES` | csv | `""` |  |
| `JUPYTER_KERNEL_NETWORK_ENABLED` | bool | `false` |  |
| `JUPYTER_KERNEL_MOUNT_WORKDIR` | bool | `true` |  |
| `JUPYTER_KERNEL_CONTAINER_WORKDIR` | str | `/workspace` |  |

## Hooks

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `HOOKS_ENABLED` | bool | `true` |  |
| `HOOKS_DEFINITIONS_DIR` | str | `hook-definitions` |  |
| `HOOKS_DEFAULT_TIMEOUT_MS` | float | `200.0` |  |
| `HOOKS_CHAIN_TIMEOUT_MS` | float | `500.0` |  |
| `HOOKS_FAIL_OPEN_DEFAULT` | bool | `true` |  |
| `HOOKS_MAX_PER_EVENT` | int | `20` |  |
| `HOOKS_EXECUTION_LOG_ENABLED` | bool | `true` |  |
| `HOOKS_EXECUTION_LOG_RETENTION_HOURS` | int | `24` |  |
| `SCRIPT_HOOKS_ENABLED` | bool | `true` |  |
| `SCRIPT_HOOKS_PROJECT_DIR` | str | (defaults to `<cwd>/.claude/hooks/`) |  |
| `SCRIPT_HOOKS_USER_DIR` | str | (defaults to `~/.agent33/hooks/`) |  |
| `SCRIPT_HOOKS_DEFAULT_TIMEOUT_MS` | float | `5000.0` |  |
| `SCRIPT_HOOKS_MAX_TIMEOUT_MS` | float | `30000.0` |  |

## MCP (Model Context Protocol)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `MCP_SERVERS` | csv | `""` | Comma-separated MCP server URLs. |
| `MCP_TIMEOUT_SECONDS` | float | `30.0` |  |
| `MCP_AUTO_DISCOVER` | bool | `true` |  |
| `MCP_PROXY_CONFIG_PATH` | str | `""` |  |
| `MCP_PROXY_ENABLED` | bool | `false` |  |
| `MCP_PROXY_TOOL_SEPARATOR` | str | `__` |  |
| `MCP_PROXY_HEALTH_CHECK_ENABLED` | bool | `true` |  |
| `MCP_SYNC_BACKUP_ENABLED` | bool | `true` |  |

## Tool approvals

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `APPROVAL_TOKEN_TTL_SECONDS` | int | `300` |  |
| `APPROVAL_TOKEN_ENABLED` | bool | `true` |  |
| `APPROVAL_TOKEN_ONE_TIME_DEFAULT` | bool | `true` |  |
| `P69B_DB_PATH` | str | `var/p69b.db` |  |
| `TOOL_DISCOVERY_MODE` | enum | `legacy` | `legacy` or `dynamic`. |

## Connector boundary

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `CONNECTOR_BOUNDARY_ENABLED` | bool | `false` |  |
| `CONNECTOR_POLICY_PACK` | str | `default` |  |
| `CONNECTOR_GOVERNANCE_BLOCKED_CONNECTORS` | csv | `""` |  |
| `CONNECTOR_GOVERNANCE_BLOCKED_OPERATIONS` | csv | `""` |  |
| `CONNECTOR_CIRCUIT_BREAKER_ENABLED` | bool | `false` |  |
| `CONNECTOR_CIRCUIT_FAILURE_THRESHOLD` | int | `3` |  |
| `CONNECTOR_CIRCUIT_RECOVERY_SECONDS` | float | `30.0` |  |
| `CONNECTOR_CIRCUIT_HALF_OPEN_SUCCESSES` | int | `2` |  |
| `CONNECTOR_CIRCUIT_MAX_RECOVERY_SECONDS` | float | `300.0` |  |

## Observability

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `METRICS_ROLLING_WINDOW_SECONDS` | int | `300` |  |
| `OBSERVABILITY_EFFORT_ALERTS_ENABLED` | bool | `true` |  |
| `OBSERVABILITY_EFFORT_ALERT_HIGH_EFFORT_COUNT_THRESHOLD` | int | `25` |  |
| `OBSERVABILITY_EFFORT_ALERT_HIGH_COST_USD_THRESHOLD` | float | `5.0` |  |
| `OBSERVABILITY_EFFORT_ALERT_HIGH_TOKEN_BUDGET_THRESHOLD` | int | `8000` |  |
| `OBSERVABILITY_EFFORT_EXPORT_ENABLED` | bool | `false` |  |
| `OBSERVABILITY_EFFORT_EXPORT_PATH` | str | `var/effort_routing_events.jsonl` |  |
| `OBSERVABILITY_EFFORT_EXPORT_FAIL_CLOSED` | bool | `false` |  |
| `PROVENANCE_ENABLED` | bool | `true` |  |
| `PROVENANCE_MAX_RECEIPTS` | int | `10000` |  |
| `SLO_AVAILABILITY_TARGET` | float | `0.999` |  |
| `SLO_LATENCY_P99_MS` | int | `500` |  |
| `SLO_LATENCY_AGENT_P99_MS` | int | `10000` |  |
| `SLOW_QUERY_THRESHOLD_MS` | int | `100` |  |

## Streaming

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `STREAMING_MAX_CONNECTIONS` | int | `100` |  |
| `STREAMING_PING_INTERVAL_SECONDS` | int | `30` |  |
| `WORKFLOW_TRANSPORT_PREFERRED` | enum | `auto` | `auto`, `websocket`, or `sse`. |
| `WORKFLOW_WS_PING_INTERVAL` | float | `30.0` |  |
| `WORKFLOW_WS_PING_TIMEOUT` | float | `10.0` |  |
| `SSE_SCHEMA_V2_ENABLED` | bool | `false` | Opt-in to SSE v2 schema. |

## Browser automation

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `BROWSER_CLOUD_API_KEY` | secret | `""` | BrowserBase key; empty = local only. |
| `BROWSER_SESSION_TTL_SECONDS` | int | `300` |  |
| `BROWSER_VISION_MODEL` | str | `""` |  |
| `BROWSER_CLOUD_API_URL` | str | `https://www.browserbase.com/v1` |  |
| `BROWSER_COMPUTER_USE_ENABLED` | bool | `false` |  |
| `MAX_BROWSER_SESSIONS_PER_TENANT` | int | `3` |  |

## Messaging integrations (Matrix)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `MATRIX_HOMESERVER_URL` | str | `""` |  |
| `MATRIX_ACCESS_TOKEN` | secret | `""` |  |
| `MATRIX_USER_ID` | str | `""` |  |
| `MATRIX_ROOM_IDS` | csv | `""` (empty = all joined) |  |
| `MATRIX_SYNC_TIMEOUT_MS` | int | `30000` |  |

## Self-improvement

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SELF_IMPROVE_ENABLED` | bool | `true` |  |
| `SELF_IMPROVE_SCOPE` | csv | `prompts,workflows,templates` |  |
| `SELF_IMPROVE_REQUIRE_APPROVAL` | bool | `true` |  |
| `SELF_IMPROVE_PROPOSAL_SANDBOX_ENABLED` | bool | `true` |  |
| `IMPROVEMENT_LEARNING_ENABLED` | bool | `false` |  |
| `IMPROVEMENT_TUNING_LOOP_ENABLED` | bool | `false` |  |
| `IMPROVEMENT_TUNING_LOOP_INTERVAL_HOURS` | float | `24.0` |  |
| `IMPROVEMENT_TUNING_LOOP_REQUIRE_APPROVAL` | bool | `true` |  |
| `IMPROVEMENT_TUNING_LOOP_DRY_RUN` | bool | `false` |  |
| `IMPROVEMENT_LEARNING_PERSISTENCE_BACKEND` | enum | `db` | `memory`, `file`, `db`. |

The improvement subsystem has more fine-grained knobs (quality weights,
thresholds, retention); see `engine/src/agent33/config.py` for the full list.

## Outcomes and impact

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `OUTCOMES_DB_PATH` | str | `var/outcomes.db` |  |
| `PPACK_V3_ENABLED` | bool | `false` |  |
| `PPACK_V3_AB_ENABLED` | bool | `true` |  |
| `PPACK_V3_AB_EXPERIMENT_KEY` | str | `ppack_v3` |  |
| `PPACK_V3_AB_MIN_SAMPLES_PER_VARIANT` | int | `30` |  |
| `PPACK_V3_AB_REGRESSION_THRESHOLD` | float | `-0.05` |  |
| `PPACK_V3_AB_WEEKLY_WINDOW_DAYS` | int | `7` |  |

## Evaluation

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `EVALUATION_JUDGE_MODEL` | str | `""` | Empty = rule-based evaluator. |
| `EVALUATION_CTRF_OUTPUT_DIR` | str | `var/ctrf-reports` |  |
| `EVALUATION_BENCHMARK_CATALOG_PATH` | str | `""` |  |
| `EVALUATION_BENCHMARK_DEFAULT_TRIALS` | int | `5` |  |
| `SCHEDULED_GATES_ENABLED` | bool | `false` |  |
| `SCHEDULED_GATES_MAX_SCHEDULES` | int | `50` |  |
| `SCHEDULED_GATES_HISTORY_RETENTION` | int | `100` |  |

## Comparative scoring

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `COMPARATIVE_ELO_K_FACTOR` | float | `32.0` |  |
| `COMPARATIVE_MIN_POPULATION_SIZE` | int | `2` |  |
| `COMPARATIVE_CONFIDENCE_LEVEL` | float | `0.95` |  |

## Operator sessions

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `OPERATOR_SESSION_ENABLED` | bool | `true` |  |
| `OPERATOR_SESSION_BASE_DIR` | str | (`~/.agent33/sessions/`) |  |
| `OPERATOR_SESSION_CHECKPOINT_INTERVAL_SECONDS` | float | `60.0` |  |
| `OPERATOR_SESSION_MAX_REPLAY_FILE_MB` | int | `50` |  |
| `OPERATOR_SESSION_MAX_RETAINED` | int | `100` |  |
| `OPERATOR_SESSION_CRASH_RECOVERY_ENABLED` | bool | `true` |  |

## Context engine

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROMPT_CACHE_ENABLED` | bool | `true` |  |
| `CONTEXT_COMPRESSION_ENABLED` | bool | `false` |  |
| `CONTEXT_COMPRESSION_THRESHOLD_PERCENT` | float | `0.50` |  |
| `CONTEXT_COMPRESSION_PROTECT_FIRST_N` | int | `3` |  |
| `CONTEXT_COMPRESSION_TAIL_TOKEN_BUDGET` | int | `20000` |  |
| `CONTEXT_COMPRESSION_SUMMARY_TARGET_RATIO` | float | `0.20` |  |
| `CONTEXT_COMPRESSION_SUMMARY_TOKENS_CEILING` | int | `12000` |  |
| `CONTEXT_COMPRESSION_SUMMARIZE_MODEL` | str | `llama3.2` |  |
| `CONTEXT_ENGINE_DEFAULT` | str | `builtin` |  |
| `CONTEXT_COMPACTION_ENABLED` | bool | `true` |  |
| `SESSION_SPAWN_TEMPLATES_DIR` | str | `""` |  |
| `SESSION_ARCHIVE_RETENTION_DAYS` | int | `90` |  |

## Webhook delivery

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `WEBHOOK_DELIVERY_MAX_RETRIES` | int | `5` |  |
| `WEBHOOK_DELIVERY_BASE_DELAY` | float | `1.0` |  |
| `WEBHOOK_DELIVERY_MAX_DELAY` | float | `300.0` |  |
| `WEBHOOK_DELIVERY_MAX_RECORDS` | int | `10000` |  |

## Workflows and runs

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `WORKFLOW_MARKETPLACE_ENABLED` | bool | `true` |  |
| `WORKFLOW_TEMPLATES_DIR` | str | `workflow-templates` |  |
| `SYNTHETIC_ENV_WORKFLOW_DIR` | str | `workflow-definitions` |  |
| `SYNTHETIC_ENV_TOOL_DIR` | str | `tool-definitions` |  |
| `SYNTHETIC_ENV_BUNDLE_RETENTION` | int | `100` |  |
| `SYNTHETIC_ENV_BUNDLE_PERSISTENCE_PATH` | str | `var/synthetic_environment_bundles.json` |  |
| `WORKFLOW_RUN_ARCHIVE_DIR` | str | `var/workflow-runs` |  |
| `ORCHESTRATION_STATE_STORE_PATH` | str | `var/orchestration_state.json` |  |
| `CHECKPOINT_PERSISTENCE_ENABLED` | bool | `false` |  |

## Process registry

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROCESS_MANAGER_LOG_DIR` | str | `var/process-manager` |  |
| `PROCESS_MANAGER_MAX_PROCESSES` | int | `10` |  |

## Backups

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `BACKUP_DIR` | str | `var/backups` |  |

## Trajectory capture and MoA

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `TRAJECTORY_CAPTURE_ENABLED` | bool | `false` |  |
| `TRAJECTORY_OUTPUT_DIR` | str | `trajectories` |  |
| `MOA_REFERENCE_MODELS` | csv | `""` |  |
| `MOA_AGGREGATOR_MODEL` | str | `""` |  |
| `MOA_REFERENCE_TEMPERATURE` | float | `0.6` |  |
| `MOA_AGGREGATOR_TEMPERATURE` | float | `0.4` |  |

## Programmatic tool calling (PTC)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PTC_ENABLED` | bool | `true` |  |
| `PTC_TIMEOUT_S` | int | `300` |  |
| `PTC_MAX_CALLS` | int | `50` |  |
| `PTC_MAX_STDOUT_BYTES` | int | `51200` |  |
| `PTC_ALLOWED_TOOLS` | csv | `""` |  |

## Control plane backend

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `CONTROL_PLANE_BACKEND` | enum | `sqlite` | `memory` or `sqlite`. |
| `CONTROL_PLANE_DB_PATH` | str | `agent33_control_plane.db` |  |

## Training

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `TRAINING_ENABLED` | bool | `true` |  |
| `TRAINING_OPTIMIZE_INTERVAL` | int | `100` |  |
| `TRAINING_IDLE_OPTIMIZE_SECONDS` | int | `300` |  |
| `TRAINING_MIN_ROLLOUTS` | int | `10` |  |
| `TRAINING_EVAL_MODEL` | str | `""` |  |

## Alembic

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ALEMBIC_CONFIG_PATH` | str | `alembic.ini` |  |
| `ALEMBIC_AUTO_CHECK_ON_STARTUP` | bool | `false` |  |

## Component security scans

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `COMPONENT_SECURITY_SCAN_STORE_ENABLED` | bool | `false` |  |
| `COMPONENT_SECURITY_SCAN_STORE_DB_PATH` | str | `var/component_security_scans.sqlite3` |  |
| `COMPONENT_SECURITY_SCAN_STORE_RETENTION_DAYS` | int | `90` |  |

## Lite mode

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SQLITE_MEMORY_DB_PATH` | str | `var/agent33_memory.db` | Lite-mode long-term memory path. Use `:memory:` for ephemeral. |

## See also

- [setup-guide.md](setup-guide.md) — how to layer settings across environments.
- [../INSTALL.md](../INSTALL.md) — environment-specific examples.
- [troubleshooting.md](troubleshooting.md) — common misconfigurations.
- The authoritative source is always `engine/src/agent33/config.py`; if a value
  here disagrees with the code, the code wins.
