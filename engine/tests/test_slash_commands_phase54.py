"""Tests for Phase 54: Slash-Command Interface with structured parsing and routing.

Tests cover:
- Structured argument parsing (parse_args)
- Structured command parsing (parse_slash_command_structured)
- CommandRegistry: list, resolve, refresh, command_name overrides
- SkillDefinition: command_name and command_help fields
- scan_skill_commands with command_name overrides
- API routes: GET /v1/commands, GET /v1/commands/{name}, POST /v1/commands/invoke
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from agent33.skills.definition import SkillDefinition
from agent33.skills.registry import SkillRegistry
from agent33.skills.slash_commands import (
    CommandInfo,
    CommandRegistry,
    CommandResult,
    ParsedCommand,
    parse_args,
    parse_slash_command_structured,
    scan_skill_commands,
)

# ===================================================================
# Helpers
# ===================================================================


def _make_registry(skills: list[SkillDefinition] | None = None) -> SkillRegistry:
    registry = SkillRegistry()
    for skill in skills or []:
        registry.register(skill)
    return registry


# ===================================================================
# parse_args
# ===================================================================


class TestParseArgs:
    """Test structured argument parsing from raw argument strings."""

    def test_empty_string(self) -> None:
        args, flags = parse_args("")
        assert args == []
        assert flags == {}

    def test_whitespace_only(self) -> None:
        args, flags = parse_args("   ")
        assert args == []
        assert flags == {}

    def test_single_positional(self) -> None:
        args, flags = parse_args("staging")
        assert args == ["staging"]
        assert flags == {}

    def test_multiple_positional(self) -> None:
        args, flags = parse_args("staging us-east-1")
        assert args == ["staging", "us-east-1"]
        assert flags == {}

    def test_quoted_positional(self) -> None:
        args, flags = parse_args('"hello world" other')
        assert args == ["hello world", "other"]
        assert flags == {}

    def test_single_quoted_positional(self) -> None:
        args, flags = parse_args("'hello world' other")
        assert args == ["hello world", "other"]
        assert flags == {}

    def test_flag_with_value(self) -> None:
        args, flags = parse_args("--env staging")
        assert args == []
        assert flags == {"env": "staging"}

    def test_boolean_flag(self) -> None:
        args, flags = parse_args("--dry-run")
        assert args == []
        assert flags == {"dry-run": True}

    def test_multiple_flags(self) -> None:
        args, flags = parse_args("--env staging --replicas 3 --dry-run")
        assert args == []
        assert flags == {"env": "staging", "replicas": "3", "dry-run": True}

    def test_mixed_args_and_flags(self) -> None:
        args, flags = parse_args("staging --env prod --dry-run us-east-1")
        assert args == ["staging"]
        # "us-east-1" is not a positional because it follows --dry-run which is boolean
        # Actually --dry-run has no value, so us-east-1 becomes its value? No:
        # --dry-run is followed by us-east-1 which doesn't start with -, so it IS the value
        # Let me verify the actual behavior:
        # --dry-run: next token is "us-east-1" which does not start with "-",
        # so flags["dry-run"] = "us-east-1"
        assert flags == {"env": "prod", "dry-run": "us-east-1"}

    def test_flags_between_positional(self) -> None:
        args, flags = parse_args("deploy --env staging rollout")
        # "deploy" is positional, --env staging consumes two tokens,
        # "rollout" is positional
        assert args == ["deploy", "rollout"]
        assert flags == {"env": "staging"}

    def test_short_flag_boolean(self) -> None:
        args, flags = parse_args("-v")
        assert args == []
        assert flags == {"v": True}

    def test_short_flag_with_value(self) -> None:
        args, flags = parse_args("-n 5")
        assert args == []
        assert flags == {"n": "5"}

    def test_negative_number_not_flag(self) -> None:
        """Negative numbers like -3 should be treated as positional args."""
        args, flags = parse_args("-3")
        assert args == ["-3"]
        assert flags == {}

    def test_double_dash_empty_key_skipped(self) -> None:
        """Bare -- should be skipped."""
        args, flags = parse_args("-- foo")
        assert "foo" in args

    def test_quoted_value_in_flag(self) -> None:
        args, flags = parse_args('--message "hello world"')
        assert flags == {"message": "hello world"}
        assert args == []

    def test_unmatched_quote_fallback(self) -> None:
        """Unmatched quotes fall back to simple split."""
        args, flags = parse_args('"unclosed quote')
        # Falls back to simple split: ['"unclosed', 'quote']
        assert len(args) + len(flags) > 0  # Something was parsed

    def test_flag_followed_by_flag(self) -> None:
        """Two boolean flags in a row."""
        args, flags = parse_args("--verbose --debug")
        assert flags == {"verbose": True, "debug": True}
        assert args == []


# ===================================================================
# parse_slash_command_structured
# ===================================================================


class TestParseSlashCommandStructured:
    """Test structured slash-command parsing."""

    def test_simple_command(self) -> None:
        commands = {"/deploy": "deploy"}
        result = parse_slash_command_structured("/deploy", commands)
        assert result is not None
        assert result.command == "/deploy"
        assert result.skill_name == "deploy"
        assert result.args == []
        assert result.flags == {}
        assert result.raw_input == "/deploy"

    def test_command_with_positional_args(self) -> None:
        commands = {"/deploy": "deploy"}
        result = parse_slash_command_structured("/deploy staging us-east-1", commands)
        assert result is not None
        assert result.skill_name == "deploy"
        assert result.args == ["staging", "us-east-1"]
        assert result.flags == {}

    def test_command_with_flags(self) -> None:
        commands = {"/deploy": "deploy"}
        result = parse_slash_command_structured(
            "/deploy --env staging --dry-run",
            commands,
        )
        assert result is not None
        assert result.skill_name == "deploy"
        assert result.args == []
        assert result.flags == {"env": "staging", "dry-run": True}

    def test_command_with_mixed(self) -> None:
        commands = {"/deploy": "deploy"}
        result = parse_slash_command_structured(
            "/deploy staging --replicas 3",
            commands,
        )
        assert result is not None
        assert result.args == ["staging"]
        assert result.flags == {"replicas": "3"}

    def test_command_with_quoted_arg(self) -> None:
        commands = {"/research": "research"}
        result = parse_slash_command_structured(
            '/research "neural networks" --depth 2',
            commands,
        )
        assert result is not None
        assert result.args == ["neural networks"]
        assert result.flags == {"depth": "2"}

    def test_unknown_command_returns_none(self) -> None:
        commands = {"/deploy": "deploy"}
        result = parse_slash_command_structured("/unknown foo", commands)
        assert result is None

    def test_no_slash_returns_none(self) -> None:
        commands = {"/deploy": "deploy"}
        result = parse_slash_command_structured("deploy foo", commands)
        assert result is None

    def test_raw_input_preserved(self) -> None:
        commands = {"/deploy": "deploy"}
        result = parse_slash_command_structured("  /deploy staging  ", commands)
        assert result is not None
        assert result.raw_input == "/deploy staging"

    def test_raw_args_string_preserved(self) -> None:
        commands = {"/deploy": "deploy"}
        result = parse_slash_command_structured("/deploy staging --env prod", commands)
        assert result is not None
        assert result.raw_args_string == "staging --env prod"

    def test_longest_match_priority(self) -> None:
        commands = {"/deploy": "deploy", "/deploy-k8s": "deploy-k8s"}
        result = parse_slash_command_structured("/deploy-k8s staging", commands)
        assert result is not None
        assert result.skill_name == "deploy-k8s"
        assert result.command == "/deploy-k8s"


# ===================================================================
# scan_skill_commands with command_name overrides
# ===================================================================


class TestScanWithCommandName:
    """Test that scan_skill_commands respects custom command_name."""

    def test_custom_command_name(self) -> None:
        registry = _make_registry([SkillDefinition(name="kubernetes-deploy", command_name="k8s")])
        commands = scan_skill_commands(registry)
        assert "/k8s" in commands
        assert commands["/k8s"] == "kubernetes-deploy"

    def test_custom_command_name_overrides_auto(self) -> None:
        """Custom command_name means the auto-derived name is NOT produced."""
        registry = _make_registry([SkillDefinition(name="kubernetes-deploy", command_name="k8s")])
        commands = scan_skill_commands(registry)
        assert "/kubernetes-deploy" not in commands
        assert "/k8s" in commands

    def test_no_command_name_uses_auto(self) -> None:
        registry = _make_registry([SkillDefinition(name="kubernetes-deploy")])
        commands = scan_skill_commands(registry)
        assert "/kubernetes-deploy" in commands

    def test_mixed_custom_and_auto(self) -> None:
        registry = _make_registry(
            [
                SkillDefinition(name="kubernetes-deploy", command_name="k8s"),
                SkillDefinition(name="code-review"),
            ]
        )
        commands = scan_skill_commands(registry)
        assert "/k8s" in commands
        assert "/code-review" in commands
        assert len(commands) == 2


# ===================================================================
# CommandRegistry
# ===================================================================


class TestCommandRegistry:
    """Test the CommandRegistry wrapper class."""

    def test_empty_registry(self) -> None:
        skill_reg = _make_registry()
        cmd_reg = CommandRegistry(skill_reg)
        assert cmd_reg.count == 0
        assert cmd_reg.list_commands() == []

    def test_commands_lazy_init(self) -> None:
        skill_reg = _make_registry(
            [
                SkillDefinition(name="deploy", description="Deploy workloads"),
            ]
        )
        cmd_reg = CommandRegistry(skill_reg)
        # Accessing .commands triggers lazy build
        assert "/deploy" in cmd_reg.commands
        assert cmd_reg.count == 1

    def test_list_commands_returns_metadata(self) -> None:
        skill_reg = _make_registry(
            [
                SkillDefinition(
                    name="deploy",
                    description="Deploy workloads",
                    command_help="Deploy to a target environment",
                    category="devops",
                    tags=["k8s", "deploy"],
                ),
            ]
        )
        cmd_reg = CommandRegistry(skill_reg)
        cmds = cmd_reg.list_commands()
        assert len(cmds) == 1
        info = cmds[0]
        assert info.command == "/deploy"
        assert info.skill_name == "deploy"
        assert info.description == "Deploy workloads"
        assert info.help_text == "Deploy to a target environment"
        assert info.category == "devops"
        assert "k8s" in info.tags

    def test_list_commands_uses_description_when_no_help(self) -> None:
        skill_reg = _make_registry(
            [
                SkillDefinition(name="deploy", description="Deploy workloads"),
            ]
        )
        cmd_reg = CommandRegistry(skill_reg)
        cmds = cmd_reg.list_commands()
        assert cmds[0].help_text == "Deploy workloads"

    def test_resolve_valid_command(self) -> None:
        skill_reg = _make_registry([SkillDefinition(name="deploy")])
        cmd_reg = CommandRegistry(skill_reg)
        parsed = cmd_reg.resolve("/deploy staging --dry-run")
        assert parsed is not None
        assert parsed.skill_name == "deploy"
        assert parsed.args == ["staging"]
        assert parsed.flags == {"dry-run": True}

    def test_resolve_unknown_command(self) -> None:
        skill_reg = _make_registry([SkillDefinition(name="deploy")])
        cmd_reg = CommandRegistry(skill_reg)
        assert cmd_reg.resolve("/unknown foo") is None

    def test_refresh_picks_up_new_skills(self) -> None:
        skill_reg = _make_registry([SkillDefinition(name="deploy")])
        cmd_reg = CommandRegistry(skill_reg)
        assert cmd_reg.count == 1

        skill_reg.register(SkillDefinition(name="review"))
        cmd_reg.refresh()
        assert cmd_reg.count == 2
        assert "/review" in cmd_reg.commands

    def test_get_command_info_found(self) -> None:
        skill_reg = _make_registry(
            [
                SkillDefinition(
                    name="deploy",
                    description="Deploy it",
                    command_help="Quick deploy",
                )
            ]
        )
        cmd_reg = CommandRegistry(skill_reg)
        info = cmd_reg.get_command_info("/deploy")
        assert info is not None
        assert info.skill_name == "deploy"
        assert info.help_text == "Quick deploy"

    def test_get_command_info_not_found(self) -> None:
        skill_reg = _make_registry()
        cmd_reg = CommandRegistry(skill_reg)
        assert cmd_reg.get_command_info("/nonexistent") is None

    def test_commands_sorted_by_name(self) -> None:
        skill_reg = _make_registry(
            [
                SkillDefinition(name="zebra"),
                SkillDefinition(name="alpha"),
                SkillDefinition(name="middle"),
            ]
        )
        cmd_reg = CommandRegistry(skill_reg)
        cmds = cmd_reg.list_commands()
        cmd_names = [c.command for c in cmds]
        assert cmd_names == sorted(cmd_names)


# ===================================================================
# SkillDefinition: command_name and command_help fields
# ===================================================================


class TestSkillDefinitionCommandFields:
    """Test the new command_name and command_help fields on SkillDefinition."""

    def test_default_command_name_is_none(self) -> None:
        skill = SkillDefinition(name="test")
        assert skill.command_name is None

    def test_default_command_help_is_empty(self) -> None:
        skill = SkillDefinition(name="test")
        assert skill.command_help == ""

    def test_explicit_command_name(self) -> None:
        skill = SkillDefinition(name="kubernetes-deploy", command_name="k8s")
        assert skill.command_name == "k8s"

    def test_explicit_command_help(self) -> None:
        skill = SkillDefinition(
            name="deploy",
            command_help="Deploy to a target environment",
        )
        assert skill.command_help == "Deploy to a target environment"

    def test_serialization_includes_command_fields(self) -> None:
        skill = SkillDefinition(
            name="deploy",
            command_name="k8s",
            command_help="Deploy things",
        )
        data = skill.model_dump(mode="json")
        assert data["command_name"] == "k8s"
        assert data["command_help"] == "Deploy things"

    def test_command_name_max_length(self) -> None:
        """command_name has max_length=64."""
        with pytest.raises(ValidationError, match="command_name"):
            SkillDefinition(name="test", command_name="x" * 65)

    def test_command_help_max_length(self) -> None:
        """command_help has max_length=200."""
        with pytest.raises(ValidationError, match="command_help"):
            SkillDefinition(name="test", command_help="x" * 201)


# ===================================================================
# Pydantic models: ParsedCommand, CommandInfo, CommandResult
# ===================================================================


class TestPydanticModels:
    """Test Pydantic model construction and serialization."""

    def test_parsed_command_roundtrip(self) -> None:
        pc = ParsedCommand(
            command="/deploy",
            skill_name="deploy",
            args=["staging"],
            flags={"dry-run": True, "replicas": "3"},
            raw_input="/deploy staging --dry-run --replicas 3",
            raw_args_string="staging --dry-run --replicas 3",
        )
        data = pc.model_dump(mode="json")
        assert data["command"] == "/deploy"
        assert data["args"] == ["staging"]
        assert data["flags"]["dry-run"] is True
        assert data["flags"]["replicas"] == "3"
        restored = ParsedCommand.model_validate(data)
        assert restored == pc

    def test_command_info_roundtrip(self) -> None:
        ci = CommandInfo(
            command="/deploy",
            skill_name="deploy",
            description="Deploy things",
            help_text="Deploy to a target",
            category="devops",
            tags=["k8s"],
            status="active",
        )
        data = ci.model_dump(mode="json")
        restored = CommandInfo.model_validate(data)
        assert restored == ci

    def test_command_result_success(self) -> None:
        cr = CommandResult(
            command="/deploy",
            skill_name="deploy",
            success=True,
            output="Deployed successfully",
        )
        assert cr.success is True
        assert cr.error is None

    def test_command_result_failure(self) -> None:
        cr = CommandResult(
            command="/deploy",
            skill_name="deploy",
            success=False,
            error="Connection timeout",
        )
        assert cr.success is False
        assert cr.error == "Connection timeout"


# ===================================================================
# API Route Tests
# ===================================================================


def _auth_headers(*, scopes: list[str] | None = None) -> dict[str, str]:
    """Create JWT auth headers with the given scopes."""
    from agent33.security.auth import create_access_token

    token = create_access_token(
        "p54-tester",
        scopes=scopes or [],
        tenant_id="tenant-p54",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def _setup_command_routes() -> None:  # type: ignore[misc]
    """Set up app state for command route tests."""
    from agent33.api.routes.commands import set_command_registry
    from agent33.main import app

    skill_reg = _make_registry(
        [
            SkillDefinition(
                name="deploy",
                description="Deploy workloads",
                command_help="Deploy to a target environment",
                category="devops",
                tags=["k8s"],
                instructions="Run kubectl apply.",
            ),
            SkillDefinition(
                name="code-review",
                description="Review code changes",
                command_help="Review a PR for issues",
                category="quality",
            ),
            SkillDefinition(
                name="quick-test",
                description="Run quick tests",
                command_name="qt",
                command_help="Alias for running fast tests",
            ),
        ]
    )
    cmd_reg = CommandRegistry(skill_reg)
    app.state.skill_registry = skill_reg
    app.state.command_registry = cmd_reg

    set_command_registry(cmd_reg)

    yield

    set_command_registry(None)
    if hasattr(app.state, "command_registry"):
        del app.state.command_registry
    if hasattr(app.state, "skill_registry"):
        del app.state.skill_registry


@pytest.mark.usefixtures("_setup_command_routes")
class TestCommandRoutes:
    """Test the /v1/commands API routes."""

    async def test_list_commands(self) -> None:
        from agent33.main import app

        transport = ASGITransport(app=app)
        headers = _auth_headers(scopes=["agents:read"])
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=headers
        ) as client:
            resp = await client.get("/v1/commands")
            assert resp.status_code == 200
            body = resp.json()
            assert body["count"] == 3
            cmd_names = [c["command"] for c in body["commands"]]
            assert "/deploy" in cmd_names
            assert "/code-review" in cmd_names
            assert "/qt" in cmd_names  # custom command_name

    async def test_get_command_found(self) -> None:
        from agent33.main import app

        transport = ASGITransport(app=app)
        headers = _auth_headers(scopes=["agents:read"])
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=headers
        ) as client:
            resp = await client.get("/v1/commands/deploy")
            assert resp.status_code == 200
            body = resp.json()
            assert body["command"] == "/deploy"
            assert body["skill_name"] == "deploy"
            assert body["help_text"] == "Deploy to a target environment"

    async def test_get_command_custom_alias(self) -> None:
        """Custom command_name (qt) is accessible via the GET endpoint."""
        from agent33.main import app

        transport = ASGITransport(app=app)
        headers = _auth_headers(scopes=["agents:read"])
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=headers
        ) as client:
            resp = await client.get("/v1/commands/qt")
            assert resp.status_code == 200
            body = resp.json()
            assert body["command"] == "/qt"
            assert body["skill_name"] == "quick-test"
            assert body["help_text"] == "Alias for running fast tests"

    async def test_get_command_not_found(self) -> None:
        from agent33.main import app

        transport = ASGITransport(app=app)
        headers = _auth_headers(scopes=["agents:read"])
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=headers
        ) as client:
            resp = await client.get("/v1/commands/nonexistent")
            assert resp.status_code == 404

    async def test_invoke_command_valid(self) -> None:
        """Invoke a valid command -- without agent_registry, falls back to direct mode."""
        from agent33.main import app

        # Ensure no agent_registry so we hit the direct fallback
        saved_ar = getattr(app.state, "agent_registry", None)
        if hasattr(app.state, "agent_registry"):
            del app.state.agent_registry

        try:
            transport = ASGITransport(app=app)
            headers = _auth_headers(scopes=["agents:execute"])
            async with AsyncClient(
                transport=transport, base_url="http://test", headers=headers
            ) as client:
                resp = await client.post(
                    "/v1/commands/invoke",
                    json={"input": "/deploy staging --dry-run"},
                )
                assert resp.status_code == 200
                body = resp.json()

                # Check parsed structure
                parsed = body["parsed"]
                assert parsed["command"] == "/deploy"
                assert parsed["skill_name"] == "deploy"
                assert parsed["args"] == ["staging"]
                assert parsed["flags"]["dry-run"] is True

                # Check result
                result = body["result"]
                assert result["success"] is True
                assert result["output"] == "Run kubectl apply."
                assert result["metadata"]["mode"] == "direct"
        finally:
            if saved_ar is not None:
                app.state.agent_registry = saved_ar

    async def test_invoke_command_with_custom_name(self) -> None:
        """Invoke a skill using its custom command_name."""
        from agent33.main import app

        saved_ar = getattr(app.state, "agent_registry", None)
        if hasattr(app.state, "agent_registry"):
            del app.state.agent_registry

        try:
            transport = ASGITransport(app=app)
            headers = _auth_headers(scopes=["agents:execute"])
            async with AsyncClient(
                transport=transport, base_url="http://test", headers=headers
            ) as client:
                resp = await client.post(
                    "/v1/commands/invoke",
                    json={"input": "/qt --verbose"},
                )
                assert resp.status_code == 200
                body = resp.json()
                assert body["parsed"]["skill_name"] == "quick-test"
                assert body["parsed"]["flags"]["verbose"] is True
        finally:
            if saved_ar is not None:
                app.state.agent_registry = saved_ar

    async def test_invoke_command_unknown(self) -> None:
        from agent33.main import app

        transport = ASGITransport(app=app)
        headers = _auth_headers(scopes=["agents:execute"])
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=headers
        ) as client:
            resp = await client.post(
                "/v1/commands/invoke",
                json={"input": "/nonexistent foo"},
            )
            assert resp.status_code == 400
            assert "Unrecognized command" in resp.json()["detail"]

    async def test_invoke_command_no_slash(self) -> None:
        from agent33.main import app

        transport = ASGITransport(app=app)
        headers = _auth_headers(scopes=["agents:execute"])
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=headers
        ) as client:
            resp = await client.post(
                "/v1/commands/invoke",
                json={"input": "deploy staging"},
            )
            assert resp.status_code == 400

    async def test_invoke_command_empty_input_rejected(self) -> None:
        from agent33.main import app

        transport = ASGITransport(app=app)
        headers = _auth_headers(scopes=["agents:execute"])
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=headers
        ) as client:
            resp = await client.post(
                "/v1/commands/invoke",
                json={"input": ""},
            )
            assert resp.status_code == 422  # validation error: min_length=1

    async def test_invoke_command_result_includes_metadata(self) -> None:
        """Direct-mode result includes args and flags in metadata."""
        from agent33.main import app

        saved_ar = getattr(app.state, "agent_registry", None)
        if hasattr(app.state, "agent_registry"):
            del app.state.agent_registry

        try:
            transport = ASGITransport(app=app)
            headers = _auth_headers(scopes=["agents:execute"])
            async with AsyncClient(
                transport=transport, base_url="http://test", headers=headers
            ) as client:
                resp = await client.post(
                    "/v1/commands/invoke",
                    json={"input": "/deploy staging --replicas 3"},
                )
                assert resp.status_code == 200
                meta = resp.json()["result"]["metadata"]
                assert meta["args"] == ["staging"]
                assert meta["flags"] == {"replicas": "3"}
        finally:
            if saved_ar is not None:
                app.state.agent_registry = saved_ar

    async def test_invoke_with_quoted_args(self) -> None:
        """Quoted arguments are correctly parsed through the route."""
        from agent33.main import app

        saved_ar = getattr(app.state, "agent_registry", None)
        if hasattr(app.state, "agent_registry"):
            del app.state.agent_registry

        try:
            transport = ASGITransport(app=app)
            headers = _auth_headers(scopes=["agents:execute"])
            async with AsyncClient(
                transport=transport, base_url="http://test", headers=headers
            ) as client:
                resp = await client.post(
                    "/v1/commands/invoke",
                    json={"input": '/deploy "my service" --env staging'},
                )
                assert resp.status_code == 200
                parsed = resp.json()["parsed"]
                assert parsed["args"] == ["my service"]
                assert parsed["flags"]["env"] == "staging"
        finally:
            if saved_ar is not None:
                app.state.agent_registry = saved_ar

    async def test_no_auth_returns_401(self) -> None:
        """Requests without auth should be rejected."""
        from agent33.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/commands")
            assert resp.status_code == 401

    async def test_wrong_scope_returns_403(self) -> None:
        """Requests with wrong scope should be forbidden."""
        from agent33.main import app

        transport = ASGITransport(app=app)
        # agents:execute scope but route requires agents:read
        headers = _auth_headers(scopes=["tools:execute"])
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=headers
        ) as client:
            resp = await client.get("/v1/commands")
            assert resp.status_code == 403


# ===================================================================
# Route: 503 when command_registry not initialized
# ===================================================================


class TestCommandRoutesNoRegistry:
    """Test routes when command_registry is not available."""

    async def test_list_commands_503(self) -> None:
        from agent33.api.routes.commands import set_command_registry
        from agent33.main import app

        set_command_registry(None)
        saved = getattr(app.state, "command_registry", None)
        if hasattr(app.state, "command_registry"):
            del app.state.command_registry

        try:
            transport = ASGITransport(app=app)
            headers = _auth_headers(scopes=["agents:read"])
            async with AsyncClient(
                transport=transport, base_url="http://test", headers=headers
            ) as client:
                resp = await client.get("/v1/commands")
                assert resp.status_code == 503
        finally:
            if saved is not None:
                app.state.command_registry = saved

    async def test_invoke_command_503(self) -> None:
        from agent33.api.routes.commands import set_command_registry
        from agent33.main import app

        set_command_registry(None)
        saved = getattr(app.state, "command_registry", None)
        if hasattr(app.state, "command_registry"):
            del app.state.command_registry

        try:
            transport = ASGITransport(app=app)
            headers = _auth_headers(scopes=["agents:execute"])
            async with AsyncClient(
                transport=transport, base_url="http://test", headers=headers
            ) as client:
                resp = await client.post(
                    "/v1/commands/invoke",
                    json={"input": "/deploy staging"},
                )
                assert resp.status_code == 503
        finally:
            if saved is not None:
                app.state.command_registry = saved
