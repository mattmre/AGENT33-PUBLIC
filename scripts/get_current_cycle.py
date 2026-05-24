#!/usr/bin/env python3
"""scripts/get_current_cycle.py — minimal cycle-index resolver (issue #26).

Reads v3.5/docs/conventions/brutal-honesty-kit/v3.5/tables/cycle-ledger.yaml
(or the file pointed to by the BHS_CYCLE_LEDGER environment variable, which
takes precedence) and returns an integer cycle index.

The cycle counter is the *clock* that R23/R24 TTL math runs against
(see scripts/validate_pr_brutal_honesty.py and §6.3 of the rulebook).

CLI:
  python scripts/get_current_cycle.py              # → highest cycle index
  python scripts/get_current_cycle.py --as-of T    # → cycle in effect at ISO-8601 T
  python scripts/get_current_cycle.py --ledger P   # → read ledger from path P

The cycle in effect at timestamp T is defined as the highest cycle whose
`merged_at <= T`. If no row qualifies, the result is 0 (matches the install
seed convention — every adopter starts at cycle 0).

This script does NOT write the ledger; cycle_append.py is deferred to a
later PR (see issue #26 §10 carried debt). For tests, override the path
via BHS_CYCLE_LEDGER or --ledger.

Schema validation (v3.6 carry-debt, MEDIUM-rollup cluster B):

  Before returning the current cycle, the loaded ledger is validated
  against cycle-ledger.schema.json. Validation is performed by a small
  in-house stdlib-only validator (no `jsonschema` runtime dep — adopters
  who installed only PyYAML still get the check). A malformed ledger
  (missing required field, wrong type, unknown extra key, non-ISO
  merged_at, negative cycle) raises ValueError from `load()` so the
  downstream TTL math (R23/R24) never silently consumes garbage.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import yaml  # type: ignore[import-not-found]
except ImportError as exc:  # pragma: no cover — missing-dep path
    print(
        f"ERROR: PyYAML required (pip install pyyaml): {exc}", file=sys.stderr
    )
    sys.exit(2)


DEFAULT_LEDGER = (
    Path(__file__).resolve().parent.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
    / "tables"
    / "cycle-ledger.yaml"
)

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
    / "schemas"
    / "cycle-ledger.schema.json"
)


# --- minimal stdlib-only schema validator -----------------------------------
#
# Scoped strictly to what cycle-ledger.schema.json expresses today:
#   - top-level type: array
#   - each item: object with required fields + additionalProperties: false
#   - per-property: type (string / integer), pattern, format=date-time,
#                   minimum (for cycle), minLength (for pr)
#
# A more general implementation would be `jsonschema`; we deliberately
# avoid that runtime dep because get_current_cycle.py is called from R23/R24
# TTL math hot paths and adopters MAY have only PyYAML installed (per
# v3.5/INSTALL.md the dep matrix is yaml-required, jsonschema-optional).


# ISO-8601 date-time accepted by datetime.fromisoformat after stripping a
# trailing 'Z'. Mirrors _parse_iso below so the schema check and the math
# check agree on what counts as a valid `merged_at`.
_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)


def _validate_against_schema(data: object, schema: dict, path: str = "$") -> None:
    """Validate `data` against `schema`. Raise ValueError with a path-tagged
    message on the first failure (fail-fast, like jsonschema.validate)."""
    expected_type = schema.get("type")
    if expected_type == "array":
        if not isinstance(data, list):
            raise ValueError(
                f"cycle-ledger schema: at {path}: expected array, got "
                f"{type(data).__name__}"
            )
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(data):
                _validate_against_schema(item, item_schema, f"{path}[{idx}]")
        return

    if expected_type == "object":
        if not isinstance(data, dict):
            raise ValueError(
                f"cycle-ledger schema: at {path}: expected object, got "
                f"{type(data).__name__}"
            )
        required = schema.get("required", [])
        for field in required:
            if field not in data:
                raise ValueError(
                    f"cycle-ledger schema: at {path}: missing required "
                    f"field {field!r}"
                )
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = set(data.keys()) - set(props.keys())
            if extras:
                raise ValueError(
                    f"cycle-ledger schema: at {path}: unknown field(s) "
                    f"{sorted(extras)} (additionalProperties: false)"
                )
        for field, value in data.items():
            sub_schema = props.get(field)
            if isinstance(sub_schema, dict):
                _validate_against_schema(value, sub_schema, f"{path}.{field}")
        return

    if expected_type == "integer":
        if isinstance(data, bool) or not isinstance(data, int):
            raise ValueError(
                f"cycle-ledger schema: at {path}: expected integer, got "
                f"{type(data).__name__}"
            )
        minimum = schema.get("minimum")
        if minimum is not None and data < minimum:
            raise ValueError(
                f"cycle-ledger schema: at {path}: value {data} below "
                f"minimum {minimum}"
            )
        return

    if expected_type == "string":
        if not isinstance(data, str):
            raise ValueError(
                f"cycle-ledger schema: at {path}: expected string, got "
                f"{type(data).__name__}"
            )
        min_length = schema.get("minLength")
        if min_length is not None and len(data) < min_length:
            raise ValueError(
                f"cycle-ledger schema: at {path}: string length {len(data)} "
                f"below minLength {min_length}"
            )
        fmt = schema.get("format")
        if fmt == "date-time":
            if not _ISO_RE.match(data):
                raise ValueError(
                    f"cycle-ledger schema: at {path}: value {data!r} is "
                    f"not ISO-8601 date-time"
                )
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, data) is None:
            raise ValueError(
                f"cycle-ledger schema: at {path}: value {data!r} does not "
                f"match pattern {pattern!r}"
            )
        return

    # Any other type keyword (number / boolean / null) is unused by
    # cycle-ledger.schema.json today; if a future schema bump adds one,
    # the missing branch will raise here loudly rather than silently
    # passing untyped data through.
    if expected_type is not None:
        raise ValueError(
            f"cycle-ledger schema: at {path}: unsupported schema type "
            f"{expected_type!r} for the in-house validator"
        )


def _load_schema() -> Optional[dict]:
    """Load cycle-ledger.schema.json. Return None when the file is absent
    (back-compat for stripped-down checkouts; downstream code skips the
    check rather than crashing)."""
    if not SCHEMA_PATH.exists():
        return None
    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def resolve_ledger_path(explicit: Optional[Path] = None) -> Path:
    """Resolve which ledger file to read.

    Precedence: explicit arg > BHS_CYCLE_LEDGER env var > DEFAULT_LEDGER.
    The env var hook is what makes R23/R24 testable — pytest fixtures pin a
    deterministic cycle (e.g. 10) without rewriting the repo's seed file.
    """
    if explicit is not None:
        return explicit
    env = os.environ.get("BHS_CYCLE_LEDGER")
    if env:
        return Path(env)
    return DEFAULT_LEDGER


def load(path: Optional[Path] = None) -> list[dict]:
    """Load the ledger rows. Returns [] if the file is absent or empty.

    Raises ValueError when the file is present but malformed (non-list
    top level, missing required field, wrong type, unknown extra key,
    non-ISO merged_at, negative cycle). See module docstring "Schema
    validation" for the back-compat semantics — the check is best-effort
    against cycle-ledger.schema.json; if that file is missing from a
    stripped-down checkout the validator silently skips.
    """
    target = resolve_ledger_path(path)
    if not target.exists():
        return []
    raw = target.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or []
    if not isinstance(data, list):
        raise ValueError(
            f"cycle-ledger at {target} must be a YAML list; got {type(data).__name__}"
        )
    schema = _load_schema()
    if schema is not None:
        try:
            _validate_against_schema(data, schema)
        except ValueError as exc:
            # Re-raise with the source path so the error message includes
            # the file the operator needs to fix.
            raise ValueError(f"cycle-ledger at {target}: {exc}") from exc
    return data


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 string into a tz-aware UTC datetime.

    Date-only strings (e.g. ``2026-04-15``) and naive datetimes are treated as
    UTC midnight so they can be compared against ledger rows whose
    ``merged_at`` carries an explicit timezone (the seed format is
    ``...Z``). Without this normalization, mixing the two would raise
    ``TypeError: can't compare offset-naive and offset-aware datetimes``.
    """
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def current(as_of: Optional[str] = None, path: Optional[Path] = None) -> int:
    """Return the cycle index in effect at as_of (or now / latest).

    With as_of=None, returns the highest cycle present.
    With as_of=ISO date, returns the highest cycle whose merged_at <= as_of.
    """
    rows = load(path)
    if not rows:
        return 0
    if as_of is None:
        return max(r["cycle"] for r in rows)
    ts = _parse_iso(as_of)
    eligible = [
        r for r in rows if _parse_iso(str(r["merged_at"])) <= ts
    ]
    return max((r["cycle"] for r in eligible), default=0)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--as-of",
        default=None,
        help="ISO-8601 timestamp; return the cycle in effect at that moment.",
    )
    ap.add_argument(
        "--ledger",
        default=None,
        help="Override the ledger file path (also honored via BHS_CYCLE_LEDGER).",
    )
    args = ap.parse_args(argv)
    path = Path(args.ledger) if args.ledger else None
    print(current(args.as_of, path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
