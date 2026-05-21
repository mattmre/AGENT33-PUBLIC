"""AES-256-GCM encryption utilities."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_BYTES = 12
_KEY_BYTES = 32  # 256-bit


def generate_key() -> bytes:
    """Generate a random 256-bit encryption key."""
    return AESGCM.generate_key(_KEY_BYTES * 8)


def encrypt(plaintext: str, key: bytes) -> str:
    """Encrypt *plaintext* with AES-256-GCM and return a base64-encoded token.

    The token layout is ``nonce || ciphertext+tag``, all base64-encoded.
    """
    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt(ciphertext: str, key: bytes) -> str:
    """Decrypt a base64-encoded token produced by :func:`encrypt`."""
    raw = base64.urlsafe_b64decode(ciphertext)
    nonce = raw[:_NONCE_BYTES]
    ct = raw[_NONCE_BYTES:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None).decode("utf-8")
