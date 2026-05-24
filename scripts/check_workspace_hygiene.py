#!/usr/bin/env python3
"""scripts/check_workspace_hygiene.py -- the PR-ready workspace hygiene
gate (issue #8 -- cluster G 1/3).

Walks --root with deterministic ordering and applies eight finding-kind
scanners (todo-debris, fixme-debris, stray-temp-file, oversized-binary,
secret-shaped-string, debug-print-leftover, broken-symlink,
misencoded-file). Emits one `hygiene_finding` row per finding followed
by a terminal `run_summary` row to the JSONL file named by
--report-out (default v3.5/out/workspace-hygiene-report.jsonl). Each row
carries an 8-hex CRC32 footer mirroring the bhs-trajectory.jsonl /
charter-merge-log.jsonl / endurance-run-report.jsonl contract, plus a
`crc32_prev` link forming a hash chain (first row's crc32_prev is
`00000000`).

Operator commands:

    # Scan + emit report (always exits 0/1/2/3/4/5 from the gate's
    # 5 exit-code classes; cap-breach is the validator's R73c concern):
    python v3.5/scripts/check_workspace_hygiene.py \\
        --root v3.5/ \\
        --report-out v3.5/out/workspace-hygiene-report.jsonl

    # Scan-only (prints findings; does not write a report):
    python v3.5/scripts/check_workspace_hygiene.py \\
        --root v3.5/ \\
        --report-out -

Exit codes (highest priority wins):
    0  scan completed; report written cleanly
    1  drift -- ALL findings reported, but the underlying scan completed
       (deferred-scope marker for future per-finding-class hard caps;
       reserved -- the gate currently only emits 0 OR a corruption code)
    2  schema invalid -- the config YAML did not validate against
       workspace-hygiene-config.schema.json
    3  enum unknown -- the config YAML referenced a finding-kind /
       severity-class not in the closed enums
    4  chain break -- the gate's own emit-time chain self-check
       detected a CRC32 chain inconsistency (should never happen
       absent a coding bug)
    5  corruption -- the scan tree contained a structural corruption
       the walker could not handle (control-byte filename, unresolvable
       symlink cycle, etc.)
"""

from __future__ import annotations

import argparse
import binascii
import fnmatch
import hashlib
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


_SCRIPT_DIR = Path(__file__).resolve().parent
_V35_ROOT = _SCRIPT_DIR.parent
_DEFAULT_CONFIG = _SCRIPT_DIR / "workspace_hygiene.config.yaml"
_DEFAULT_REPORT_OUT = _V35_ROOT / "out" / "workspace-hygiene-report.jsonl"
_DEFAULT_LANE_ID = "lane-workspace-hygiene-v35"
_DEFAULT_AGENT_SESSION_ID = "01HQ9X7P5K3J2NQHJZ4Y6HYGIENE0"
_SCHEMA_DIR = (
    _V35_ROOT / "_internal" / "conventions" / "brutal-honesty-kit" / "v3.5"
    / "schemas"
)
_ENUM_DIR = (
    _V35_ROOT / "_internal" / "conventions" / "brutal-honesty-kit" / "v3.5"
    / "enums"
)

# Module constants -- match the rule-prefixed naming pattern used by
# _R72_BUDGET_MS in run_endurance_benchmark and _R69_WINDOW_DEFAULT in
# validate_score_trajectory. Distinct from #52's HYGIENE_CAP (charter-
# level); no symbol collision.
_R73_HYGIENE_CAP = 90
_R73_SEVERITY_TOTAL_CLAMP = 999
_R73_BINARY_PEEK_BYTES = 8192
_R73_SNIPPET_MAX_LEN = 200

# Built-in unconditional walker exclusions (operator globs are layered
# on top via config.exclusion_globs).
_BUILTIN_EXCLUDED_DIR_NAMES = frozenset({
    ".git",
    "__pycache__",
    "_generated",
    "node_modules",
})

# Closed-set finding-kinds. Mirror enums/workspace-hygiene-finding-kinds.txt
# verbatim; drift FAILs validate_v33_schema_drift.py via
# validate_workspace_hygiene_finding_kinds_parity. Tokens are lowercase
# kebab-case to match the v3.5 enum house style (validate_v33_schema_drift.py
# enforces ^[a-z][a-z0-9-]*$).
FINDING_KINDS: tuple[str, ...] = (
    "todo-debris",
    "fixme-debris",
    "stray-temp-file",
    "oversized-binary",
    "secret-shaped-string",
    "debug-print-leftover",
    "broken-symlink",
    "misencoded-file",
)

# Closed-set severity classes. Mirror enums/workspace-hygiene-
# severity-classes.txt verbatim; drift FAILs validate_v33_schema_drift.py
# via validate_workspace_hygiene_severity_classes_parity. Tokens are
# lowercase kebab-case to match the v3.5 enum house style.
SEVERITY_CLASSES: tuple[str, ...] = ("info", "low", "medium", "high")

# Secret-shaped regex catalog. Each entry is (compiled_re, finding_label).
# The label is recorded as the snippet prefix so an operator can tell
# `aws-access-key` from `bearer-token` without re-running the gate.
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"), "aws-access-key"),
    (
        re.compile(
            r"(?i)aws_secret_access_key\s*=\s*[A-Za-z0-9/+=]{40}"
        ),
        "aws-secret-key",
    ),
    (
        re.compile(
            r"-----BEGIN (?:RSA|OPENSSH|DSA|EC|PGP) PRIVATE KEY-----"
        ),
        "private-key-block",
    ),
    (
        re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-+/]{20,}"),
        "bearer-token",
    ),
    (
        re.compile(r"(?i)password\s*=\s*['\"][^'\"]{8,}['\"]"),
        "password-literal",
    ),
]

# Allow-suffixes for files that legitimately CONTAIN secret-shaped
# strings (operator examples / test fixtures of secret patterns).
_SECRET_ALLOW_SUFFIXES = (".example", ".template")

# Exit-code classes -- highest priority wins. Mirrors the
# validate_lane_consistency.py exit-code priority pattern.
EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_SCHEMA = 2
EXIT_ENUM = 3
EXIT_CHAIN = 4
EXIT_CORRUPTION = 5
_EXIT_PRIORITY: tuple[int, ...] = (
    EXIT_CORRUPTION,
    EXIT_CHAIN,
    EXIT_ENUM,
    EXIT_SCHEMA,
    EXIT_DRIFT,
    EXIT_OK,
)


# ---------------------------------------------------------------------------
# CRC32 helpers (mirror run_endurance_benchmark / charter-merge-log).
# ---------------------------------------------------------------------------


def _serialize_for_crc(record: dict) -> bytes:
    """Mirror run_endurance_benchmark._serialize_for_crc verbatim.

    The serialization MUST be byte-stable across processes for the CRC
    footer to be reproducible. sort_keys + the (',', ':') separators
    are the canonical contract; the `crc32` field is excluded.
    """
    return json.dumps(
        {k: v for k, v in record.items() if k != "crc32"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_crc32(record: dict) -> str:
    """Mirror run_endurance_benchmark.compute_crc32 verbatim."""
    return (
        f"{binascii.crc32(_serialize_for_crc(record)) & 0xFFFFFFFF:08x}"
    )


# ---------------------------------------------------------------------------
# YAML config load (stdlib-only). Reuses validate_lane_consistency's
# strict-subset YAML parser via in-process import; falls back to a
# minimal builtin parser when the upstream module is not importable
# (back-compat for stripped-down checkouts).
# ---------------------------------------------------------------------------


def _import_simple_yaml_parser():
    """Try to reuse the in-house strict-subset YAML parser from
    validate_lane_consistency.py. Returns None when the module is not
    importable (tests can monkeypatch this).
    """
    import importlib.util

    target = _SCRIPT_DIR / "validate_lane_consistency.py"
    if not target.exists():
        return None
    spec = importlib.util.spec_from_file_location(
        "_bhs_hygiene_lane_consistency", target
    )
    if spec is None or spec.loader is None:
        return None
    module = type(sys)("_bhs_hygiene_lane_consistency")
    sys.modules["_bhs_hygiene_lane_consistency"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 -- defensive
        return None
    return getattr(module, "_parse_simple_yaml", None)


def _builtin_yaml(text: str) -> dict:
    """Minimal stdlib-only YAML subset parser. Supports:
        key: scalar
        key:           (then indented children)
            sub: scalar
        key:
            - listitem
            - listitem
        "string with spaces"

    Mirrors validate_lane_consistency._parse_simple_yaml's contract.
    """
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    return _yaml_block(lines, 0, 0)[0]


def _yaml_indent(line: str) -> int:
    i = 0
    while i < len(line) and line[i] == " ":
        i += 1
    return i


_YAML_DOUBLE_QUOTE_ESCAPES = {
    "\\": "\\",
    '"': '"',
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "0": "\0",
}


def _yaml_unescape_double_quoted(body: str) -> str:
    """Process the YAML double-quoted-string escape set used by the
    workspace_hygiene config. Limited to the subset actually appearing
    in shipped YAML: ``\\\\``, ``\\"``, ``\\n``, ``\\t``, ``\\r``,
    ``\\0``. Unknown escapes are passed through verbatim so the parser
    never silently mangles content. (Single-quoted YAML strings only
    escape the single quote via doubling -- handled separately by the
    caller.)
    """
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in _YAML_DOUBLE_QUOTE_ESCAPES:
                out.append(_YAML_DOUBLE_QUOTE_ESCAPES[nxt])
                i += 2
                continue
            # Unknown escape -- pass through verbatim.
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _yaml_scalar(raw: str) -> Any:
    s = raw.strip()
    if not s:
        return None
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    if s in ("null", "~"):
        return None
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        return _yaml_unescape_double_quoted(s[1:-1])
    if s.startswith("'") and s.endswith("'") and len(s) >= 2:
        # Single-quoted YAML: only `''` is an escape (for a literal `'`).
        return s[1:-1].replace("''", "'")
    if re.fullmatch(r"-?\d+", s):
        try:
            return int(s)
        except ValueError:
            return s
    if re.fullmatch(r"-?\d+\.\d+", s):
        try:
            return float(s)
        except ValueError:
            return s
    return s


def _yaml_block(
    lines: list[str], start: int, indent: int
) -> tuple[Any, int]:
    i = start
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s or s.startswith("#"):
            i += 1
            continue
        if _yaml_indent(ln) != indent:
            return {}, start
        if s.startswith("- "):
            return _yaml_list(lines, i, indent)
        return _yaml_map(lines, i, indent)
    return {}, i


def _yaml_list(
    lines: list[str], start: int, indent: int
) -> tuple[list, int]:
    out: list = []
    i = start
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s or s.startswith("#"):
            i += 1
            continue
        if _yaml_indent(ln) < indent:
            break
        if not s.startswith("- "):
            break
        out.append(_yaml_scalar(s[2:]))
        i += 1
    return out, i


def _yaml_map(
    lines: list[str], start: int, indent: int
) -> tuple[dict, int]:
    out: dict = {}
    i = start
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s or s.startswith("#"):
            i += 1
            continue
        cur = _yaml_indent(ln)
        if cur < indent:
            break
        if cur != indent:
            i += 1
            continue
        if ":" not in s:
            i += 1
            continue
        key, _, val = s.partition(":")
        key = key.strip()
        val_stripped = val.strip()
        if val_stripped == "":
            child, next_i = _yaml_block(lines, i + 1, indent + 2)
            out[key] = child
            i = next_i
        else:
            out[key] = _yaml_scalar(val_stripped)
            i += 1
    return out, i


def _coerce_numeric_strings(value: Any) -> Any:
    """Recursively coerce string scalars that look like numbers into
    int / float. The upstream `_parse_simple_yaml` in
    `validate_lane_consistency.py` does NOT coerce floats (only ints),
    so e.g. `secret_shaped_min_entropy: 3.5` comes back as the string
    "3.5" and downstream JSON-Schema validation fails on
    `'is not of type number'`. This pass fixes both that gap and any
    similar one in the upstream parser without touching upstream code.

    Strings already known to be non-numeric (alphabetic, regex, glob)
    are left untouched -- the int/float regexes are anchored.
    """
    if isinstance(value, dict):
        return {
            k: _coerce_numeric_strings(v) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_coerce_numeric_strings(v) for v in value]
    if isinstance(value, str):
        if re.fullmatch(r"-?\d+", value):
            try:
                return int(value)
            except ValueError:
                return value
        if re.fullmatch(r"-?\d+\.\d+", value):
            try:
                return float(value)
            except ValueError:
                return value
    return value


def _parse_yaml(text: str) -> dict:
    """Parse the workspace_hygiene config YAML.

    Prefers the in-house builtin parser because it correctly handles:
      * floats (`3.5` -> 3.5, not the string "3.5")
      * double-quoted-string escapes (`"py:print\\\\("` -> `py:print\\(`,
        not the literal `py:print\\\\(` two-backslash form which would
        compile into a regex that matches `print\\(` instead of
        `print(`).

    The upstream `_parse_simple_yaml` from
    `validate_lane_consistency.py` predates issue #8 and supports
    neither, so it is held in reserve as a fallback only when the
    builtin chokes on a future YAML extension. A numeric-coercion
    post-pass runs unconditionally so downstream JSON-Schema validation
    sees numbers as `number`, not `string`, regardless of which parser
    produced the dict.
    """
    parsed: dict | None = None
    try:
        parsed = _builtin_yaml(text)
    except Exception:  # noqa: BLE001 -- defensive
        parsed = None
    if parsed is None:
        upstream = _import_simple_yaml_parser()
        if upstream is not None:
            try:
                parsed = upstream(text)
            except Exception:  # noqa: BLE001 -- defensive
                parsed = None
    if parsed is None:
        return {}
    return _coerce_numeric_strings(parsed)


def _load_config(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return _parse_yaml(text)


def _compute_config_sha256(path: Path) -> str:
    """Full 64-hex SHA256 of the config bytes. R73a re-computes this and
    compares against the run_summary row's config_sha256 field.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_config_schema() -> dict | None:
    p = _SCHEMA_DIR / "workspace-hygiene-config.schema.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Walker.
# ---------------------------------------------------------------------------


def _is_excluded(rel_path: str, config_globs: list[str]) -> bool:
    """Apply config.exclusion_globs against a POSIX-relative path."""
    for pattern in config_globs:
        if fnmatch.fnmatch(rel_path, pattern):
            return True
    return False


def _walk_files(
    root: Path, config_globs: list[str]
) -> Iterator[Path]:
    """Deterministic walk: every level sorted; built-in directory
    blocklist applied unconditionally; operator globs applied on top.
    """
    root = root.resolve()
    for current_dir, dirnames, filenames in os.walk(root):
        # Sort in place so subsequent recursion is deterministic.
        dirnames.sort()
        filenames.sort()
        # Drop built-in blocklisted directory names from the in-place
        # list so os.walk does not descend into them.
        dirnames[:] = [
            d for d in dirnames
            if d not in _BUILTIN_EXCLUDED_DIR_NAMES
        ]
        # Apply operator globs to dirs (so a glob like `vendor/**`
        # prunes the entire subtree, not just leaf files).
        cur_path = Path(current_dir)
        try:
            cur_rel = cur_path.relative_to(root)
        except ValueError:
            cur_rel = Path(".")
        cur_rel_posix = cur_rel.as_posix()
        kept_dirs: list[str] = []
        for d in dirnames:
            child_rel = (
                d if cur_rel_posix in (".", "")
                else f"{cur_rel_posix}/{d}"
            )
            if _is_excluded(child_rel + "/", config_globs):
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs
        for fn in filenames:
            file_rel = (
                fn if cur_rel_posix in (".", "")
                else f"{cur_rel_posix}/{fn}"
            )
            if _is_excluded(file_rel, config_globs):
                continue
            yield cur_path / fn


# ---------------------------------------------------------------------------
# Finding dataclass + scanners.
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    kind: str
    severity: str
    path: str  # POSIX-normalized relative
    line_no: int
    snippet: str
    severity_weight: int = 0


def _truncate(text: str) -> str:
    text = text.replace("\n", " ").replace("\r", " ")
    if len(text) > _R73_SNIPPET_MAX_LEN:
        return text[: _R73_SNIPPET_MAX_LEN - 3] + "..."
    return text


def _is_binary(content: bytes) -> bool:
    """Heuristic: a NUL byte in the first 8KB means binary."""
    return b"\x00" in content[: _R73_BINARY_PEEK_BYTES]


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for c in s:
        counts[c] = counts.get(c, 0) + 1
    n = len(s)
    h = 0.0
    for c in counts.values():
        p = c / n
        h -= p * math.log2(p)
    return h


def scan_todo_debris(
    rel_path: str,
    text: str,
    config: dict,
) -> list[Finding]:
    out: list[Finding] = []
    severity = config["default_severities"]["todo-debris"]
    weight = config["weights"][severity]
    for i, line in enumerate(text.splitlines(), start=1):
        if re.search(r"\bTODO\b", line):
            out.append(
                Finding(
                    kind="todo-debris",
                    severity=severity,
                    path=rel_path,
                    line_no=i,
                    snippet=_truncate(line.strip()),
                    severity_weight=weight,
                )
            )
    return out


def scan_fixme_debris(
    rel_path: str,
    text: str,
    config: dict,
) -> list[Finding]:
    out: list[Finding] = []
    severity = config["default_severities"]["fixme-debris"]
    weight = config["weights"][severity]
    for i, line in enumerate(text.splitlines(), start=1):
        if re.search(r"\bFIXME\b|\bXXX\b|\bHACK\b", line):
            out.append(
                Finding(
                    kind="fixme-debris",
                    severity=severity,
                    path=rel_path,
                    line_no=i,
                    snippet=_truncate(line.strip()),
                    severity_weight=weight,
                )
            )
    return out


def scan_stray_temp_file(
    rel_path: str,
    basename: str,
    config: dict,
) -> list[Finding]:
    severity = config["default_severities"]["stray-temp-file"]
    weight = config["weights"][severity]
    for pattern in config.get("temp_file_patterns", []):
        if fnmatch.fnmatch(basename, pattern):
            return [
                Finding(
                    kind="stray-temp-file",
                    severity=severity,
                    path=rel_path,
                    line_no=0,
                    snippet=_truncate(basename),
                    severity_weight=weight,
                )
            ]
    return []


def scan_oversized_binary(
    rel_path: str,
    size: int,
    content: bytes,
    config: dict,
) -> list[Finding]:
    max_bytes = int(config.get("oversized_binary_max_bytes", 10485760))
    if size <= max_bytes:
        return []
    if not _is_binary(content):
        return []
    severity = config["default_severities"]["oversized-binary"]
    weight = config["weights"][severity]
    return [
        Finding(
            kind="oversized-binary",
            severity=severity,
            path=rel_path,
            line_no=0,
            snippet=_truncate(f"{size} bytes (>{max_bytes})"),
            severity_weight=weight,
        )
    ]


def scan_secret_shaped_string(
    rel_path: str,
    text: str,
    config: dict,
) -> list[Finding]:
    out: list[Finding] = []
    # Skip files whose suffix says they are intentional examples.
    for suf in _SECRET_ALLOW_SUFFIXES:
        if rel_path.endswith(suf):
            return out
    allow_marker = config.get(
        "secret_allow_marker", "# bhk-allow-secret-shape"
    )
    min_entropy = float(
        config.get("secret_shaped_min_entropy", 3.5)
    )
    severity = config["default_severities"]["secret-shaped-string"]
    weight = config["weights"][severity]
    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        # Allow-marker on the matched line OR the line above.
        if allow_marker in line:
            continue
        if i >= 2 and allow_marker in lines[i - 2]:
            continue
        for pattern, label in _SECRET_PATTERNS:
            m = pattern.search(line)
            if m is None:
                continue
            matched = m.group(0)
            # Skip low-entropy hand-typed examples (e.g. all zeros).
            if _shannon_entropy(matched) < min_entropy:
                continue
            out.append(
                Finding(
                    kind="secret-shaped-string",
                    severity=severity,
                    path=rel_path,
                    line_no=i,
                    snippet=_truncate(f"[{label}] " + matched),
                    severity_weight=weight,
                )
            )
            break  # one finding per line is enough
    return out


def scan_debug_print_leftover(
    rel_path: str,
    text: str,
    config: dict,
) -> list[Finding]:
    out: list[Finding] = []
    severity = config["default_severities"]["debug-print-leftover"]
    weight = config["weights"][severity]
    suffix_to_re: dict[str, list[re.Pattern[str]]] = {}
    for spec in config.get("debug_print_patterns", []):
        if ":" not in spec:
            continue
        lang, _, pat = spec.partition(":")
        try:
            compiled = re.compile(pat)
        except re.error:
            continue
        suffix_to_re.setdefault(lang.strip().lower(), []).append(
            compiled
        )
    # Determine the language from the file suffix.
    suffix = Path(rel_path).suffix.lstrip(".").lower()
    patterns = suffix_to_re.get(suffix, [])
    if not patterns:
        return out
    for i, line in enumerate(text.splitlines(), start=1):
        for compiled in patterns:
            if compiled.search(line):
                out.append(
                    Finding(
                        kind="debug-print-leftover",
                        severity=severity,
                        path=rel_path,
                        line_no=i,
                        snippet=_truncate(line.strip()),
                        severity_weight=weight,
                    )
                )
                break
    return out


def scan_broken_symlink(
    rel_path: str,
    abs_path: Path,
    config: dict,
) -> list[Finding]:
    """Detect symlinks that cannot be resolved.

    Catches BOTH `OSError` (target file missing on a host that
    supports symlink lookup) AND `RuntimeError` (Python's
    `Path.resolve()` raises `RuntimeError("Symlink loop from ...")`
    on circular symlink chains -- the canonical EXIT_CORRUPTION
    trigger). Either way the symlink is unusable and the gate emits
    a `broken-symlink` finding; the corrupt-fixture-unparseable-tree
    scenario relies on this.
    """
    try:
        if not abs_path.is_symlink():
            return []
    except (OSError, RuntimeError):
        # is_symlink() should not raise on a path that exists but is
        # itself a symlink, but a stat() error on a vanished or cycle-
        # reachable path can surface here. Treat as not-a-symlink.
        return []
    try:
        target = abs_path.resolve(strict=False)
        if target.exists():
            return []
    except (OSError, RuntimeError):
        # OSError -- the target cannot be opened.
        # RuntimeError -- Python detected a symlink cycle.
        # Either is a broken-symlink finding.
        pass
    severity = config["default_severities"]["broken-symlink"]
    weight = config["weights"][severity]
    return [
        Finding(
            kind="broken-symlink",
            severity=severity,
            path=rel_path,
            line_no=0,
            snippet=_truncate(f"broken symlink: {rel_path}"),
            severity_weight=weight,
        )
    ]


def _looks_like_utf16(content: bytes) -> bool:
    """Detect UTF-16 LE/BE by BOM or by an alternating-null-byte
    pattern in the first 1KB of an ASCII-dominated file. UTF-16
    intentionally contains null bytes for ASCII codepoints (every
    other byte), which means `_is_binary`'s NUL-byte heuristic
    falsely classifies UTF-16 as binary -- that misclassification is
    why `misencoded-file` was silently dropped before this guard.
    """
    # BOM check (cheap and definitive).
    if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return True
    if not content:
        return False
    # Heuristic: ASCII-dominated UTF-16 LE has a NUL at every odd
    # index; ASCII-dominated UTF-16 BE has a NUL at every even index.
    sample = content[:1024]
    if len(sample) < 4 or len(sample) % 2 != 0:
        sample = sample[: len(sample) - (len(sample) % 2)]
    if not sample:
        return False
    le_nulls = sum(1 for i in range(1, len(sample), 2) if sample[i] == 0)
    be_nulls = sum(1 for i in range(0, len(sample), 2) if sample[i] == 0)
    half = len(sample) // 2
    if half == 0:
        return False
    return (le_nulls / half) > 0.85 or (be_nulls / half) > 0.85


def scan_misencoded_file(
    rel_path: str,
    content: bytes,
    config: dict,
) -> list[Finding]:
    """Detect files that fail UTF-8 decoding.

    The binary heuristic (`_is_binary` — NUL byte in the first 8KB) is
    NOT a short-circuit here: UTF-16 LE/BE files contain alternating
    NUL bytes for ASCII codepoints, so the heuristic falsely flags
    them as binary. Instead:

      1. Try UTF-8 decode -> success: not misencoded; return [].
      2. UnicodeDecodeError AND content looks like UTF-16 (BOM or
         alternating-NUL heuristic) -> emit `misencoded-file`.
      3. UnicodeDecodeError AND content looks like genuine binary
         (no BOM, no alternating-NUL pattern) -> return [] -- the
         file is binary, not text-with-wrong-encoding.

    `oversized-binary` keeps its own size-based check independently;
    this function only fires on the misencoded text case.
    """
    try:
        content.decode("utf-8")
        return []
    except UnicodeDecodeError as exc:
        # Distinguish "misencoded text" (UTF-16, latin-1, etc.) from
        # "actual binary blob" (PNG, ELF, .pyc).
        if not _looks_like_utf16(content) and _is_binary(content):
            # Genuinely binary -- not misencoded text.
            return []
        severity = config["default_severities"]["misencoded-file"]
        weight = config["weights"][severity]
        return [
            Finding(
                kind="misencoded-file",
                severity=severity,
                path=rel_path,
                line_no=0,
                snippet=_truncate(
                    f"utf-8 decode error at byte {exc.start}: "
                    f"{exc.reason}"
                ),
                severity_weight=weight,
            )
        ]


def _sort_findings(findings: list[Finding]) -> list[Finding]:
    """Deterministic order: (path, line_no, kind, snippet[:80])."""
    return sorted(
        findings,
        key=lambda f: (f.path, f.line_no, f.kind, f.snippet[:80]),
    )


# ---------------------------------------------------------------------------
# JSONL emitter.
# ---------------------------------------------------------------------------


@dataclass
class _EmitState:
    prev_crc32: str = "00000000"
    rows_written: int = 0


def _emit_record(
    record: dict,
    out_path: Path | None,
    state: _EmitState,
) -> dict:
    """Emit one CRC-footed JSONL row. Returns the finalised record (with
    crc32 field) so the caller can re-use it (e.g. for the chain
    self-check). When out_path is None, no I/O happens (used in tests).
    """
    record_with_chain = dict(record)
    record_with_chain["crc32_prev"] = state.prev_crc32
    record_with_chain["crc32"] = compute_crc32(record_with_chain)
    line = json.dumps(
        record_with_chain,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    state.prev_crc32 = record_with_chain["crc32"]
    state.rows_written += 1
    return record_with_chain


# ---------------------------------------------------------------------------
# Schema validation (defensive -- jsonschema may be absent).
# ---------------------------------------------------------------------------


def _validate_config_against_schema(
    config: dict,
    schema: dict,
) -> tuple[bool, str]:
    try:
        import jsonschema  # type: ignore

        jsonschema.validate(instance=config, schema=schema)
        return True, ""
    except ImportError:
        # When jsonschema is not installed, fall back to a minimal
        # required-keys + enum check (stdlib-only).
        return _validate_config_minimal(config, schema)
    except Exception as exc:  # noqa: BLE001 -- bound to validator
        return False, f"{type(exc).__name__}: {exc}"


def _validate_config_minimal(
    config: dict, schema: dict
) -> tuple[bool, str]:
    required = schema.get("required", [])
    for key in required:
        if key not in config:
            return False, f"missing required top-level key: {key!r}"
    weights = config.get("weights", {})
    for sev in SEVERITY_CLASSES:
        if sev not in weights:
            return False, f"weights missing severity class: {sev!r}"
        if not isinstance(weights[sev], int):
            return False, f"weights[{sev!r}] is not an integer"
    defaults = config.get("default_severities", {})
    for kind in FINDING_KINDS:
        if kind not in defaults:
            return False, (
                f"default_severities missing finding kind: {kind!r}"
            )
        if defaults[kind] not in SEVERITY_CLASSES:
            return False, (
                f"default_severities[{kind!r}]={defaults[kind]!r} "
                f"is not a known severity class"
            )
    return True, ""


def _check_enums(config: dict) -> tuple[bool, str]:
    """Closed-set check: every key in default_severities MUST be in
    FINDING_KINDS; every value MUST be in SEVERITY_CLASSES; every key in
    weights MUST be in SEVERITY_CLASSES.
    """
    defaults = config.get("default_severities", {})
    for k in defaults.keys():
        if k not in FINDING_KINDS:
            return False, (
                f"default_severities references unknown finding "
                f"kind: {k!r}"
            )
    for v in defaults.values():
        if v not in SEVERITY_CLASSES:
            return False, (
                f"default_severities references unknown severity "
                f"class: {v!r}"
            )
    weights = config.get("weights", {})
    for k in weights.keys():
        if k not in SEVERITY_CLASSES:
            return False, (
                f"weights references unknown severity class: {k!r}"
            )
    return True, ""


# ---------------------------------------------------------------------------
# Wallclock helpers.
# ---------------------------------------------------------------------------


def _wallclock_iso8601() -> str:
    epoch_ms = int(time.time() * 1000)
    secs, ms = divmod(epoch_ms, 1000)
    tm = time.gmtime(secs)
    return (
        f"{tm.tm_year:04d}-{tm.tm_mon:02d}-{tm.tm_mday:02d}T"
        f"{tm.tm_hour:02d}:{tm.tm_min:02d}:{tm.tm_sec:02d}.{ms:03d}Z"
    )


# ---------------------------------------------------------------------------
# Main scan + emit.
# ---------------------------------------------------------------------------


def _safe_is_symlink(p: Path) -> bool:
    try:
        return p.is_symlink()
    except (OSError, RuntimeError):
        return False


def _safe_exists(p: Path) -> bool:
    try:
        return p.exists()
    except (OSError, RuntimeError):
        return False


def _scan_one_file(
    abs_path: Path,
    rel_posix: str,
    config: dict,
) -> tuple[list[Finding], bool]:
    """Apply every applicable scanner to `abs_path`. Returns
    (findings, corruption_encountered). When ANY scanner raises an
    unexpected exception that is NOT an `OSError`/`RuntimeError`
    already handled inside the scanner, `corruption_encountered` is
    True so the caller can promote the gate's exit code to
    EXIT_CORRUPTION (5). Findings collected before the failure are
    still returned.
    """
    findings: list[Finding] = []
    corruption = False
    basename = abs_path.name

    def _safe(scan_call):
        nonlocal corruption
        try:
            return scan_call()
        except (OSError, RuntimeError) as exc:
            sys.stderr.write(
                f"check_workspace_hygiene: scanner error on "
                f"{rel_posix!r}: {type(exc).__name__}: {exc}\n"
            )
            corruption = True
            return []
        except Exception as exc:  # noqa: BLE001 -- defensive umbrella
            sys.stderr.write(
                f"check_workspace_hygiene: unexpected scanner "
                f"error on {rel_posix!r}: "
                f"{type(exc).__name__}: {exc}\n"
            )
            corruption = True
            return []

    # Symlink check first -- a broken symlink cannot be opened. The
    # scanner itself catches OSError/RuntimeError on the resolve call;
    # _safe is a belt-and-suspenders wrapper for any future scanner
    # variant that forgets to catch.
    findings.extend(
        _safe(lambda: scan_broken_symlink(rel_posix, abs_path, config))
    )
    # Symlink cycles are the canonical EXIT_CORRUPTION trigger.
    # `Path.resolve()` raises RuntimeError("Symlink loop from ...") on
    # circular chains; we probe explicitly here so the gate's exit
    # code is promoted to 5 even though the scanner already swallowed
    # the exception to emit a clean `broken-symlink` finding.
    if _safe_is_symlink(abs_path):
        try:
            abs_path.resolve(strict=False)
        except RuntimeError:
            corruption = True
        except OSError:
            # Plain missing-target -- not a corruption signal.
            pass
    if _safe_is_symlink(abs_path) and not _safe_exists(abs_path):
        # Skip further scanning -- the symlink is broken.
        findings.extend(
            _safe(
                lambda: scan_stray_temp_file(rel_posix, basename, config)
            )
        )
        return findings, corruption

    # Stray-temp-file is a basename-only check; runs even on
    # unreadable files.
    findings.extend(
        _safe(
            lambda: scan_stray_temp_file(rel_posix, basename, config)
        )
    )

    # Read the file once.
    try:
        content = abs_path.read_bytes()
    except OSError as exc:
        sys.stderr.write(
            f"check_workspace_hygiene: read failed for "
            f"{rel_posix!r}: {type(exc).__name__}: {exc}\n"
        )
        corruption = True
        return findings, corruption
    size = len(content)

    findings.extend(
        _safe(
            lambda: scan_oversized_binary(
                rel_posix, size, content, config
            )
        )
    )
    findings.extend(
        _safe(
            lambda: scan_misencoded_file(rel_posix, content, config)
        )
    )

    if _is_binary(content):
        return findings, corruption

    # Text-content scanners.
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return findings, corruption

    findings.extend(
        _safe(lambda: scan_todo_debris(rel_posix, text, config))
    )
    findings.extend(
        _safe(lambda: scan_fixme_debris(rel_posix, text, config))
    )
    findings.extend(
        _safe(
            lambda: scan_secret_shaped_string(rel_posix, text, config)
        )
    )
    findings.extend(
        _safe(
            lambda: scan_debug_print_leftover(rel_posix, text, config)
        )
    )
    return findings, corruption


def run_scan(
    *,
    root: Path,
    config: dict,
    config_path: Path,
    config_sha256: str,
    report_out: Path | None,
    lane_id: str,
    agent_session_id: str,
    severity_cap: int,
) -> tuple[int, dict]:
    """Drive the scan + emit. Returns (exit_code, run_summary_dict)."""
    if report_out is not None and report_out.exists():
        report_out.unlink()

    state = _EmitState()
    run_started = _wallclock_iso8601()
    started_ms = int(time.time() * 1000)

    try:
        files = list(_walk_files(root, config.get("exclusion_globs", [])))
    except OSError as exc:
        sys.stderr.write(
            f"check_workspace_hygiene: walk failed: "
            f"{type(exc).__name__}: {exc}\n"
        )
        return EXIT_CORRUPTION, {}

    findings: list[Finding] = []
    corruption_encountered = False
    for abs_path in files:
        try:
            rel = abs_path.relative_to(root.resolve())
        except ValueError:
            rel = Path(abs_path.name)
        rel_posix = rel.as_posix()
        try:
            file_findings, file_corruption = _scan_one_file(
                abs_path, rel_posix, config
            )
        except (OSError, RuntimeError) as exc:
            # Defensive: _scan_one_file already wraps each scanner in
            # _safe, but a top-level os.walk artefact (race: file
            # vanishes mid-walk) could still surface here. Promote to
            # EXIT_CORRUPTION but keep walking so the report still
            # captures the findings collected so far.
            sys.stderr.write(
                f"check_workspace_hygiene: scan failed for "
                f"{rel_posix!r}: {type(exc).__name__}: {exc}\n"
            )
            corruption_encountered = True
            continue
        findings.extend(file_findings)
        if file_corruption:
            corruption_encountered = True

    findings = _sort_findings(findings)

    # Emit one hygiene_finding row per finding.
    for f in findings:
        rec = {
            "ts": run_started,
            "kind": "hygiene_finding",
            "lane_id": lane_id,
            "finding_kind": f.kind,
            "severity_class": f.severity,
            "severity_weight": f.severity_weight,
            "path": f.path,
            "line_no": f.line_no,
            "snippet": f.snippet,
            "computed_by_agent_session_id": agent_session_id,
        }
        _emit_record(rec, report_out, state)

    findings_by_kind = {k: 0 for k in FINDING_KINDS}
    findings_by_severity = {s: 0 for s in SEVERITY_CLASSES}
    severity_total = 0
    for f in findings:
        findings_by_kind[f.kind] = findings_by_kind.get(f.kind, 0) + 1
        findings_by_severity[f.severity] = (
            findings_by_severity.get(f.severity, 0) + 1
        )
        severity_total += f.severity_weight
    severity_total = max(0, min(severity_total, _R73_SEVERITY_TOTAL_CLAMP))

    finished_ms = int(time.time() * 1000)
    run_finished = _wallclock_iso8601()
    wallclock = max(0, finished_ms - started_ms)

    summary = {
        "ts": run_finished,
        "kind": "run_summary",
        "lane_id": lane_id,
        "findings_total": len(findings),
        "findings_by_kind": findings_by_kind,
        "findings_by_severity": findings_by_severity,
        "severity_total_score": severity_total,
        "severity_cap": severity_cap,
        "cap_breached": severity_total > severity_cap,
        "config_sha256": config_sha256,
        "config_path": _to_posix_repo_rel(config_path),
        "scan_root": _to_posix_repo_rel(root),
        "run_started_at_iso8601": run_started,
        "run_finished_at_iso8601": run_finished,
        "wallclock_ms": wallclock,
        "computed_by_agent_session_id": agent_session_id,
    }
    _emit_record(summary, report_out, state)
    # Even when every scanner returned cleanly, if ANY scanner raised
    # an unexpected exception during the walk (e.g. RuntimeError on a
    # symlink loop) the gate exits 5 (EXIT_CORRUPTION). The
    # run_summary row is still emitted so downstream consumers can
    # still read the partial scan; only the exit code is promoted.
    exit_code = (
        EXIT_CORRUPTION if corruption_encountered else EXIT_OK
    )
    return exit_code, summary


def _to_posix_repo_rel(path: Path) -> str:
    """Render `path` as a forward-slash POSIX string. Tries to make it
    relative to the v3.5 root's parent so the recorded path is
    reproducible across hosts; falls back to the absolute path string
    when not resolvable.
    """
    try:
        p = Path(path).resolve()
    except OSError:
        p = Path(path)
    repo_root = _V35_ROOT.parent
    try:
        rel = p.relative_to(repo_root)
        return rel.as_posix()
    except ValueError:
        return p.as_posix()


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "PR-ready workspace hygiene gate (issue #8 -- "
            "cluster G 1/3)."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Directory to walk (default: cwd).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_DEFAULT_CONFIG,
        help=(
            "Path to the workspace_hygiene config YAML "
            f"(default: {_DEFAULT_CONFIG})."
        ),
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=_DEFAULT_REPORT_OUT,
        help=(
            "Path to write the JSONL run report "
            f"(default: {_DEFAULT_REPORT_OUT})."
        ),
    )
    parser.add_argument(
        "--severity-cap",
        type=int,
        default=_R73_HYGIENE_CAP,
        help=(
            "Soft severity_total_score cap recorded on the "
            f"run_summary row (default: {_R73_HYGIENE_CAP})."
        ),
    )
    parser.add_argument(
        "--lane-id",
        default=_DEFAULT_LANE_ID,
        help=(
            "lane_id stamp for every emitted row "
            f"(default: {_DEFAULT_LANE_ID})."
        ),
    )
    parser.add_argument(
        "--agent-session-id",
        default=_DEFAULT_AGENT_SESSION_ID,
        help=(
            "computed_by_agent_session_id stamp for every emitted "
            f"row (default: {_DEFAULT_AGENT_SESSION_ID})."
        ),
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help=(
            "Force rebuild of the canonical fixture catalog before "
            "running. Idempotent."
        ),
    )
    args = parser.parse_args(argv)

    # Config presence.
    if not args.config.exists():
        sys.stderr.write(
            f"check_workspace_hygiene: config file does not exist: "
            f"{args.config}\n"
        )
        return EXIT_DRIFT

    config = _load_config(args.config)
    if config is None or not isinstance(config, dict):
        sys.stderr.write(
            f"check_workspace_hygiene: config file is empty or "
            f"unparseable: {args.config}\n"
        )
        return EXIT_SCHEMA

    # Schema validation.
    schema = _load_config_schema()
    if schema is not None:
        ok, err = _validate_config_against_schema(config, schema)
        if not ok:
            sys.stderr.write(
                f"check_workspace_hygiene: config schema "
                f"validation failed: {err}\n"
            )
            return EXIT_SCHEMA

    # Closed-set enum check (runs even when schema absent).
    ok, err = _check_enums(config)
    if not ok:
        sys.stderr.write(
            f"check_workspace_hygiene: config enum check failed: "
            f"{err}\n"
        )
        return EXIT_ENUM

    config_sha256 = _compute_config_sha256(args.config)

    if args.rebuild:
        _rebuild_fixture_catalog()

    report_out: Path | None
    if str(args.report_out) == "-":
        report_out = None
    else:
        report_out = args.report_out

    exit_code, summary = run_scan(
        root=args.root,
        config=config,
        config_path=args.config,
        config_sha256=config_sha256,
        report_out=report_out,
        lane_id=args.lane_id,
        agent_session_id=args.agent_session_id,
        severity_cap=args.severity_cap,
    )

    # Self-check: re-read the report and verify the chain.
    if exit_code == EXIT_OK and report_out is not None:
        if not _self_check_chain(report_out):
            sys.stderr.write(
                f"check_workspace_hygiene: emit-time chain "
                f"self-check failed against {report_out}\n"
            )
            return EXIT_CHAIN

    return exit_code


def _rebuild_fixture_catalog() -> None:
    """Optional --rebuild path: import the canonical fixture builder
    and call build_all_fixtures(). Silently skips when the builder is
    not importable (back-compat).
    """
    import importlib.util

    builder_path = (
        _V35_ROOT / "tests" / "fixtures" / "workspace_hygiene"
        / "_build_fixtures.py"
    )
    if not builder_path.exists():
        return
    spec = importlib.util.spec_from_file_location(
        "_workspace_hygiene_build_fixtures", builder_path
    )
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules["_workspace_hygiene_build_fixtures"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 -- defensive
        return
    if hasattr(module, "build_all_fixtures"):
        try:
            module.build_all_fixtures()
        except Exception:  # noqa: BLE001 -- defensive
            return


def _self_check_chain(report_path: Path) -> bool:
    """Re-walk the JSONL we just wrote and verify CRC32 chain. Returns
    True when the chain is consistent.
    """
    if not report_path.exists():
        return False
    prev = "00000000"
    try:
        for raw in report_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("crc32_prev") != prev:
                return False
            recomputed = compute_crc32(row)
            if recomputed != row.get("crc32"):
                return False
            prev = row["crc32"]
    except (json.JSONDecodeError, OSError):
        return False
    return True


# ---------------------------------------------------------------------------
# Public API for tests + sister tooling.
# ---------------------------------------------------------------------------


def finding_kind_names() -> list[str]:
    """Closed-set finding kinds in canonical order. Used by the parity
    validators in validate_v33_schema_drift.py.
    """
    return list(FINDING_KINDS)


def severity_class_names() -> list[str]:
    """Closed-set severity classes in canonical order. Used by the
    parity validators.
    """
    return list(SEVERITY_CLASSES)


if __name__ == "__main__":
    sys.exit(main())
