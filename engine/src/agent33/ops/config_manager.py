"""Config management service — schema introspection, validation, and apply.

Wraps the existing :mod:`agent33.config_schema` and :mod:`agent33.config_apply`
modules under a single service interface for the ``/v1/ops/config`` endpoints.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, SecretStr

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

# Category mappings — derived from field-name prefixes.  We reuse the same
# mapping logic that config_schema uses, but expose a simpler flat model.
_CATEGORY_PREFIXES: list[tuple[str, str]] = [
    ("database_", "database"),
    ("db_", "database"),
    ("redis_", "redis"),
    ("nats_", "nats"),
    ("ollama_", "llm"),
    ("local_orchestration_", "llm"),
    ("openai_", "llm"),
    ("openrouter_", "llm"),
    ("default_model", "llm"),
    ("jwt_", "security"),
    ("auth_", "security"),
    ("api_secret", "security"),
    ("encryption_", "security"),
    ("rate_limit_", "security"),
    ("searxng_", "web_search"),
    ("tavily_", "web_search"),
    ("brave_", "web_search"),
    ("web_search_", "web_search"),
    ("voice_", "features"),
    ("airllm_", "features"),
    ("jina_", "features"),
    ("embedding_", "features"),
    ("training_", "features"),
    ("skill", "features"),
    ("mcp_", "features"),
    ("plugin_", "features"),
    ("hook", "features"),
    ("pack_", "features"),
    ("agent_", "features"),
    ("api_", "api"),
    ("cors_", "api"),
    ("max_request_", "api"),
    ("environment", "api"),
]


def _classify_category(field_name: str) -> str:
    """Assign a category to a field based on its name prefix."""
    for prefix, category in _CATEGORY_PREFIXES:
        if field_name.startswith(prefix):
            return category
    return "general"


class ConfigField(BaseModel):
    """Schema for a single configuration field."""

    name: str
    type: str
    current_value: Any = None
    default_value: Any = None
    description: str = ""
    required: bool = False
    category: str = "general"


class ConfigDiff(BaseModel):
    """A single field-level change."""

    field: str
    old_value: Any = None
    new_value: Any = None


class ConfigManagerResult(BaseModel):
    """Result of a validate or apply operation."""

    diffs: list[ConfigDiff] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    restart_required: bool = False


# ---------------------------------------------------------------------------
# ConfigManager service
# ---------------------------------------------------------------------------


class ConfigManager:
    """Introspects, validates, and applies configuration changes.

    This service introspects the Pydantic Settings class dynamically (not
    from a hardcoded list) so that any new field added to ``Settings`` is
    automatically visible.

    Parameters
    ----------
    settings_instance:
        The live :class:`~agent33.config.Settings` singleton.
    settings_cls:
        The Settings class (default: ``type(settings_instance)``).
    """

    def __init__(
        self,
        settings_instance: Any,
        settings_cls: type[Any] | None = None,
    ) -> None:
        self._settings = settings_instance
        self._settings_cls: type[Any] = settings_cls or type(settings_instance)

    def get_schema(self) -> list[ConfigField]:
        """Introspect the Settings class and return field metadata.

        SecretStr current values are redacted to ``"***"``.
        """
        fields: list[ConfigField] = []
        for name, field_info in self._settings_cls.model_fields.items():
            annotation = field_info.annotation
            is_secret = annotation is SecretStr
            type_label = _type_label(annotation)

            # Current value (redacted for secrets)
            raw_value = getattr(self._settings, name, None)
            if is_secret:
                current_value: Any = "***"
            elif isinstance(raw_value, SecretStr):
                current_value = "***"
            else:
                current_value = raw_value

            # Default value (redacted for secrets)
            default_raw = field_info.default
            if is_secret or isinstance(default_raw, SecretStr):
                default_value: Any = "***"
            else:
                default_value = default_raw

            fields.append(
                ConfigField(
                    name=name,
                    type=type_label,
                    current_value=current_value,
                    default_value=default_value,
                    description=field_info.description or "",
                    required=field_info.is_required(),
                    category=_classify_category(name),
                )
            )
        return fields

    def get_current(self) -> dict[str, Any]:
        """Return current config values as a dict (secrets redacted)."""
        result: dict[str, Any] = {}
        for name, field_info in self._settings_cls.model_fields.items():
            annotation = field_info.annotation
            is_secret = annotation is SecretStr
            raw_value = getattr(self._settings, name, None)
            if is_secret or isinstance(raw_value, SecretStr):
                result[name] = "***"
            else:
                result[name] = raw_value
        return result

    def validate_changes(self, changes: dict[str, Any]) -> list[str]:
        """Validate proposed changes without applying them.

        Returns a list of error messages (empty = valid).
        """
        from agent33.config_apply import ConfigApplyService

        svc = ConfigApplyService(settings_cls=self._settings_cls)
        return svc.validate_only(changes)

    def apply_changes(self, changes: dict[str, Any]) -> ConfigManagerResult:
        """Apply configuration changes to the live Settings instance.

        Returns diffs and any validation errors.
        """
        from agent33.config_apply import ConfigApplyRequest, ConfigApplyService

        svc = ConfigApplyService(settings_cls=self._settings_cls)
        request = ConfigApplyRequest(changes=changes, write_to_env_file=False)

        # Capture old values for diff
        old_values: dict[str, Any] = {}
        for key in changes:
            if key in self._settings_cls.model_fields:
                raw = getattr(self._settings, key, None)
                if isinstance(raw, SecretStr):
                    old_values[key] = "***"
                else:
                    old_values[key] = raw

        result = svc.apply(request, settings_instance=self._settings)

        diffs: list[ConfigDiff] = []
        for key in result.applied:
            new_raw = getattr(self._settings, key, None)
            new_val: Any = "***" if isinstance(new_raw, SecretStr) else new_raw
            diffs.append(
                ConfigDiff(
                    field=key,
                    old_value=old_values.get(key),
                    new_value=new_val,
                )
            )

        return ConfigManagerResult(
            diffs=diffs,
            validation_errors=result.validation_errors,
            restart_required=result.restart_required,
        )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _type_label(annotation: Any) -> str:
    """Human-readable type label from a Python annotation."""
    if annotation is None:
        return "unknown"
    if annotation is SecretStr:
        return "SecretStr"
    origin = getattr(annotation, "__origin__", None)
    if origin is not None:
        args = getattr(annotation, "__args__", ())
        arg_labels = ", ".join(_type_label(a) for a in args) if args else ""
        origin_name = getattr(origin, "__name__", str(origin))
        return f"{origin_name}[{arg_labels}]" if arg_labels else origin_name
    if isinstance(annotation, type):
        return annotation.__name__
    union_args = getattr(annotation, "__args__", None)
    if union_args:
        return " | ".join(_type_label(a) for a in union_args)
    return str(annotation)
