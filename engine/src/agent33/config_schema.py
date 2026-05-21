"""Config schema introspection for Track 9 Operations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, SecretStr

if TYPE_CHECKING:
    from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# Mapping of field-name prefixes to logical groups.
# Order matters: first matching prefix wins.
_PREFIX_GROUPS: list[tuple[str, str]] = [
    ("database_", "database"),
    ("redis_", "redis"),
    ("nats_", "nats"),
    ("ollama_", "ollama"),
    ("local_orchestration_", "orchestration"),
    ("jwt_", "security"),
    ("auth_", "security"),
    ("api_secret", "security"),
    ("encryption_", "security"),
    ("rate_limit_", "security"),
    ("openai_", "llm"),
    ("elevenlabs_", "voice"),
    ("voice_", "voice"),
    ("airllm_", "airllm"),
    ("jina_", "embeddings"),
    ("embedding_", "embeddings"),
    ("http_", "http"),
    ("rag_", "rag"),
    ("chunk_", "rag"),
    ("bm25_", "rag"),
    ("training_", "training"),
    ("agent_", "agents"),
    ("observability_", "observability"),
    ("plugin_", "plugins"),
    ("skill", "skills"),
    ("pack_", "packs"),
    ("mcp_", "mcp"),
    ("approval_token_", "mcp"),
    ("tool_discovery_", "mcp"),
    ("connector_", "mcp"),
    ("jupyter_", "execution"),
    ("hooks_", "hooks"),
    ("script_hooks_", "hooks"),
    ("operator_session_", "sessions"),
    ("context_", "context"),
    ("session_", "sessions"),
    ("matrix_", "messaging"),
    ("self_improve_", "improvement"),
    ("autonomy_", "improvement"),
    ("offline_", "improvement"),
    ("intake_", "improvement"),
    ("analysis_", "improvement"),
    ("synthetic_env_", "evaluation"),
    ("orchestration_", "orchestration"),
    ("process_manager_", "orchestration"),
    ("backup_", "backup"),
    ("improvement_learning_", "improvement"),
    ("comparative_", "evaluation"),
    ("searxng_", "search"),
    ("api_", "api"),
    ("cors_", "api"),
    ("max_request_", "api"),
    ("environment", "general"),
]


class ConfigFieldSchema(BaseModel):
    """Schema for a single configuration field."""

    name: str
    type: str
    default: Any = None
    description: str = ""
    group: str = ""
    is_secret: bool = False
    env_var: str = ""


class ConfigSchemaResponse(BaseModel):
    """Grouped configuration schema response."""

    groups: dict[str, list[ConfigFieldSchema]] = Field(default_factory=dict)
    total_fields: int = 0


def _classify_group(field_name: str) -> str:
    """Determine the group for a field based on its name prefix."""
    for prefix, group in _PREFIX_GROUPS:
        if field_name.startswith(prefix):
            return group
    return "general"


def _type_label(annotation: Any) -> str:
    """Produce a human-readable type label from a Python annotation."""
    if annotation is None:
        return "unknown"

    origin = getattr(annotation, "__origin__", None)

    # Handle typing generics (dict, list, etc.)
    if origin is not None:
        args = getattr(annotation, "__args__", ())
        arg_labels = ", ".join(_type_label(a) for a in args) if args else ""
        origin_name = getattr(origin, "__name__", str(origin))
        return f"{origin_name}[{arg_labels}]" if arg_labels else origin_name

    # Handle SecretStr
    if annotation is SecretStr:
        return "SecretStr"

    # Handle basic types
    if isinstance(annotation, type):
        return annotation.__name__

    # Union types (e.g. str | None)
    union_args = getattr(annotation, "__args__", None)
    if union_args:
        return " | ".join(_type_label(a) for a in union_args)

    return str(annotation)


def introspect_settings_schema(settings_cls: type[BaseSettings]) -> ConfigSchemaResponse:
    """Introspect a Pydantic Settings class and return grouped field schemas.

    Uses ``model_fields`` to extract field names, types, defaults, and
    descriptions. Groups are assigned based on field name prefixes.
    SecretStr fields are marked with ``is_secret=True``.
    """
    groups: dict[str, list[ConfigFieldSchema]] = {}

    for field_name, field_info in settings_cls.model_fields.items():
        # Determine type
        annotation = field_info.annotation
        type_label = _type_label(annotation)

        # Check for SecretStr
        is_secret = annotation is SecretStr

        # Determine default value
        default_value: Any = None
        if field_info.default is not None:
            default_value = "***" if is_secret else field_info.default

        # Extract description from field metadata
        description = field_info.description or ""

        # Determine group
        group = _classify_group(field_name)

        # Env var = uppercase of field name
        env_var = field_name.upper()

        schema = ConfigFieldSchema(
            name=field_name,
            type=type_label,
            default=default_value,
            description=description,
            group=group,
            is_secret=is_secret,
            env_var=env_var,
        )

        if group not in groups:
            groups[group] = []
        groups[group].append(schema)

    total = sum(len(fields) for fields in groups.values())
    return ConfigSchemaResponse(groups=groups, total_fields=total)
