"""Secret redaction for log output and tool results.

Phase 52: Detects and masks secrets, API keys, tokens, private keys,
database URIs, and other sensitive values in arbitrary text.  Compiled
patterns are reused across calls for performance.
"""

from __future__ import annotations

import re
from typing import Final

# ---------------------------------------------------------------------------
# Pattern catalogue
# ---------------------------------------------------------------------------
# Each entry is (label, compiled regex).  Patterns are applied in order;
# earlier matches take precedence when ranges overlap because the result
# string is mutated in-place.

_PATTERNS: Final[list[tuple[str, re.Pattern[str]]]] = [
    # --- Well-known API-key prefixes ---
    ("openai_key", re.compile(r"\b(sk-[a-zA-Z0-9]{20,})\b")),
    ("github_token", re.compile(r"\b(ghp_[a-zA-Z0-9]{36})\b")),
    ("github_pat", re.compile(r"\b(github_pat_[a-zA-Z0-9_]{80,})\b")),
    ("slack_token", re.compile(r"\b(xox[baprs]-[a-zA-Z0-9\-]{10,})\b")),
    ("google_api", re.compile(r"\b(AIza[a-zA-Z0-9_\-]{35})\b")),
    ("perplexity_key", re.compile(r"\b(pplx-[a-zA-Z0-9]{48,})\b")),
    ("hf_token", re.compile(r"\b(hf_[a-zA-Z0-9]{34,})\b")),
    ("replicate_token", re.compile(r"\b(r8_[a-zA-Z0-9]{20,})\b")),
    ("npm_token", re.compile(r"\b(npm_[a-zA-Z0-9]{36})\b")),
    ("pypi_token", re.compile(r"\b(pypi-[a-zA-Z0-9]{100,})\b")),
    ("sendgrid_key", re.compile(r"\b(SG\.[a-zA-Z0-9_\-]{22}\.[a-zA-Z0-9_\-]{43})\b")),
    ("aws_key", re.compile(r"\b(AKIA[A-Z0-9]{16})\b")),
    ("stripe_key", re.compile(r"\b(sk_(?:live|test)_[a-zA-Z0-9]{24,})\b")),
    ("digitalocean", re.compile(r"\b(dop_v1_[a-f0-9]{64})\b")),
    ("anthropic_key", re.compile(r"\b(sk-ant-[a-zA-Z0-9\-_]{20,})\b")),
    (
        "jwt_token",
        re.compile(r"\b(eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]+)\b"),
    ),
    (
        "azure_connection",
        re.compile(r"(DefaultEndpointsProtocol=https?;AccountName=[^;]+;AccountKey=[^;]+)"),
    ),
    # --- Structured secret assignments ---
    (
        "env_secret",
        re.compile(
            r"(?i)((?:API_KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)"
            r"\s*=\s*)\S+"
        ),
    ),
    (
        "json_secret",
        re.compile(
            r'(?i)"(?:apiKey|api_key|secret|token|password|credential)'
            r'"\s*:\s*"([^"]+)"'
        ),
    ),
    (
        "cli_secret_flag",
        re.compile(
            r"(?i)"
            r"((?:--?|/)(?:api[-_]?key|secret|token|password|credential)(?:\s+|=))"
            r"(?:"
            r'"([^"]+)"'
            r"|"
            r"'([^']+)'"
            r"|"
            r"([^\s]+)"
            r")"
        ),
    ),
    # --- Auth headers ---
    (
        "auth_header",
        re.compile(r"(?i)(Authorization:\s*(?:Bearer|Basic|Token)\s+)\S+"),
    ),
    # --- Private keys (multiline) ---
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
            r"[\s\S]*?"
            r"-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
        ),
    ),
    # --- Database connection strings (mask password segment) ---
    (
        "db_uri",
        re.compile(
            r"(?i)((?:postgres|postgresql|mysql|mongodb|redis)"
            r"(?:\+\w+)?://[^:]*:)"  # scheme://user:
            r"([^@]+)"  # password
            r"(@)"  # @ separator
        ),
    ),
]


def _mask_token(token: str) -> str:
    """Smart masking: short tokens -> full mask, longer -> prefix...suffix."""
    if len(token) < 18:
        return "***"
    return f"{token[:6]}...{token[-4:]}"


def redact_secrets(text: str, *, enabled: bool = True) -> str:
    """Apply all secret patterns to *text*, replacing matches with masks.

    When *enabled* is ``False`` the input is returned unchanged (useful for
    local development where you may want raw output).

    The function is intentionally pure: it takes a string and returns a
    string, so it can be used as a structlog processor value transformer
    or wrapped around tool output with zero coupling.
    """
    if not enabled or not text:
        return text

    result = text

    for name, pattern in _PATTERNS:
        if name == "private_key":
            # Replace entire PEM block.
            result = pattern.sub("[PRIVATE_KEY_REDACTED]", result)
        elif name == "db_uri":
            # Keep scheme://user: and @host, mask only the password.
            result = pattern.sub(r"\g<1>***\g<3>", result)
        elif name == "env_secret":
            # Preserve the key name and `=`, mask only the value.
            result = pattern.sub(lambda m: m.group(1) + "***", result)
        elif name == "json_secret":
            # Replace only the value inside the quotes.
            def _json_replacer(m: re.Match[str]) -> str:
                full = m.group(0)
                val = m.group(1)
                return full.replace(val, _mask_token(val))

            result = pattern.sub(_json_replacer, result)
        elif name == "cli_secret_flag":
            # Preserve the flag and quoting, redact only the value.
            def _cli_replacer(m: re.Match[str]) -> str:
                value = m.group(2) or m.group(3) or m.group(4) or ""
                quote = '"' if m.group(2) is not None else "'" if m.group(3) is not None else ""
                return f"{m.group(1)}{quote}{_mask_token(value)}{quote}"

            result = pattern.sub(_cli_replacer, result)
        elif name == "auth_header":
            # Preserve "Authorization: Bearer ", mask the token.
            result = pattern.sub(lambda m: m.group(1) + "***", result)
        else:
            # Standard token pattern: group(1) is the full token.
            result = pattern.sub(lambda m: _mask_token(m.group(1)), result)

    return result
