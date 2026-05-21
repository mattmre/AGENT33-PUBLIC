"""Canonical argument hashing for approval-token argument tampering prevention."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_arg_hash(tool_name: str, arguments: dict[str, Any]) -> str:
    """Produce a deterministic SHA-256 hash of tool arguments.

    Normalization rules:
    1. Sort keys recursively (via ``sort_keys=True``)
    2. Serialize with ``json.dumps(separators=(',', ':'), sort_keys=True)``
    3. Prepend *tool_name* as namespace
    4. SHA-256 the UTF-8 bytes

    Returns a string of the form ``sha256:<hex>``.
    """
    normalized = json.dumps(arguments, separators=(",", ":"), sort_keys=True)
    payload = f"{tool_name}:{normalized}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
