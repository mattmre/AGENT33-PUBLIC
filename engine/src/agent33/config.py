"""Application configuration via environment variables."""

from __future__ import annotations

import json
import logging
import os
import secrets
import string
from typing import Literal
from urllib.parse import urlparse, urlunparse

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

_logger = logging.getLogger(__name__)
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def resolve_runtime_service_url(url: str) -> str:
    """Rewrite loopback service URLs when the engine runs inside Docker."""
    normalized = url.strip()
    if not normalized or not os.path.exists("/.dockerenv"):
        return normalized

    parsed = urlparse(normalized)
    if parsed.hostname not in _LOOPBACK_HOSTS:
        return normalized

    credentials = ""
    if parsed.username:
        credentials = parsed.username
        if parsed.password:
            credentials += f":{parsed.password}"
        credentials += "@"

    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunparse(parsed._replace(netloc=f"{credentials}host.docker.internal{port}"))


class Settings(BaseSettings):
    """AGENT-33 engine settings loaded from environment."""

    model_config = {
        "env_prefix": "",
        "env_file": (".env", ".env.local"),
        "extra": "ignore",
    }

    # API
    api_port: int = 8000
    api_log_level: str = "info"
    api_secret_key: SecretStr = SecretStr("change-me-in-production")
    cors_allowed_origins: str = ""  # comma-separated; empty = deny all origins (secure default)
    max_request_size_bytes: int = 10 * 1024 * 1024  # 10 MB default

    # Ollama
    default_model: str = ""
    ollama_base_url: str = "http://ollama:11434"
    ollama_default_model: str = "llama3.2:3b"
    lm_studio_base_url: str = "http://localhost:1234/v1"
    lm_studio_default_model: str = "local-model"

    # Local small-LLM & Ultra-Sparse Orchestration
    # (optimized for single RTX 3090 - 24GB VRAM).
    # Top targets: Qwen3-Coder-Next (via llama.cpp tensor offloading),
    # Qwen2.5-Coder-32B-Instruct-abliterated, Lexi-3.0.
    local_orchestration_model: str = "qwen3-coder-next"
    local_orchestration_format: str = "gguf_q4_k_m"
    local_orchestration_engine: str = "llama.cpp"
    local_orchestration_base_url: str = "http://host.docker.internal:8033/v1"

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://agent33:agent33@postgres:5432/agent33"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_pre_ping: bool = True
    db_pool_recycle: int = 1800  # seconds; recycle connections after 30 min

    # Redis
    redis_url: str = "redis://redis:6379/0"
    redis_max_connections: int = 50

    # NATS
    nats_url: str = "nats://nats:4222"

    # Security
    jwt_secret: SecretStr = SecretStr("change-me-in-production")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    encryption_key: SecretStr = SecretStr("")
    auth_bootstrap_enabled: bool = False
    auth_bootstrap_admin_username: str = "admin"
    auth_bootstrap_admin_password: SecretStr = SecretStr("")
    auth_bootstrap_admin_scopes: str = (
        "admin,agents:read,agents:write,agents:invoke,"
        "workflows:read,workflows:write,workflows:execute,tools:execute"
    )
    component_security_scan_store_enabled: bool = False
    component_security_scan_store_db_path: str = "var/component_security_scans.sqlite3"
    component_security_scan_store_retention_days: int = 90

    # Policy control (Gate 3.2)
    tool_use_mode: str = "audit"  # "audit" | "dry-run" | "approved"
    evidence_required: bool = True
    review_authority: str = "user"  # "user" | "automation" | "disabled"

    # Secret redaction in logs & tool output (Phase 52)
    redact_secrets_enabled: bool = True

    # Rate limiting (per-tenant, sliding window)
    rate_limit_enabled: bool = True
    rate_limit_default_tier: str = "standard"
    rate_limit_per_minute: int = 60  # max tool executions per minute
    rate_limit_burst: int = 10  # max burst above per-minute rate

    # SearXNG
    searxng_url: str = "http://searxng:8080"

    # Web search providers (Track 7)
    tavily_api_key: SecretStr = SecretStr("")
    brave_api_key: SecretStr = SecretStr("")
    web_search_max_results: int = 10
    web_search_default_provider: str | None = None

    # Optional cloud LLM
    openai_api_key: SecretStr = SecretStr("")
    openai_base_url: str = ""
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = "http://localhost"
    openrouter_app_name: str = "AGENT-33"
    openrouter_app_category: str = "cli-agent"
    openrouter_default_fallback_models: str = ""
    elevenlabs_api_key: SecretStr = SecretStr("")
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    voice_daemon_enabled: bool = True
    voice_daemon_transport: str = "stub"  # stub | sidecar | livekit
    voice_daemon_url: str = ""
    voice_daemon_api_key: SecretStr = SecretStr("")
    voice_daemon_api_secret: SecretStr = SecretStr("")
    voice_daemon_room_prefix: str = "agent33-voice"
    voice_daemon_max_sessions: int = 25
    voice_sidecar_url: str = ""
    voice_sidecar_probe_timeout_seconds: float = 2.0
    voice_sidecar_voices_path: str = "config/voice/voices.json"
    voice_sidecar_artifacts_dir: str = "var/voice-sidecar"
    voice_sidecar_playback_backend: str = "noop"

    # ElevenLabs audio transport (S31)
    voice_elevenlabs_enabled: bool = False
    voice_elevenlabs_api_key: SecretStr = SecretStr("")
    voice_elevenlabs_default_voice_id: str = ""
    voice_elevenlabs_model_id: str = "eleven_multilingual_v2"

    # LiveKit media transport (S32)
    voice_livekit_enabled: bool = False
    voice_livekit_api_key: SecretStr = SecretStr("")
    voice_livekit_api_secret: SecretStr = SecretStr("")
    voice_livekit_ws_url: str = ""

    # Phase 35: provider-agnostic TTS/STT
    voice_tts_provider: str = "stub"  # stub | elevenlabs | piper
    voice_stt_provider: str = "stub"  # stub | whisper | openai_whisper
    voice_stt_whisper_model_size: str = "base"  # tiny | base | small | medium | large
    voice_stt_whisper_device: str = "cpu"  # cpu | cuda
    voice_tts_piper_model_path: str = ""
    voice_tts_piper_voice_id: str = "en_US-lessac-medium"
    voice_stt_openai_api_key: SecretStr = SecretStr("")
    voice_stt_openai_model: str = "whisper-1"

    # AirLLM (layer-sharded large model inference)
    airllm_enabled: bool = False
    airllm_model_path: str = ""
    airllm_device: str = "cuda:0"
    airllm_compression: str = ""  # "4bit" | "8bit" | ""
    airllm_max_seq_len: int = 2048
    airllm_prefetch: bool = True

    # Jina
    jina_api_key: SecretStr = SecretStr("")
    jina_reader_url: str = "https://r.jina.ai"

    # Embeddings
    embedding_provider: str = "ollama"  # "ollama" | "jina"
    embedding_dim: int = 768  # nomic-embed-text=768, text-embedding-3-large=1536

    # HTTP client pool settings
    http_max_connections: int = 20
    http_max_keepalive: int = 10
    embedding_batch_size: int = 100

    # Embedding cache
    embedding_cache_enabled: bool = True
    embedding_cache_max_size: int = 1024

    # Embedding hot-swap (S44)
    embedding_hot_swap_enabled: bool = False
    embedding_default_model: str = "nomic-embed-text"
    embedding_default_dimensions: int = 768

    # Embedding quantization (TurboQuant-style compression)
    embedding_quantization_enabled: bool = False  # opt-in, requires numpy
    embedding_quantization_bits: int = 4  # 4-bit = ~8× compression
    embedding_quantization_seed: int = 42

    # RAG / Hybrid search
    rag_top_k: int = 5
    rag_similarity_threshold: float = 0.3
    rag_hybrid_enabled: bool = True
    rag_vector_weight: float = 0.7  # BM25 weight = 1 - vector_weight
    rag_rrf_k: int = 60

    # Chunking
    chunk_tokens: int = 1200
    chunk_overlap_tokens: int = 100

    # BM25 warm-up
    bm25_warmup_enabled: bool = True
    bm25_warmup_max_records: int = 10_000
    bm25_warmup_page_size: int = 200

    # Knowledge ingestion (P70)
    knowledge_default_tenant_id: str = "system"

    # Training (self-evolving loop)
    training_enabled: bool = True
    training_optimize_interval: int = 100
    training_idle_optimize_seconds: int = 300
    training_min_rollouts: int = 10
    training_eval_model: str = ""

    # Evaluation
    evaluation_judge_model: str = ""
    """Model identifier for the LLM evaluation judge.

    When empty (default), the LLM evaluator is not registered and the
    rule-based evaluator remains the default.  Set to a model ID such as
    ``"llama3.2"`` or ``"gpt-4o-mini"`` to enable the LLM judge backend.
    """

    # Agent definitions
    agent_definitions_dir: str = "agent-definitions"
    agent_effort_routing_enabled: bool = False
    agent_effort_default: str = "medium"
    agent_effort_low_model: str = ""
    agent_effort_medium_model: str = ""
    agent_effort_high_model: str = ""
    agent_effort_low_token_multiplier: float = 1.0
    agent_effort_medium_token_multiplier: float = 1.0
    agent_effort_high_token_multiplier: float = 1.0
    agent_effort_heuristic_enabled: bool = True
    agent_effort_policy_tenant: str = ""  # JSON object: {"tenant-id": "low|medium|high"}
    agent_effort_policy_domain: str = ""  # JSON object: {"domain": "low|medium|high"}
    agent_effort_policy_tenant_domain: str = (
        ""  # JSON object: {"tenant-id|domain": "low|medium|high"}
    )
    agent_effort_cost_per_1k_tokens: float = 0.0
    agent_effort_heuristic_low_score_threshold: int = 1
    agent_effort_heuristic_high_score_threshold: int = 4
    agent_effort_heuristic_medium_payload_chars: int = 800
    agent_effort_heuristic_large_payload_chars: int = 2000
    agent_effort_heuristic_many_input_fields_threshold: int = 10
    agent_effort_heuristic_high_iteration_threshold: int = 15
    # Phase 49: fast-path pre-filter thresholds for simple messages
    heuristic_simple_max_chars: int = 160
    heuristic_simple_max_words: int = 28
    pricing_catalog_overrides: str = ""
    """Optional JSON array of pricing override entries applied at startup."""
    # Rolling-window metrics (P3.6)
    metrics_rolling_window_seconds: int = 300  # 5-minute rolling window for observations

    observability_effort_alerts_enabled: bool = True
    observability_effort_alert_high_effort_count_threshold: int = 25
    observability_effort_alert_high_cost_usd_threshold: float = 5.0
    observability_effort_alert_high_token_budget_threshold: int = 8000
    observability_effort_export_enabled: bool = False
    observability_effort_export_path: str = "var/effort_routing_events.jsonl"
    observability_effort_export_fail_closed: bool = False

    # Plugins (Phase 32.8 — Plugin SDK)
    plugin_definitions_dir: str = "plugins"
    plugin_auto_enable: bool = True  # Auto-enable plugins after loading
    plugin_state_store_path: str = "var/plugin_lifecycle_state.json"
    plugin_allowlist: str = ""  # comma-separated list of allowed plugin names (empty = allow all)
    plugin_discovery_paths: str = ""  # comma-separated extra directories to scan for plugins

    # Skills
    skill_definitions_dir: str = "skills"
    skill_max_instructions_chars: int = 16000
    skill_lineage_store_path: str = "var/skill_lineage_events.json"
    skillsbench_skill_matcher_enabled: bool = False
    skillsbench_skill_matcher_model: str = "llama3.2"
    skillsbench_skill_matcher_top_k: int = 20
    skillsbench_skill_matcher_skip_llm_below: int = 3
    skillsbench_context_manager_enabled: bool = True
    skillsbench_storage_path: str = "var/skillsbench_runs"

    # P69b tool-approval persistence
    p69b_db_path: str = "var/p69b.db"

    # Phase 23 lifecycle persistence
    phase23_lifecycle_backend: Literal["memory", "sqlite"] = "sqlite"
    phase23_auth_db_path: str = "var/phase23_auth_lifecycle.db"
    phase23_workspace_db_path: str = "var/phase23_workspace_lifecycle.db"

    # Ingestion persistence (Sprint 1)
    ingestion_db_path: str = "var/ingestion.db"

    # Ingestion mailbox inbox persistence (Session 132)
    ingestion_mailbox_db_path: str = "var/ingestion_mailbox.db"

    # Ingestion journal persistence (Sprint 4)
    ingestion_journal_db_path: str = "var/ingestion_journal.db"
    ingestion_journal_retention_days: int = 90  # 0 disables journal expiry
    ingestion_task_metrics_db_path: str = "var/ingestion_task_metrics.db"
    ingestion_task_metrics_retention_days: int = 30  # 0 disables task-metrics expiry
    ingestion_notification_hooks_db_path: str = "var/ingestion_notification_hooks.db"
    ingestion_notification_timeout_seconds: float = 5.0

    # Outcomes persistence (P72)
    outcomes_db_path: str = "var/outcomes.db"
    ppack_v3_ab_db_path: str = "var/ppack_ab.db"
    ppack_v3_ab_enabled: bool = True
    ppack_v3_enabled: bool = False
    ppack_v3_ab_experiment_key: str = "ppack_v3"
    ppack_v3_ab_min_samples_per_variant: int = 30
    ppack_v3_ab_regression_threshold: float = -0.05
    ppack_v3_ab_weekly_window_days: int = 7
    ppack_v3_ab_issue_alert_enabled: bool = False
    ppack_v3_ab_github_owner: str = ""
    ppack_v3_ab_github_repo: str = ""
    ppack_v3_ab_github_token: SecretStr = SecretStr("")

    # Skill Packs
    pack_definitions_dir: str = "packs"
    pack_marketplace_dir: str = "pack-marketplace"
    pack_marketplace_remote_sources: str = ""  # JSON array of remote source configs
    pack_marketplace_cache_dir: str = "var/pack-marketplace-cache"
    pack_auto_enable: bool = False
    pack_max_size_mb: int = 50
    pack_checksums_required: bool = False
    pack_rollback_archive_dir: str = "var/pack-rollback-archive"
    pack_curation_enabled: bool = False
    pack_min_quality_score: float = 0.5
    pack_require_review_for_listing: bool = True
    pack_default_categories: str = (
        "automation,data-analysis,devops,security,testing,"
        "ai-ml,integration,workflow,research,general"
    )
    pack_signing_key: str = ""

    # MCP (Model Context Protocol) servers
    mcp_servers: str = ""  # Comma-separated server URLs
    mcp_timeout_seconds: float = 30.0
    mcp_auto_discover: bool = True

    # MCP Proxy (Phase 45)
    mcp_proxy_config_path: str = ""  # path to mcp.config.json
    mcp_proxy_enabled: bool = False
    mcp_proxy_tool_separator: str = "__"
    mcp_proxy_health_check_enabled: bool = True

    # Approval Tokens (Phase 45)
    approval_token_ttl_seconds: int = 300  # 5 minutes
    approval_token_enabled: bool = True
    approval_token_one_time_default: bool = True

    # MCP Sync (Phase 45)
    mcp_sync_backup_enabled: bool = True  # create .bak before writing CLI configs
    tool_discovery_mode: str = "legacy"  # legacy | dynamic
    connector_boundary_enabled: bool = False
    connector_policy_pack: str = "default"
    connector_governance_blocked_connectors: str = ""  # comma-separated
    connector_governance_blocked_operations: str = ""  # comma-separated
    connector_circuit_breaker_enabled: bool = False
    connector_circuit_failure_threshold: int = 3
    connector_circuit_recovery_seconds: float = 30.0
    connector_circuit_half_open_successes: int = 2
    connector_circuit_max_recovery_seconds: float = 300.0

    # Jupyter kernel execution
    jupyter_kernel_enabled: bool = False
    jupyter_kernel_adapter_id: str = "jupyter-kernel"
    jupyter_kernel_tool_id: str = "code-interpreter"
    jupyter_kernel_mode: str = "local"  # local | docker
    jupyter_kernel_name: str = "python3"
    jupyter_kernel_max_sessions: int = 10
    jupyter_kernel_idle_timeout_seconds: float = 300.0
    jupyter_kernel_startup_timeout_seconds: float = 30.0
    jupyter_kernel_execution_timeout_seconds: float = 60.0
    jupyter_kernel_docker_image: str = "quay.io/jupyter/minimal-notebook:python-3.11"
    jupyter_kernel_allowed_images: str = ""
    jupyter_kernel_network_enabled: bool = False
    jupyter_kernel_mount_workdir: bool = True
    jupyter_kernel_container_workdir: str = "/workspace"

    # Agent profiling (S40)
    agent_profiler_max_profiles: int = 1000

    # Context window budgeting (S27)
    agent_default_context_window: int = 128000
    agent_context_warn_threshold: float = 0.8

    # Tool loop scoring (S28)
    agent_tool_loop_max_retries: int = 3
    agent_tool_loop_backoff_base_ms: float = 100

    # Skill match calibration (S29)
    skill_match_fuzzy_threshold: float = 0.7
    skill_match_semantic_threshold: float = 0.5
    skill_match_contextual_threshold: float = 0.4
    skill_match_max_candidates: int = 10

    # GPU / Custom Docker image execution (S30)
    execution_gpu_enabled: bool = False
    execution_default_docker_image: str = "python:3.11-slim"
    execution_gpu_runtime: str = "nvidia"  # nvidia | amd

    # Hook framework
    hooks_enabled: bool = True
    hooks_definitions_dir: str = "hook-definitions"
    hooks_default_timeout_ms: float = 200.0
    hooks_chain_timeout_ms: float = 500.0
    hooks_fail_open_default: bool = True
    hooks_max_per_event: int = 20
    hooks_execution_log_enabled: bool = True
    hooks_execution_log_retention_hours: int = 24

    # Provenance
    provenance_enabled: bool = True
    provenance_max_receipts: int = 10000

    # Environment
    environment: str = "development"

    # Deployment mode (P60a — lite/standard/enterprise)
    # Defaults to "standard" for backward compatibility with existing deployments.
    agent33_mode: Literal["lite", "standard", "enterprise"] = "standard"

    # SQLite long-term memory path (P60b — used when agent33_mode=lite or no database_url)
    # Set to ":memory:" for ephemeral in-process storage (useful in tests).
    sqlite_memory_db_path: str = "var/agent33_memory.db"

    # Matrix messaging adapter
    matrix_homeserver_url: str = ""  # e.g. "https://matrix.org"
    matrix_access_token: SecretStr = SecretStr("")
    matrix_user_id: str = ""  # e.g. "@agent33:matrix.org"
    matrix_room_ids: str = ""  # comma-separated room IDs (empty = all joined rooms)
    matrix_sync_timeout_ms: int = 30_000

    # Self-improvement
    self_improve_enabled: bool = True
    self_improve_scope: str = "prompts,workflows,templates"
    self_improve_require_approval: bool = True
    self_improve_proposal_sandbox_enabled: bool = True
    autonomy_max_stretch_hours: int = 24
    autonomy_allow_security_recon: bool = True
    # P67: 0=supervised, 1=read-auto/write-approval, 2=auto-no-destructive, 3=full
    autonomy_default_level: int = 1
    offline_mode: bool = False
    intake_output_dir: str = "var/repo_dossiers"
    analysis_template_dir: str = "docs/research/templates"
    synthetic_env_workflow_dir: str = "workflow-definitions"
    synthetic_env_tool_dir: str = "tool-definitions"
    synthetic_env_bundle_retention: int = 100
    synthetic_env_bundle_persistence_path: str = "var/synthetic_environment_bundles.json"
    orchestration_state_store_path: str = "var/orchestration_state.json"
    workflow_run_archive_dir: str = "var/workflow-runs"
    process_manager_log_dir: str = "var/process-manager"
    process_manager_max_processes: int = 10
    backup_dir: str = "var/backups"

    # Workflow template marketplace (S41)
    workflow_marketplace_enabled: bool = True
    workflow_templates_dir: str = "workflow-templates"

    # Continuous improvement learning signals (Phase 31)
    improvement_learning_enabled: bool = False
    improvement_learning_summary_default_limit: int = 50
    improvement_learning_auto_intake_enabled: bool = False
    improvement_learning_auto_intake_min_severity: str = "high"
    improvement_learning_auto_intake_max_items: int = 3
    improvement_learning_persistence_backend: str = "db"  # memory | file | db
    improvement_learning_persistence_path: str = "var/improvement_learning_signals.json"
    improvement_learning_persistence_db_path: str = "var/improvement_learning_signals.sqlite3"
    improvement_learning_persistence_migrate_on_start: bool = False
    improvement_learning_persistence_migration_backup_on_start: bool = False
    improvement_learning_persistence_migration_backup_path: str = (
        "var/improvement_learning_signals.backup.json"
    )
    improvement_learning_file_corruption_behavior: str = "reset"  # reset | raise
    improvement_learning_db_corruption_behavior: str = "reset"  # reset | raise
    improvement_learning_dedupe_window_minutes: int = 30
    improvement_learning_retention_days: int = 180
    improvement_learning_max_signals: int = 5000
    improvement_learning_max_generated_intakes: int = 1000
    improvement_learning_auto_intake_min_quality: float = 0.45
    improvement_learning_max_metrics_snapshots: int = 100

    # Quality scoring parameters (Phase 31 signal tuning)
    improvement_quality_weight_summary: float = 0.25
    improvement_quality_weight_details: float = 0.20
    improvement_quality_weight_source: float = 0.10
    improvement_quality_weight_context: float = 0.10
    improvement_quality_weight_severity: float = 0.35
    improvement_quality_high_threshold: float = 0.70
    improvement_quality_medium_threshold: float = 0.45

    # Trend detection (Phase 31 signal tuning)
    improvement_metrics_trend_threshold: float = 0.05

    # Tuning loop automation (Phase 31)
    improvement_tuning_loop_enabled: bool = False
    improvement_tuning_loop_interval_hours: float = 24.0
    improvement_tuning_loop_max_quality_delta: float = 0.15
    improvement_tuning_loop_max_retention_delta_days: int = 30
    improvement_tuning_loop_require_approval: bool = True
    improvement_tuning_loop_dry_run: bool = False
    improvement_tuning_loop_min_sample_size: int = 10

    # Comparative evaluation (AWM Tier 2 group-relative scoring)
    comparative_elo_k_factor: float = 32.0  # K-factor for Elo rating updates
    comparative_min_population_size: int = 2  # min agents for round-robin
    comparative_confidence_level: float = 0.95  # stat. significance threshold

    # CTRF reporting (SkillsBench integration)
    evaluation_ctrf_output_dir: str = "var/ctrf-reports"

    # Benchmark harness (S26)
    evaluation_benchmark_catalog_path: str = ""  # path to custom catalog JSON
    evaluation_benchmark_default_trials: int = 5

    # Phase 44: Operator session
    operator_session_enabled: bool = True
    operator_session_base_dir: str = ""  # default: ~/.agent33/sessions/
    operator_session_checkpoint_interval_seconds: float = 60.0
    operator_session_max_replay_file_mb: int = 50
    operator_session_max_retained: int = 100
    operator_session_crash_recovery_enabled: bool = True

    # Phase 51: Anthropic prompt caching
    prompt_cache_enabled: bool = True

    # Phase 50: Context compression engine
    context_compression_enabled: bool = False
    context_compression_threshold_percent: float = 0.50
    context_compression_protect_first_n: int = 3
    context_compression_tail_token_budget: int = 20_000
    context_compression_summary_target_ratio: float = 0.20
    context_compression_summary_tokens_ceiling: int = 12_000
    context_compression_summarize_model: str = "llama3.2"

    # Track 8: Context engine and session catalog
    context_engine_default: str = "builtin"
    context_compaction_enabled: bool = True
    session_spawn_templates_dir: str = ""
    session_archive_retention_days: int = 90

    # Phase 44: Script hooks
    script_hooks_enabled: bool = True
    script_hooks_project_dir: str = ""  # default: <cwd>/.claude/hooks/
    script_hooks_user_dir: str = ""  # default: ~/.agent33/hooks/
    script_hooks_default_timeout_ms: float = 5000.0
    script_hooks_max_timeout_ms: float = 30000.0

    # Scheduled evaluation gates (S45)
    scheduled_gates_enabled: bool = False
    scheduled_gates_max_schedules: int = 50
    scheduled_gates_history_retention: int = 100

    # Alembic migration checker (S34)
    alembic_config_path: str = "alembic.ini"
    alembic_auto_check_on_startup: bool = False

    # Control-plane repository backend (P4.5)
    control_plane_backend: str = "sqlite"  # "memory" or "sqlite"
    control_plane_db_path: str = "agent33_control_plane.db"

    # Webhook delivery reliability (S43)
    webhook_delivery_max_retries: int = 5
    webhook_delivery_base_delay: float = 1.0
    webhook_delivery_max_delay: float = 300.0
    webhook_delivery_max_records: int = 10_000

    # SLO thresholds (P3.3)
    slo_availability_target: float = 0.999  # 99.9%
    slo_latency_p99_ms: int = 500  # milliseconds
    slo_latency_agent_p99_ms: int = 10000  # milliseconds for agent invocations

    # Query profiling (P1.4)
    slow_query_threshold_ms: int = 100  # log WARNING when a tracked DB op exceeds this

    # Agent streaming transport (P2.5)
    streaming_max_connections: int = 100
    streaming_ping_interval_seconds: int = 30

    # Workflow transport (S33: WS-first / SSE fallback)
    workflow_transport_preferred: str = "auto"  # auto | websocket | sse
    workflow_ws_ping_interval: float = 30.0
    workflow_ws_ping_timeout: float = 10.0
    # SSE schema v2 rollout (backend foundation only; v1 remains the default).
    # Kill switch: /tmp/agent33_disable_sse_v2
    sse_schema_v2_enabled: bool = False

    # Session trajectory capture (Phase 59)
    trajectory_capture_enabled: bool = False  # opt-in
    trajectory_output_dir: str = "trajectories"

    # Mixture-of-Agents (Phase 58)
    moa_reference_models: str = ""  # comma-separated model IDs for the parallel reference layer
    moa_aggregator_model: str = ""  # model ID for the aggregator/synthesis step
    moa_reference_temperature: float = 0.6
    moa_aggregator_temperature: float = 0.4

    # Browser automation (Phase 55)
    browser_cloud_api_key: SecretStr = SecretStr("")  # BrowserBase API key; empty = local only
    browser_session_ttl_seconds: int = 300  # idle TTL before session cleanup
    browser_vision_model: str = ""  # model for vision_analyze; empty = auto-detect
    browser_cloud_api_url: str = "https://www.browserbase.com/v1"
    browser_computer_use_enabled: bool = False
    max_browser_sessions_per_tenant: int = 3

    # Checkpoint persistence (W18-F2)
    checkpoint_persistence_enabled: bool = False

    # Programmatic Tool Calling (Phase 56)
    ptc_enabled: bool = True
    ptc_timeout_s: int = 300
    ptc_max_calls: int = 50
    ptc_max_stdout_bytes: int = 51200  # 50 KB
    ptc_allowed_tools: str = ""  # comma-separated override; empty = default list

    @property
    def runtime_ollama_base_url(self) -> str:
        """Return the Ollama URL that runtime code should use."""
        return resolve_runtime_service_url(self.ollama_base_url)

    @property
    def runtime_lm_studio_base_url(self) -> str:
        """Return the LM Studio URL that runtime code should use."""
        return resolve_runtime_service_url(self.lm_studio_base_url)

    @property
    def runtime_local_orchestration_base_url(self) -> str:
        """Return the local orchestration URL that runtime code should use."""
        return resolve_runtime_service_url(self.local_orchestration_base_url)

    @field_validator("control_plane_backend")
    @classmethod
    def _validate_control_plane_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"memory", "sqlite"}:
            raise ValueError("control_plane_backend must be one of: memory, sqlite")
        return normalized

    @field_validator("phase23_lifecycle_backend")
    @classmethod
    def _validate_phase23_lifecycle_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"memory", "sqlite"}:
            raise ValueError("phase23_lifecycle_backend must be one of: memory, sqlite")
        return normalized

    @field_validator("workflow_transport_preferred")
    @classmethod
    def _validate_workflow_transport_preferred(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"auto", "websocket", "sse"}:
            raise ValueError("workflow_transport_preferred must be one of: auto, websocket, sse")
        return normalized

    @field_validator(
        "improvement_learning_file_corruption_behavior",
        "improvement_learning_db_corruption_behavior",
    )
    @classmethod
    def _validate_learning_corruption_behavior(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"reset", "raise"}:
            raise ValueError("corruption behavior must be one of: reset, raise")
        return normalized

    @field_validator("jupyter_kernel_mode")
    @classmethod
    def _validate_jupyter_kernel_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"local", "docker"}:
            raise ValueError("jupyter kernel mode must be one of: local, docker")
        return normalized

    @field_validator("voice_daemon_transport")
    @classmethod
    def _validate_voice_daemon_transport(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"stub", "sidecar", "livekit"}:
            raise ValueError("voice_daemon_transport must be one of: stub, sidecar, livekit")
        return normalized

    @field_validator("voice_tts_provider")
    @classmethod
    def _validate_voice_tts_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"stub", "elevenlabs", "piper"}:
            raise ValueError("voice_tts_provider must be one of: stub, elevenlabs, piper")
        return normalized

    @field_validator("voice_stt_provider")
    @classmethod
    def _validate_voice_stt_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"stub", "whisper", "openai_whisper"}:
            raise ValueError("voice_stt_provider must be one of: stub, whisper, openai_whisper")
        return normalized

    @field_validator("tool_discovery_mode")
    @classmethod
    def _validate_tool_discovery_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"legacy", "dynamic"}:
            raise ValueError("tool_discovery_mode must be one of: legacy, dynamic")
        return normalized

    @field_validator("execution_gpu_runtime")
    @classmethod
    def _validate_execution_gpu_runtime(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"nvidia", "amd"}:
            raise ValueError("execution_gpu_runtime must be one of: nvidia, amd")
        return normalized

    @field_validator(
        "component_security_scan_store_retention_days",
        "ingestion_journal_retention_days",
        "ingestion_task_metrics_retention_days",
        "improvement_learning_dedupe_window_minutes",
        "improvement_learning_retention_days",
        "improvement_learning_max_signals",
        "improvement_learning_max_generated_intakes",
        "voice_daemon_max_sessions",
        "process_manager_max_processes",
    )
    @classmethod
    def _validate_learning_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("learning persistence settings must be non-negative")
        return value

    @field_validator(
        "agent_effort_heuristic_low_score_threshold",
        "agent_effort_heuristic_high_score_threshold",
        "agent_effort_heuristic_medium_payload_chars",
        "agent_effort_heuristic_large_payload_chars",
        "agent_effort_heuristic_many_input_fields_threshold",
        "agent_effort_heuristic_high_iteration_threshold",
    )
    @classmethod
    def _validate_phase30_heuristic_thresholds(cls, value: int) -> int:
        if value < 0:
            raise ValueError("agent effort heuristic settings must be non-negative")
        return value

    @field_validator("pricing_catalog_overrides")
    @classmethod
    def _validate_pricing_catalog_overrides(cls, value: str) -> str:
        if not value.strip():
            return value
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("pricing_catalog_overrides must be valid JSON") from exc
        if not isinstance(parsed, list):
            raise ValueError("pricing_catalog_overrides must be a JSON array")
        return value

    @model_validator(mode="after")
    def _validate_phase30_heuristic_threshold_order(self) -> Settings:
        if self.agent_effort_heuristic_high_score_threshold <= (
            self.agent_effort_heuristic_low_score_threshold
        ):
            raise ValueError(
                "agent_effort_heuristic_high_score_threshold must be greater than "
                "agent_effort_heuristic_low_score_threshold"
            )
        if self.agent_effort_heuristic_large_payload_chars <= (
            self.agent_effort_heuristic_medium_payload_chars
        ):
            raise ValueError(
                "agent_effort_heuristic_large_payload_chars must be greater than "
                "agent_effort_heuristic_medium_payload_chars"
            )
        return self

    @field_validator("improvement_learning_auto_intake_min_quality")
    @classmethod
    def _validate_learning_quality_threshold(cls, value: float) -> float:
        if value < 0.0 or value > 1.0:
            raise ValueError(
                "improvement_learning_auto_intake_min_quality must be between 0.0 and 1.0"
            )
        return value

    @field_validator("improvement_learning_auto_intake_max_items")
    @classmethod
    def _validate_learning_auto_intake_max_items(cls, value: int) -> int:
        if value < 1:
            raise ValueError("improvement_learning_auto_intake_max_items must be at least 1")
        return value

    @field_validator("improvement_learning_auto_intake_min_severity")
    @classmethod
    def _validate_learning_auto_intake_severity(cls, value: str) -> str:
        allowed = {"low", "medium", "high", "critical"}
        normalized = value.strip().lower()
        if normalized not in allowed:
            raise ValueError(
                "improvement_learning_auto_intake_min_severity must be one of: "
                "low, medium, high, critical"
            )
        return normalized

    @model_validator(mode="after")
    def _validate_jwt_secret_not_default(self) -> Settings:
        """AEP-A01: Reject the default JWT secret in non-dev/test environments.

        In ``lite`` mode (or when ``environment`` is ``development``/``test``),
        auto-generate a secure random JWT secret if the caller left the default
        placeholder in place.  A prominent WARNING is emitted so operators are
        never silently using an ephemeral secret in a context where they would
        expect persistence.

        In ``standard`` / ``enterprise`` mode with a non-safe environment, the
        original ``SystemExit`` behaviour is preserved.
        """
        _safe_envs = {"development", "test"}
        _dev_modes = {"lite"}

        if self.jwt_secret.get_secret_value() != "change-me-in-production":
            # Caller supplied an explicit secret — nothing to do.
            return self

        if self.environment in _safe_envs or self.agent33_mode in _dev_modes:
            # Auto-generate a random secret and warn loudly.
            alphabet = string.ascii_letters + string.digits
            generated = "".join(secrets.choice(alphabet) for _ in range(64))
            object.__setattr__(self, "jwt_secret", SecretStr(generated))
            _logger.warning(
                "WARNING: Auto-generated JWT_SECRET for %s/%s mode. DO NOT use in production.",
                self.environment,
                self.agent33_mode,
            )
            return self

        _logger.critical(
            "FATAL: jwt_secret is using the insecure default value "
            "in environment=%s. Set the JWT_SECRET environment variable "
            "to a strong random value before starting the application.",
            self.environment,
        )
        raise SystemExit(
            "Refusing to start: jwt_secret must be changed from the default "
            f"in environment={self.environment!r}. "
            "Set JWT_SECRET to a cryptographically random value."
        )

    @model_validator(mode="after")
    def _warn_default_database_credentials(self) -> Settings:
        """AEP-A02: Warn when default database credentials are detected."""
        _safe_envs = {"development", "test"}
        if "agent33:agent33@" in self.database_url and self.environment not in _safe_envs:
            _logger.warning(
                "Default database credentials detected in database_url "
                "for environment=%s. Rotate the credentials before "
                "deploying to a non-development environment.",
                self.environment,
            )
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Wire in ProfileSettingsSource between dotenv and file secrets.

        Priority (highest to lowest):
        1. init_settings — values passed directly to Settings(...)
        2. env_settings — environment variables (e.g. AGENT33_MODE=enterprise)
        3. dotenv_settings — .env file
        4. ProfileSettingsSource — profile preset via AGENT33_PROFILE env var
        5. file_secret_settings — mounted secrets
        """
        import os

        from agent33.config_profiles import ProfileSettingsSource

        profile_name = os.environ.get("AGENT33_PROFILE")
        profile_source = ProfileSettingsSource(settings_cls, profile_name=profile_name)
        return (init_settings, env_settings, dotenv_settings, profile_source, file_secret_settings)

    def check_production_secrets(self) -> list[str]:
        """Check for default secrets.  Raises in production mode."""
        warnings = []
        if self.api_secret_key.get_secret_value() == "change-me-in-production":
            warnings.append("api_secret_key is using the default value")
        if self.jwt_secret.get_secret_value() == "change-me-in-production":
            warnings.append("jwt_secret is using the default value")
        if self.auth_bootstrap_enabled:
            warnings.append("auth_bootstrap_enabled is true")
        bootstrap_password = self.auth_bootstrap_admin_password.get_secret_value()
        if self.auth_bootstrap_enabled and bootstrap_password in {"", "admin"}:
            warnings.append("auth_bootstrap_admin_password is empty or using default value")
        if warnings and self.environment == "production":
            raise RuntimeError(
                "FATAL: Default secrets in production mode. "
                f"Override via environment variables: {', '.join(warnings)}"
            )
        return warnings


settings = Settings()
