"""Tests for Phase 44 hook extensions: new event types, ScriptHook, ScriptHookDiscovery."""

from __future__ import annotations

from pathlib import Path

from agent33.hooks.models import HookContext, HookEventType
from agent33.hooks.protocol import BaseHook
from agent33.hooks.registry import HookRegistry
from agent33.hooks.script_discovery import ScriptHookDiscovery, resolve_project_hooks_dir
from agent33.hooks.script_hook import ScriptHook


class TestNewEventTypes:
    """Tests for the 4 new session lifecycle event types."""

    def test_session_start_event_type_exists(self) -> None:
        assert HookEventType.SESSION_START == "session.start"

    def test_session_end_event_type_exists(self) -> None:
        assert HookEventType.SESSION_END == "session.end"

    def test_session_checkpoint_event_type_exists(self) -> None:
        assert HookEventType.SESSION_CHECKPOINT == "session.checkpoint"

    def test_session_resume_event_type_exists(self) -> None:
        assert HookEventType.SESSION_RESUME == "session.resume"

    def test_new_event_types_coexist_with_existing(self) -> None:
        """All 12 event types should be present."""
        all_types = list(HookEventType)
        assert len(all_types) == 12
        assert HookEventType.AGENT_INVOKE_PRE in all_types
        assert HookEventType.SESSION_START in all_types

    def test_new_event_types_register_in_hook_registry(self) -> None:
        registry = HookRegistry(max_per_event=20)
        hook = BaseHook(
            name="test-session-hook",
            event_type=HookEventType.SESSION_START.value,
            priority=100,
        )
        registry.register(hook)
        hooks = registry.get_hooks(HookEventType.SESSION_START.value)
        assert len(hooks) == 1
        assert hooks[0].name == "test-session-hook"

    def test_registry_tenant_filtering_with_session_events(self) -> None:
        registry = HookRegistry(max_per_event=20)
        hook_system = BaseHook(
            name="system-hook",
            event_type=HookEventType.SESSION_END.value,
            tenant_id="",
        )
        hook_tenant = BaseHook(
            name="tenant-hook",
            event_type=HookEventType.SESSION_END.value,
            tenant_id="t1",
        )
        registry.register(hook_system)
        registry.register(hook_tenant)

        # System hooks visible to all tenants
        hooks_t1 = registry.get_hooks(HookEventType.SESSION_END.value, tenant_id="t1")
        assert len(hooks_t1) == 2

        # Other tenant only sees system hooks
        hooks_t2 = registry.get_hooks(HookEventType.SESSION_END.value, tenant_id="t2")
        assert len(hooks_t2) == 1
        assert hooks_t2[0].name == "system-hook"

    def test_builtin_hooks_include_session_events(self) -> None:
        """Verify builtins register for session event types too."""
        from agent33.hooks.builtins import _PHASE1_EVENT_TYPES

        session_types = {
            HookEventType.SESSION_START,
            HookEventType.SESSION_END,
            HookEventType.SESSION_CHECKPOINT,
            HookEventType.SESSION_RESUME,
        }
        assert session_types.issubset(set(_PHASE1_EVENT_TYPES))


class TestScriptHook:
    """Tests for the ScriptHook adapter."""

    def _make_script(self, tmp_path: Path, name: str, content: str) -> Path:
        """Helper: write a Python script and return its path."""
        script = tmp_path / name
        script.write_text(content, encoding="utf-8")
        return script

    async def test_script_hook_success(self, tmp_path: Path) -> None:
        """Script returns JSON on stdout, modifying context metadata."""
        script = self._make_script(
            tmp_path,
            "ok_hook.py",
            "import json, sys\n"
            "ctx = json.load(sys.stdin)\n"
            'print(json.dumps({"metadata": {"processed": True}}))\n',
        )
        hook = ScriptHook(
            name="ok",
            event_type="session.start",
            script_path=script,
            timeout_ms=5000,
        )
        ctx = HookContext(event_type="session.start", tenant_id="t1")

        next_called = False

        async def call_next(c: HookContext) -> HookContext:
            nonlocal next_called
            next_called = True
            return c

        result = await hook.execute(ctx, call_next)
        assert next_called
        assert result.metadata.get("processed") is True

    async def test_script_hook_exit_nonzero_fail_open(self, tmp_path: Path) -> None:
        """Script exits with code 1, fail-open continues chain."""
        script = self._make_script(
            tmp_path,
            "fail_hook.py",
            "import sys\nsys.exit(1)\n",
        )
        hook = ScriptHook(
            name="fail-open",
            event_type="session.start",
            script_path=script,
            fail_mode="open",
            timeout_ms=5000,
        )
        ctx = HookContext(event_type="session.start", tenant_id="")

        next_called = False

        async def call_next(c: HookContext) -> HookContext:
            nonlocal next_called
            next_called = True
            return c

        result = await hook.execute(ctx, call_next)
        assert next_called  # chain continues
        assert not result.abort

    async def test_script_hook_exit_nonzero_fail_closed(self, tmp_path: Path) -> None:
        """Script exits with code 1, fail-closed aborts chain."""
        script = self._make_script(
            tmp_path,
            "fail_closed.py",
            "import sys\nsys.exit(1)\n",
        )
        hook = ScriptHook(
            name="fail-closed",
            event_type="session.start",
            script_path=script,
            fail_mode="closed",
            timeout_ms=5000,
        )
        ctx = HookContext(event_type="session.start", tenant_id="")

        async def call_next(c: HookContext) -> HookContext:
            return c

        result = await hook.execute(ctx, call_next)
        assert result.abort
        assert "fail-closed" in result.abort_reason

    async def test_script_hook_abort_via_stdout(self, tmp_path: Path) -> None:
        """Script requests abort via JSON stdout."""
        script = self._make_script(
            tmp_path,
            "abort_hook.py",
            'import json\nprint(json.dumps({"abort": True, "abort_reason": "Blocked"}))\n',
        )
        hook = ScriptHook(
            name="aborter",
            event_type="session.start",
            script_path=script,
            timeout_ms=5000,
        )
        ctx = HookContext(event_type="session.start", tenant_id="")

        async def call_next(c: HookContext) -> HookContext:
            return c

        result = await hook.execute(ctx, call_next)
        assert result.abort
        assert result.abort_reason == "Blocked"

    async def test_script_hook_timeout_fail_open(self, tmp_path: Path) -> None:
        """Script that takes too long is cancelled, chain continues."""
        script = self._make_script(
            tmp_path,
            "slow_hook.py",
            "import time\ntime.sleep(10)\n",
        )
        hook = ScriptHook(
            name="slow",
            event_type="session.start",
            script_path=script,
            timeout_ms=200,  # very short timeout
            fail_mode="open",
        )
        ctx = HookContext(event_type="session.start", tenant_id="")

        next_called = False

        async def call_next(c: HookContext) -> HookContext:
            nonlocal next_called
            next_called = True
            return c

        result = await hook.execute(ctx, call_next)
        assert next_called
        assert not result.abort

    async def test_script_hook_timeout_fail_closed(self, tmp_path: Path) -> None:
        """Script that times out aborts when fail-closed."""
        script = self._make_script(
            tmp_path,
            "slow_closed.py",
            "import time\ntime.sleep(10)\n",
        )
        hook = ScriptHook(
            name="slow-closed",
            event_type="session.start",
            script_path=script,
            timeout_ms=200,
            fail_mode="closed",
        )
        ctx = HookContext(event_type="session.start", tenant_id="")

        async def call_next(c: HookContext) -> HookContext:
            return c

        result = await hook.execute(ctx, call_next)
        assert result.abort
        assert "timed out" in result.abort_reason

    async def test_script_hook_missing_script(self, tmp_path: Path) -> None:
        """Missing script file continues chain (fail-open default)."""
        hook = ScriptHook(
            name="missing",
            event_type="session.start",
            script_path=tmp_path / "nonexistent.py",
            timeout_ms=5000,
        )
        ctx = HookContext(event_type="session.start", tenant_id="")

        next_called = False

        async def call_next(c: HookContext) -> HookContext:
            nonlocal next_called
            next_called = True
            return c

        await hook.execute(ctx, call_next)
        assert next_called

    async def test_script_hook_empty_stdout(self, tmp_path: Path) -> None:
        """Script with no stdout output continues normally."""
        script = self._make_script(tmp_path, "silent.py", "pass\n")
        hook = ScriptHook(
            name="silent",
            event_type="session.start",
            script_path=script,
            timeout_ms=5000,
        )
        ctx = HookContext(event_type="session.start", tenant_id="")

        next_called = False

        async def call_next(c: HookContext) -> HookContext:
            nonlocal next_called
            next_called = True
            return c

        await hook.execute(ctx, call_next)
        assert next_called

    async def test_script_hook_malformed_json_stdout(self, tmp_path: Path) -> None:
        """Script with non-JSON stdout continues (logged but ignored)."""
        script = self._make_script(tmp_path, "bad_json.py", 'print("not json")\n')
        hook = ScriptHook(
            name="bad-json",
            event_type="session.start",
            script_path=script,
            timeout_ms=5000,
        )
        ctx = HookContext(event_type="session.start", tenant_id="")

        async def call_next(c: HookContext) -> HookContext:
            return c

        result = await hook.execute(ctx, call_next)
        assert not result.abort

    async def test_script_hook_receives_env_vars(self, tmp_path: Path) -> None:
        """Script receives AGENT33_* environment variables."""
        script = self._make_script(
            tmp_path,
            "env_hook.py",
            "import os, json\n"
            'print(json.dumps({"metadata": {\n'
            '    "event": os.environ.get("AGENT33_EVENT_TYPE", ""),\n'
            '    "tenant": os.environ.get("AGENT33_TENANT_ID", ""),\n'
            '    "session": os.environ.get("AGENT33_SESSION_ID", ""),\n'
            "}}))\n",
        )
        hook = ScriptHook(
            name="env-check",
            event_type="session.start",
            script_path=script,
            timeout_ms=5000,
        )
        ctx = HookContext(
            event_type="session.start",
            tenant_id="tenant-abc",
            metadata={"session_id": "sess-xyz"},
        )

        async def call_next(c: HookContext) -> HookContext:
            return c

        result = await hook.execute(ctx, call_next)
        assert result.metadata.get("event") == "session.start"
        assert result.metadata.get("tenant") == "tenant-abc"
        assert result.metadata.get("session") == "sess-xyz"

    def test_script_hook_properties(self, tmp_path: Path) -> None:
        hook = ScriptHook(
            name="props",
            event_type="session.end",
            script_path=tmp_path / "hook.py",
            timeout_ms=3000,
            fail_mode="closed",
            priority=150,
            tenant_id="t1",
        )
        assert hook.name == "props"
        assert hook.event_type == "session.end"
        assert hook.script_path == tmp_path / "hook.py"
        assert hook.fail_mode == "closed"
        assert hook.priority == 150
        assert hook.tenant_id == "t1"

    async def test_script_hook_execution_log(self, tmp_path: Path) -> None:
        """Execution log is populated after each run."""
        script = self._make_script(tmp_path, "logged.py", "pass\n")
        hook = ScriptHook(
            name="logged",
            event_type="session.start",
            script_path=script,
            timeout_ms=5000,
        )
        ctx = HookContext(event_type="session.start", tenant_id="")

        async def call_next(c: HookContext) -> HookContext:
            return c

        await hook.execute(ctx, call_next)
        assert len(hook.execution_log) == 1
        assert hook.execution_log[0]["hook_name"] == "logged"
        assert hook.execution_log[0]["success"] is True

    async def test_script_hook_missing_bash_on_windows_fails_open(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        script = self._make_script(tmp_path, "guard.sh", "echo ok\n")
        hook = ScriptHook(
            name="guard",
            event_type="session.start",
            script_path=script,
            timeout_ms=5000,
        )
        ctx = HookContext(event_type="session.start", tenant_id="")

        monkeypatch.setattr("agent33.hooks.script_hook.sys.platform", "win32")
        monkeypatch.setattr("agent33.hooks.script_hook.shutil.which", lambda _cmd: None)

        next_called = False

        async def call_next(c: HookContext) -> HookContext:
            nonlocal next_called
            next_called = True
            return c

        result = await hook.execute(ctx, call_next)
        assert next_called
        assert not result.abort
        assert hook.execution_log[0]["success"] is False
        assert "bash is required" in hook.execution_log[0]["error"]


class TestScriptHookInChain:
    """Tests for ScriptHook integration with HookChainRunner."""

    async def test_script_hook_in_sequential_chain(self, tmp_path: Path) -> None:
        """ScriptHook participates in a chain with Python hooks."""
        from agent33.hooks.chain import HookChainRunner

        script = tmp_path / "chain_hook.py"
        script.write_text(
            "import json, sys\n"
            "ctx = json.load(sys.stdin)\n"
            'print(json.dumps({"metadata": {"script_ran": True}}))\n',
            encoding="utf-8",
        )

        python_hook = BaseHook(
            name="python-first",
            event_type="session.start",
            priority=100,
        )
        script_hook = ScriptHook(
            name="script-second",
            event_type="session.start",
            script_path=script,
            priority=200,
            timeout_ms=5000,
        )

        runner = HookChainRunner(
            hooks=[script_hook, python_hook],
            timeout_ms=10000,
            fail_open=True,
        )
        ctx = HookContext(event_type="session.start", tenant_id="")
        result = await runner.run(ctx)

        assert result.metadata.get("script_ran") is True
        assert len(result.results) == 2  # both hooks ran


class TestScriptHookDiscovery:
    """Tests for ScriptHookDiscovery filesystem scanner."""

    def test_discover_from_project_dir(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project_hooks"
        project_dir.mkdir()
        (project_dir / "session.start--purpose-gate.py").write_text("pass\n")
        (project_dir / "session.end--cleanup.py").write_text("pass\n")

        registry = HookRegistry(max_per_event=20)
        discovery = ScriptHookDiscovery(
            hook_registry=registry,
            project_hooks_dir=project_dir,
        )
        count = discovery.discover()
        assert count == 2
        assert "purpose-gate" in discovery.discovered_hooks
        assert "cleanup" in discovery.discovered_hooks

    def test_discover_from_user_dir(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "user_hooks"
        user_dir.mkdir()
        (user_dir / "tool.execute.pre--safety.py").write_text("pass\n")

        registry = HookRegistry(max_per_event=20)
        discovery = ScriptHookDiscovery(
            hook_registry=registry,
            user_hooks_dir=user_dir,
        )
        count = discovery.discover()
        assert count == 1

    def test_project_overrides_user(self, tmp_path: Path) -> None:
        """When same hook name exists in both, project takes priority."""
        project_dir = tmp_path / "project"
        user_dir = tmp_path / "user"
        project_dir.mkdir()
        user_dir.mkdir()

        (project_dir / "session.start--gate.py").write_text("# project\n")
        (user_dir / "session.start--gate.py").write_text("# user\n")

        registry = HookRegistry(max_per_event=20)
        discovery = ScriptHookDiscovery(
            hook_registry=registry,
            project_hooks_dir=project_dir,
            user_hooks_dir=user_dir,
        )
        count = discovery.discover()
        assert count == 1  # deduplicated

        hook = discovery.discovered_hooks["gate"]
        assert "project" in str(hook.script_path)

    def test_ignore_unsupported_extensions(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "hooks"
        project_dir.mkdir()
        (project_dir / "session.start--good.py").write_text("pass\n")
        (project_dir / "session.start--bad.txt").write_text("bad\n")
        (project_dir / "session.start--also-bad.exe").write_text("bad\n")

        registry = HookRegistry(max_per_event=20)
        discovery = ScriptHookDiscovery(
            hook_registry=registry,
            project_hooks_dir=project_dir,
        )
        count = discovery.discover()
        assert count == 1

    def test_parse_rejects_files_without_extension(self, tmp_path: Path) -> None:
        hook_path = tmp_path / "session.start--no-extension"
        hook_path.write_text("pass\n")

        assert ScriptHookDiscovery._parse_hook_filename(hook_path) is None

    def test_parse_allows_hyphenated_event_type_segments(self, tmp_path: Path) -> None:
        hook_path = tmp_path / "tool-execute.pre-hook--guard.py"
        hook_path.write_text("pass\n")

        parsed = ScriptHookDiscovery._parse_hook_filename(hook_path)
        assert parsed == ("tool-execute.pre-hook", "guard")

    def test_ignore_invalid_filenames(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "hooks"
        project_dir.mkdir()
        (project_dir / "no-separator.py").write_text("pass\n")
        (project_dir / "--no-event.py").write_text("pass\n")
        (project_dir / "session.start--.py").write_text("pass\n")  # empty name

        registry = HookRegistry(max_per_event=20)
        discovery = ScriptHookDiscovery(
            hook_registry=registry,
            project_hooks_dir=project_dir,
        )
        count = discovery.discover()
        assert count == 0

    def test_ignore_directories(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "hooks"
        project_dir.mkdir()
        (project_dir / "session.start--subdir").mkdir()

        registry = HookRegistry(max_per_event=20)
        discovery = ScriptHookDiscovery(
            hook_registry=registry,
            project_hooks_dir=project_dir,
        )
        count = discovery.discover()
        assert count == 0

    def test_discover_nonexistent_dirs(self, tmp_path: Path) -> None:
        registry = HookRegistry(max_per_event=20)
        discovery = ScriptHookDiscovery(
            hook_registry=registry,
            project_hooks_dir=tmp_path / "nope",
            user_hooks_dir=tmp_path / "also_nope",
        )
        count = discovery.discover()
        assert count == 0

    def test_rediscover_cleans_and_rescans(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "hooks"
        project_dir.mkdir()
        (project_dir / "session.start--hook1.py").write_text("pass\n")

        registry = HookRegistry(max_per_event=20)
        discovery = ScriptHookDiscovery(
            hook_registry=registry,
            project_hooks_dir=project_dir,
        )
        count1 = discovery.discover()
        assert count1 == 1

        # Add another hook file
        (project_dir / "session.end--hook2.py").write_text("pass\n")
        count2 = discovery.rediscover()
        assert count2 == 2

    def test_parse_hook_filename_valid(self) -> None:
        result = ScriptHookDiscovery._parse_hook_filename(Path("session.start--purpose-gate.py"))
        assert result == ("session.start", "purpose-gate")

    def test_parse_hook_filename_no_extension(self) -> None:
        # "session.start--gate" has suffix ".start--gate" per Path parsing,
        # which is not a supported extension, so it should be rejected.
        result = ScriptHookDiscovery._parse_hook_filename(Path("session.start--gate"))
        assert result is None

    def test_parse_hook_filename_shell(self) -> None:
        result = ScriptHookDiscovery._parse_hook_filename(
            Path("tool.execute.pre--damage-control.sh")
        )
        assert result == ("tool.execute.pre", "damage-control")

    def test_parse_hook_filename_invalid_no_separator(self) -> None:
        result = ScriptHookDiscovery._parse_hook_filename(Path("noseparator.py"))
        assert result is None

    def test_supported_extensions(self, tmp_path: Path) -> None:
        """All supported extensions are discovered."""
        project_dir = tmp_path / "hooks"
        project_dir.mkdir()
        # Each file needs a unique hook name (the part after --)
        for i, ext in enumerate([".py", ".sh", ".ps1", ".js"]):
            (project_dir / f"session.start--hook{i}{ext}").write_text("pass\n")

        registry = HookRegistry(max_per_event=20)
        discovery = ScriptHookDiscovery(
            hook_registry=registry,
            project_hooks_dir=project_dir,
        )
        count = discovery.discover()
        assert count == 4

    def test_resolve_project_hooks_dir_prefers_scripts_hooks(self, tmp_path: Path) -> None:
        scripts_hooks = tmp_path / "scripts" / "hooks"
        scripts_hooks.mkdir(parents=True)
        resolved = resolve_project_hooks_dir(tmp_path)
        assert resolved == scripts_hooks

    def test_resolve_project_hooks_dir_falls_back_to_dot_claude(self, tmp_path: Path) -> None:
        resolved = resolve_project_hooks_dir(tmp_path)
        assert resolved == tmp_path / ".claude" / "hooks"
