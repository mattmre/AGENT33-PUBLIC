"""Tests for Phase 52: Secret Redaction in Logs & Tool Output."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from agent33.security.redaction import _mask_token, redact_secrets

# ---------------------------------------------------------------------------
# Smart masking
# ---------------------------------------------------------------------------


class TestMaskToken:
    """Verify _mask_token output for short and long tokens."""

    def test_short_token_fully_masked(self) -> None:
        assert _mask_token("abc123") == "***"

    def test_boundary_token_17_chars_masked(self) -> None:
        # 17 chars -> still < 18 -> full mask
        assert _mask_token("a" * 17) == "***"

    def test_long_token_preserves_prefix_suffix(self) -> None:
        token = "sk-abcdefghijklmnopqrst"  # 24 chars
        result = _mask_token(token)
        assert result.startswith("sk-abc")
        assert result.endswith("qrst")
        assert "..." in result

    def test_exactly_18_chars_shows_prefix_suffix(self) -> None:
        token = "123456789012345678"
        result = _mask_token(token)
        assert result == "123456...5678"


# ---------------------------------------------------------------------------
# API key prefixes
# ---------------------------------------------------------------------------


class TestAPIKeyPatterns:
    """Each known key format is properly detected and redacted."""

    def test_openai_key(self) -> None:
        text = "export OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz1234567890"
        result = redact_secrets(text)
        assert "sk-abc" not in result or "..." in result
        assert "abcdefghijklmnopqrstuvwxyz1234567890" not in result

    def test_github_token(self) -> None:
        token = "ghp_" + "a" * 36
        text = f"git clone https://user:{token}@github.com/repo"
        result = redact_secrets(text)
        assert token not in result

    def test_github_pat(self) -> None:
        token = "github_pat_" + "a" * 80
        text = f"Authorization: Bearer {token}"
        result = redact_secrets(text)
        assert token not in result

    def test_slack_token(self) -> None:
        token = "xoxb-1234567890-abcdefghij"
        text = f"SLACK_TOKEN={token}"
        result = redact_secrets(text)
        assert token not in result

    def test_google_api_key(self) -> None:
        token = "AIza" + "x" * 35
        text = f"key={token}"
        result = redact_secrets(text)
        assert token not in result

    def test_perplexity_key(self) -> None:
        token = "pplx-" + "a" * 48
        text = f"PERPLEXITY_API_KEY={token}"
        result = redact_secrets(text)
        assert token not in result

    def test_huggingface_token(self) -> None:
        token = "hf_" + "a" * 34
        text = f"HF_TOKEN={token}"
        result = redact_secrets(text)
        assert token not in result

    def test_replicate_token(self) -> None:
        token = "r8_" + "a" * 20
        text = f"REPLICATE_API_TOKEN={token}"
        result = redact_secrets(text)
        assert token not in result

    def test_npm_token(self) -> None:
        token = "npm_" + "a" * 36
        text = f"//registry.npmjs.org/:_authToken={token}"
        result = redact_secrets(text)
        assert token not in result

    def test_pypi_token(self) -> None:
        token = "pypi-" + "a" * 100
        text = f"password = {token}"
        result = redact_secrets(text)
        assert token not in result

    def test_sendgrid_key(self) -> None:
        token = "SG." + "a" * 22 + "." + "b" * 43
        text = f"SENDGRID_API_KEY={token}"
        result = redact_secrets(text)
        assert token not in result

    def test_aws_access_key(self) -> None:
        token = "AKIA" + "A" * 16
        text = f"aws_access_key_id = {token}"
        result = redact_secrets(text)
        assert token not in result

    def test_stripe_live_key(self) -> None:
        token = "sk_live_" + "a" * 24
        text = f"STRIPE_SECRET_KEY={token}"
        result = redact_secrets(text)
        assert token not in result

    def test_stripe_test_key(self) -> None:
        token = "sk_test_" + "a" * 24
        text = f"stripe.api_key = '{token}'"
        result = redact_secrets(text)
        assert token not in result

    def test_digitalocean_token(self) -> None:
        token = "dop_v1_" + "a" * 64
        text = f"DIGITALOCEAN_TOKEN={token}"
        result = redact_secrets(text)
        assert token not in result


# ---------------------------------------------------------------------------
# Structured secret patterns
# ---------------------------------------------------------------------------


class TestStructuredSecretPatterns:
    """ENV assignments, JSON fields, auth headers, private keys, DB URIs."""

    def test_env_assignment_api_key(self) -> None:
        text = "API_KEY=mysecretvalue123"
        result = redact_secrets(text)
        assert "API_KEY=***" in result
        assert "mysecretvalue123" not in result

    def test_env_assignment_password(self) -> None:
        text = "PASSWORD=hunter2"
        result = redact_secrets(text)
        assert "PASSWORD=***" in result
        assert "hunter2" not in result

    def test_env_assignment_secret(self) -> None:
        text = "SECRET = my-very-secret-value"
        result = redact_secrets(text)
        assert "my-very-secret-value" not in result

    def test_env_assignment_token(self) -> None:
        text = "TOKEN=tok_abc123def456"
        result = redact_secrets(text)
        assert "tok_abc123def456" not in result

    def test_env_assignment_credential(self) -> None:
        text = "CREDENTIAL=cred-xyz"
        result = redact_secrets(text)
        assert "cred-xyz" not in result

    def test_json_secret_api_key(self) -> None:
        text = '{"apiKey": "my-secret-api-key-1234567890"}'
        result = redact_secrets(text)
        assert "my-secret-api-key-1234567890" not in result
        # JSON structure preserved
        assert '"apiKey"' in result

    def test_json_secret_password(self) -> None:
        text = '{"password": "hunter2"}'
        result = redact_secrets(text)
        assert "hunter2" not in result

    def test_json_secret_token(self) -> None:
        text = '{"token": "tok_abcdef1234567890xyz"}'
        result = redact_secrets(text)
        assert "tok_abcdef1234567890xyz" not in result

    def test_cli_secret_flag_space_delimited(self) -> None:
        token = "sk-ant-" + "a" * 30
        text = f"python worker.py --api-key {token}"
        result = redact_secrets(text)
        assert token not in result
        assert "--api-key " in result

    def test_cli_secret_flag_equals_delimited(self) -> None:
        password = "example" + "-placeholder-" + "value-12345"
        text = f"python worker.py --password={password}"
        result = redact_secrets(text)
        assert password not in result
        assert "--password=" in result

    def test_cli_secret_flag_preserves_quotes(self) -> None:
        text = 'python worker.py --token "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"'
        result = redact_secrets(text)
        assert "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in result
        assert '--token "' in result

    def test_auth_header_bearer(self) -> None:
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature"
        result = redact_secrets(text)
        assert "eyJhbGciOiJIUzI1NiJ9" not in result
        assert "Authorization: Bearer ***" in result

    def test_auth_header_basic(self) -> None:
        text = "Authorization: Basic dXNlcjpwYXNz"
        result = redact_secrets(text)
        assert "dXNlcjpwYXNz" not in result
        assert "Authorization: Basic ***" in result

    def test_auth_header_token(self) -> None:
        text = "Authorization: Token ghp_abcdefghijklmnopqrstuvwxyz0123456789"
        result = redact_secrets(text)
        # The token after "Token " should be masked
        assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in result

    def test_private_key_rsa(self) -> None:
        text = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEA0Z3VS5JJcds...\n"
            "-----END RSA PRIVATE KEY-----"
        )
        result = redact_secrets(text)
        assert "MIIEpAIBAAKCAQEA0Z3VS5JJcds" not in result
        assert "[PRIVATE_KEY_REDACTED]" in result

    def test_private_key_ec(self) -> None:
        text = "-----BEGIN EC PRIVATE KEY-----\nMHQCAQEEIBkg...\n-----END EC PRIVATE KEY-----"
        result = redact_secrets(text)
        assert "[PRIVATE_KEY_REDACTED]" in result

    def test_private_key_openssh(self) -> None:
        text = (
            "-----BEGIN OPENSSH PRIVATE KEY-----\n"
            "b3BlbnNzaC1rZXktdjEAAAAACmFlczI1Ni1jdHI=\n"
            "-----END OPENSSH PRIVATE KEY-----"
        )
        result = redact_secrets(text)
        assert "[PRIVATE_KEY_REDACTED]" in result

    def test_private_key_generic(self) -> None:
        text = "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBg...\n-----END PRIVATE KEY-----"
        result = redact_secrets(text)
        assert "[PRIVATE_KEY_REDACTED]" in result


# ---------------------------------------------------------------------------
# Database connection strings
# ---------------------------------------------------------------------------


class TestDatabaseURIRedaction:
    """Database URI passwords are masked while preserving structure."""

    def test_postgresql_uri(self) -> None:
        text = "DATABASE_URL=postgresql://admin:s3cretP4ss@db.example.com:5432/mydb"
        result = redact_secrets(text)
        assert "s3cretP4ss" not in result
        assert "admin:" in result
        assert "@db.example.com" in result

    def test_postgres_asyncpg_uri(self) -> None:
        text = "postgresql+asyncpg://user:password123@localhost:5432/app"
        result = redact_secrets(text)
        assert "password123" not in result
        assert "user:" in result
        assert "@localhost" in result

    def test_mysql_uri(self) -> None:
        text = "mysql://root:my-pass@mysql-host:3306/db"
        result = redact_secrets(text)
        assert "my-pass" not in result
        assert "@mysql-host" in result

    def test_mongodb_uri(self) -> None:
        text = "mongodb://admin:MongoP4ss!@cluster.mongodb.net/db"
        result = redact_secrets(text)
        assert "MongoP4ss!" not in result
        assert "@cluster.mongodb.net" in result

    def test_redis_uri(self) -> None:
        text = "redis://default:redispass@redis.internal:6379/0"
        result = redact_secrets(text)
        assert "redispass" not in result
        assert "@redis.internal" in result


# ---------------------------------------------------------------------------
# Disabled / edge cases
# ---------------------------------------------------------------------------


class TestDisabledAndEdgeCases:
    """Setting enabled=False bypasses redaction; edge cases handled safely."""

    def test_disabled_bypasses_redaction(self) -> None:
        secret = "sk-" + "a" * 30
        text = f"key={secret}"
        result = redact_secrets(text, enabled=False)
        assert result == text
        assert secret in result

    def test_empty_string_passthrough(self) -> None:
        assert redact_secrets("") == ""
        assert redact_secrets("", enabled=False) == ""

    def test_none_like_empty_passthrough(self) -> None:
        # redact_secrets expects str, but should handle empty gracefully
        assert redact_secrets("") == ""

    def test_non_matching_text_unchanged(self) -> None:
        text = "Hello world, this is a normal log message with no secrets."
        assert redact_secrets(text) == text

    def test_multiple_secrets_in_one_string(self) -> None:
        openai = "sk-" + "a" * 30
        aws = "AKIA" + "B" * 16
        text = f"openai={openai} and aws={aws}"
        result = redact_secrets(text)
        assert openai not in result
        assert aws not in result

    def test_multiline_with_private_key_and_token(self) -> None:
        text = (
            "Config:\n"
            "API_KEY=my-api-key\n"
            "-----BEGIN PRIVATE KEY-----\n"
            "MIIEvgIBADANBg...\n"
            "-----END PRIVATE KEY-----\n"
            "Done.\n"
        )
        result = redact_secrets(text)
        assert "my-api-key" not in result
        assert "[PRIVATE_KEY_REDACTED]" in result
        assert "Config:" in result
        assert "Done." in result


# ---------------------------------------------------------------------------
# Structlog processor integration
# ---------------------------------------------------------------------------


class TestStructlogProcessor:
    """The secret_redaction_processor works correctly in a structlog chain."""

    def test_processor_redacts_string_values(self) -> None:
        from agent33.observability.logging import secret_redaction_processor

        event_dict: dict[str, Any] = {
            "event": "User provided API_KEY=secret123",
            "level": "info",
            "count": 42,
        }
        with patch("agent33.config.settings") as mock_settings:
            mock_settings.redact_secrets_enabled = True
            result = secret_redaction_processor(None, "info", event_dict)

        assert "secret123" not in result["event"]
        # Non-string values pass through unchanged
        assert result["count"] == 42
        assert result["level"] == "info"

    def test_processor_disabled_passes_through(self) -> None:
        from agent33.observability.logging import secret_redaction_processor

        event_dict: dict[str, Any] = {
            "event": "API_KEY=secret123",
        }
        with patch("agent33.config.settings") as mock_settings:
            mock_settings.redact_secrets_enabled = False
            result = secret_redaction_processor(None, "info", event_dict)

        assert result["event"] == "API_KEY=secret123"

    def test_processor_handles_non_string_values(self) -> None:
        from agent33.observability.logging import secret_redaction_processor

        event_dict: dict[str, Any] = {
            "event": "normal message",
            "count": 10,
            "flag": True,
            "data": None,
        }
        with patch("agent33.config.settings") as mock_settings:
            mock_settings.redact_secrets_enabled = True
            result = secret_redaction_processor(None, "info", event_dict)

        assert result["count"] == 10
        assert result["flag"] is True
        assert result["data"] is None

    def test_processor_redacts_openai_key_in_event(self) -> None:
        from agent33.observability.logging import secret_redaction_processor

        token = "sk-" + "x" * 40
        event_dict: dict[str, Any] = {
            "event": f"LLM call with key {token}",
        }
        with patch("agent33.config.settings") as mock_settings:
            mock_settings.redact_secrets_enabled = True
            result = secret_redaction_processor(None, "info", event_dict)

        assert token not in result["event"]
        assert "..." in result["event"]


# ---------------------------------------------------------------------------
# Config integration
# ---------------------------------------------------------------------------


class TestConfigIntegration:
    """The config setting controls redaction behavior."""

    def test_config_default_enabled(self) -> None:
        """Default config has redaction enabled."""
        from agent33.config import Settings

        s = Settings(environment="test")
        assert s.redact_secrets_enabled is True

    def test_config_can_be_disabled(self) -> None:
        from agent33.config import Settings

        s = Settings(environment="test", redact_secrets_enabled=False)
        assert s.redact_secrets_enabled is False


# ---------------------------------------------------------------------------
# Regression: patterns should not false-positive on normal text
# ---------------------------------------------------------------------------


class TestFalsePositiveResistance:
    """Normal text should not be incorrectly redacted."""

    def test_normal_code_unchanged(self) -> None:
        text = "result = sklearn.fit(X_train, y_train)"
        assert redact_secrets(text) == text

    def test_url_without_password_unchanged(self) -> None:
        text = "https://example.com/api/v1/users"
        assert redact_secrets(text) == text

    def test_short_sk_prefix_not_matched(self) -> None:
        # "sk-" followed by < 20 chars should not match OpenAI pattern
        text = "sk-short"
        assert redact_secrets(text) == text

    def test_non_secret_cli_flag_unchanged(self) -> None:
        text = "python worker.py --tokenizer qwen"
        assert redact_secrets(text) == text

    def test_normal_json_field_unchanged(self) -> None:
        text = '{"name": "John", "age": 30}'
        assert redact_secrets(text) == text

    def test_similar_but_non_secret_env_var(self) -> None:
        # "PATH" doesn't match any of the secret keywords
        text = "PATH=/usr/local/bin:/usr/bin"
        assert redact_secrets(text) == text

    @pytest.mark.parametrize(
        "text",
        [
            "LOG_LEVEL=debug",
            "HOST=localhost",
            "PORT=8080",
            "DB_NAME=myapp",
        ],
    )
    def test_non_secret_env_vars_unchanged(self, text: str) -> None:
        assert redact_secrets(text) == text
