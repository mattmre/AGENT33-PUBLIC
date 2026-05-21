"""FastAPI application entry point with full integration wiring."""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from agent33.llm.router import ModelRouter

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from agent33.api.middleware.session_pod import SessionPodMiddleware
from agent33.api.routes import (
    agents,
    artifacts,
    auth,
    autonomy,
    backups,
    benchmarks,
    browser_sessions,
    chat,
    checkpoints,
    commands,
    comparative,
    compatibility,
    completion_gate,
    component_security,
    connectors,
    context,
    cron,
    dashboard,
    delegation,
    doctor,
    evaluations,
    explanations,
    health,
    hooks,
    improvements,
    ingestion,
    insights,
    knowledge,
    lm_studio,
    marketplace,
    mcp,
    mcp_proxy,
    mcp_sync,
    memory_search,
    migrations,
    moa,
    model_health,
    multimodal,
    ollama,
    openrouter,
    operations,
    operations_hub,
    operator,
    outcomes,
    p69b,
    packs,
    planning,
    policy,
    processes,
    provenance,
    rag,
    reasoning,
    releases,
    replay,
    research,
    resources,
    reviews,
    run_ledger,
    sandboxing,
    sessions,
    spawner,
    step_retry,
    streaming,
    support,
    synthetic_envs,
    tool_approvals,
    tool_gateway,
    tool_mutations,
    traces,
    training,
    visualizations,
    web_research,
    webhook_delivery,
    webhooks,
    workflow_marketplace,
    workflow_sse,
    workflow_templates,
    workflow_transport,
    workflow_ws,
    workflows,
)
from agent33.api.routes import (
    capability_packs as capability_packs_routes,
)
from agent33.api.routes import (
    config as config_routes,
)
from agent33.api.routes import (
    discovery as discovery_routes,
)
from agent33.api.routes import (
    embedding_swap as embedding_swap_routes,
)
from agent33.api.routes import (
    execution as execution_routes,
)
from agent33.api.routes import (
    plugins as plugins_routes,
)
from agent33.api.routes import (
    rate_limits as rate_limits_routes,
)
from agent33.api.routes import (
    scheduled_gates as scheduled_gates_routes,
)
from agent33.api.routes import (
    skill_authoring as skill_authoring_routes,
)
from agent33.api.routes import (
    skill_matching as skill_matching_routes,
)
from agent33.api.routes import (
    tool_catalog as tool_catalog_routes,
)
from agent33.config import settings
from agent33.hooks.middleware import HookMiddleware
from agent33.memory.long_term import LongTermMemory
from agent33.messaging.bus import NATSMessageBus
from agent33.observability.http_metrics import HTTPMetricsMiddleware
from agent33.security.middleware import AuthMiddleware
from agent33.state_paths import RuntimeStatePaths

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup and shutdown.

    Startup initialises:
    - PostgreSQL connection pool (via LongTermMemory / SQLAlchemy async engine)
    - Redis async connection
    - NATS message bus
    - Agent runtime wiring into the workflow executor

    All resources are stored on ``app.state`` for access by route handlers.
    """
    logger.info("agent33_starting")

    # Record startup time for uptime calculation
    _start_time = time.time()
    app_root = Path.cwd().resolve()
    state_paths = RuntimeStatePaths.from_app_root(app_root)
    app.state.runtime_state_paths = state_paths

    # Warn about insecure defaults
    secret_warnings = settings.check_production_secrets()
    for warning in secret_warnings:
        logger.warning("SECURITY: %s — override via environment variable", warning)

    # -- Database (PostgreSQL + pgvector) ----------------------------------
    long_term_memory: LongTermMemory | None
    if settings.agent33_mode == "lite":
        logger.warning("database_init_skipped", reason="lite mode")
        long_term_memory = None
    else:
        long_term_memory = LongTermMemory(
            settings.database_url,
            embedding_dim=settings.embedding_dim,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=settings.db_pool_pre_ping,
            pool_recycle=settings.db_pool_recycle,
        )
        try:
            await long_term_memory.initialize()
            logger.info(
                "database_connected",
                url=_redact_url(settings.database_url),
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_pre_ping=settings.db_pool_pre_ping,
                pool_recycle=settings.db_pool_recycle,
            )
        except Exception as exc:
            logger.warning("database_init_failed", error=str(exc))
    app.state.long_term_memory = long_term_memory

    # -- Shared orchestration state -----------------------------------------
    orchestration_state_store = None
    if settings.orchestration_state_store_path.strip():
        from agent33.services.orchestration_state import OrchestrationStateStore

        orchestration_state_path = state_paths.resolve_approved(
            settings.orchestration_state_store_path
        )
        orchestration_state_store = OrchestrationStateStore(str(orchestration_state_path))
        logger.info(
            "orchestration_state_store_enabled",
            path=str(orchestration_state_path),
        )
    app.state.orchestration_state_store = orchestration_state_store

    from agent33.explanation.store import ExplanationStore as _ExplanationStore

    _explanation_db_path = state_paths.resolve_approved("data/explanations.db")
    _explanation_db_path.parent.mkdir(parents=True, exist_ok=True)
    app.state.explanation_store = _ExplanationStore(str(_explanation_db_path))
    logger.info("explanation_store_initialized", path=str(_explanation_db_path))

    from agent33.autonomy.service import AutonomyService
    from agent33.backup.service import BackupService
    from agent33.evaluation.service import EvaluationService
    from agent33.observability.trace_collector import TraceCollector
    from agent33.release.service import ReleaseService
    from agent33.review.service import ReviewService
    from agent33.workflows.run_archive import WorkflowRunArchiveService
    from agent33.workflows.state import WorkflowStateService

    autonomy_service = AutonomyService(state_store=orchestration_state_store)
    evaluation_service = EvaluationService(state_store=orchestration_state_store)
    release_service = ReleaseService(state_store=orchestration_state_store)
    review_service = ReviewService(state_store=orchestration_state_store)
    trace_collector = TraceCollector(state_store=orchestration_state_store)
    workflow_run_archive_dir = state_paths.resolve_approved(settings.workflow_run_archive_dir)
    workflow_run_archive_service = WorkflowRunArchiveService(workflow_run_archive_dir)
    workflow_state_service = WorkflowStateService(
        state_store=orchestration_state_store,
        max_execution_history=1000,
        registry=workflows.get_workflow_registry(),
        execution_history=workflows.get_execution_history(),
    )
    app.state.autonomy_service = autonomy_service
    app.state.evaluation_service = evaluation_service
    app.state.release_service = release_service
    app.state.review_service = review_service
    app.state.trace_collector = trace_collector
    app.state.workflow_run_archive_service = workflow_run_archive_service
    app.state.workflow_state_service = workflow_state_service
    autonomy.set_autonomy_service(autonomy_service)
    evaluations.set_evaluation_service(evaluation_service)
    releases.set_release_service(release_service)
    reviews.set_review_service(review_service)
    traces.set_trace_collector(trace_collector)
    workflows.set_workflow_run_archive_service(workflow_run_archive_service)
    workflows.set_workflow_state_service(workflow_state_service)
    logger.info("workflow_run_archive_initialized", path=str(workflow_run_archive_dir))

    # -- Redis -------------------------------------------------------------
    from agent33.lifespan.fallbacks import InProcessCache, InProcessMessageBus

    if settings.agent33_mode == "lite":
        logger.warning("redis_init_skipped_using_in_process_cache", reason="lite mode")
        redis_conn: Any = InProcessCache()
    else:
        redis_conn = None
        try:
            import redis.asyncio as aioredis

            _redis_client = aioredis.from_url(  # type: ignore[no-untyped-call]
                settings.redis_url,
                decode_responses=True,
                max_connections=settings.redis_max_connections,
            )
            await _redis_client.ping()
            redis_conn = _redis_client
            logger.info(
                "redis_connected",
                url=_redact_url(settings.redis_url),
                max_connections=settings.redis_max_connections,
            )
        except Exception as exc:
            logger.warning("redis_init_failed_using_in_process_cache", error=str(exc))
            redis_conn = InProcessCache()
    app.state.redis = redis_conn

    # -- NATS message bus --------------------------------------------------
    if settings.agent33_mode == "lite":
        logger.warning("nats_init_skipped_using_in_process_bus", reason="lite mode")
        nats_bus: Any = InProcessMessageBus()
    else:
        _nats_bus = NATSMessageBus(settings.nats_url)
        try:
            await _nats_bus.connect()
            logger.info("nats_connected", url=_redact_url(settings.nats_url))
            nats_bus = _nats_bus
        except Exception as exc:
            logger.warning("nats_init_failed_using_in_process_bus", error=str(exc))
            nats_bus = InProcessMessageBus()
    app.state.nats_bus = nats_bus

    # -- Instance registry and scaling guards (P1.2) -----------------------
    from agent33.scaling.distributed_lock import create_lock
    from agent33.scaling.instance_registry import InstanceRegistry
    from agent33.scaling.state_guards import SchedulerOwnershipGuard

    instance_registry = InstanceRegistry(redis=redis_conn)
    await instance_registry.register()
    app.state.instance_registry = instance_registry

    scheduler_lock = create_lock(
        name="scheduler_ownership",
        redis=redis_conn,
        ttl_seconds=60,
    )
    scheduler_guard = SchedulerOwnershipGuard(
        lock=scheduler_lock,
        registry=instance_registry,
        surface_name="scheduler",
    )
    app.state.scheduler_guard = scheduler_guard
    logger.info(
        "scaling_guards_initialized",
        instance_id=instance_registry.instance_id,
        lock_backend="redis" if redis_conn is not None else "in-process",
    )

    # -- Agent registry ----------------------------------------------------
    from agent33.agents.registry import AgentRegistry

    agent_registry = AgentRegistry()
    defs_dir = Path(settings.agent_definitions_dir)
    if defs_dir.is_dir():
        count = agent_registry.discover(defs_dir)
        logger.info("agent_registry_loaded", count=count, path=str(defs_dir))
    else:
        logger.warning("agent_definitions_dir_not_found", path=str(defs_dir))
    app.state.agent_registry = agent_registry

    # -- Capability pack registry (Phase 47) --------------------------------
    from agent33.agents.capability_packs import CapabilityPackRegistry

    app.state.capability_pack_registry = CapabilityPackRegistry()
    logger.info(
        "capability_pack_registry_initialized",
        pack_count=len(app.state.capability_pack_registry),
    )

    # -- Agent profiler (S40) ----------------------------------------------
    from agent33.agents.profiling import AgentProfiler

    agent_profiler = AgentProfiler(max_profiles=settings.agent_profiler_max_profiles)
    app.state.agent_profiler = agent_profiler
    logger.info(
        "agent_profiler_initialized",
        max_profiles=settings.agent_profiler_max_profiles,
    )

    # -- Tool-loop scorer (Gate 4.3) ---------------------------------------
    from agent33.agents.tool_loop_scoring import ToolLoopScorer as _ToolLoopScorer

    _tool_loop_scorer = _ToolLoopScorer()
    app.state.tool_loop_scorer = _tool_loop_scorer
    logger.info("tool_loop_scorer_initialized")

    # -- Observability metrics + alerts -------------------------------------
    from agent33.observability.alerts import AlertManager
    from agent33.observability.effort_telemetry import (
        FileEffortTelemetryExporter,
        NoopEffortTelemetryExporter,
    )
    from agent33.observability.metrics import MetricsCollector

    metrics_collector = MetricsCollector(
        window_seconds=settings.metrics_rolling_window_seconds,
    )
    app.state.metrics_collector = metrics_collector
    agents.set_metrics(metrics_collector)
    dashboard.set_metrics(metrics_collector)

    # Wire metrics into webhook delivery and dead-letter subsystems (P3.10)
    from agent33.automation import dead_letter as dead_letter_mod
    from agent33.automation import webhook_delivery as webhook_delivery_mod

    webhook_delivery_mod.set_metrics(metrics_collector)
    dead_letter_mod.set_metrics(metrics_collector)

    # Wire metrics into evaluation subsystem (P4.7)
    from agent33.evaluation import service as evaluation_service_mod

    evaluation_service_mod.set_metrics(metrics_collector)

    # Wire reasoning ISC criteria state store
    from agent33.api.routes import reasoning as reasoning_routes

    reasoning_routes.set_reasoning_state_store(orchestration_state_store)

    # Wire ResourceService with state_store for persistence
    from agent33.resources.service import ResourceService as _ResourceService
    from agent33.resources.service import set_resource_service

    set_resource_service(_ResourceService(state_store=orchestration_state_store))

    # Wire metrics into messaging connector boundary (P4.7)
    from agent33.messaging import boundary as messaging_boundary_mod

    messaging_boundary_mod.set_metrics(metrics_collector)

    effort_telemetry_exporter = (
        FileEffortTelemetryExporter(settings.observability_effort_export_path)
        if settings.observability_effort_export_enabled
        else NoopEffortTelemetryExporter()
    )
    app.state.effort_telemetry_exporter = effort_telemetry_exporter
    agents.set_effort_telemetry_exporter(effort_telemetry_exporter)

    alert_manager = AlertManager(metrics_collector)
    if settings.observability_effort_alerts_enabled:
        alert_manager.add_rule(
            name="high_effort_routing_volume",
            metric="effort_routing_high_effort_total",
            threshold=float(settings.observability_effort_alert_high_effort_count_threshold),
            comparator="gt",
        )
        alert_manager.add_rule(
            name="high_effort_cost_spike",
            metric="effort_routing_estimated_cost_usd",
            threshold=settings.observability_effort_alert_high_cost_usd_threshold,
            comparator="gt",
            statistic="max",
        )
        alert_manager.add_rule(
            name="high_effort_token_budget_spike",
            metric="effort_routing_estimated_token_budget",
            threshold=float(settings.observability_effort_alert_high_token_budget_threshold),
            comparator="gt",
            statistic="max",
        )
    app.state.alert_manager = alert_manager
    dashboard.set_alert_manager(alert_manager)

    # Wire ExecutionLineage with state_store for persistence
    from agent33.observability.lineage import ExecutionLineage as _ExecutionLineage

    _execution_lineage = _ExecutionLineage(state_store=orchestration_state_store)
    app.state.execution_lineage = _execution_lineage
    dashboard.set_lineage(_execution_lineage)

    # -- ExecutionReplay -------------------------------------------------------
    from agent33.observability.replay import ExecutionReplay

    app.state.execution_replay = ExecutionReplay()

    # -- CheckpointManager (W18-F2) --------------------------------------------
    if settings.checkpoint_persistence_enabled:
        from agent33.workflows.checkpoint import CheckpointManager

        app.state.checkpoint_manager = CheckpointManager()
    else:
        app.state.checkpoint_manager = None

    # -- Session analytics (Phase 57) -----------------------------------------
    from agent33.llm.pricing import apply_pricing_overrides_json
    from agent33.observability.metrics import CostTracker

    applied_pricing_overrides = apply_pricing_overrides_json(settings.pricing_catalog_overrides)
    if applied_pricing_overrides:
        logger.info("pricing_catalog_overrides_applied count=%d", applied_pricing_overrides)

    cost_tracker = CostTracker(state_store=orchestration_state_store)
    app.state.cost_tracker = cost_tracker
    insights.set_insights_dependencies(metrics_collector, cost_tracker)

    # -- Connector metrics collector & breaker registry (Phase 32) ----------
    from agent33.connectors.circuit_breaker import CircuitBreakerRegistry
    from agent33.connectors.monitoring import ConnectorMetricsCollector

    connector_metrics = ConnectorMetricsCollector()
    app.state.connector_metrics = connector_metrics
    breaker_registry = CircuitBreakerRegistry()
    app.state.breaker_registry = breaker_registry
    logger.info("connector_metrics_and_registry_initialized")

    # -- Agent runtime / workflow integration ------------------------------
    from agent33.workflows.actions.invoke_agent import (
        register_agent,
        set_definition_registry,
        set_pack_sharing_service,
    )

    set_definition_registry(agent_registry)

    # -- Code execution layer ------------------------------------------
    from agent33.execution.executor import CodeExecutor
    from agent33.workflows.actions import execute_code

    code_executor = CodeExecutor(tool_registry=None)
    if settings.jupyter_kernel_enabled:
        from agent33.execution.adapters.jupyter import (
            JupyterAdapter,
            build_default_jupyter_definition,
        )

        try:
            jupyter_definition = build_default_jupyter_definition(
                adapter_id=settings.jupyter_kernel_adapter_id,
                tool_id=settings.jupyter_kernel_tool_id,
                kernel_name=settings.jupyter_kernel_name,
                max_sessions=settings.jupyter_kernel_max_sessions,
                idle_timeout_seconds=settings.jupyter_kernel_idle_timeout_seconds,
                startup_timeout_seconds=settings.jupyter_kernel_startup_timeout_seconds,
                execution_timeout_seconds=settings.jupyter_kernel_execution_timeout_seconds,
                docker_enabled=settings.jupyter_kernel_mode == "docker",
                docker_image=settings.jupyter_kernel_docker_image,
                docker_allowed_images=[
                    image.strip()
                    for image in settings.jupyter_kernel_allowed_images.split(",")
                    if image.strip()
                ],
                docker_network_enabled=settings.jupyter_kernel_network_enabled,
                docker_mount_working_directory=settings.jupyter_kernel_mount_workdir,
                docker_container_workdir=settings.jupyter_kernel_container_workdir,
            )
            code_executor.register_adapter(JupyterAdapter(jupyter_definition))
            logger.info(
                "jupyter_kernel_adapter_registered",
                adapter_id=settings.jupyter_kernel_adapter_id,
                tool_id=settings.jupyter_kernel_tool_id,
                mode=settings.jupyter_kernel_mode,
            )
        except Exception as exc:
            logger.warning("jupyter_kernel_adapter_failed", error=str(exc))
    app.state.code_executor = code_executor
    execute_code.set_executor(code_executor)
    logger.info("code_executor_initialized")

    # -- GPU Docker manager (S30) ------------------------------------------
    from agent33.execution.gpu import GPUDockerManager

    gpu_docker_manager = GPUDockerManager(
        default_image=settings.execution_default_docker_image,
    )
    app.state.gpu_docker_manager = gpu_docker_manager
    logger.info(
        "gpu_docker_manager_initialized",
        gpu_enabled=settings.execution_gpu_enabled,
        default_image=settings.execution_default_docker_image,
    )

    from agent33.llm.runtime_config import build_model_router, llamacpp_enabled

    model_router = build_model_router()

    if llamacpp_enabled():
        logger.info(
            "local_orchestration_provider_registered",
            engine=settings.local_orchestration_engine,
            base_url=settings.local_orchestration_base_url,
            model=settings.local_orchestration_model,
        )

    app.state.model_router = model_router
    logger.info("model_router_initialized")

    # -- Delegation manager (Phase 53) ------------------------------------
    from agent33.agents.delegation import DelegationManager

    delegation_manager = DelegationManager(
        registry=agent_registry,
        router=model_router,
        state_store=orchestration_state_store,
    )
    app.state.delegation_manager = delegation_manager
    logger.info("delegation_manager_initialized")

    # -- Sub-Agent Spawner (Phase 71) --------------------------------------
    from agent33.spawner.service import SpawnerService

    spawner_service = SpawnerService(delegation_manager=delegation_manager)
    app.state.spawner_service = spawner_service
    logger.info("spawner_service_initialized")

    # -- Tool registry + governance ----------------------------------------
    from agent33.security.approval_tokens import ApprovalTokenManager
    from agent33.tools.approvals import ToolApprovalService
    from agent33.tools.builtin.apply_patch import ApplyPatchTool
    from agent33.tools.governance import ToolGovernance
    from agent33.tools.mutation_audit import MutationAuditStore
    from agent33.tools.registry import ToolRegistry

    tool_registry = ToolRegistry()
    tool_registry.discover_from_entrypoints()
    app.state.tool_registry = tool_registry

    tool_approval_service = ToolApprovalService(state_store=orchestration_state_store)
    app.state.tool_approval_service = tool_approval_service
    tool_approvals.set_tool_approval_service(tool_approval_service)

    from agent33.planning.plans import PlannerService

    planner_service = PlannerService(state_store=orchestration_state_store)
    app.state.planner_service = planner_service
    planning.set_planner_service(planner_service)

    # -- Skill registry bootstrap -----------------------------------------
    from agent33.skills.lineage import SkillLineageStore
    from agent33.skills.registry import SkillRegistry

    skill_registry = SkillRegistry(
        lineage_store=SkillLineageStore(Path(settings.skill_lineage_store_path)),
        state_store=orchestration_state_store,
    )
    skills_dir = Path(settings.skill_definitions_dir)
    if skills_dir.is_dir():
        skill_count = skill_registry.discover(skills_dir)
        logger.info("skill_registry_loaded", count=skill_count, path=str(skills_dir))
    app.state.skill_registry = skill_registry

    # -- Ingestion candidate lifecycle (Sprint 1 + Sprint 2 + Sprint 4) -----------
    from agent33.ingestion.intake import IntakePipeline
    from agent33.ingestion.journal import TransitionJournal
    from agent33.ingestion.persistence import IngestionPersistence
    from agent33.ingestion.service import IngestionService

    ingestion_db_path = state_paths.resolve_approved(settings.ingestion_db_path)
    ingestion_journal_db_path = state_paths.resolve_approved(settings.ingestion_journal_db_path)
    ingestion_mailbox_db_path = state_paths.resolve_approved(settings.ingestion_mailbox_db_path)
    ingestion_task_metrics_db_path = state_paths.resolve_approved(
        settings.ingestion_task_metrics_db_path
    )
    ingestion_notification_hooks_db_path = state_paths.resolve_approved(
        settings.ingestion_notification_hooks_db_path
    )
    ingestion_persistence = IngestionPersistence(ingestion_db_path)
    ingestion_journal = TransitionJournal(
        ingestion_journal_db_path,
        retention_days=settings.ingestion_journal_retention_days,
    )
    expired_journal_entries = ingestion_journal.cleanup_expired()
    from agent33.ingestion.notifications import (
        IngestionNotificationService,
        NotificationHookStore,
    )

    ingestion_notification_store = NotificationHookStore(ingestion_notification_hooks_db_path)
    ingestion_notification_service = IngestionNotificationService(
        ingestion_notification_store,
        timeout_seconds=settings.ingestion_notification_timeout_seconds,
    )
    ingestion_service = IngestionService(
        persistence=ingestion_persistence,
        journal=ingestion_journal,
        notifications=ingestion_notification_service,
        skill_registry=skill_registry,
    )
    intake_pipeline = IntakePipeline(ingestion_service)
    app.state.ingestion_persistence = ingestion_persistence
    app.state.ingestion_journal = ingestion_journal
    app.state.ingestion_notification_service = ingestion_notification_service
    app.state.ingestion_service = ingestion_service
    app.state.intake_pipeline = intake_pipeline
    ingestion.set_ingestion_service(ingestion_service)
    ingestion.set_intake_pipeline(intake_pipeline)
    ingestion.set_ingestion_notification_service(ingestion_notification_service)
    logger.info(
        "ingestion_service_initialized",
        db_path=str(ingestion_db_path),
        journal_db_path=str(ingestion_journal_db_path),
        notification_hooks_db_path=str(ingestion_notification_hooks_db_path),
        journal_retention_days=settings.ingestion_journal_retention_days,
        expired_journal_entries=expired_journal_entries,
    )

    from agent33.ingestion.doctor import SkillsDoctor
    from agent33.ingestion.mailbox import IngestionMailbox
    from agent33.ingestion.mailbox_persistence import MailboxInboxPersistence
    from agent33.ingestion.metrics import TaskMetricsCollector

    ingestion_mailbox_persistence = MailboxInboxPersistence(ingestion_mailbox_db_path)
    ingestion_mailbox = IngestionMailbox(
        pipeline=intake_pipeline,
        persistence=ingestion_mailbox_persistence,
    )
    task_metrics = TaskMetricsCollector(
        ingestion_task_metrics_db_path,
        retention_days=settings.ingestion_task_metrics_retention_days,
    )
    expired_task_metrics = task_metrics.cleanup_expired()
    app.state.ingestion_mailbox_persistence = ingestion_mailbox_persistence
    app.state.ingestion_mailbox = ingestion_mailbox
    app.state.task_metrics = task_metrics
    ingestion.set_ingestion_mailbox(ingestion_mailbox)
    ingestion.set_task_metrics(task_metrics)
    logger.info(
        "ingestion_mailbox_initialized",
        mailbox_db_path=str(ingestion_mailbox_db_path),
    )
    logger.info(
        "ingestion_task_metrics_initialized",
        metrics_db_path=str(ingestion_task_metrics_db_path),
        retention_days=settings.ingestion_task_metrics_retention_days,
        expired_task_metrics=expired_task_metrics,
    )

    skills_doctor = SkillsDoctor(service=ingestion_service)
    app.state.skills_doctor = skills_doctor
    ingestion.set_skills_doctor(skills_doctor)
    logger.info("skills_doctor_initialized")

    # -- P69b tool approval gate (POST-4.3 + Session-131 T2 persistence) ------
    from agent33.autonomy.p69b_persistence import P69bPersistence
    from agent33.autonomy.p69b_service import P69bService

    p69b_persistence = P69bPersistence(Path(settings.p69b_db_path))
    p69b_service = P69bService(timeout_seconds=300, persistence=p69b_persistence)
    app.state.p69b_persistence = p69b_persistence
    app.state.p69b_service = p69b_service
    logger.info("p69b_service_initialized", db_path=settings.p69b_db_path)

    approval_token_manager = None
    if settings.approval_token_enabled:
        approval_token_manager = ApprovalTokenManager(
            secret=settings.jwt_secret.get_secret_value(),
            algorithm=settings.jwt_algorithm,
            default_ttl_seconds=settings.approval_token_ttl_seconds,
            default_one_time=settings.approval_token_one_time_default,
            state_store=orchestration_state_store,
        )
    app.state.approval_token_manager = approval_token_manager
    tool_approvals.set_approval_token_manager(approval_token_manager)

    tool_governance = ToolGovernance(
        approval_service=tool_approval_service,
        approval_token_manager=approval_token_manager,
    )
    tool_governance.load_approved_tools_file(Path.home() / ".agent33" / "approved-tools.json")
    app.state.tool_governance = tool_governance
    mutation_audit_store = MutationAuditStore(state_store=orchestration_state_store)
    app.state.mutation_audit_store = mutation_audit_store
    tool_mutations.set_mutation_audit_store(mutation_audit_store)
    tool_registry.register(ApplyPatchTool(audit_store=mutation_audit_store))

    from agent33.tools.builtin.delegate_subtask import DelegateSubtaskTool

    tool_registry.register(DelegateSubtaskTool(router=model_router, tool_registry=tool_registry))

    from agent33.tools.builtin.browser import BrowserTool

    cloud_backend = None
    if settings.browser_cloud_api_key.get_secret_value():
        from agent33.tools.builtin.browser_cloud import CloudBrowserBackend

        cloud_backend = CloudBrowserBackend(
            api_key=settings.browser_cloud_api_key.get_secret_value(),
            api_url=settings.browser_cloud_api_url,
        )
        logger.info("browser_cloud_backend_configured")

    tool_registry.register(
        BrowserTool(
            router=model_router,
            session_ttl_seconds=settings.browser_session_ttl_seconds,
            vision_model=settings.browser_vision_model,
            cloud_backend=cloud_backend,
        )
    )

    if settings.ptc_enabled:
        from agent33.tools.builtin.ptc_execute import PTCExecuteTool

        _ptc_allowed: list[str] | None = None
        if settings.ptc_allowed_tools.strip():
            _ptc_allowed = [t.strip() for t in settings.ptc_allowed_tools.split(",") if t.strip()]
        tool_registry.register(
            PTCExecuteTool(
                tool_registry=tool_registry,
                allowed_tools=_ptc_allowed,
                timeout_s=float(settings.ptc_timeout_s),
                max_calls=settings.ptc_max_calls,
                max_stdout_bytes=settings.ptc_max_stdout_bytes,
            )
        )
        logger.info("ptc_tool_registered")

    from agent33.tools.builtin.search import SearchTool

    # SearchTool is initialized without a registry here; it will be
    # re-registered with the full SearchProviderRegistry later in lifespan
    # once the registry is created.
    tool_registry.register(SearchTool())
    logger.info("tool_registry_initialized", tool_count=len(tool_registry.list_all()))

    from agent33.processes.service import ProcessManagerService

    process_manager_log_dir = state_paths.resolve_approved(settings.process_manager_log_dir)
    process_manager_service = ProcessManagerService(
        workspace_root=app_root,
        log_dir=process_manager_log_dir,
        state_store=orchestration_state_store,
        max_processes=settings.process_manager_max_processes,
    )
    app.state.process_manager_service = process_manager_service
    logger.info(
        "process_manager_service_initialized",
        workspace_root=str(app_root),
        log_dir=str(process_manager_log_dir),
        max_processes=settings.process_manager_max_processes,
    )

    backup_dir = state_paths.resolve_approved(settings.backup_dir)
    backup_service = BackupService(
        backup_dir=backup_dir,
        settings=settings,
        app_root=app_root,
        workspace_dir=None,
        state_paths=state_paths,
    )
    app.state.backup_service = backup_service
    logger.info(
        "backup_service_initialized",
        backup_dir=str(backup_dir),
    )

    # -- Component security persistence (AEP-B01) ----------------------------
    from agent33.api.routes.component_security import init_component_security_service

    init_component_security_service(app, settings)
    logger.info("component_security_service_initialized")
    # Wire the security scan service into the release service (RL-06 gate).
    # ReleaseService is constructed before component-security is initialized,
    # so we inject the reference here once it is available.
    _sec_svc = getattr(app.state, "security_scan_service", None)
    if _sec_svc is not None:
        app.state.release_service._security_scan_service = _sec_svc

    # -- Embedding provider + cache ----------------------------------------
    from agent33.memory.embeddings import EmbeddingProvider

    embedding_provider = EmbeddingProvider(
        base_url=settings.runtime_ollama_base_url,
        model=settings.embedding_default_model,
        max_connections=settings.http_max_connections,
        max_keepalive_connections=settings.http_max_keepalive,
    )
    app.state.embedding_provider = embedding_provider

    active_embedder: Any = embedding_provider
    compressor = None
    if settings.embedding_quantization_enabled:
        from agent33.memory.quantization import TurboQuantCompressor

        compressor = TurboQuantCompressor(
            dim=settings.embedding_dim,
            bits=settings.embedding_quantization_bits,
            seed=settings.embedding_quantization_seed,
        )
        logger.info(
            "turboquant_compressor_initialized",
            dim=settings.embedding_dim,
            bits=settings.embedding_quantization_bits,
            ratio=f"{compressor.compression_ratio():.1f}x",
        )

    if settings.embedding_cache_enabled:
        from agent33.memory.cache import EmbeddingCache

        embedding_cache = EmbeddingCache(
            provider=embedding_provider,
            max_size=settings.embedding_cache_max_size,
            compressor=compressor,
        )
        active_embedder = embedding_cache
        app.state.embedding_cache = embedding_cache

    logger.info(
        "embedding_provider_initialized",
        cache=settings.embedding_cache_enabled,
        quantized=settings.embedding_quantization_enabled,
    )

    # -- Embedding hot-swap manager (S44) ----------------------------------
    embedding_swap_manager = None
    if settings.embedding_hot_swap_enabled:
        from agent33.memory.embedding_swap import EmbeddingModelInfo, EmbeddingSwapManager

        default_model_info = EmbeddingModelInfo(
            model_id=settings.embedding_default_model,
            provider=settings.embedding_provider,
            dimensions=settings.embedding_default_dimensions,
            max_tokens=8192,
            version="1.0",
            description="Default embedding model",
        )
        embedding_swap_manager = EmbeddingSwapManager(
            current_model=default_model_info,
        )
        embedding_swap_manager.set_embedding_provider(embedding_provider)
        if settings.embedding_cache_enabled:
            embedding_swap_manager.set_embedding_cache(getattr(app.state, "embedding_cache", None))
        app.state.embedding_swap = embedding_swap_manager
        logger.info(
            "embedding_swap_manager_initialized",
            model_id=default_model_info.model_id,
            provider=default_model_info.provider,
        )

    # -- BM25 + Hybrid + RAG ----------------------------------------------
    from agent33.memory.bm25 import BM25Index
    from agent33.memory.rag import RAGPipeline

    bm25_index = BM25Index()
    app.state.bm25_index = bm25_index

    # -- BM25 warm-up from existing records --
    if settings.bm25_warmup_enabled and long_term_memory is not None:
        from agent33.memory.warmup import warm_up_bm25

        try:
            warmup_count = await warm_up_bm25(
                long_term_memory=long_term_memory,
                bm25_index=bm25_index,
                page_size=settings.bm25_warmup_page_size,
                max_records=settings.bm25_warmup_max_records,
            )
            logger.info("bm25_warmup_done", records_loaded=warmup_count)
        except Exception as exc:
            logger.warning("bm25_warmup_failed", error=str(exc), exc_info=True)

    hybrid_searcher = None
    if settings.rag_hybrid_enabled and long_term_memory is not None:
        from agent33.memory.hybrid import HybridSearcher

        hybrid_searcher = HybridSearcher(
            long_term_memory=long_term_memory,
            embedding_provider=active_embedder,
            bm25_index=bm25_index,
            vector_weight=settings.rag_vector_weight,
            rrf_k=settings.rag_rrf_k,
        )
        app.state.hybrid_searcher = hybrid_searcher

    rag_pipeline = None
    if long_term_memory is not None:
        rag_pipeline = RAGPipeline(
            embedding_provider=active_embedder,
            long_term_memory=long_term_memory,
            top_k=settings.rag_top_k,
            similarity_threshold=settings.rag_similarity_threshold,
            hybrid_searcher=hybrid_searcher,
            redact_enabled=settings.redact_secrets_enabled,
        )
        logger.info(
            "rag_pipeline_initialized",
            hybrid=settings.rag_hybrid_enabled,
            top_k=settings.rag_top_k,
        )
    else:
        logger.warning("rag_pipeline_skipped", reason="no long_term_memory in lite mode")
    app.state.rag_pipeline = rag_pipeline

    # -- Progressive recall ------------------------------------------------
    from agent33.memory.progressive_recall import ProgressiveRecall

    progressive_recall = None
    if long_term_memory is not None:
        progressive_recall = ProgressiveRecall(
            long_term_memory=long_term_memory,
            embedding_provider=active_embedder,
        )
    app.state.progressive_recall = progressive_recall

    # -- Knowledge ingestion service (P70) ---------------------------------
    from agent33.knowledge.service import KnowledgeIngestionService

    knowledge_service = KnowledgeIngestionService(
        long_term_memory=long_term_memory,
        embedding_provider=active_embedder,
        default_tenant_id=settings.knowledge_default_tenant_id,
    )
    knowledge_service.start()
    app.state.knowledge_service = knowledge_service
    logger.info("knowledge_ingestion_service_initialized")

    # -- Skill injector -----------------------------------------------------
    from agent33.skills.injection import SkillInjector

    skill_injector = SkillInjector(skill_registry)
    app.state.skill_injector = skill_injector
    logger.info("skill_injector_initialized")

    # -- Command registry (Phase 54) --------------------------------------
    from agent33.skills.slash_commands import CommandRegistry

    command_registry = CommandRegistry(skill_registry)
    skill_registry.add_change_listener(command_registry.refresh)
    app.state.command_registry = command_registry
    logger.info("command_registry_initialized", count=command_registry.count)

    # -- Hybrid skill matcher (S29) ----------------------------------------
    from agent33.skills.calibration import HybridSkillMatcher, MatchThresholds

    hybrid_thresholds = MatchThresholds(
        fuzzy_threshold=settings.skill_match_fuzzy_threshold,
        semantic_threshold=settings.skill_match_semantic_threshold,
        contextual_threshold=settings.skill_match_contextual_threshold,
        max_candidates=settings.skill_match_max_candidates,
    )
    hybrid_skill_matcher = HybridSkillMatcher(
        skill_registry=skill_registry,
        thresholds=hybrid_thresholds,
    )
    app.state.hybrid_skill_matcher = hybrid_skill_matcher
    logger.info("hybrid_skill_matcher_initialized")

    # -- Pack registry (optional) ------------------------------------------
    from agent33.packs.marketplace import LocalPackMarketplace
    from agent33.packs.marketplace_aggregator import MarketplaceAggregator
    from agent33.packs.registry import PackRegistry
    from agent33.packs.remote_marketplace import RemoteMarketplaceConfig, RemotePackMarketplace
    from agent33.packs.rollback import PackRollbackManager
    from agent33.packs.trust_manager import TrustPolicyManager

    packs_dir = Path(settings.pack_definitions_dir)
    local_pack_marketplace = LocalPackMarketplace(Path(settings.pack_marketplace_dir))
    remote_marketplaces: list[RemotePackMarketplace] = []
    raw_remote_sources = settings.pack_marketplace_remote_sources.strip()
    if raw_remote_sources:
        try:
            parsed_sources = json.loads(raw_remote_sources)
        except json.JSONDecodeError:
            parsed_sources = []
            logger.warning("pack_marketplace_remote_sources_invalid")
        if isinstance(parsed_sources, list):
            for item in parsed_sources:
                if not isinstance(item, dict):
                    continue
                try:
                    config = RemoteMarketplaceConfig.model_validate(item)
                except Exception:
                    logger.warning(
                        "pack_marketplace_remote_source_invalid",
                        name=item.get("name"),
                        index_url=item.get("index_url"),
                    )
                    continue
                remote_marketplaces.append(
                    RemotePackMarketplace(
                        config,
                        cache_dir=Path(settings.pack_marketplace_cache_dir),
                        max_download_size_bytes=settings.pack_max_size_mb * 1024 * 1024,
                    )
                )
    pack_marketplace = MarketplaceAggregator([local_pack_marketplace, *remote_marketplaces])
    pack_trust_manager = TrustPolicyManager(orchestration_state_store)
    pack_registry = PackRegistry(
        packs_dir=packs_dir,
        skill_registry=skill_registry,
        marketplace=pack_marketplace,
        trust_policy_manager=pack_trust_manager,
        ppack_v3_enabled=settings.ppack_v3_enabled,
    )
    pack_rollback_manager = PackRollbackManager(
        pack_registry,
        archive_dir=Path(settings.pack_rollback_archive_dir),
        state_store=orchestration_state_store,
    )
    if packs_dir.is_dir():
        pack_count = pack_registry.discover()
        logger.info("pack_registry_loaded", count=pack_count, path=str(packs_dir))
    else:
        logger.debug("pack_definitions_dir_not_found", path=str(packs_dir))
    app.state.pack_registry = pack_registry
    app.state.pack_marketplace = pack_marketplace
    app.state.pack_trust_manager = pack_trust_manager
    app.state.pack_rollback_manager = pack_rollback_manager

    # -- Pack Hub (P-PACK v2) — lazy init, no startup refresh ---------------
    from agent33.packs.hub import PackHub

    app.state.pack_hub = PackHub()
    logger.info("pack_hub_initialized")

    # -- Pack Sharing Service (P-PACK v2) -----------------------------------
    from agent33.packs.sharing import PackSharingService

    app.state.pack_sharing_service = PackSharingService(pack_registry)
    set_pack_sharing_service(app.state.pack_sharing_service)
    logger.info("pack_sharing_service_initialized")

    # -- Marketplace curation (Phase 33) -----------------------------------
    from agent33.packs.categories import CategoryRegistry
    from agent33.packs.curation_service import CurationService

    category_registry = CategoryRegistry(
        orchestration_state_store, settings.pack_default_categories
    )
    curation_service = CurationService(
        pack_registry,
        category_registry,
        orchestration_state_store,
        settings.pack_min_quality_score,
        settings.pack_require_review_for_listing,
    )
    app.state.category_registry = category_registry
    app.state.curation_service = curation_service
    logger.info("marketplace_curation_initialized")

    # -- Trust analytics dashboard (Phase 33 / S23) ------------------------
    from agent33.packs.trust_analytics import TrustAnalyticsService

    trust_analytics = TrustAnalyticsService(
        pack_registry,
        pack_trust_manager,
        provenance_collector=None,  # wired later after provenance init
        curation_service=curation_service,
        verification_key=settings.pack_signing_key,
    )
    app.state.trust_analytics = trust_analytics
    logger.info("trust_analytics_initialized")

    # -- Pack audit service (Phase 33 / S24) -------------------------------
    from agent33.packs.audit import PackAuditService

    pack_audit = PackAuditService(
        pack_registry,
        trust_analytics=trust_analytics,
        curation_service=curation_service,
        provenance_collector=None,  # wired later after provenance init
    )
    app.state.pack_audit = pack_audit
    logger.info("pack_audit_service_initialized")

    # -- Hook registry -----------------------------------------------------
    hook_registry = None
    if settings.hooks_enabled:
        from agent33.hooks.registry import HookRegistry

        hook_registry = HookRegistry(max_per_event=settings.hooks_max_per_event)
        hook_registry.discover_builtins()
        app.state.hook_registry = hook_registry
        logger.info("hook_registry_initialized", hook_count=hook_registry.count())

    # -- Script hook discovery (Phase 44) ----------------------------------
    script_hook_discovery = None
    if settings.script_hooks_enabled and hook_registry is not None:
        from agent33.hooks.script_discovery import (
            ScriptHookDiscovery,
            resolve_project_hooks_dir,
        )

        project_hooks = (
            state_paths.resolve(settings.script_hooks_project_dir)
            if settings.script_hooks_project_dir.strip()
            else resolve_project_hooks_dir(app_root)
        )
        user_hooks = (
            state_paths.resolve(settings.script_hooks_user_dir)
            if settings.script_hooks_user_dir.strip()
            else state_paths.default_user_state_dir("hooks")
        )
        script_hook_discovery = ScriptHookDiscovery(
            hook_registry=hook_registry,
            project_hooks_dir=project_hooks,
            user_hooks_dir=user_hooks,
            default_timeout_ms=settings.script_hooks_default_timeout_ms,
            max_timeout_ms=settings.script_hooks_max_timeout_ms,
        )
        discovered = script_hook_discovery.discover()
        app.state.script_hook_discovery = script_hook_discovery
        logger.info("script_hook_discovery_complete", count=discovered)

    # -- Operator session service (Phase 44) -------------------------------
    operator_session_service = None
    if settings.operator_session_enabled:
        from agent33.sessions.service import OperatorSessionService
        from agent33.sessions.storage import FileSessionStorage

        base_dir = (
            state_paths.resolve_approved(settings.operator_session_base_dir)
            if settings.operator_session_base_dir.strip()
            else state_paths.default_user_state_dir("sessions")
        )
        session_storage = FileSessionStorage(
            base_dir=base_dir,
            max_replay_file_bytes=settings.operator_session_max_replay_file_mb * 1024 * 1024,
        )
        operator_session_service = OperatorSessionService(
            storage=session_storage,
            hook_registry=hook_registry,
            checkpoint_interval_seconds=settings.operator_session_checkpoint_interval_seconds,
            max_sessions_retained=settings.operator_session_max_retained,
            session_cleanup_callback=pack_registry.clear_session_state,
        )
        app.state.operator_session_service = operator_session_service
        sessions.set_session_service(operator_session_service)

        # Crash detection on startup
        if settings.operator_session_crash_recovery_enabled:
            try:
                crashed = await operator_session_service.detect_incomplete_sessions()
                if crashed:
                    logger.warning(
                        "incomplete_sessions_found",
                        count=len(crashed),
                        session_ids=[s.session_id for s in crashed],
                    )
            except Exception:
                logger.warning("crash_detection_failed", exc_info=True)

        logger.info("operator_session_service_initialized", base_dir=str(base_dir))

    # -- Track 8: Session catalog, lineage, spawn, archive -----------------
    if operator_session_service is not None:
        from agent33.sessions.archive import SessionArchiveService
        from agent33.sessions.catalog import SessionCatalog
        from agent33.sessions.lineage import SessionLineageBuilder
        from agent33.sessions.spawn import SessionSpawnService

        session_catalog = SessionCatalog(operator_session_service)
        app.state.session_catalog = session_catalog
        sessions.set_session_catalog(session_catalog)

        session_lineage_builder = SessionLineageBuilder(operator_session_service)
        app.state.session_lineage_builder = session_lineage_builder
        sessions.set_session_lineage_builder(session_lineage_builder)

        session_spawn_service = SessionSpawnService(
            session_service=operator_session_service,
            templates_dir=settings.session_spawn_templates_dir,
        )
        app.state.session_spawn_service = session_spawn_service
        sessions.set_session_spawn_service(session_spawn_service)

        session_archive_service = SessionArchiveService(operator_session_service)
        app.state.session_archive_service = session_archive_service
        sessions.set_session_archive_service(session_archive_service)

        logger.info("track8_session_services_initialized")

    # -- Track 8: Context engine registry -----------------------------------
    from agent33.context.registry import ContextEngineRegistry

    context_engine_registry = ContextEngineRegistry(
        default_engine=settings.context_engine_default,
    )
    app.state.context_engine_registry = context_engine_registry
    context.set_context_engine_registry(context_engine_registry)
    logger.info(
        "context_engine_registry_initialized",
        default_engine=settings.context_engine_default,
    )

    # -- Track 8 upstream agent OS: Memory session catalog, context slots, compaction --
    from agent33.memory.compaction import CompactionDiagnostics
    from agent33.memory.context_slots import ContextSlotManager
    from agent33.memory.session_catalog import SessionCatalog as MemorySessionCatalog

    memory_session_catalog = MemorySessionCatalog(state_store=orchestration_state_store)
    app.state.memory_session_catalog = memory_session_catalog
    sessions.set_memory_session_catalog(memory_session_catalog)

    context_slot_manager = ContextSlotManager()
    app.state.context_slot_manager = context_slot_manager
    sessions.set_context_slot_manager(context_slot_manager)

    compaction_diagnostics = CompactionDiagnostics()
    app.state.compaction_diagnostics = compaction_diagnostics
    sessions.set_compaction_diagnostics(compaction_diagnostics)

    logger.info("track8_memory_services_initialized")

    # -- Web research service (Track 7) ------------------------------------
    from agent33.web_research.service import (
        create_default_web_research_service,
        create_search_provider_registry,
    )

    search_provider_registry = create_search_provider_registry()
    app.state.search_provider_registry = search_provider_registry
    web_research.set_search_provider_registry(search_provider_registry)
    logger.info(
        "search_provider_registry_initialized",
        providers=search_provider_registry.list_provider_ids(),
        default=search_provider_registry.default_provider_id,
    )

    web_research_service = create_default_web_research_service(
        search_registry=search_provider_registry,
    )
    app.state.web_research_service = web_research_service
    research.set_research_service(web_research_service)

    # Re-register the SearchTool with the full provider registry
    from agent33.tools.builtin.search import SearchTool

    tool_registry.register(SearchTool(search_registry=search_provider_registry))
    logger.info("web_research_service_initialized")

    # -- Voice sidecar probe / status-line services ------------------------
    voice_sidecar_probe = None
    if settings.voice_sidecar_url.strip() or settings.voice_daemon_transport == "sidecar":
        from agent33.voice.client import VoiceSidecarProbe

        sidecar_url = settings.voice_sidecar_url.strip() or settings.voice_daemon_url.strip()
        voice_sidecar_probe = VoiceSidecarProbe(
            base_url=sidecar_url,
            enabled=settings.voice_daemon_enabled,
            transport=settings.voice_daemon_transport,
            timeout_seconds=settings.voice_sidecar_probe_timeout_seconds,
        )
        app.state.voice_sidecar_probe = voice_sidecar_probe

    from agent33.operator.status_line import StatusLineService

    status_line_service = StatusLineService(
        app_state=app.state,
        workspace_root=app_root,
        voice_probe=voice_sidecar_probe,
    )
    app.state.status_line_service = status_line_service
    if operator_session_service is not None:
        operator_session_service.set_status_snapshot_builder(status_line_service.build_snapshot)

    # -- WebSocket manager for workflow events ------------------------------
    from agent33.workflows.ws_manager import WorkflowWSManager

    ws_manager = WorkflowWSManager(archive_service=workflow_run_archive_service)
    app.state.ws_manager = ws_manager
    workflows.set_ws_manager(ws_manager)
    logger.info("workflow_ws_manager_initialized")

    # -- Streaming manager for agent WebSocket transport (P2.5) -------------
    from agent33.api.routes.streaming import StreamingManager

    streaming_manager = StreamingManager(
        max_connections=settings.streaming_max_connections,
    )
    app.state.streaming_manager = streaming_manager
    logger.info(
        "streaming_manager_initialized",
        max_connections=settings.streaming_max_connections,
    )

    # -- Workflow transport manager (S33: WS-first / SSE fallback) ----------
    from agent33.workflows.transport import (
        TransportConfig,
        TransportType,
        WorkflowTransportManager,
    )

    _transport_config = TransportConfig(
        preferred=TransportType(settings.workflow_transport_preferred),
        ws_ping_interval=settings.workflow_ws_ping_interval,
        ws_ping_timeout=settings.workflow_ws_ping_timeout,
    )
    workflow_transport_manager = WorkflowTransportManager(
        config=_transport_config,
        ws_manager=ws_manager,
    )
    app.state.workflow_transport_manager = workflow_transport_manager
    logger.info(
        "workflow_transport_manager_initialized",
        preferred=settings.workflow_transport_preferred,
    )

    # -- MCP bridge / server / transport ------------------------------------
    from agent33.mcp_server.bridge import MCPServiceBridge
    from agent33.mcp_server.proxy_manager import ProxyManager
    from agent33.mcp_server.proxy_models import ProxyFleetConfig
    from agent33.mcp_server.server import create_mcp_server

    proxy_config = ProxyFleetConfig()
    if settings.mcp_proxy_config_path.strip():
        proxy_config_path = Path(settings.mcp_proxy_config_path)
        try:
            if proxy_config_path.exists():
                proxy_config = ProxyFleetConfig.model_validate_json(
                    proxy_config_path.read_text(encoding="utf-8")
                )
            else:
                logger.warning("mcp_proxy_config_not_found", path=str(proxy_config_path))
        except Exception as exc:
            logger.warning(
                "mcp_proxy_config_invalid",
                path=str(proxy_config_path),
                error=str(exc),
                exc_info=True,
            )

    proxy_manager = ProxyManager(
        config=proxy_config,
        tool_separator=settings.mcp_proxy_tool_separator,
        health_check_enabled=settings.mcp_proxy_health_check_enabled,
    )
    proxy_manager.set_native_tool_names({tool.name for tool in tool_registry.list_all()})
    if settings.mcp_proxy_enabled:
        await proxy_manager.start_all()
    app.state.proxy_manager = proxy_manager
    mcp_proxy.set_proxy_manager(proxy_manager)
    mcp_proxy.set_config_path(settings.mcp_proxy_config_path)

    mcp_bridge = MCPServiceBridge(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        model_router=model_router,
        rag_pipeline=rag_pipeline,
        skill_registry=skill_registry,
        workflow_registry=workflows.get_workflow_registry(),
        proxy_manager=proxy_manager,
        tool_governance=tool_governance,
    )
    mcp_server = create_mcp_server(mcp_bridge)
    mcp_transport = None
    if mcp_server is not None:
        try:
            from mcp.server.sse import SseServerTransport
        except ImportError as exc:
            logger.warning(
                "mcp_sse_transport_unavailable",
                error=str(exc),
                exc_info=True,
            )
        else:
            mcp_transport = SseServerTransport("/v1/mcp/messages")

    app.state.mcp_bridge = mcp_bridge
    app.state.mcp_server = mcp_server
    app.state.mcp_transport = mcp_transport
    logger.info(
        "mcp_services_initialized",
        server_enabled=mcp_server is not None,
        transport_enabled=mcp_transport is not None,
    )

    # -- Plugin registry (Phase 32.8 — Plugin SDK) -------------------------
    from agent33.plugins.capabilities import CapabilityGrant
    from agent33.plugins.config_store import PluginConfigStore
    from agent33.plugins.context import PluginContext
    from agent33.plugins.doctor import PluginDoctor
    from agent33.plugins.events import PluginEventStore
    from agent33.plugins.installer import PluginInstaller
    from agent33.plugins.registry import PluginRegistry
    from agent33.plugins.scoped import (
        ReadOnlySettingsProxy,
        ScopedSkillRegistry,
        ScopedToolRegistry,
    )
    from agent33.services.orchestration_state import OrchestrationStateStore

    plugin_state_store = OrchestrationStateStore(
        str(state_paths.resolve_approved(settings.plugin_state_store_path))
    )
    plugin_event_store = PluginEventStore(plugin_state_store)
    plugin_config_store = PluginConfigStore(plugin_state_store)
    _plugin_allowlist = (
        [name.strip() for name in settings.plugin_allowlist.split(",") if name.strip()]
        if settings.plugin_allowlist.strip()
        else None
    )
    plugin_registry = PluginRegistry(
        event_store=plugin_event_store,
        allowlist=_plugin_allowlist,
    )
    plugins_dir = Path(settings.plugin_definitions_dir)

    def _plugin_context_factory(manifest: Any, plugin_dir: Path) -> PluginContext:
        """Build a scoped context for a plugin."""
        entry = plugin_registry.get(manifest.name)
        owner_tenant_id = entry.tenant_id if entry is not None else ""
        requested_permissions = [p.value for p in manifest.permissions]
        grants = CapabilityGrant(
            manifest_permissions=requested_permissions,
            tenant_grants=plugin_config_store.granted_permissions(
                manifest.name,
                tenant_id=owner_tenant_id,
                manifest_permissions=requested_permissions,
            ),
        )
        stored_config = plugin_config_store.get(manifest.name, tenant_id=owner_tenant_id)
        return PluginContext(
            plugin_name=manifest.name,
            plugin_dir=plugin_dir,
            granted_permissions=grants.effective_permissions,
            skill_registry=ScopedSkillRegistry(skill_registry, grants),
            tool_registry=ScopedToolRegistry(tool_registry, grants),
            agent_registry=agent_registry,
            hook_registry=getattr(app.state, "hook_registry", None),
            plugin_config=(
                dict(stored_config.config_overrides) if stored_config is not None else {}
            ),
            settings_reader=(
                ReadOnlySettingsProxy(settings) if grants.check("config:read") else None
            ),
        )

    app.state.plugin_context_factory = _plugin_context_factory
    app.state.plugin_state_store = plugin_state_store
    app.state.plugin_event_store = plugin_event_store
    app.state.plugin_config_store = plugin_config_store

    if plugins_dir.is_dir():
        plugin_count = plugin_registry.discover(plugins_dir)
        logger.info("plugin_registry_discovered", count=plugin_count, path=str(plugins_dir))
        if plugin_count > 0:
            loaded = await plugin_registry.load_all(_plugin_context_factory)
            logger.info("plugin_registry_loaded", loaded=loaded)
            if settings.plugin_auto_enable:
                for manifest in plugin_registry.list_all():
                    state = plugin_registry.get_state(manifest.name)
                    if state and state.value == "loaded":
                        try:
                            await plugin_registry.enable(manifest.name)
                        except Exception:
                            logger.warning(
                                "plugin_auto_enable_failed",
                                plugin=manifest.name,
                                exc_info=True,
                            )
    else:
        logger.debug("plugin_definitions_dir_not_found", path=str(plugins_dir))

    # Scan extra plugin discovery paths (P2.7)
    if settings.plugin_discovery_paths.strip():
        for extra_path_str in settings.plugin_discovery_paths.split(","):
            extra_path = Path(extra_path_str.strip())
            if extra_path.is_dir():
                extra_count = plugin_registry.discover(extra_path)
                logger.info(
                    "plugin_extra_path_discovered",
                    count=extra_count,
                    path=str(extra_path),
                )

    app.state.plugin_registry = plugin_registry
    app.state.plugin_installer = PluginInstaller(
        plugin_registry,
        plugins_dir=plugins_dir,
        context_factory=_plugin_context_factory,
        event_store=plugin_event_store,
        state_store=plugin_state_store,
        auto_enable=settings.plugin_auto_enable,
    )
    app.state.plugin_doctor = PluginDoctor(
        plugin_registry,
        config_store=plugin_config_store,
        installer=app.state.plugin_installer,
    )

    # -- Tool catalog service (aggregates all tool sources) -----------------
    from agent33.tools.catalog import ToolCatalogService

    tool_catalog_service = ToolCatalogService(
        tool_registry=tool_registry,
        skill_registry=skill_registry,
        plugin_registry=plugin_registry,
    )
    app.state.tool_catalog_service = tool_catalog_service
    tool_catalog_routes.set_catalog_service(tool_catalog_service)
    logger.info("tool_catalog_service_initialized")

    # -- Agent-workflow bridge (with subsystem injection) -------------------
    _register_agent_runtime_bridge(
        model_router,
        register_agent,
        registry=agent_registry,
        skill_injector=skill_injector,
        progressive_recall=progressive_recall,
        effort_router=getattr(agents, "_effort_router", None),
        routing_metrics_emitter=getattr(agents, "_record_effort_routing_metrics", None),
        hook_registry=hook_registry,
    )
    logger.info("agent_workflow_bridge_registered")

    # --- AirLLM provider (optional) ---
    if settings.airllm_enabled and settings.airllm_model_path:
        try:
            from agent33.llm.airllm_provider import AirLLMProvider

            airllm = AirLLMProvider(
                model_path=settings.airllm_model_path,
                device=settings.airllm_device,
                compression=settings.airllm_compression,
                max_seq_len=settings.airllm_max_seq_len,
                prefetch=settings.airllm_prefetch,
            )
            app.state.airllm_provider = airllm
            logger.info("airllm_provider_registered", model=settings.airllm_model_path)
        except ImportError:
            logger.warning("airllm_not_available", reason="airllm package not installed")

    # --- Memory subsystem ---
    try:
        from agent33.memory.observation import ObservationCapture
        from agent33.memory.summarizer import SessionSummarizer

        capture = ObservationCapture(
            nats_bus=nats_bus,
            redact_enabled=settings.redact_secrets_enabled,
        )
        app.state.observation_capture = capture
        logger.info("observation_capture_initialized")

        # Summarizer needs a router - will be available after agents routes init
        app.state.session_summarizer_class = SessionSummarizer
    except Exception:
        logger.debug("memory_subsystem_init_skipped", exc_info=True)

    # --- Phase 59: Session trajectory tracker & title generator ---
    try:
        from agent33.memory.title_generator import TitleGenerator
        from agent33.memory.trajectory import SessionTrajectoryTracker

        trajectory_tracker = SessionTrajectoryTracker()
        app.state.trajectory_tracker = trajectory_tracker

        # TitleGenerator uses heuristic-only until a router is wired.
        title_gen = TitleGenerator(router=model_router)
        app.state.title_generator = title_gen

        from agent33.api.routes import sessions as sessions_route_mod

        sessions_route_mod.set_trajectory_tracker(trajectory_tracker)
        sessions_route_mod.set_title_generator(title_gen)

        logger.info("trajectory_tracker_initialized")
    except Exception:
        logger.debug("trajectory_tracker_init_skipped", exc_info=True)

    # --- Comparative evaluation (AWM Tier 2 group-relative scoring) ---
    from agent33.evaluation.comparative.service import ComparativeEvaluationService

    comparative_service = ComparativeEvaluationService(
        elo_k_factor=settings.comparative_elo_k_factor,
        min_population_size=settings.comparative_min_population_size,
        confidence_level=settings.comparative_confidence_level,
    )
    app.state.comparative_service = comparative_service
    comparative.set_comparative_service(comparative_service)
    logger.info("comparative_evaluation_initialized")

    # --- Scheduled evaluation gates (S45) ---
    if settings.scheduled_gates_enabled:
        from agent33.evaluation.scheduled_gates import ScheduledGateService

        _eval_svc = evaluations.get_evaluation_service()
        scheduled_gate_service = ScheduledGateService(
            evaluation_service=_eval_svc,
            max_schedules=settings.scheduled_gates_max_schedules,
            history_retention=settings.scheduled_gates_history_retention,
        )
        # Guard scheduler startup with distributed lock (P1.2)
        _sched_owns = await scheduler_guard.acquire_ownership()
        if _sched_owns:
            await scheduled_gate_service.start()
            logger.info("scheduled_gate_service_initialized")
        else:
            logger.warning(
                "scheduled_gate_service_skipped_lock_held",
                instance_id=instance_registry.instance_id,
            )
        app.state.scheduled_gate_service = scheduled_gate_service
        scheduled_gates_routes.set_service(scheduled_gate_service)
        app.include_router(scheduled_gates_routes.router)

    # --- Synthetic environment generation (AWM Tier 2 A5) ---
    from agent33.evaluation.synthetic_envs.service import SyntheticEnvironmentService

    synthetic_environment_service = SyntheticEnvironmentService(
        workflow_dir=Path(settings.synthetic_env_workflow_dir),
        tool_dir=Path(settings.synthetic_env_tool_dir),
        max_saved_bundles=settings.synthetic_env_bundle_retention,
        persistence_path=(
            Path(settings.synthetic_env_bundle_persistence_path)
            if settings.synthetic_env_bundle_persistence_path.strip()
            else None
        ),
    )
    app.state.synthetic_environment_service = synthetic_environment_service
    synthetic_envs.set_synthetic_environment_service(synthetic_environment_service)
    logger.info(
        "synthetic_environment_service_initialized",
        workflow_count=len(synthetic_environment_service.list_workflows()),
    )

    configured_multimodal_service = multimodal.get_multimodal_service()
    daemon_factory = None
    if settings.voice_daemon_transport == "sidecar":
        from agent33.voice.client import SidecarVoiceDaemon

        daemon_factory = SidecarVoiceDaemon
    configured_multimodal_service.configure_voice_runtime(
        enabled=settings.voice_daemon_enabled,
        transport=settings.voice_daemon_transport,
        url=settings.voice_sidecar_url.strip() or settings.voice_daemon_url,
        api_key=settings.voice_daemon_api_key.get_secret_value(),
        api_secret=settings.voice_daemon_api_secret.get_secret_value(),
        room_prefix=settings.voice_daemon_room_prefix,
        max_sessions=settings.voice_daemon_max_sessions,
        daemon_factory=daemon_factory,
    )
    app.state.multimodal_service = configured_multimodal_service
    logger.info(
        "voice_runtime_configured",
        enabled=settings.voice_daemon_enabled,
        transport=settings.voice_daemon_transport,
        room_prefix=settings.voice_daemon_room_prefix,
    )

    # --- Operator control plane ---
    from agent33.operator.service import OperatorService

    operator_service = OperatorService(
        app_state=app.state,
        settings=settings,
        start_time=_start_time,
    )
    app.state.operator_service = operator_service
    logger.info("operator_service_initialized")

    # --- Rate limiter (S42) ---
    # The RateLimiter instance is created eagerly at module scope (for middleware
    # registration). Store the reference on app.state for route DI access.
    if settings.rate_limit_enabled:
        app.state.rate_limiter = _boot_rate_limiter
        logger.info(
            "rate_limiter_initialized",
            default_tier=settings.rate_limit_default_tier,
        )

    # --- Cron CRUD and job history (Track 9) ---
    from agent33.automation.cron_models import JobDefinition, JobHistoryStore

    cron_job_store: dict[str, JobDefinition] = {}
    job_history_store = JobHistoryStore()
    app.state.cron_job_store = cron_job_store
    app.state.job_history_store = job_history_store
    logger.info("cron_job_store_initialized")

    # --- Config apply service (Track 9) ---
    from agent33.config_apply import ConfigApplyService

    config_apply_service = ConfigApplyService(settings_cls=type(settings))
    app.state.config_apply_service = config_apply_service
    logger.info("config_apply_service_initialized")

    # --- Onboarding service (Track 9) ---
    from agent33.operator.onboarding import OnboardingService

    onboarding_service = OnboardingService(app_state=app.state, settings=settings)
    app.state.onboarding_service = onboarding_service
    logger.info("onboarding_service_initialized")

    # --- Ops subsystem (Track 9 — doctor, config, cron, onboarding) ---
    from agent33.ops.config_manager import ConfigManager
    from agent33.ops.cron_manager import CronManager
    from agent33.ops.doctor import SystemDoctor
    from agent33.ops.onboarding import OnboardingChecklistService

    _ops_version = ""
    _ops_version_info = getattr(app.state, "runtime_version_info", None)
    if _ops_version_info is not None:
        _ops_version = getattr(_ops_version_info, "version", "0.1.0")

    system_doctor = SystemDoctor(
        app_state=app.state,
        settings=settings,
        version=_ops_version,
    )
    app.state.system_doctor = system_doctor

    ops_config_manager = ConfigManager(
        settings_instance=settings,
    )
    app.state.ops_config_manager = ops_config_manager

    ops_cron_manager = CronManager(
        job_store=cron_job_store,
        scheduler=getattr(app.state, "workflow_scheduler", None),
        history_store=job_history_store,
    )
    app.state.ops_cron_manager = ops_cron_manager

    ops_onboarding = OnboardingChecklistService(
        app_state=app.state,
        settings=settings,
    )
    app.state.ops_onboarding = ops_onboarding

    app.state.start_time = _start_time
    logger.info("ops_subsystem_initialized")

    # --- Training subsystem (optional) ---
    if settings.training_enabled:
        try:
            from agent33.training.store import TrainingStore

            training_store = TrainingStore(settings.database_url)
            await training_store.initialize()
            app.state.training_store = training_store
            logger.info("training_store_initialized")
        except Exception:
            logger.warning("training_store_init_failed", exc_info=True)

    # -- Template catalog --------------------------------------------------
    from agent33.workflows.template_catalog import TemplateCatalog

    _template_dir = Path(settings.agent_definitions_dir).parent / "..core"
    # Resolve the core/workflows directory relative to the engine root
    _core_workflows_dir = Path(settings.agent_definitions_dir).parent.parent / "core" / "workflows"
    if not _core_workflows_dir.is_dir():
        # Fallback: try relative to CWD
        _core_workflows_dir = Path("core/workflows")
    template_catalog = TemplateCatalog(_core_workflows_dir)
    template_catalog.refresh()

    # Add quick-start operator templates from core/templates/ (P65)
    _core_templates_dir = Path(settings.agent_definitions_dir).parent.parent / "core" / "templates"
    if not _core_templates_dir.is_dir():
        _core_templates_dir = Path("core/templates")
    _qs_count = template_catalog.add_directory(_core_templates_dir)

    app.state.template_catalog = template_catalog
    workflow_templates.set_template_catalog(template_catalog)
    logger.info(
        "template_catalog_initialized",
        count=len(template_catalog.list_templates()),
        quick_start_count=_qs_count,
        path=str(_core_workflows_dir),
    )

    # -- Workflow template marketplace (S41) --------------------------------
    if settings.workflow_marketplace_enabled:
        from agent33.workflows.marketplace import WorkflowMarketplace

        _wm_dir = settings.workflow_templates_dir
        wf_marketplace = WorkflowMarketplace(_wm_dir if _wm_dir else None)
        wf_marketplace.discover_builtin_templates()
        app.state.workflow_marketplace = wf_marketplace
        workflow_marketplace.set_workflow_marketplace(wf_marketplace)
        logger.info(
            "workflow_marketplace_initialized",
            count=wf_marketplace.count,
            path=_wm_dir,
        )

    # -- Discovery service (Phase 46A) --------------------------------------
    from agent33.discovery.service import DiscoveryService
    from agent33.tools.discovery_runtime import (
        DISCOVER_TOOLS_TOOL_NAME,
        DISCOVER_TOOLS_TOOL_VERSION,
        DiscoverToolsTool,
        ToolActivationManager,
    )
    from agent33.tools.registry_entry import ToolRegistryEntry

    discovery_service = DiscoveryService(
        tool_registry=tool_registry,
        skill_registry=skill_registry,
        pack_registry=pack_registry,
        workflow_registry=workflows.get_workflow_registry(),
        template_catalog=template_catalog,
    )
    tool_activation_manager = ToolActivationManager()
    discover_tools_tool = DiscoverToolsTool(
        discovery_service=discovery_service,
        activation_manager=tool_activation_manager,
        mode=settings.tool_discovery_mode,
    )
    tool_registry.register_with_entry(
        discover_tools_tool,
        ToolRegistryEntry(
            tool_id=DISCOVER_TOOLS_TOOL_NAME,
            name=DISCOVER_TOOLS_TOOL_NAME,
            version=DISCOVER_TOOLS_TOOL_VERSION,
            description=discover_tools_tool.description,
            owner="agent33",
            tags=["discovery", "meta"],
            parameters_schema=discover_tools_tool.parameters_schema,
        ),
    )
    app.state.discovery_service = discovery_service
    app.state.tool_activation_manager = tool_activation_manager
    discovery_routes.set_discovery_service(discovery_service)
    mcp_bridge.discovery_service = discovery_service
    mcp_bridge.tool_activation_manager = tool_activation_manager
    mcp_bridge.tool_discovery_mode = settings.tool_discovery_mode
    proxy_manager.set_native_tool_names({tool.name for tool in tool_registry.list_all()})
    logger.info("discovery_service_initialized")

    # -- Provenance & runtime version -----------------------------------------
    from agent33.provenance.audit_export import AuditExporter as _AuditExporter
    from agent33.provenance.collector import ProvenanceCollector as _ProvenanceCollector
    from agent33.provenance.timeline import AuditTimelineService as _AuditTimelineService
    from agent33.runtime.version import resolve_version as _resolve_version

    _provenance_collector = _ProvenanceCollector(
        max_receipts=settings.provenance_max_receipts,
    )
    _audit_timeline_service = _AuditTimelineService(_provenance_collector)
    _audit_exporter = _AuditExporter(_provenance_collector)
    app.state.provenance_collector = _provenance_collector
    app.state.audit_timeline_service = _audit_timeline_service
    app.state.audit_exporter = _audit_exporter

    # Back-wire provenance collector into trust analytics (initialized earlier)
    if hasattr(app.state, "trust_analytics"):
        app.state.trust_analytics._provenance_collector = _provenance_collector

    # Back-wire provenance collector into pack audit service (initialized earlier)
    if hasattr(app.state, "pack_audit"):
        app.state.pack_audit._provenance_collector = _provenance_collector

    _runtime_version_info = _resolve_version()
    app.state.runtime_version_info = _runtime_version_info
    logger.info(
        "provenance_and_runtime_initialized",
        version=_runtime_version_info.version,
        git_hash=_runtime_version_info.git_short_hash,
    )

    # -- Receipt store, receipt exporter, runtime guard (upstream agent OS T10) --------
    from agent33.ops.runtime_guard import RuntimeGuard as _RuntimeGuard
    from agent33.provenance.audit_export import ReceiptExporter as _ReceiptExporter
    from agent33.provenance.receipts import ReceiptStore as _ReceiptStore

    _receipt_store = _ReceiptStore(
        max_receipts=settings.provenance_max_receipts,
        state_store=orchestration_state_store,
    )
    _receipt_exporter = _ReceiptExporter(_receipt_store)
    _runtime_guard = _RuntimeGuard(app.state, start_time=_start_time)
    app.state.receipt_store = _receipt_store
    app.state.receipt_exporter = _receipt_exporter
    app.state.runtime_guard = _runtime_guard
    logger.info("t10_services_initialized")

    # -- Benchmark harness (S26) ----------------------------------------------
    from agent33.evaluation.benchmark import BenchmarkHarness
    from agent33.evaluation.benchmark_catalog import DEFAULT_BENCHMARK_CATALOG

    _benchmark_catalog = list(DEFAULT_BENCHMARK_CATALOG)
    if settings.evaluation_benchmark_catalog_path.strip():
        _custom_catalog_path = Path(settings.evaluation_benchmark_catalog_path)
        if _custom_catalog_path.exists():
            try:
                _benchmark_catalog = BenchmarkHarness.load_catalog_from_file(_custom_catalog_path)
                logger.info(
                    "benchmark_catalog_loaded_from_file",
                    path=str(_custom_catalog_path),
                    count=len(_benchmark_catalog),
                )
            except Exception as exc:
                logger.warning(
                    "benchmark_catalog_load_failed",
                    path=str(_custom_catalog_path),
                    error=str(exc),
                )
        else:
            logger.warning(
                "benchmark_catalog_path_not_found",
                path=str(_custom_catalog_path),
            )

    benchmark_harness = BenchmarkHarness(task_catalog=_benchmark_catalog)
    app.state.benchmark_harness = benchmark_harness
    evaluations.set_benchmark_harness(benchmark_harness)
    logger.info("benchmark_harness_initialized", tasks=len(_benchmark_catalog))

    # -- Tuning loop scheduler (Phase 31) ------------------------------------
    if settings.improvement_tuning_loop_enabled and settings.improvement_learning_enabled:
        # Only start the tuning loop if this instance owns the scheduler lock (P1.2)
        _tuning_owns = scheduler_guard._lock.is_held
        if not _tuning_owns:
            # If scheduled gates did not claim ownership, try now
            _tuning_owns = await scheduler_guard.acquire_ownership()
        if _tuning_owns:
            try:
                from agent33.improvement.tuning import TuningLoopScheduler, TuningLoopService

                _improvement_svc = improvements.get_improvement_service()
                _config_apply_svc = getattr(app.state, "config_apply_service", None)
                _tuning_svc = TuningLoopService(_improvement_svc, _config_apply_svc, settings)
                _tuning_scheduler = TuningLoopScheduler(
                    _tuning_svc, settings.improvement_tuning_loop_interval_hours
                )
                app.state.tuning_loop_scheduler = _tuning_scheduler
                await _tuning_scheduler.start()
                logger.info("tuning_loop_scheduler_started")
            except Exception:
                logger.warning("tuning_loop_scheduler_init_failed", exc_info=True)
        else:
            logger.warning(
                "tuning_loop_scheduler_skipped_lock_held",
                instance_id=instance_registry.instance_id,
            )

    # -- Webhook delivery manager (S43) ------------------------------------
    from agent33.automation.webhook_delivery import WebhookDeliveryManager

    _webhook_delivery_mgr = WebhookDeliveryManager(
        max_retries=settings.webhook_delivery_max_retries,
        base_delay_seconds=settings.webhook_delivery_base_delay,
        max_delay_seconds=settings.webhook_delivery_max_delay,
        max_records=settings.webhook_delivery_max_records,
    )
    app.state.webhook_delivery = _webhook_delivery_mgr
    logger.info(
        "webhook_delivery_manager_initialized",
        max_retries=settings.webhook_delivery_max_retries,
        max_records=settings.webhook_delivery_max_records,
    )

    # -- Alembic migration checker (S34) ------------------------------------
    from agent33.migrations.checker import MigrationChecker as _MigrationChecker

    _migration_checker = _MigrationChecker(
        alembic_dir=str(Path(settings.alembic_config_path).parent / "alembic"),
        config_file=settings.alembic_config_path,
    )
    app.state.migration_checker = _migration_checker
    if settings.alembic_auto_check_on_startup:
        try:
            _mig_status = _migration_checker.get_status()
            if not _mig_status.chain_valid:
                logger.warning("alembic_chain_invalid", heads=_mig_status.heads)
            elif _mig_status.has_multiple_heads:
                logger.warning("alembic_multiple_heads", heads=_mig_status.heads)
            else:
                logger.info(
                    "alembic_chain_ok",
                    head=_mig_status.current_head,
                    revisions=len(_migration_checker.list_revisions()),
                )
        except Exception:
            logger.warning("alembic_auto_check_failed", exc_info=True)

    # -- Multi-replica state repositories (P3.4) ----------------------------
    from agent33.automation.webhook_repository import (
        InMemoryWebhookRepository,
        get_webhook_repository,
        set_webhook_repository,
    )
    from agent33.security.auth_repository import (
        InMemoryAuthRepository,
        get_auth_repository,
    )

    # Install SQLite-backed control-plane repositories when configured (P4.5).
    if settings.control_plane_backend == "sqlite":
        from agent33.automation.job_history_repository import set_job_history_repository
        from agent33.automation.pg_job_history_repository import SqliteJobHistoryRepository
        from agent33.automation.pg_scheduler_repository import SqliteSchedulerJobRepository
        from agent33.automation.pg_webhook_repository import SqliteWebhookRepository
        from agent33.automation.scheduler_repository import set_scheduler_job_repository

        _cp_db = settings.control_plane_db_path
        set_scheduler_job_repository(SqliteSchedulerJobRepository(_cp_db))
        set_job_history_repository(SqliteJobHistoryRepository(_cp_db))
        set_webhook_repository(SqliteWebhookRepository(_cp_db))
        logger.info(
            "control_plane_sqlite_repositories_installed",
            db_path=_cp_db,
        )

    # Use get_*() to reuse the lazily-created default repository instead of
    # creating a new one.  This preserves the reference that module-level
    # ``_users`` / ``_api_keys`` backwards-compatible aliases already hold.
    auth_repo = get_auth_repository()
    logger.info(
        "auth_repository_initialized",
        backend="in_memory" if isinstance(auth_repo, InMemoryAuthRepository) else "custom",
    )

    webhook_repo = get_webhook_repository()
    logger.info(
        "webhook_repository_initialized",
        backend="in_memory" if isinstance(webhook_repo, InMemoryWebhookRepository) else "custom",
    )

    from agent33.automation.job_history_repository import (
        InMemoryJobHistoryRepository,
        get_job_history_repository,
    )
    from agent33.automation.scheduler_repository import (
        InMemorySchedulerJobRepository,
        get_scheduler_job_repository,
    )

    scheduler_job_repo = get_scheduler_job_repository()
    logger.info(
        "scheduler_job_repository_initialized",
        backend=(
            "in_memory"
            if isinstance(scheduler_job_repo, InMemorySchedulerJobRepository)
            else "custom"
        ),
    )

    job_history_repo = get_job_history_repository()
    logger.info(
        "job_history_repository_initialized",
        backend=(
            "in_memory" if isinstance(job_history_repo, InMemoryJobHistoryRepository) else "custom"
        ),
    )

    # -- Outcomes service (P68-Lite + P72 persistence) -------------------------
    from agent33.evaluation.ppack_ab_persistence import PPackABPersistence
    from agent33.evaluation.ppack_ab_service import GitHubIssueAlertConfig, PPackABService
    from agent33.outcomes.persistence import OutcomePersistence
    from agent33.outcomes.service import OutcomesService

    outcomes_persistence = OutcomePersistence(Path(settings.outcomes_db_path))
    outcomes_service = OutcomesService(persistence=outcomes_persistence)
    ppack_ab_persistence = PPackABPersistence(settings.ppack_v3_ab_db_path)
    ppack_ab_service = PPackABService(
        outcomes_service=outcomes_service,
        persistence=ppack_ab_persistence,
        enabled=settings.ppack_v3_ab_enabled,
        experiment_key=settings.ppack_v3_ab_experiment_key,
        confidence_level=settings.comparative_confidence_level,
        minimum_sample_size=settings.ppack_v3_ab_min_samples_per_variant,
        regression_threshold=settings.ppack_v3_ab_regression_threshold,
        weekly_window_days=settings.ppack_v3_ab_weekly_window_days,
        alert_config=GitHubIssueAlertConfig(
            enabled=settings.ppack_v3_ab_issue_alert_enabled,
            owner=settings.ppack_v3_ab_github_owner,
            repo=settings.ppack_v3_ab_github_repo,
            token=settings.ppack_v3_ab_github_token.get_secret_value(),
        ),
    )
    app.state.outcomes_service = outcomes_service
    app.state.outcomes_persistence = outcomes_persistence
    app.state.ppack_ab_service = ppack_ab_service
    app.state.ppack_ab_persistence = ppack_ab_persistence
    outcomes.set_outcomes_service(outcomes_service)
    outcomes.set_ppack_ab_service(ppack_ab_service)
    logger.info("outcomes_service_initialized", db_path=settings.outcomes_db_path)
    logger.info("ppack_ab_service_initialized", db_path=settings.ppack_v3_ab_db_path)

    # -- Context compression engine (Phase 50) ---------------------------------
    context_compressor = None
    if settings.context_compression_enabled:
        from agent33.memory.context_compressor import ContextCompressor

        context_compressor = ContextCompressor(
            threshold_percent=settings.context_compression_threshold_percent,
            protect_first_n=settings.context_compression_protect_first_n,
            tail_token_budget=settings.context_compression_tail_token_budget,
            summary_target_ratio=settings.context_compression_summary_target_ratio,
            summary_tokens_ceiling=settings.context_compression_summary_tokens_ceiling,
            summarize_model=settings.context_compression_summarize_model,
        )
        logger.info(
            "context_compressor_initialized",
            threshold_percent=settings.context_compression_threshold_percent,
            protect_first_n=settings.context_compression_protect_first_n,
            tail_token_budget=settings.context_compression_tail_token_budget,
        )
    app.state.context_compressor = context_compressor

    yield

    # -- Shutdown ----------------------------------------------------------
    logger.info("agent33_stopping")

    # Flush operator sessions before other subsystems shut down
    _session_svc: Any = getattr(app.state, "operator_session_service", None)
    if _session_svc is not None:
        try:
            await _session_svc.shutdown()
            logger.info("operator_session_service_shutdown")
        except Exception:
            logger.warning("operator_session_service_shutdown_failed", exc_info=True)

    _process_manager: Any = getattr(app.state, "process_manager_service", None)
    if _process_manager is not None:
        try:
            await _process_manager.shutdown()
            logger.info("process_manager_service_shutdown")
        except Exception:
            logger.warning("process_manager_service_shutdown_failed", exc_info=True)

    workflows.set_ws_manager(None)
    workflows.set_workflow_run_archive_service(None)

    _spawner_svc: Any = getattr(app.state, "spawner_service", None)
    if _spawner_svc is not None:
        try:
            await _spawner_svc.shutdown()
            logger.info("spawner_service_shutdown")
        except Exception:
            logger.warning("spawner_service_shutdown_failed", exc_info=True)

    _ollama_readiness_svc: Any = getattr(app.state, "ollama_readiness_service", None)
    if _ollama_readiness_svc is not None:
        await _ollama_readiness_svc.aclose()
        logger.info("ollama_readiness_service_shutdown")

    _lm_studio_readiness_svc: Any = getattr(app.state, "lm_studio_readiness_service", None)
    if _lm_studio_readiness_svc is not None:
        await _lm_studio_readiness_svc.aclose()
        logger.info("lm_studio_readiness_service_shutdown")

    shutdown_multimodal_service: Any = getattr(app.state, "multimodal_service", None)
    if shutdown_multimodal_service is not None:
        await shutdown_multimodal_service.shutdown_voice_sessions()
        logger.info("voice_runtime_shutdown")

    _plugin_reg: Any = getattr(app.state, "plugin_registry", None)
    if _plugin_reg is not None:
        try:
            await _plugin_reg.unload_all()
            logger.info("plugin_registry_unloaded")
        except Exception:
            logger.warning("plugin_registry_unload_failed", exc_info=True)

    _training_store: Any = getattr(app.state, "training_store", None)
    if _training_store is not None:
        await _training_store.close()

    _scheduled_gate_svc: Any = getattr(app.state, "scheduled_gate_service", None)
    if _scheduled_gate_svc is not None:
        await _scheduled_gate_svc.stop()
        logger.info("scheduled_gate_service_stopped")

    _proxy_manager: Any = getattr(app.state, "proxy_manager", None)
    if _proxy_manager is not None:
        await _proxy_manager.stop_all()
        logger.info("mcp_proxy_manager_stopped")

    scheduler = getattr(app.state, "training_scheduler", None)
    if scheduler is not None:
        await scheduler.stop()

    _tuning_loop_scheduler: Any = getattr(app.state, "tuning_loop_scheduler", None)
    if _tuning_loop_scheduler is not None:
        await _tuning_loop_scheduler.stop()
        logger.info("tuning_loop_scheduler_stopped")

    _knowledge_svc: Any = getattr(app.state, "knowledge_service", None)
    if _knowledge_svc is not None:
        _knowledge_svc.stop()
        logger.info("knowledge_ingestion_service_stopped")

    # Close embedding provider (cache.close() delegates to provider.close())
    _embedder = getattr(app.state, "embedding_cache", None) or getattr(
        app.state, "embedding_provider", None
    )
    if _embedder is not None:
        await _embedder.close()
        logger.info("embedding_provider_closed")

    # Release scheduler ownership and deregister instance (P1.2)
    # Must happen before Redis is closed since it uses Redis keys.
    _sched_guard: Any = getattr(app.state, "scheduler_guard", None)
    if _sched_guard is not None:
        try:
            await _sched_guard.release_ownership()
        except Exception:
            logger.warning("scheduler_guard_release_failed", exc_info=True)

    _inst_registry: Any = getattr(app.state, "instance_registry", None)
    if _inst_registry is not None:
        try:
            await _inst_registry.deregister()
            logger.info("instance_deregistered")
        except Exception:
            logger.warning("instance_deregister_failed", exc_info=True)

    _ingestion_persistence: Any = getattr(app.state, "ingestion_persistence", None)
    if _ingestion_persistence is not None:
        _ingestion_persistence.close()
        logger.info("ingestion_persistence_closed")

    _ingestion_journal: Any = getattr(app.state, "ingestion_journal", None)
    if _ingestion_journal is not None:
        _ingestion_journal.close()
        logger.info("ingestion_journal_closed")

    _ingestion_notification_service: Any = getattr(
        app.state,
        "ingestion_notification_service",
        None,
    )
    if _ingestion_notification_service is not None:
        _ingestion_notification_service.close()
        logger.info("ingestion_notification_service_closed")

    _ingestion_mailbox_persistence: Any = getattr(app.state, "ingestion_mailbox_persistence", None)
    if _ingestion_mailbox_persistence is not None:
        _ingestion_mailbox_persistence.close()
        logger.info("ingestion_mailbox_persistence_closed")

    _task_metrics: Any = getattr(app.state, "task_metrics", None)
    if _task_metrics is not None:
        _task_metrics.close()
        logger.info("ingestion_task_metrics_closed")

    _p69b_persistence: Any = getattr(app.state, "p69b_persistence", None)
    if _p69b_persistence is not None:
        _p69b_persistence.close()
        logger.info("p69b_persistence_closed")

    _outcomes_persistence: Any = getattr(app.state, "outcomes_persistence", None)
    if _outcomes_persistence is not None:
        _outcomes_persistence.close()
        logger.info("outcomes_persistence_closed")

    _ppack_ab_persistence: Any = getattr(app.state, "ppack_ab_persistence", None)
    if _ppack_ab_persistence is not None:
        _ppack_ab_persistence.close()
        logger.info("ppack_ab_persistence_closed")

    _security_store: Any = getattr(app.state, "security_scan_store", None)
    if _security_store is not None:
        _security_store.close()
        logger.info("security_scan_store_closed")

    if nats_bus.is_connected:
        await nats_bus.close()
        logger.info("nats_closed")

    if redis_conn is not None:
        await redis_conn.aclose()
        logger.info("redis_closed")

    if long_term_memory is not None:
        await long_term_memory.close()
        logger.info("database_closed")


def _redact_url(url: str) -> str:
    """Return the host portion of a database URL to avoid logging credentials."""
    if "@" in url:
        return url.split("@", 1)[-1]
    return url


def _register_agent_runtime_bridge(
    model_router: ModelRouter,
    register_fn: Callable[..., object],
    registry: Any = None,
    skill_injector: Any = None,
    progressive_recall: Any = None,
    effort_router: Any = None,
    routing_metrics_emitter: Callable[[dict[str, Any] | None], None] | None = None,
    hook_registry: Any = None,
) -> None:
    """Create a bridge so workflow invoke-agent steps can run AgentRuntime.

    The bridge intercepts calls from the workflow executor's invoke-agent
    action.  It first looks up the agent in the registry to use the real
    definition (with governance, ownership, safety rules).  Falls back to
    a lightweight throwaway definition only when the name is not registered.
    """
    from agent33.agents.definition import (
        AgentConstraints,
        AgentDefinition,
        AgentParameter,
        AgentRole,
    )
    from agent33.agents.runtime import AgentRuntime

    async def _bridge(inputs: dict[str, Any]) -> dict[str, Any]:
        agent_name = inputs.pop("agent_name", "workflow-agent")
        model = inputs.pop("model", None)
        active_skills_raw = inputs.pop("active_skills", None)

        # Try to look up actual registered definition first
        definition = None
        if registry is not None:
            definition = registry.get(agent_name)

        if definition is None:
            # Fall back to throwaway definition for unknown agents
            definition = AgentDefinition(
                name=agent_name,
                version="0.1.0",
                role=AgentRole.WORKER,
                description=f"Dynamically invoked agent '{agent_name}'",
                inputs={
                    k: AgentParameter(type="string", description="Workflow input")
                    for k in inputs
                    if k.isidentifier()
                },
                outputs={
                    "result": AgentParameter(type="string", description="result"),
                },
                constraints=AgentConstraints(),
            )
        if active_skills_raw is None:
            active_skills = list(definition.skills)
        elif isinstance(active_skills_raw, list):
            active_skills = [
                str(skill).strip() for skill in active_skills_raw if str(skill).strip()
            ]
        else:
            normalized = str(active_skills_raw).strip()
            active_skills = [normalized] if normalized else list(definition.skills)

        runtime = AgentRuntime(
            definition=definition,
            router=model_router,
            model=model,
            skill_injector=skill_injector,
            active_skills=active_skills,
            progressive_recall=progressive_recall,
            effort_router=effort_router,
            routing_metrics_emitter=routing_metrics_emitter,
            hook_registry=hook_registry,
        )
        result = await runtime.invoke(inputs)
        return result.output

    register_fn("__default__", _bridge)


# -- Request size limit middleware ----------------------------------------------


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds the configured limit."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > settings.max_request_size_bytes:
            return Response(
                content='{"detail":"Request body too large"}',
                status_code=413,
                media_type="application/json",
            )
        response: Response = await call_next(request)
        return response


# -- Application factory ------------------------------------------------------

app = FastAPI(
    title="AGENT-33",
    description="Autonomous AI agent orchestration engine",
    version="0.1.0",
    lifespan=lifespan,
)

# -- Middleware (order matters: last added = first executed) --------------------
# Order: SessionPod -> HTTPMetrics -> CORS -> Auth -> RateLimit -> SizeLimit -> Hooks -> Router
# HookMiddleware added first so it runs last (after auth resolves tenant_id)
app.add_middleware(HookMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)

# Rate limit middleware: runs after auth resolves tenant_id.
# The RateLimiter is a lightweight in-memory object, safe to create eagerly.
if settings.rate_limit_enabled:
    from agent33.security.rate_limiter import (
        RateLimiter as _BootRateLimiter,
    )
    from agent33.security.rate_limiter import (
        RateLimitMiddleware,
    )
    from agent33.security.rate_limiter import (
        RateLimitTier as _BootRateLimitTier,
    )

    _boot_rate_limiter = _BootRateLimiter(
        default_tier=_BootRateLimitTier(settings.rate_limit_default_tier),
    )
    # Store eagerly on app.state so tests can reset per-tenant state even
    # before the async lifespan runs (TestClient without context manager).
    app.state.rate_limiter = _boot_rate_limiter
    app.add_middleware(RateLimitMiddleware, rate_limiter=_boot_rate_limiter)

app.add_middleware(AuthMiddleware)

_cors_origins = settings.cors_allowed_origins.split(",") if settings.cors_allowed_origins else []
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

# HTTP metrics middleware: records request count and latency.
# Collector is resolved lazily from app.state.metrics_collector (set in lifespan).
app.add_middleware(HTTPMetricsMiddleware)

# Session pod identity middleware: outermost layer, adds X-Agent33-Session-Pod
# header for debugging sticky routing in multi-replica deployments.
app.add_middleware(SessionPodMiddleware)


# -- Routers -------------------------------------------------------------------

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(agents.router)
app.include_router(workflows.router)
app.include_router(visualizations.router)
app.include_router(explanations.router)
app.include_router(auth.router)
app.include_router(browser_sessions.router)
app.include_router(webhooks.router)
app.include_router(webhook_delivery.router)
app.include_router(dashboard.router)
app.include_router(dashboard.prometheus_router)
app.include_router(memory_search.router)
app.include_router(discovery_routes.router)
app.include_router(reviews.router)
app.include_router(run_ledger.router)
app.include_router(traces.router)
app.include_router(evaluations.router)
app.include_router(autonomy.router)
app.include_router(releases.router)
app.include_router(research.router)
app.include_router(resources.router)
app.include_router(web_research.router)
app.include_router(improvements.router)
app.include_router(insights.router)
app.include_router(training.router)
app.include_router(benchmarks.router)
app.include_router(component_security.router)
app.include_router(outcomes.router)
app.include_router(multimodal.router)
app.include_router(multimodal.voice_health_router)
app.include_router(operations_hub.router)
app.include_router(marketplace.router)
app.include_router(mcp.router)
app.include_router(mcp_proxy.router)
app.include_router(mcp_sync.router)
app.include_router(plugins_routes.router)
app.include_router(packs.router)
app.include_router(capability_packs_routes.router)
app.include_router(reasoning.router)
app.include_router(replay.router)
app.include_router(checkpoints.router)
app.include_router(artifacts.router)
app.include_router(step_retry.router)
app.include_router(rag.router)
app.include_router(hooks.router)
app.include_router(comparative.router)
app.include_router(compatibility.router)
app.include_router(synthetic_envs.router)
app.include_router(p69b.router)
app.include_router(ingestion.router)
app.include_router(tool_approvals.router)
app.include_router(tool_mutations.router)
app.include_router(processes.router)
app.include_router(backups.router)
app.include_router(sessions.router)
app.include_router(context.router)
app.include_router(operator.router)
app.include_router(openrouter.router)
app.include_router(ollama.router)
app.include_router(lm_studio.router)
app.include_router(model_health.router)
app.include_router(cron.router)
app.include_router(config_routes.router)
app.include_router(operations.router)
app.include_router(workflow_sse.router)
app.include_router(workflow_templates.router)
app.include_router(workflow_marketplace.router)
app.include_router(moa.router)
app.include_router(workflow_transport.router)
app.include_router(workflow_ws.router)
app.include_router(tool_catalog_routes.router)
app.include_router(provenance.router)
app.include_router(connectors.router)
app.include_router(doctor.router)
app.include_router(delegation.router)
app.include_router(spawner.router)
app.include_router(skill_authoring_routes.router)
app.include_router(skill_matching_routes.router)
app.include_router(commands.router)
app.include_router(execution_routes.router)
app.include_router(tool_gateway.router)
app.include_router(completion_gate.router)
app.include_router(migrations.router)
app.include_router(rate_limits_routes.router)
app.include_router(streaming.router)
app.include_router(support.router)
app.include_router(sandboxing.router)
app.include_router(planning.router)
app.include_router(knowledge.router)
app.include_router(policy.router)
if settings.embedding_hot_swap_enabled:
    app.include_router(embedding_swap_routes.router)
