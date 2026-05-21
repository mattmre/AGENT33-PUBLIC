"""Prompt injection detection and defence."""

from __future__ import annotations

import base64
import codecs
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Scan result
# ---------------------------------------------------------------------------


@dataclass
class ScanResult:
    """Outcome of a prompt-injection scan."""

    is_safe: bool
    threats: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

_OVERRIDE_VERBS = r"(previous|prior|above)\s+(instructions|prompts|directives)"
_SYSTEM_OVERRIDE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(rf"ignore\s+(all\s+)?{_OVERRIDE_VERBS}", re.I),
    re.compile(rf"disregard\s+(all\s+)?{_OVERRIDE_VERBS}", re.I),
    re.compile(rf"forget\s+(all\s+)?{_OVERRIDE_VERBS}", re.I),
    re.compile(r"you\s+are\s+now\s+(?:a|an|the)\s+", re.I),
    re.compile(r"new\s+system\s+prompt", re.I),
    re.compile(r"override\s+system\s+(prompt|message|instructions)", re.I),
]

_DELIMITER_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"```\s*system", re.I),
    re.compile(r"\[SYSTEM\]", re.I),
    re.compile(r"<\|?(system|im_start|endoftext)\|?>", re.I),
    re.compile(r"###\s*(system|instruction)", re.I),
    re.compile(r"<\s*/?system\s*>", re.I),
]

_INSTRUCTION_OVERRIDE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"do\s+not\s+follow\s+(your|the)\s+(original|initial)", re.I),
    re.compile(r"instead\s*,?\s+follow\s+these\s+instructions", re.I),
    re.compile(r"act\s+as\s+if\s+you\s+have\s+no\s+(restrictions|rules|guidelines)", re.I),
    re.compile(r"pretend\s+(that\s+)?you\s+(are|have)\s+no\s+(rules|restrictions)", re.I),
    re.compile(r"reveal\s+(your|the)\s+(system|initial|original)\s+(prompt|instructions)", re.I),
]

_UNICODE_ESCAPE_RE = re.compile(r"(?:\\u[0-9a-fA-F]{4}){4,}")
_HEX_ENCODED_RE = re.compile(r"\b(?:[0-9a-fA-F]{2}){16,}\b")


def _contains_known_injection(text: str) -> bool:
    for pat in (
        _SYSTEM_OVERRIDE_PATTERNS + _DELIMITER_INJECTION_PATTERNS + _INSTRUCTION_OVERRIDE_PATTERNS
    ):
        if pat.search(text):
            return True
    return False


def _check_encoded_payloads(text: str) -> list[str]:
    """Attempt to detect encoded injection payloads."""
    threats: list[str] = []
    b64_re = re.compile(r"(?:[A-Za-z0-9+/]{4}){10,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?")
    for match in b64_re.finditer(text):
        try:
            decoded = base64.b64decode(
                match.group(),
                validate=True,
            ).decode("utf-8", errors="ignore")
            if _contains_known_injection(decoded):
                threats.append("encoded_payload: hidden injection in encoded segment")
                return threats
        except Exception:
            continue

    for match in _UNICODE_ESCAPE_RE.finditer(text):
        try:
            decoded = codecs.decode(match.group(), "unicode_escape")
            if _contains_known_injection(decoded):
                threats.append("encoded_payload: hidden injection in encoded segment")
                return threats
        except Exception:
            continue

    for match in _HEX_ENCODED_RE.finditer(text):
        try:
            decoded = bytes.fromhex(match.group()).decode("utf-8", errors="ignore")
            if _contains_known_injection(decoded):
                threats.append("encoded_payload: hidden injection in encoded segment")
                return threats
        except Exception:
            continue

    return threats


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan_input(text: str) -> ScanResult:
    """Scan *text* for prompt-injection attempts.

    Returns a :class:`ScanResult` with ``is_safe=True`` when no threats are
    detected.
    """
    threats: list[str] = []

    for pat in _SYSTEM_OVERRIDE_PATTERNS:
        if pat.search(text):
            threats.append("system_prompt_override")
            break

    for pat in _DELIMITER_INJECTION_PATTERNS:
        if pat.search(text):
            threats.append("delimiter_injection")
            break

    for pat in _INSTRUCTION_OVERRIDE_PATTERNS:
        if pat.search(text):
            threats.append("instruction_override")
            break

    threats.extend(_check_encoded_payloads(text))

    return ScanResult(is_safe=len(threats) == 0, threats=threats)


def scan_inputs_recursive(data: object) -> ScanResult:
    """Recursively scan all string values in a nested structure.

    Walks dicts, lists, and raw strings to catch injection payloads
    buried in nested input structures.
    """
    if isinstance(data, str):
        return scan_input(data)
    if isinstance(data, dict):
        for value in data.values():
            result = scan_inputs_recursive(value)
            if not result.is_safe:
                return result
    elif isinstance(data, list):
        for item in data:
            result = scan_inputs_recursive(item)
            if not result.is_safe:
                return result
    return ScanResult(is_safe=True)
