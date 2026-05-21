"""Comprehensive tests for agent33.config_apply module.

Covers: ConfigApplyService.validate_only(), apply(), _coerce_value(),
_write_env_file(), validation error paths, edge cases (unknown fields,
type mismatches, mixed valid/invalid batches, SecretStr handling, env file
update vs append).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from agent33.config import Settings
from agent33.config_apply import (
    _RESTART_REQUIRED_FIELDS,
    ConfigApplyRequest,
    ConfigApplyResult,
    ConfigApplyService,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_settings(**overrides: Any) -> Settings:
    """Create a test Settings instance with safe defaults."""
    defaults: dict[str, Any] = {
        "environment": "test",
        "database_url": "postgresql+asyncpg://test:test@localhost/test",
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestCoerceValue:
    """Tests for _coerce_value type coercion logic."""

    def setup_method(self) -> None:
        self.svc = ConfigApplyService(settings_cls=Settings)

    def test_coerce_int_from_string(self) -> None:
        """Integer fields accept numeric strings."""
        result = self.svc._coerce_value("api_port", "9000", int)
        assert result == 9000
        assert isinstance(result, int)

    def test_coerce_int_from_int(self) -> None:
        """Integer fields accept native ints."""
        result = self.svc._coerce_value("api_port", 8080, int)
        assert result == 8080

    def test_coerce_int_rejects_non_numeric_string(self) -> None:
        """Non-numeric strings raise ValueError for int fields."""
        with pytest.raises((TypeError, ValueError)):
            self.svc._coerce_value("api_port", "not-a-number", int)

    def test_coerce_float_from_string(self) -> None:
        """Float fields accept numeric strings."""
        result = self.svc._coerce_value("rag_similarity_threshold", "0.75", float)
        assert result == 0.75
        assert isinstance(result, float)

    def test_coerce_bool_true_variants(self) -> None:
        """Boolean fields accept 'true', '1', 'yes' as True."""
        for val in ("true", "True", "TRUE", "1", "yes", "YES"):
            result = self.svc._coerce_value("training_enabled", val, bool)
            assert result is True, f"Expected True for input {val!r}"

    def test_coerce_bool_false_variants(self) -> None:
        """Boolean fields accept 'false', '0', 'no' as False."""
        for val in ("false", "False", "FALSE", "0", "no", "NO"):
            result = self.svc._coerce_value("training_enabled", val, bool)
            assert result is False, f"Expected False for input {val!r}"

    def test_coerce_bool_invalid_string_raises(self) -> None:
        """Boolean fields reject ambiguous strings like 'maybe'."""
        with pytest.raises(ValueError, match="Cannot convert"):
            self.svc._coerce_value("training_enabled", "maybe", bool)

    def test_coerce_secretstr_from_string(self) -> None:
        """SecretStr fields wrap string values."""
        result = self.svc._coerce_value("jwt_secret", "my-secret", SecretStr)
        assert isinstance(result, SecretStr)
        assert result.get_secret_value() == "my-secret"

    def test_coerce_secretstr_rejects_non_string(self) -> None:
        """SecretStr fields reject non-string values."""
        with pytest.raises(TypeError, match="Expected string"):
            self.svc._coerce_value("jwt_secret", 12345, SecretStr)

    def test_coerce_str_from_non_string(self) -> None:
        """String fields coerce other types via str()."""
        result = self.svc._coerce_value("api_log_level", 42, str)
        assert result == "42"
        assert isinstance(result, str)

    def test_coerce_passthrough_for_complex_types(self) -> None:
        """Complex/unknown annotation types pass values through unchanged."""
        sentinel = object()
        result = self.svc._coerce_value("anything", sentinel, list)
        assert result is sentinel


class TestValidateOnly:
    """Tests for ConfigApplyService.validate_only()."""

    def setup_method(self) -> None:
        self.svc = ConfigApplyService(settings_cls=Settings)

    def test_valid_changes_produce_no_errors(self) -> None:
        """A batch of valid changes returns an empty error list."""
        errors = self.svc.validate_only(
            {"api_port": 9000, "training_enabled": False, "api_log_level": "debug"}
        )
        assert errors == []

    def test_unknown_field_produces_error(self) -> None:
        """Unknown field names produce exactly one error per field."""
        errors = self.svc.validate_only({"nonexistent_field": "value"})
        assert len(errors) == 1
        assert "Unknown field: nonexistent_field" in errors[0]

    def test_multiple_unknown_fields(self) -> None:
        """Multiple unknown fields each produce their own error."""
        errors = self.svc.validate_only({"bad_a": 1, "bad_b": 2})
        assert len(errors) == 2
        unknown_fields = [e for e in errors if "Unknown field" in e]
        assert len(unknown_fields) == 2

    def test_type_mismatch_produces_error(self) -> None:
        """A value that cannot be coerced to the field type produces an error."""
        errors = self.svc.validate_only({"api_port": "not-a-number"})
        assert len(errors) == 1
        assert "Invalid value for api_port" in errors[0]

    def test_mixed_valid_and_invalid(self) -> None:
        """Valid changes pass; invalid ones produce errors; both coexist."""
        errors = self.svc.validate_only(
            {
                "api_port": 8080,  # valid
                "fake_field": "x",  # unknown
                "jwt_secret": 999,  # wrong type (not string for SecretStr)
            }
        )
        assert len(errors) == 2
        error_text = " ".join(errors)
        assert "fake_field" in error_text
        assert "jwt_secret" in error_text

    def test_empty_changes_no_errors(self) -> None:
        """An empty change set is trivially valid."""
        errors = self.svc.validate_only({})
        assert errors == []


class TestApply:
    """Tests for ConfigApplyService.apply()."""

    def setup_method(self) -> None:
        self.svc = ConfigApplyService(settings_cls=Settings)

    def test_apply_modifies_settings_instance(self) -> None:
        """Applied changes actually mutate the settings object."""
        settings = _make_settings(api_port=8000)
        result = self.svc.apply(
            ConfigApplyRequest(changes={"api_port": 9999}),
            settings_instance=settings,
        )
        assert "api_port" in result.applied
        assert settings.api_port == 9999

    def test_apply_rejects_unknown_field(self) -> None:
        """Unknown fields land in result.rejected, not applied."""
        settings = _make_settings()
        result = self.svc.apply(
            ConfigApplyRequest(changes={"totally_fake": "value"}),
            settings_instance=settings,
        )
        assert len(result.rejected) == 1
        assert result.rejected[0][0] == "totally_fake"
        assert "Unknown field" in result.rejected[0][1]
        assert result.applied == []

    def test_apply_type_error_goes_to_validation_errors(self) -> None:
        """Values that fail coercion land in validation_errors."""
        settings = _make_settings()
        original_port = settings.api_port
        result = self.svc.apply(
            ConfigApplyRequest(changes={"api_port": "xyz"}),
            settings_instance=settings,
        )
        assert len(result.validation_errors) == 1
        assert "api_port" in result.validation_errors[0]
        # Setting must remain unchanged
        assert settings.api_port == original_port

    def test_apply_infrastructure_field_flags_restart(self) -> None:
        """Fields in _RESTART_REQUIRED_FIELDS set restart_required=True."""
        settings = _make_settings()
        result = self.svc.apply(
            ConfigApplyRequest(changes={"redis_url": "redis://newhost:6379/0"}),
            settings_instance=settings,
        )
        assert result.restart_required is True
        assert "redis_url" in result.applied
        assert settings.redis_url == "redis://newhost:6379/0"

    def test_apply_non_infrastructure_no_restart(self) -> None:
        """Non-infrastructure fields do not flag restart."""
        settings = _make_settings(training_enabled=True)
        result = self.svc.apply(
            ConfigApplyRequest(changes={"training_enabled": False}),
            settings_instance=settings,
        )
        assert result.restart_required is False
        assert settings.training_enabled is False

    def test_apply_secretstr_field(self) -> None:
        """SecretStr fields are coerced and applied correctly."""
        settings = _make_settings()
        result = self.svc.apply(
            ConfigApplyRequest(changes={"jwt_secret": "super-secret-value"}),
            settings_instance=settings,
        )
        assert "jwt_secret" in result.applied
        assert settings.jwt_secret.get_secret_value() == "super-secret-value"
        assert result.restart_required is True  # jwt_secret is infrastructure

    def test_apply_bool_from_string(self) -> None:
        """Boolean fields accept string representations in apply()."""
        settings = _make_settings(training_enabled=True)
        result = self.svc.apply(
            ConfigApplyRequest(changes={"training_enabled": "no"}),
            settings_instance=settings,
        )
        assert "training_enabled" in result.applied
        assert settings.training_enabled is False

    def test_apply_mixed_batch(self) -> None:
        """A batch with valid, unknown, and type-error items sorts correctly."""
        settings = _make_settings(api_port=8000)
        result = self.svc.apply(
            ConfigApplyRequest(
                changes={
                    "api_port": 9090,  # valid
                    "fake_field": "x",  # unknown -> rejected
                    "db_pool_size": "not-int",  # type error -> validation_errors
                }
            ),
            settings_instance=settings,
        )
        assert "api_port" in result.applied
        assert settings.api_port == 9090
        assert len(result.rejected) == 1
        assert result.rejected[0][0] == "fake_field"
        assert len(result.validation_errors) == 1
        assert "db_pool_size" in result.validation_errors[0]

    def test_apply_imports_global_settings_when_none(self) -> None:
        """When settings_instance is None, apply() imports the global singleton."""
        from agent33.config import settings as global_settings

        original = global_settings.rag_top_k
        try:
            result = self.svc.apply(
                ConfigApplyRequest(changes={"rag_top_k": 99}),
                settings_instance=None,
            )
            assert "rag_top_k" in result.applied
            assert global_settings.rag_top_k == 99
        finally:
            # Restore the original value to avoid test pollution
            object.__setattr__(global_settings, "rag_top_k", original)


class TestWriteEnvFile:
    """Tests for _write_env_file, using tmp_path for isolation."""

    def setup_method(self) -> None:
        self.svc = ConfigApplyService(settings_cls=Settings)

    def test_creates_env_file_when_absent(self, tmp_path: Path) -> None:
        """A new .env file is created with the applied key."""
        env_file = tmp_path / ".env"
        with patch("agent33.config_apply.Path") as mock_path_cls:
            mock_path_cls.return_value = env_file
            self.svc._write_env_file(
                changes={"api_port": 9000},
                applied_keys=["api_port"],
            )
        content = env_file.read_text(encoding="utf-8")
        assert "API_PORT=9000" in content

    def test_appends_new_key_to_existing_env(self, tmp_path: Path) -> None:
        """New keys are appended to an existing .env file, preserving old entries."""
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING_KEY=existing_value\n", encoding="utf-8")

        with patch("agent33.config_apply.Path") as mock_path_cls:
            mock_path_cls.return_value = env_file
            self.svc._write_env_file(
                changes={"api_port": 9000},
                applied_keys=["api_port"],
            )

        content = env_file.read_text(encoding="utf-8")
        assert "EXISTING_KEY=existing_value" in content
        assert "API_PORT=9000" in content

    def test_updates_existing_key_in_env(self, tmp_path: Path) -> None:
        """An already-present key is updated in place, not duplicated."""
        env_file = tmp_path / ".env"
        env_file.write_text("API_PORT=8000\nOTHER=value\n", encoding="utf-8")

        with patch("agent33.config_apply.Path") as mock_path_cls:
            mock_path_cls.return_value = env_file
            self.svc._write_env_file(
                changes={"api_port": 9999},
                applied_keys=["api_port"],
            )

        content = env_file.read_text(encoding="utf-8")
        lines = [ln for ln in content.splitlines() if ln.strip()]
        # The old API_PORT=8000 should be replaced, not duplicated
        api_port_lines = [ln for ln in lines if ln.startswith("API_PORT=")]
        assert len(api_port_lines) == 1
        assert api_port_lines[0] == "API_PORT=9999"
        # OTHER should be preserved
        assert any(ln.startswith("OTHER=") for ln in lines)

    def test_preserves_comments_and_blank_lines(self, tmp_path: Path) -> None:
        """Comments and blank lines in .env are preserved."""
        env_file = tmp_path / ".env"
        env_file.write_text("# Main config\n\nAPI_PORT=8000\n# End\n", encoding="utf-8")

        with patch("agent33.config_apply.Path") as mock_path_cls:
            mock_path_cls.return_value = env_file
            self.svc._write_env_file(
                changes={"api_port": 7777},
                applied_keys=["api_port"],
            )

        content = env_file.read_text(encoding="utf-8")
        assert "# Main config" in content
        assert "# End" in content

    def test_writes_secretstr_as_plain_value(self, tmp_path: Path) -> None:
        """SecretStr values are written as their plain string representation."""
        env_file = tmp_path / ".env"

        with patch("agent33.config_apply.Path") as mock_path_cls:
            mock_path_cls.return_value = env_file
            self.svc._write_env_file(
                changes={"jwt_secret": SecretStr("my-secret-123")},
                applied_keys=["jwt_secret"],
            )

        content = env_file.read_text(encoding="utf-8")
        assert "JWT_SECRET=my-secret-123" in content
        # Must not contain the SecretStr repr
        assert "SecretStr" not in content


class TestApplyWithEnvWrite:
    """Tests for apply() with write_to_env_file=True."""

    def setup_method(self) -> None:
        self.svc = ConfigApplyService(settings_cls=Settings)

    def test_apply_with_write_to_env_calls_write(self, tmp_path: Path) -> None:
        """When write_to_env_file=True and changes apply, _write_env_file is called."""
        settings = _make_settings()

        with patch.object(self.svc, "_write_env_file") as mock_write:
            result = self.svc.apply(
                ConfigApplyRequest(
                    changes={"api_port": 7777},
                    write_to_env_file=True,
                ),
                settings_instance=settings,
            )
            assert "api_port" in result.applied
            mock_write.assert_called_once_with({"api_port": 7777}, ["api_port"])

    def test_apply_without_write_skips_env_file(self) -> None:
        """When write_to_env_file=False, _write_env_file is not called."""
        settings = _make_settings()
        with patch.object(self.svc, "_write_env_file") as mock_write:
            self.svc.apply(
                ConfigApplyRequest(
                    changes={"api_port": 7777},
                    write_to_env_file=False,
                ),
                settings_instance=settings,
            )
            mock_write.assert_not_called()

    def test_apply_env_write_failure_is_non_fatal(self) -> None:
        """If _write_env_file raises, the apply still succeeds with a warning."""
        settings = _make_settings()
        with patch.object(
            self.svc, "_write_env_file", side_effect=PermissionError("read-only fs")
        ):
            result = self.svc.apply(
                ConfigApplyRequest(
                    changes={"api_port": 7777},
                    write_to_env_file=True,
                ),
                settings_instance=settings,
            )
            # The field was still applied in-memory
            assert "api_port" in result.applied
            assert settings.api_port == 7777
            # But the env write failure is reported
            assert any("Failed to write .env" in e for e in result.validation_errors)

    def test_apply_no_applied_keys_skips_write(self) -> None:
        """If no changes were successfully applied, env write is skipped."""
        settings = _make_settings()
        with patch.object(self.svc, "_write_env_file") as mock_write:
            result = self.svc.apply(
                ConfigApplyRequest(
                    changes={"fake_field": "x"},
                    write_to_env_file=True,
                ),
                settings_instance=settings,
            )
            assert result.applied == []
            mock_write.assert_not_called()


class TestRestartRequiredFields:
    """Verify the _RESTART_REQUIRED_FIELDS set is consistent."""

    def test_all_restart_fields_exist_in_settings(self) -> None:
        """Every field in _RESTART_REQUIRED_FIELDS must be a real Settings field."""
        known_fields = Settings.model_fields
        for field_name in _RESTART_REQUIRED_FIELDS:
            assert field_name in known_fields, (
                f"{field_name} is in _RESTART_REQUIRED_FIELDS but not in Settings.model_fields"
            )

    def test_expected_infrastructure_fields_present(self) -> None:
        """Key infrastructure fields are in the restart-required set."""
        expected = {"database_url", "redis_url", "nats_url", "jwt_secret"}
        assert expected.issubset(_RESTART_REQUIRED_FIELDS)


class TestConfigApplyResultModel:
    """Tests for the ConfigApplyResult Pydantic model defaults."""

    def test_default_values(self) -> None:
        """ConfigApplyResult defaults are all empty/false."""
        result = ConfigApplyResult()
        assert result.applied == []
        assert result.rejected == []
        assert result.validation_errors == []
        assert result.restart_required is False
