"""Tests for configuration profiles (P61).

These tests verify:
- The 5 named presets exist and contain the expected field values.
- ProfileSettingsSource returns the correct dict for known/unknown profiles.
- The Settings class honours AGENT33_PROFILE env var (profile values show up).
- Explicit env vars override profile defaults (env wins over profile).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent33.config_profiles import PROFILE_NAMES, PROFILES, ProfileSettingsSource

if TYPE_CHECKING:
    import pytest


# ---------------------------------------------------------------------------
# Profile content tests
# ---------------------------------------------------------------------------


def test_all_five_profiles_exist() -> None:
    assert "minimal" in PROFILES
    assert "developer" in PROFILES
    assert "production" in PROFILES
    assert "enterprise" in PROFILES
    assert "airgapped" in PROFILES
    assert len(PROFILES) == 5


def test_profile_names_list_contains_all_five() -> None:
    assert set(PROFILE_NAMES) == {"minimal", "developer", "production", "enterprise", "airgapped"}


def test_minimal_profile_is_lite_mode() -> None:
    assert PROFILES["minimal"]["agent33_mode"] == "lite"


def test_minimal_profile_has_warning_log_level() -> None:
    assert PROFILES["minimal"]["api_log_level"] == "warning"


def test_minimal_profile_disables_bm25_warmup() -> None:
    assert PROFILES["minimal"]["bm25_warmup_enabled"] is False


def test_developer_profile_is_lite_with_debug_logging() -> None:
    p = PROFILES["developer"]
    assert p["agent33_mode"] == "lite"
    assert p["api_log_level"] == "debug"
    assert p["bm25_warmup_enabled"] is False


def test_production_profile_is_standard_mode() -> None:
    p = PROFILES["production"]
    assert p["agent33_mode"] == "standard"
    assert p["bm25_warmup_enabled"] is True


def test_enterprise_profile_is_enterprise_mode() -> None:
    p = PROFILES["enterprise"]
    assert p["agent33_mode"] == "enterprise"
    assert p["bm25_warmup_enabled"] is True


def test_airgapped_profile_is_lite_with_local_ollama() -> None:
    p = PROFILES["airgapped"]
    assert p["agent33_mode"] == "lite"
    assert p["bm25_warmup_enabled"] is False
    assert "localhost" in p["ollama_base_url"]


# ---------------------------------------------------------------------------
# ProfileSettingsSource unit tests
# ---------------------------------------------------------------------------


def test_profile_source_developer_returns_overrides() -> None:
    from agent33.config import Settings

    source = ProfileSettingsSource(Settings, profile_name="developer")
    result = source()
    assert result.get("agent33_mode") == "lite"
    assert result.get("api_log_level") == "debug"
    assert result.get("bm25_warmup_enabled") is False


def test_profile_source_unknown_profile_returns_empty_dict() -> None:
    from agent33.config import Settings

    source = ProfileSettingsSource(Settings, profile_name="nonexistent_profile")
    result = source()
    assert result == {}


def test_profile_source_none_returns_empty_dict() -> None:
    from agent33.config import Settings

    source = ProfileSettingsSource(Settings, profile_name=None)
    result = source()
    assert result == {}


def test_profile_source_production_returns_standard_mode() -> None:
    from agent33.config import Settings

    source = ProfileSettingsSource(Settings, profile_name="production")
    result = source()
    assert result.get("agent33_mode") == "standard"
    assert result.get("bm25_warmup_enabled") is True


def test_profile_source_enterprise_returns_enterprise_mode() -> None:
    from agent33.config import Settings

    source = ProfileSettingsSource(Settings, profile_name="enterprise")
    result = source()
    assert result.get("agent33_mode") == "enterprise"


def test_profile_source_airgapped_sets_local_ollama_url() -> None:
    from agent33.config import Settings

    source = ProfileSettingsSource(Settings, profile_name="airgapped")
    result = source()
    assert "localhost" in result.get("ollama_base_url", "")


# ---------------------------------------------------------------------------
# Settings integration tests — profile wired via settings_customise_sources
# ---------------------------------------------------------------------------


def test_settings_developer_profile_sets_lite_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENT33_PROFILE=developer → Settings picks up lite mode from profile."""
    monkeypatch.setenv("AGENT33_PROFILE", "developer")
    # Provide environment=test so JWT default is accepted without SystemExit
    monkeypatch.setenv("ENVIRONMENT", "test")
    # Clear any AGENT33_MODE override from the environment
    monkeypatch.delenv("AGENT33_MODE", raising=False)

    from agent33.config import Settings

    s = Settings()
    assert s.agent33_mode == "lite"
    assert s.bm25_warmup_enabled is False


def test_settings_production_profile_sets_standard_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENT33_PROFILE=production → Settings picks up standard mode from profile."""
    monkeypatch.setenv("AGENT33_PROFILE", "production")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("AGENT33_MODE", raising=False)

    from agent33.config import Settings

    s = Settings()
    assert s.agent33_mode == "standard"
    assert s.bm25_warmup_enabled is True


def test_settings_enterprise_profile_sets_enterprise_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENT33_PROFILE=enterprise → Settings picks up enterprise mode from profile."""
    monkeypatch.setenv("AGENT33_PROFILE", "enterprise")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("AGENT33_MODE", raising=False)

    from agent33.config import Settings

    s = Settings()
    assert s.agent33_mode == "enterprise"


def test_env_var_overrides_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENT33_MODE=enterprise env var wins over developer profile's lite default."""
    monkeypatch.setenv("AGENT33_PROFILE", "developer")
    monkeypatch.setenv("AGENT33_MODE", "enterprise")
    monkeypatch.setenv("ENVIRONMENT", "test")

    from agent33.config import Settings

    s = Settings()
    # The explicit env var AGENT33_MODE=enterprise takes priority over the profile
    assert s.agent33_mode == "enterprise"


def test_unknown_profile_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown AGENT33_PROFILE name is silently ignored; Settings loads normally."""
    monkeypatch.setenv("AGENT33_PROFILE", "totally_unknown_profile")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("AGENT33_MODE", raising=False)

    from agent33.config import Settings

    s = Settings()
    # Falls back to the field default
    assert s.agent33_mode == "standard"
