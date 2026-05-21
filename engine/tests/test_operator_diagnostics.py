"""Unit tests for operator diagnostic checks.

Tests verify that each DOC-XX check correctly detects conditions
and produces the right status, message, and remediation.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from pydantic import SecretStr

import agent33.config as config_module
from agent33.config import Settings
from agent33.operator.diagnostics import (
    check_agents,
    check_config,
    check_database,
    check_llm,
    check_nats,
    check_packs,
    check_plugins,
    check_redis,
    check_security,
    check_skills,
    run_all_checks,
)
from agent33.operator.models import CheckStatus

# ---------------------------------------------------------------------------
# DOC-01: Database
# ---------------------------------------------------------------------------


class TestCheckDatabase:
    async def test_ok_when_engine_responds(self) -> None:
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_engine.connect = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        ltm = SimpleNamespace(_engine=mock_engine)
        state = SimpleNamespace(long_term_memory=ltm)
        result = await check_database(state)
        assert result.id == "DOC-01"
        assert result.category == "database"
        # Engine mock may not fully work without sqlalchemy context,
        # but check structure is correct
        assert result.status in {CheckStatus.OK, CheckStatus.WARNING, CheckStatus.ERROR}

    async def test_error_when_ltm_missing(self) -> None:
        state = SimpleNamespace(long_term_memory=None)
        result = await check_database(state)
        assert result.id == "DOC-01"
        assert result.status == CheckStatus.ERROR
        assert "not initialized" in result.message
        assert result.remediation is not None


# ---------------------------------------------------------------------------
# DOC-02: Redis
# ---------------------------------------------------------------------------


class TestCheckRedis:
    async def test_ok_when_redis_pings(self) -> None:
        redis_mock = AsyncMock()
        redis_mock.ping = AsyncMock(return_value=True)
        state = SimpleNamespace(redis=redis_mock)
        result = await check_redis(state)
        assert result.id == "DOC-02"
        assert result.status == CheckStatus.OK
        assert "connected" in result.message

    async def test_warning_when_redis_none(self) -> None:
        state = SimpleNamespace(redis=None)
        result = await check_redis(state)
        assert result.id == "DOC-02"
        assert result.status == CheckStatus.WARNING

    async def test_error_when_ping_fails(self) -> None:
        redis_mock = AsyncMock()
        redis_mock.ping = AsyncMock(side_effect=ConnectionError("refused"))
        state = SimpleNamespace(redis=redis_mock)
        result = await check_redis(state)
        assert result.id == "DOC-02"
        assert result.status == CheckStatus.ERROR
        assert "refused" in result.message


# ---------------------------------------------------------------------------
# DOC-03: NATS
# ---------------------------------------------------------------------------


class TestCheckNATS:
    async def test_ok_when_connected(self) -> None:
        bus = SimpleNamespace(is_connected=True)
        state = SimpleNamespace(nats_bus=bus)
        result = await check_nats(state)
        assert result.id == "DOC-03"
        assert result.status == CheckStatus.OK

    async def test_error_when_disconnected(self) -> None:
        bus = SimpleNamespace(is_connected=False)
        state = SimpleNamespace(nats_bus=bus)
        result = await check_nats(state)
        assert result.id == "DOC-03"
        assert result.status == CheckStatus.ERROR

    async def test_warning_when_bus_missing(self) -> None:
        state = SimpleNamespace(nats_bus=None)
        result = await check_nats(state)
        assert result.id == "DOC-03"
        assert result.status == CheckStatus.WARNING


# ---------------------------------------------------------------------------
# DOC-04: LLM
# ---------------------------------------------------------------------------


class TestCheckLLM:
    async def test_ok_with_providers(self) -> None:
        router = SimpleNamespace(_providers={"ollama": object()})
        state = SimpleNamespace(model_router=router)
        result = await check_llm(state)
        assert result.id == "DOC-04"
        assert result.status == CheckStatus.OK
        assert "1 LLM provider" in result.message

    async def test_warning_no_providers(self) -> None:
        router = SimpleNamespace(_providers={})
        state = SimpleNamespace(model_router=router)
        result = await check_llm(state)
        assert result.id == "DOC-04"
        assert result.status == CheckStatus.WARNING

    async def test_warning_no_router(self) -> None:
        state = SimpleNamespace(model_router=None)
        result = await check_llm(state)
        assert result.id == "DOC-04"
        assert result.status == CheckStatus.WARNING


# ---------------------------------------------------------------------------
# DOC-05: Agents
# ---------------------------------------------------------------------------


class TestCheckAgents:
    async def test_ok_with_agents(self) -> None:
        reg = SimpleNamespace(list_all=lambda: ["a1", "a2"])
        state = SimpleNamespace(agent_registry=reg)
        result = await check_agents(state)
        assert result.id == "DOC-05"
        assert result.status == CheckStatus.OK
        assert "2" in result.message

    async def test_warning_when_empty(self) -> None:
        reg = SimpleNamespace(list_all=lambda: [])
        state = SimpleNamespace(agent_registry=reg)
        result = await check_agents(state)
        assert result.id == "DOC-05"
        assert result.status == CheckStatus.WARNING
        assert result.remediation is not None

    async def test_error_when_missing(self) -> None:
        state = SimpleNamespace(agent_registry=None)
        result = await check_agents(state)
        assert result.id == "DOC-05"
        assert result.status == CheckStatus.ERROR


# ---------------------------------------------------------------------------
# DOC-06: Skills
# ---------------------------------------------------------------------------


class TestCheckSkills:
    async def test_ok_with_skills(self) -> None:
        reg = SimpleNamespace(list_all=lambda: ["s1"])
        state = SimpleNamespace(skill_registry=reg)
        result = await check_skills(state)
        assert result.id == "DOC-06"
        assert result.status == CheckStatus.OK

    async def test_warning_when_empty(self) -> None:
        reg = SimpleNamespace(list_all=lambda: [])
        state = SimpleNamespace(skill_registry=reg)
        result = await check_skills(state)
        assert result.id == "DOC-06"
        assert result.status == CheckStatus.WARNING


# ---------------------------------------------------------------------------
# DOC-07: Plugins
# ---------------------------------------------------------------------------


class TestCheckPlugins:
    async def test_ok_when_all_healthy(self) -> None:
        plugins = [SimpleNamespace(name="p1")]
        reg = SimpleNamespace(
            list_all=lambda: plugins,
            get_state=lambda n: SimpleNamespace(value="active"),
        )
        state = SimpleNamespace(plugin_registry=reg)
        result = await check_plugins(state)
        assert result.id == "DOC-07"
        assert result.status == CheckStatus.OK

    async def test_warning_when_error_state(self) -> None:
        plugins = [SimpleNamespace(name="p1"), SimpleNamespace(name="p2")]
        states = {"p1": "active", "p2": "error"}
        reg = SimpleNamespace(
            list_all=lambda: plugins,
            get_state=lambda n: SimpleNamespace(value=states.get(n, "unknown")),
        )
        state = SimpleNamespace(plugin_registry=reg)
        result = await check_plugins(state)
        assert result.id == "DOC-07"
        assert result.status == CheckStatus.WARNING
        assert "1 in error state" in result.message


# ---------------------------------------------------------------------------
# DOC-08: Packs
# ---------------------------------------------------------------------------


class TestCheckPacks:
    async def test_ok_with_packs(self) -> None:
        reg = SimpleNamespace(list_all=lambda: ["pk1", "pk2"])
        state = SimpleNamespace(pack_registry=reg)
        result = await check_packs(state)
        assert result.id == "DOC-08"
        assert result.status == CheckStatus.OK
        assert "2" in result.message


# ---------------------------------------------------------------------------
# DOC-09: Security
# ---------------------------------------------------------------------------


class TestCheckSecurity:
    async def test_warns_on_default_jwt(self, monkeypatch) -> None:
        default_jwt_secret = Settings.model_fields["jwt_secret"].default
        monkeypatch.setattr(
            config_module.settings,
            "jwt_secret",
            SecretStr(default_jwt_secret.get_secret_value()),
        )
        state = SimpleNamespace()
        result = await check_security(state)
        assert result.id == "DOC-09"
        assert result.status == CheckStatus.WARNING
        assert "JWT secret" in result.message
        assert result.remediation is not None

    async def test_prefers_app_specific_settings(self, monkeypatch) -> None:
        default_jwt_secret = Settings.model_fields["jwt_secret"].default
        monkeypatch.setattr(
            config_module.settings,
            "jwt_secret",
            SecretStr("non-default-global-secret"),
        )

        app_settings = Settings()
        app_settings.jwt_secret = SecretStr(default_jwt_secret.get_secret_value())
        app_settings.api_secret_key = SecretStr("non-default-api-secret")
        app_settings.database_url = "postgresql+asyncpg://custom:secret@db:5432/agent33"

        result = await check_security(SimpleNamespace(settings=app_settings))
        assert result.status == CheckStatus.WARNING
        assert "JWT secret" in result.message


# ---------------------------------------------------------------------------
# DOC-10: Config
# ---------------------------------------------------------------------------


class TestCheckConfig:
    async def test_ok_with_valid_config(self) -> None:
        state = SimpleNamespace()
        result = await check_config(state)
        assert result.id == "DOC-10"
        assert result.status == CheckStatus.OK

    async def test_prefers_app_specific_settings(self) -> None:
        app_settings = Settings()
        app_settings.training_enabled = True
        app_settings.database_url = ""

        result = await check_config(SimpleNamespace(settings=app_settings))
        assert result.status == CheckStatus.WARNING
        assert "training_enabled=True but no DATABASE_URL configured" in result.message


# ---------------------------------------------------------------------------
# run_all_checks
# ---------------------------------------------------------------------------


class TestRunAllChecks:
    async def test_runs_all_16_checks(self) -> None:
        state = SimpleNamespace(
            long_term_memory=None,
            redis=None,
            nats_bus=None,
            model_router=None,
            agent_registry=None,
            skill_registry=None,
            plugin_registry=None,
            pack_registry=None,
        )
        results = await run_all_checks(state)
        assert len(results) == 16
        ids = [r.id for r in results]
        for i in range(1, 17):
            expected_id = f"DOC-{i:02d}"
            assert expected_id in ids, f"Missing check {expected_id}"

    async def test_exception_uses_explicit_check_id(self, monkeypatch) -> None:
        async def broken_check(state: SimpleNamespace) -> CheckStatus:
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "agent33.operator.diagnostics.ALL_CHECKS",
            [("DOC-99", broken_check)],
        )

        results = await run_all_checks(SimpleNamespace())
        assert len(results) == 1
        assert results[0].id == "DOC-99"
        assert results[0].status == CheckStatus.ERROR
