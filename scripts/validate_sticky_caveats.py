#!/usr/bin/env python3
"""scripts/validate_sticky_caveats.py — verify out/sticky-caveats.jsonl integrity.

Issue #11: enforce schema, crc32, fingerprint stability, and state-machine
legality on every record. Mechanical backstop for §6.3's claim that sticky
caveats progress through states deterministically.

Exit codes:
  0 — every record valid
  1 — schema violation (missing required field, wrong type, oneOf failure)
  2 — crc32 mismatch (truncation or silent corruption)
  3 — illegal state-machine transition (kind/prior-state/count not allowed
       by tables/caveat-state-machine.yaml)
  4 — fingerprint mismatch (sha256(canonical_text) != fingerprint)
  6 — IO / argparse error
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:
    print(
        "ERROR: jsonschema is required (pip install jsonschema). "
        "See v3.5/INSTALL.md.",
        file=sys.stderr,
    )
    sys.exit(6)

_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))
from sticky_caveats_append import (  # noqa: E402
    compute_crc32,
    transition_allowed,
)

_SCHEMA_PATH = (
    _SCRIPTS_DIR.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
    / "schemas"
    / "sticky-caveat-record.schema.json"
)


def _load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_file(ledger_path: Path) -> int:
    if not ledger_path.exists():
        print(f"ERROR: ledger file not found: {ledger_path}", file=sys.stderr)
        return 6

    schema = _load_schema()
    validator = Draft202012Validator(schema)

    raw = ledger_path.read_text(encoding="utf-8").splitlines()
    records: list[dict] = []
    for idx, line in enumerate(raw, start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            print(
                f"sticky-caveats: line {idx}: invalid JSON ({exc})",
                file=sys.stderr,
            )
            return 1
        records.append(rec)

    for idx, rec in enumerate(records, start=1):
        errors = sorted(validator.iter_errors(rec), key=lambda e: e.path)
        if errors:
            for err in errors:
                print(
                    f"sticky-caveats: line {idx}: schema violation: "
                    f"{'/'.join(str(p) for p in err.absolute_path) or '<root>'}: "
                    f"{err.message}",
                    file=sys.stderr,
                )
            return 1

        actual_crc = compute_crc32(rec)
        if actual_crc != rec["crc32"]:
            print(
                f"sticky-caveats: line {idx}: crc32 mismatch "
                f"(stored={rec['crc32']}, computed={actual_crc})",
                file=sys.stderr,
            )
            return 2

        recomputed_fp = hashlib.sha256(
            rec["canonical_text"].encode("utf-8")
        ).hexdigest()
        if recomputed_fp != rec["fingerprint"]:
            print(
                f"sticky-caveats: line {idx}: fingerprint mismatch "
                f"(stored={rec['fingerprint'][:16]}..., "
                f"sha256(canonical_text)={recomputed_fp[:16]}...)",
                file=sys.stderr,
            )
            return 4

    state_per_fp: dict[str, dict] = {}
    for idx, rec in enumerate(records, start=1):
        fp = rec["fingerprint"]
        prior = state_per_fp.get(fp)
        prior_state = prior["state"] if prior else None
        if not transition_allowed(
            kind=rec["kind"],
            prior_state=prior_state,
            state_after=rec["state_after"],
            count=rec["occurrence_count"],
        ):
            print(
                f"sticky-caveats: line {idx}: illegal transition "
                f"kind={rec['kind']} prior_state={prior_state} "
                f"state_after={rec['state_after']} "
                f"count={rec['occurrence_count']}",
                file=sys.stderr,
            )
            return 3
        state_per_fp[fp] = {
            "state": rec["state_after"],
            "count": rec["occurrence_count"],
        }

    print(
        f"sticky-caveats: {ledger_path} VALID — {len(records)} record(s), "
        f"{len(state_per_fp)} unique caveat(s)."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--file", default="out/sticky-caveats.jsonl",
        help="Path to the ledger file (default: out/sticky-caveats.jsonl).",
    )
    args = parser.parse_args(argv)
    return validate_file(Path(args.file))


if __name__ == "__main__":
    sys.exit(main())
