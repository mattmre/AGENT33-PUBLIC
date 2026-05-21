"""Tests for config_schema introspection module.

Covers:
- _classify_group prefix matching (hit, miss, first-match-wins)
- _type_label rendering for basic types, generics, SecretStr, unions
- introspect_settings_schema against the real Settings class
- ConfigFieldSchema and ConfigSchemaResponse model correctness
- Secret field masking in default values
- Edge cases: unknown annotation, fields without group prefix
"""

from __future__ import annotations

from typing import Union

from pydantic import SecretStr
from pydantic_settings import BaseSettings

from agent33.config import Settings
from agent33.config_schema import (
    ConfigFieldSchema,
    _classify_group,
    _type_label,
    introspect_settings_schema,
)

# ---------------------------------------------------------------------------
# Test _classify_group
# ---------------------------------------------------------------------------


class TestClassifyGroup:
    """Verify prefix-based group classification logic."""

    def test_known_prefix_returns_correct_group(self) -> None:
        """Each prefix in _PREFIX_GROUPS maps to its documented group."""
        assert _classify_group("database_url") == "database"
        assert _classify_group("redis_url") == "redis"
        assert _classify_group("nats_url") == "nats"
        assert _classify_group("jwt_secret") == "security"
        assert _classify_group("auth_bootstrap_enabled") == "security"
        assert _classify_group("openai_api_key") == "llm"
        assert _classify_group("elevenlabs_api_key") == "voice"
        assert _classify_group("embedding_dim") == "embeddings"
        assert _classify_group("rag_top_k") == "rag"
        assert _classify_group("chunk_tokens") == "rag"
        assert _classify_group("training_enabled") == "training"
        assert _classify_group("agent_definitions_dir") == "agents"
        assert _classify_group("plugin_definitions_dir") == "plugins"
        assert _classify_group("mcp_servers") == "mcp"
        assert _classify_group("jupyter_kernel_enabled") == "execution"
        assert _classify_group("hooks_enabled") == "hooks"
        assert _classify_group("environment") == "general"

    def test_unknown_prefix_falls_back_to_general(self) -> None:
        """Fields not matching any prefix are classified as 'general'."""
        assert _classify_group("totally_unknown_field_xyz") == "general"
        assert _classify_group("") == "general"
        assert _classify_group("provenance_enabled") == "general"

    def test_first_matching_prefix_wins(self) -> None:
        """When multiple prefixes could match, the first one in _PREFIX_GROUPS wins.

        For example, 'api_secret_key' starts with 'api_secret' (security) and
        also 'api_' (api). Since 'api_secret' appears first in _PREFIX_GROUPS,
        the result should be 'security'.
        """
        assert _classify_group("api_secret_key") == "security"
        # Whereas a plain api_ field that does NOT start with api_secret should
        # go to the 'api' group.
        assert _classify_group("api_port") == "api"

    def test_operator_session_maps_to_sessions(self) -> None:
        """The operator_session_ prefix maps to 'sessions', not 'orchestration'."""
        assert _classify_group("operator_session_enabled") == "sessions"

    def test_script_hooks_maps_to_hooks(self) -> None:
        """The script_hooks_ prefix maps to 'hooks'."""
        assert _classify_group("script_hooks_enabled") == "hooks"


# ---------------------------------------------------------------------------
# Test _type_label
# ---------------------------------------------------------------------------


class TestTypeLabel:
    """Verify human-readable type label rendering."""

    def test_basic_types(self) -> None:
        assert _type_label(str) == "str"
        assert _type_label(int) == "int"
        assert _type_label(float) == "float"
        assert _type_label(bool) == "bool"

    def test_secret_str(self) -> None:
        assert _type_label(SecretStr) == "SecretStr"

    def test_none_annotation_returns_unknown(self) -> None:
        assert _type_label(None) == "unknown"

    def test_generic_dict(self) -> None:
        label = _type_label(dict[str, int])
        assert "str" in label
        assert "int" in label
        assert "dict" in label

    def test_generic_list(self) -> None:
        label = _type_label(list[str])
        assert "str" in label
        assert "list" in label

    def test_optional_type(self) -> None:
        """Union[str, None] -- both parts should appear in the label."""
        label = _type_label(Union[str, None])  # noqa: UP007
        assert "str" in label
        assert "None" in label.lower() or "none" in label.lower()

    def test_union_type(self) -> None:
        label = _type_label(Union[str, int])  # noqa: UP007
        assert "str" in label
        assert "int" in label


# ---------------------------------------------------------------------------
# Test introspect_settings_schema with real Settings
# ---------------------------------------------------------------------------


class TestIntrospectRealSettings:
    """Introspect the real Settings class and verify structural properties."""

    def test_total_fields_matches_model_fields_count(self) -> None:
        """total_fields should equal the number of fields on Settings."""
        schema = introspect_settings_schema(Settings)
        expected_count = len(Settings.model_fields)
        assert schema.total_fields == expected_count, (
            f"total_fields={schema.total_fields} but Settings has {expected_count} model_fields"
        )

    def test_every_settings_field_appears_in_some_group(self) -> None:
        """Every field in Settings.model_fields must appear in exactly one group."""
        schema = introspect_settings_schema(Settings)
        all_field_names = set()
        for fields in schema.groups.values():
            for f in fields:
                assert f.name not in all_field_names, f"Duplicate field: {f.name}"
                all_field_names.add(f.name)
        expected_names = set(Settings.model_fields.keys())
        assert all_field_names == expected_names

    def test_secret_fields_are_masked(self) -> None:
        """SecretStr fields must have is_secret=True and default='***'."""
        schema = introspect_settings_schema(Settings)
        secret_field_names = {
            name for name, info in Settings.model_fields.items() if info.annotation is SecretStr
        }
        # There are at least a few SecretStr fields in Settings
        assert len(secret_field_names) >= 3, "Expected at least 3 SecretStr fields in Settings"
        for fields in schema.groups.values():
            for f in fields:
                if f.name in secret_field_names:
                    assert f.is_secret is True, f"{f.name} should be is_secret=True"
                    assert f.default == "***", (
                        f"{f.name} default should be '***', got {f.default!r}"
                    )
                    assert f.type == "SecretStr", (
                        f"{f.name} type should be 'SecretStr', got {f.type!r}"
                    )

    def test_env_var_is_uppercase_field_name(self) -> None:
        """env_var for each field should be the uppercased field name."""
        schema = introspect_settings_schema(Settings)
        for fields in schema.groups.values():
            for f in fields:
                assert f.env_var == f.name.upper(), (
                    f"env_var for {f.name} should be {f.name.upper()!r}, got {f.env_var!r}"
                )

    def test_known_field_has_expected_default(self) -> None:
        """Spot-check a few well-known fields for correct default extraction."""
        schema = introspect_settings_schema(Settings)
        field_map: dict[str, ConfigFieldSchema] = {}
        for fields in schema.groups.values():
            for f in fields:
                field_map[f.name] = f

        # api_port should default to 8000
        assert field_map["api_port"].default == 8000
        assert field_map["api_port"].type == "int"
        assert field_map["api_port"].group == "api"

        # rag_top_k should default to 5
        assert field_map["rag_top_k"].default == 5
        assert field_map["rag_top_k"].group == "rag"

        # environment should default to "development"
        assert field_map["environment"].default == "development"
        assert field_map["environment"].group == "general"

        # hooks_enabled should default to True
        assert field_map["hooks_enabled"].default is True
        assert field_map["hooks_enabled"].group == "hooks"


# ---------------------------------------------------------------------------
# Test introspect_settings_schema with a synthetic BaseSettings subclass
# ---------------------------------------------------------------------------


class TestIntrospectSyntheticSettings:
    """Use a small synthetic Settings class to test edge cases precisely."""

    def test_field_with_no_matching_prefix_goes_to_general(self) -> None:
        """A field name that matches no _PREFIX_GROUPS entry goes to 'general'."""

        class TinySettings(BaseSettings):
            model_config = {"env_prefix": "", "extra": "ignore"}
            zebra_mode: bool = False

        schema = introspect_settings_schema(TinySettings)
        assert "general" in schema.groups
        assert len(schema.groups["general"]) == 1
        assert schema.groups["general"][0].name == "zebra_mode"
        assert schema.groups["general"][0].group == "general"
        assert schema.total_fields == 1

    def test_non_secret_field_default_not_masked(self) -> None:
        """Non-SecretStr fields should expose their default value directly."""

        class TinySettings(BaseSettings):
            model_config = {"env_prefix": "", "extra": "ignore"}
            database_pool: int = 42

        schema = introspect_settings_schema(TinySettings)
        field = schema.groups["database"][0]
        assert field.default == 42
        assert field.is_secret is False

    def test_field_with_none_default_has_null_default(self) -> None:
        """A field whose default is None should produce default=None in schema."""

        class TinySettings(BaseSettings):
            model_config = {"env_prefix": "", "extra": "ignore"}
            redis_extra: str | None = None

        schema = introspect_settings_schema(TinySettings)
        field = schema.groups["redis"][0]
        assert field.default is None

    def test_groups_dict_structure(self) -> None:
        """ConfigSchemaResponse.groups should be a dict mapping str to list."""

        class TinySettings(BaseSettings):
            model_config = {"env_prefix": "", "extra": "ignore"}
            database_host: str = "localhost"
            redis_port: int = 6379
            mystery_flag: bool = True

        schema = introspect_settings_schema(TinySettings)
        assert isinstance(schema.groups, dict)
        assert "database" in schema.groups
        assert "redis" in schema.groups
        assert "general" in schema.groups
        assert schema.total_fields == 3
