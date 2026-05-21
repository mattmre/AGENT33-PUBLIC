"""Configuration profiles for AGENT-33.

Named presets that provide sensible defaults for common deployment scenarios.
Profiles are applied BEFORE environment variables, so env vars always win.

Usage::

    AGENT33_PROFILE=developer agent33 start
    agent33 start --profile developer
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

# 5 named presets. Each defines ONLY the fields that differ from Settings defaults.
# Fields not mentioned here fall back to Settings field defaults.
PROFILES: dict[str, dict[str, Any]] = {
    "minimal": {
        # Absolute minimum: lite mode, quiet logging, no BM25 warmup
        "agent33_mode": "lite",
        "api_log_level": "warning",
        "bm25_warmup_enabled": False,
    },
    "developer": {
        # Local development: lite mode, verbose logging, fast iteration
        "agent33_mode": "lite",
        "api_log_level": "debug",
        "bm25_warmup_enabled": False,
    },
    "production": {
        # Production: standard mode, structured logging, BM25 warmup on
        "agent33_mode": "standard",
        "api_log_level": "info",
        "bm25_warmup_enabled": True,
    },
    "enterprise": {
        # Full enterprise: pgvector, multi-tenancy, all features
        "agent33_mode": "enterprise",
        "api_log_level": "info",
        "bm25_warmup_enabled": True,
    },
    "airgapped": {
        # No external network: local LLM only, no cloud APIs
        "agent33_mode": "lite",
        "api_log_level": "info",
        "bm25_warmup_enabled": False,
        "ollama_base_url": "http://localhost:11434",
    },
}

PROFILE_NAMES = list(PROFILES.keys())


class ProfileSettingsSource(PydanticBaseSettingsSource):
    """Injects profile defaults into Pydantic Settings.

    Priority order (highest to lowest):

    1. ``init_settings`` — values passed directly to ``Settings(...)``
    2. ``env_settings`` — environment variables
    3. ``dotenv_settings`` — ``.env`` file
    4. ``ProfileSettingsSource`` — profile preset (this source)
    5. ``file_secret_settings`` — mounted secrets

    This means any env var always overrides the profile, and the profile
    overrides the Settings field defaults.
    """

    def __init__(self, settings_cls: type[BaseSettings], profile_name: str | None = None) -> None:
        super().__init__(settings_cls)
        resolved = profile_name or ""
        self._profile: dict[str, Any] = PROFILES.get(resolved, {})

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        """Return the profile value for the given field, if present."""
        value = self._profile.get(field_name)
        if value is None:
            return None, "", False
        return value, field_name, False

    def __call__(self) -> dict[str, Any]:
        return dict(self._profile)

    def field_is_complex(self, field: FieldInfo) -> bool:
        return False
