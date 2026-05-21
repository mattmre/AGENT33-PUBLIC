"""Config apply service for Track 9 Operations.

Validates and applies runtime configuration changes to the Settings instance.
Changes are applied in-memory; optionally writes to the .env file for
persistence across restarts.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, SecretStr

if TYPE_CHECKING:
    from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# Fields that require a process restart to take effect (infrastructure bindings).
_RESTART_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "database_url",
        "redis_url",
        "nats_url",
        "api_port",
        "ollama_base_url",
        "openai_api_key",
        "openai_base_url",
        "openrouter_api_key",
        "openrouter_base_url",
        "openrouter_site_url",
        "openrouter_app_name",
        "openrouter_app_category",
        "jwt_secret",
        "jwt_algorithm",
        "encryption_key",
        "mcp_proxy_config_path",
        "mcp_proxy_enabled",
    }
)


class ConfigApplyRequest(BaseModel):
    """Request to apply configuration changes."""

    changes: dict[str, Any] = Field(default_factory=dict)
    write_to_env_file: bool = False


class ConfigApplyResult(BaseModel):
    """Result of applying configuration changes."""

    applied: list[str] = Field(default_factory=list)
    rejected: list[tuple[str, str]] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    restart_required: bool = False


class ConfigApplyService:
    """Validates and applies runtime configuration changes.

    Changes are applied directly to the live Settings singleton, meaning they
    take effect immediately for all subsequent reads. Infrastructure fields
    (database_url, redis_url, etc.) are flagged as requiring a restart
    because existing connections are not automatically re-established.
    """

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        self._settings_cls = settings_cls

    def validate_only(self, changes: dict[str, Any]) -> list[str]:
        """Validate proposed changes without applying them.

        Returns a list of validation error messages (empty means valid).
        """
        errors: list[str] = []
        known_fields = self._settings_cls.model_fields

        for key, value in changes.items():
            if key not in known_fields:
                errors.append(f"Unknown field: {key}")
                continue

            field_info = known_fields[key]
            annotation = field_info.annotation

            # Type validation
            try:
                self._coerce_value(key, value, annotation)
            except (TypeError, ValueError) as exc:
                errors.append(f"Invalid value for {key}: {exc}")

        return errors

    def apply(
        self,
        request: ConfigApplyRequest,
        settings_instance: Any | None = None,
    ) -> ConfigApplyResult:
        """Apply configuration changes to the live settings.

        Parameters
        ----------
        request:
            The changes to apply plus whether to persist to .env.
        settings_instance:
            The live Settings singleton. When ``None``, imports
            ``agent33.config.settings``.
        """
        if settings_instance is None:
            from agent33.config import settings as live_settings

            settings_instance = live_settings

        result = ConfigApplyResult()
        known_fields = self._settings_cls.model_fields

        for key, value in request.changes.items():
            if key not in known_fields:
                result.rejected.append((key, f"Unknown field: {key}"))
                continue

            field_info = known_fields[key]
            annotation = field_info.annotation

            try:
                coerced = self._coerce_value(key, value, annotation)
            except (TypeError, ValueError) as exc:
                result.validation_errors.append(f"{key}: {exc}")
                continue

            # Apply to the live settings
            try:
                object.__setattr__(settings_instance, key, coerced)
                result.applied.append(key)
            except Exception as exc:
                result.rejected.append((key, f"Failed to set: {exc}"))
                continue

            # Check if restart is needed
            if key in _RESTART_REQUIRED_FIELDS:
                result.restart_required = True

        # Optionally persist to .env
        if request.write_to_env_file and result.applied:
            try:
                self._write_env_file(request.changes, result.applied)
            except Exception as exc:
                logger.warning("config_apply_env_write_failed: %s", str(exc))
                result.validation_errors.append(f"Failed to write .env: {exc}")

        return result

    def _coerce_value(self, key: str, value: Any, annotation: Any) -> Any:
        """Coerce a value to the expected type."""
        if annotation is SecretStr:
            if not isinstance(value, str):
                raise TypeError(f"Expected string for SecretStr field {key}")
            return SecretStr(value)

        if annotation is int:
            return int(value)
        if annotation is float:
            return float(value)
        if annotation is bool:
            if isinstance(value, str):
                if value.lower() in ("true", "1", "yes"):
                    return True
                if value.lower() in ("false", "0", "no"):
                    return False
                raise ValueError(f"Cannot convert {value!r} to bool")
            return bool(value)
        if annotation is str:
            return str(value)

        # For complex types, pass through as-is
        return value

    def _write_env_file(
        self,
        changes: dict[str, Any],
        applied_keys: list[str],
    ) -> None:
        """Append or update entries in the .env file."""
        env_path = Path(".env")
        existing_lines: list[str] = []
        existing_keys: set[str] = set()

        if env_path.exists():
            existing_lines = env_path.read_text(encoding="utf-8").splitlines()
            for line in existing_lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    existing_keys.add(stripped.split("=", 1)[0].strip())

        # Update existing or append new
        updated_lines: list[str] = []
        updated_keys: set[str] = set()

        for line in existing_lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                line_key = stripped.split("=", 1)[0].strip()
                env_key = line_key.upper() if line_key == line_key.upper() else line_key
                for applied_key in applied_keys:
                    if applied_key.upper() == env_key.upper():
                        value = changes[applied_key]
                        if isinstance(value, SecretStr):
                            value = value.get_secret_value()
                        updated_lines.append(f"{applied_key.upper()}={value}")
                        updated_keys.add(applied_key)
                        break
                else:
                    updated_lines.append(line)
            else:
                updated_lines.append(line)

        # Append any new keys
        for key in applied_keys:
            if key not in updated_keys:
                value = changes[key]
                if isinstance(value, SecretStr):
                    value = value.get_secret_value()
                updated_lines.append(f"{key.upper()}={value}")

        env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
