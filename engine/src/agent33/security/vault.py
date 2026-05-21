"""In-memory credential vault with encryption at rest."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from agent33.security.encryption import decrypt, encrypt, generate_key

logger = logging.getLogger(__name__)


@dataclass
class _Entry:
    encrypted_value: str
    metadata: dict[str, Any]


class CredentialVault:
    """In-memory credential store that encrypts values at rest.

    Values are encrypted using AES-256-GCM.  Plain-text values are
    **never** written to logs.
    """

    def __init__(self, key: bytes | None = None) -> None:
        self._key: bytes = key or generate_key()
        self._store: dict[str, _Entry] = {}

    def store(self, key: str, value: str, metadata: dict[str, Any] | None = None) -> None:
        """Store a credential.  *value* is encrypted before being kept in memory."""
        encrypted = encrypt(value, self._key)
        self._store[key] = _Entry(encrypted_value=encrypted, metadata=metadata or {})
        logger.info("credential_stored key=%s", key)

    def retrieve(self, key: str) -> str:
        """Return the decrypted value for *key*, or raise ``KeyError``."""
        entry = self._store[key]
        return decrypt(entry.encrypted_value, self._key)

    def delete(self, key: str) -> None:
        """Delete the credential identified by *key*."""
        del self._store[key]
        logger.info("credential_deleted key=%s", key)

    def list_keys(self) -> list[str]:
        """Return all stored credential keys (never values)."""
        return list(self._store.keys())
