"""Unit tests for the OperatorService class.

Tests exercise service methods directly (not through HTTP) to verify
business logic: status aggregation, config redaction, reset behavior,
tool summary construction, and session catalog.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from pydantic import SecretStr

from agent33.backup.manifest import BackupSummary
from agent33.config import Settings
from agent33.operator.models import CheckStatus, ResetTarget
from agent33.operator.service import OperatorService, _mask_db_url

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_service(
    *,
    agent_count: int = 2,
    tool_count: int = 3,
    redis: Any = "present",
    nats_connected: bool = True,
) -> OperatorService:
    agents = [SimpleNamespace(name=f"a{i}") for i in range(agent_count)]
    tools = [SimpleNamespace(name=f"t{i}", parameters_schema=None) for i in range(tool_count)]
    redis_obj = MagicMock() if redis == "present" else None
    nats_bus = SimpleNamespace(is_connected=nats_connected)
    ltm = MagicMock()

    state = SimpleNamespace(
        agent_registry=SimpleNamespace(
            list_all=lambda: agents,
            discover=lambda p: len(agents),
        ),
        tool_registry=SimpleNamespace(
            list_all=lambda: tools,
            get_entry=lambda n: None,
        ),
        plugin_registry=SimpleNamespace(
            list_all=lambda: [],
            get_state=lambda n: None,
            count=0,
        ),
        pack_registry=SimpleNamespace(
            list_all=lambda: [],
            discover=lambda: 0,
        ),
        skill_registry=SimpleNamespace(
            list_all=lambda: [],
        ),
        hook_registry=SimpleNamespace(count=lambda: 0),
        redis=redis_obj,
        nats_bus=nats_bus,
        long_term_memory=ltm,
        embedding_cache=None,
        bm25_index=None,
        multimodal_service=SimpleNamespace(
            list_voice_sessions=lambda limit=1000: [
                SimpleNamespace(state=SimpleNamespace(value="active"))
            ]
        ),
        voice_sidecar_probe=SimpleNamespace(health_snapshot=_async_return({"status": "ok"})),
        status_line_service=SimpleNamespace(health_snapshot=_async_return({"status": "ok"})),
    )
    return OperatorService(
        app_state=state,
        settings=Settings(),
        start_time=time.time() - 60,
    )


def _async_return(value: Any) -> Any:
    async def _inner() -> Any:
        return value

    return _inner


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class TestGetStatus:
    async def test_inventories_reflect_registry_counts(self) -> None:
        svc = _build_service(agent_count=4, tool_count=7)
        status = await svc.get_status()
        assert status.inventories["agents"].count == 4
        assert status.inventories["tools"].count == 7

    async def test_uptime_is_positive(self) -> None:
        svc = _build_service()
        status = await svc.get_status()
        assert status.runtime.uptime_seconds > 0

    async def test_healthy_when_all_services_present(self) -> None:
        svc = _build_service(redis="present", nats_connected=True)
        status = await svc.get_status()
        assert status.health["status"] == "healthy"

    async def test_degraded_when_redis_missing(self) -> None:
        svc = _build_service(redis=None)
        status = await svc.get_status()
        assert status.health["status"] == "degraded"

    async def test_degraded_when_nats_disconnected(self) -> None:
        svc = _build_service(nats_connected=False)
        status = await svc.get_status()
        assert status.health["status"] == "degraded"

    async def test_status_includes_voice_and_status_line_surfaces(self) -> None:
        svc = _build_service()
        status = await svc.get_status()
        assert status.health["services"]["voice_sidecar"] == "ok"
        assert status.health["services"]["status_line"] == "ok"
        assert status.inventories["voice_sessions"].active == 1


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestGetConfig:
    def test_jwt_secret_redacted(self) -> None:
        svc = _build_service()
        config = svc.get_config()
        assert config.groups["security"]["jwt_secret"] == "***"

    def test_api_secret_key_redacted(self) -> None:
        svc = _build_service()
        config = svc.get_config()
        assert config.groups["security"]["api_secret_key"] == "***"

    def test_database_url_masked(self) -> None:
        svc = _build_service()
        config = svc.get_config()
        db_url = config.groups["database"]["database_url"]
        assert "agent33:agent33" not in db_url
        assert "***:***@" in db_url

    def test_feature_flags_are_booleans(self) -> None:
        svc = _build_service()
        config = svc.get_config()
        for key, value in config.feature_flags.items():
            assert isinstance(value, bool), f"Flag {key} is not bool: {value}"

    def test_openrouter_key_present_and_redacted_when_set(self) -> None:
        svc = _build_service()
        object.__setattr__(svc._settings, "openrouter_api_key", SecretStr("sk-or-test"))
        config = svc.get_config()
        assert config.groups["llm"]["openrouter_api_key"] == "***"

    def test_openai_key_present_and_redacted_when_set(self) -> None:
        svc = _build_service()
        object.__setattr__(svc._settings, "openai_api_key", SecretStr("sk-openai-test"))
        config = svc.get_config()
        assert config.groups["llm"]["openai_api_key"] == "***"

    def test_default_model_is_reported_only_under_llm_group(self) -> None:
        svc = _build_service()
        object.__setattr__(svc._settings, "default_model", "openrouter/auto")
        config = svc.get_config()
        assert config.groups["llm"]["default_model"] == "openrouter/auto"
        assert "default_model" not in config.groups["ollama"]

    def test_has_expected_groups(self) -> None:
        svc = _build_service()
        config = svc.get_config()
        expected_groups = {
            "database",
            "redis",
            "nats",
            "ollama",
            "lm_studio",
            "local_orchestration",
            "llm",
            "agents",
            "skills",
            "plugins",
            "packs",
            "security",
            "environment",
        }
        assert set(config.groups.keys()) == expected_groups

    def test_local_orchestration_runtime_config_is_exposed(self) -> None:
        svc = _build_service()
        object.__setattr__(
            svc._settings, "local_orchestration_base_url", "http://localhost:8033/v1"
        )
        object.__setattr__(svc._settings, "local_orchestration_model", "qwen3-coder-next")
        object.__setattr__(svc._settings, "local_orchestration_engine", "vLLM")

        config = svc.get_config()

        lo = config.groups["local_orchestration"]
        assert lo["local_orchestration_base_url"] == "http://localhost:8033/v1"
        assert lo["local_orchestration_model"] == "qwen3-coder-next"
        assert lo["local_orchestration_engine"] == "vLLM"


# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------


class TestRunDoctor:
    async def test_returns_all_checks(self) -> None:
        svc = _build_service()
        result = await svc.run_doctor()
        assert len(result.checks) == 16

    async def test_overall_matches_worst(self) -> None:
        svc = _build_service()
        result = await svc.run_doctor()
        statuses = {c.status for c in result.checks}
        if CheckStatus.ERROR in statuses:
            assert result.overall == CheckStatus.ERROR
        elif CheckStatus.WARNING in statuses:
            assert result.overall == CheckStatus.WARNING
        else:
            assert result.overall == CheckStatus.OK

    async def test_timestamp_is_set(self) -> None:
        svc = _build_service()
        result = await svc.run_doctor()
        assert result.timestamp is not None
        assert result.timestamp.tzinfo is not None


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    async def test_all_resets_both_caches_and_registries(self) -> None:
        svc = _build_service()
        result = await svc.reset([ResetTarget.ALL])
        targets = {a.target for a in result.actions}
        # Should include cache targets AND registry targets
        assert "embedding_cache" in targets
        assert "agent_registry" in targets

    async def test_caches_only_skips_registries(self) -> None:
        svc = _build_service()
        result = await svc.reset([ResetTarget.CACHES])
        targets = {a.target for a in result.actions}
        assert "embedding_cache" in targets
        assert "agent_registry" not in targets

    async def test_registries_only_skips_caches(self) -> None:
        svc = _build_service()
        result = await svc.reset([ResetTarget.REGISTRIES])
        targets = {a.target for a in result.actions}
        assert "agent_registry" in targets
        assert "embedding_cache" not in targets

    async def test_skills_missing_dir_reports_failure(self, tmp_path) -> None:
        svc = _build_service()
        svc._settings.skill_definitions_dir = str(tmp_path / "missing-skills")
        result = await svc.reset([ResetTarget.REGISTRIES])
        skill_actions = [a for a in result.actions if a.target == "skill_registry"]
        assert len(skill_actions) == 1
        assert skill_actions[0].success is False


# ---------------------------------------------------------------------------
# Tools summary
# ---------------------------------------------------------------------------


class TestGetToolsSummary:
    def test_returns_correct_count(self) -> None:
        svc = _build_service(tool_count=5)
        summary = svc.get_tools_summary()
        assert summary.count == 5
        assert len(summary.tools) == 5

    def test_tool_items_have_names(self) -> None:
        svc = _build_service(tool_count=2)
        summary = svc.get_tools_summary()
        for item in summary.tools:
            assert item.name != ""

    def test_empty_when_no_registry(self) -> None:
        svc = _build_service(tool_count=0)
        # Remove tool_registry entirely
        svc._app_state.tool_registry = None
        summary = svc.get_tools_summary()
        assert summary.count == 0
        assert summary.tools == []


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


class TestGetSessions:
    async def test_degraded_when_no_redis(self) -> None:
        svc = _build_service(redis=None)
        result = await svc.get_sessions()
        assert result.degraded is True

    async def test_empty_list_with_redis(self) -> None:
        svc = _build_service(redis="present")
        result = await svc.get_sessions()
        assert result.degraded is False
        assert result.sessions == []


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------


class TestGetBackups:
    def test_skeleton_response(self) -> None:
        svc = _build_service()
        result = svc.get_backups()
        assert result.backups == []
        assert result.count == 0
        assert result.note == "Platform backup inventory is available under /v1/backups"

    def test_delegates_to_backup_service_when_available(self) -> None:
        svc = _build_service()
        svc._app_state.backup_service = SimpleNamespace(
            list_backups=lambda: SimpleNamespace(
                backups=[BackupSummary(backup_id="b1")],
                count=1,
            )
        )
        result = svc.get_backups()
        assert result.count == 1
        assert result.note == "Platform backup inventory is available under /v1/backups"


# ---------------------------------------------------------------------------
# Helper: _mask_db_url
# ---------------------------------------------------------------------------


class TestMaskDbUrl:
    def test_masks_credentials(self) -> None:
        url = "postgresql+asyncpg://user:pass@host:5432/db"
        masked = _mask_db_url(url)
        assert "user:pass" not in masked
        assert "***:***@host:5432/db" in masked

    def test_no_at_sign_returns_as_is(self) -> None:
        url = "sqlite:///path/to/db.sqlite"
        assert _mask_db_url(url) == url
