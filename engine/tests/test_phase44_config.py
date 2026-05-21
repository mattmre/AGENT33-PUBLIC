"""Tests for Phase 44 config settings additions."""

from __future__ import annotations

from agent33.config import Settings


class TestPhase44ConfigDefaults:
    """Verify Phase 44 settings have correct defaults."""

    def test_operator_session_enabled_default(self) -> None:
        s = Settings()
        assert s.operator_session_enabled is True

    def test_operator_session_base_dir_default_empty(self) -> None:
        s = Settings()
        assert s.operator_session_base_dir == ""

    def test_operator_session_checkpoint_interval(self) -> None:
        s = Settings()
        assert s.operator_session_checkpoint_interval_seconds == 60.0

    def test_operator_session_max_replay_file_mb(self) -> None:
        s = Settings()
        assert s.operator_session_max_replay_file_mb == 50

    def test_operator_session_max_retained(self) -> None:
        s = Settings()
        assert s.operator_session_max_retained == 100

    def test_operator_session_crash_recovery_enabled(self) -> None:
        s = Settings()
        assert s.operator_session_crash_recovery_enabled is True

    def test_script_hooks_enabled_default(self) -> None:
        s = Settings()
        assert s.script_hooks_enabled is True

    def test_script_hooks_project_dir_default_empty(self) -> None:
        s = Settings()
        assert s.script_hooks_project_dir == ""

    def test_script_hooks_user_dir_default_empty(self) -> None:
        s = Settings()
        assert s.script_hooks_user_dir == ""

    def test_script_hooks_default_timeout_ms(self) -> None:
        s = Settings()
        assert s.script_hooks_default_timeout_ms == 5000.0

    def test_script_hooks_max_timeout_ms(self) -> None:
        s = Settings()
        assert s.script_hooks_max_timeout_ms == 30000.0


class TestPhase44ConfigFromEnv:
    """Verify Phase 44 settings can be loaded from environment."""

    def test_operator_session_disabled_via_env(self, monkeypatch: object) -> None:
        import os

        os.environ["OPERATOR_SESSION_ENABLED"] = "false"
        try:
            s = Settings()
            assert s.operator_session_enabled is False
        finally:
            os.environ.pop("OPERATOR_SESSION_ENABLED", None)

    def test_script_hooks_timeout_from_env(self, monkeypatch: object) -> None:
        import os

        os.environ["SCRIPT_HOOKS_DEFAULT_TIMEOUT_MS"] = "10000"
        try:
            s = Settings()
            assert s.script_hooks_default_timeout_ms == 10000.0
        finally:
            os.environ.pop("SCRIPT_HOOKS_DEFAULT_TIMEOUT_MS", None)
