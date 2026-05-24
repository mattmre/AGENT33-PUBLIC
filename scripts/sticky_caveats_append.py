#!/usr/bin/env python3
"""scripts/sticky_caveats_append.py — append one record to out/sticky-caveats.jsonl.

Issue #11: every state transition for a sticky caveat MUST be backed by a
structured ledger record. This script is the only sanctioned writer. It
canonicalizes the caveat text via v3.5/tables/caveat-canonicalization.yaml +
v3.5/enums/caveat-synonyms.txt, computes the SHA-256 fingerprint, looks up
the prior occurrence_count for the fingerprint, then enforces the
state-machine in v3.5/tables/caveat-state-machine.yaml.

Write protocol mirrors scripts/bhs_ledger_append.py: write tmp + fsync +
atomic rename. crc32 is computed over the JSON-serialized record body
excluding the crc32 field itself.

Exit codes:
  0 — appended cleanly
  1 — argparse / IO error
  2 — illegal state-machine transition (kind/prior-state/count mismatch)
  3 — enum violation (kind not in canonical set)
  4 — missing required field for the chosen kind (e.g., caveat_promote_sticky
       without --owner)
"""

from __future__ import annotations

import argparse
import binascii
import datetime as _dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    print(
        "ERROR: PyYAML is required (pip install PyYAML). See v3.5/INSTALL.md.",
        file=sys.stderr,
    )
    sys.exit(1)


_CONVENTIONS = (
    Path(__file__).resolve().parent.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
)
_ENUM_DIR = _CONVENTIONS / "enums"
_TABLE_DIR = _CONVENTIONS / "tables"


def _load_enum(filename: str) -> set[str]:
    values: set[str] = set()
    for line in (_ENUM_DIR / filename).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            values.add(stripped)
    return values


def _load_synonyms() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in (_ENUM_DIR / "caveat-synonyms.txt").read_text(
        encoding="utf-8"
    ).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "->" not in stripped:
            continue
        original, canonical = stripped.split("->", 1)
        pairs.append((original.strip().lower(), canonical.strip().lower()))
    pairs.sort(key=lambda p: -len(p[0]))
    return pairs


def _load_canonicalization_rules() -> list[dict]:
    data = yaml.safe_load(
        (_TABLE_DIR / "caveat-canonicalization.yaml").read_text(encoding="utf-8")
    )
    return list(data.get("rules", []))


def _load_state_machine() -> list[dict]:
    data = yaml.safe_load(
        (_TABLE_DIR / "caveat-state-machine.yaml").read_text(encoding="utf-8")
    )
    return list(data.get("transitions", []))


RECORD_KINDS = _load_enum("caveat-record-kinds.txt")
CAVEAT_STATES = _load_enum("caveat-states.txt")


def canonicalize(text: str) -> str:
    rules = _load_canonicalization_rules()
    synonyms = _load_synonyms()
    s = text
    for rule in rules:
        op = rule.get("op")
        arg = rule.get("arg")
        if op == "lowercase":
            s = s.lower()
        elif op == "strip_leading_label":
            s = re.sub(r"^\s*l\d{1,2}\s*\([^)]*\)\s*:?\s*", "", s, flags=re.IGNORECASE)
        elif op == "strip_punctuation":
            chars = arg or ""
            for ch in chars:
                s = s.replace(ch, " ")
        elif op == "collapse_whitespace":
            s = re.sub(r"\s+", " ", s).strip()
        elif op == "drop_stopwords":
            stops = set(arg or [])
            tokens = [t for t in s.split() if t not in stops]
            s = " ".join(tokens)
        elif op == "apply_synonyms":
            for original, canonical in synonyms:
                s = s.replace(original, canonical)
        else:
            raise SystemExit(
                f"sticky-caveats: unknown canonicalization op {op!r}"
            )
    return s


def fingerprint_of(text: str) -> str:
    canonical = canonicalize(text)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _serialize_for_crc(record: dict) -> bytes:
    return json.dumps(
        {k: v for k, v in record.items() if k != "crc32"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_crc32(record: dict) -> str:
    return f"{binascii.crc32(_serialize_for_crc(record)) & 0xFFFFFFFF:08x}"


def _now_iso() -> str:
    now = _dt.datetime.now(_dt.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def replay(records: list[dict]) -> dict[str, dict]:
    """Replay JSONL records, return per-fingerprint state map."""
    states: dict[str, dict] = {}
    for rec in records:
        fp = rec["fingerprint"]
        s = states.setdefault(
            fp,
            {
                "state": None,
                "count": 0,
                "owner": None,
                "attempt_ref": None,
                "review_ref": None,
                "impossibility_ref": None,
            },
        )
        s["state"] = rec.get("state_after")
        s["count"] = rec.get("occurrence_count", s["count"])
        if rec.get("owner"):
            s["owner"] = rec["owner"]
        if rec.get("attempt_ref"):
            s["attempt_ref"] = rec["attempt_ref"]
        if rec.get("review_ref"):
            s["review_ref"] = rec["review_ref"]
        if rec.get("impossibility_ref"):
            s["impossibility_ref"] = rec["impossibility_ref"]
    return states


def _check_count_constraint(constraint: str, count: int) -> bool:
    m = re.match(r"^(==|>=|<=|>|<)(\d+)$", constraint)
    if not m:
        return False
    op, n = m.group(1), int(m.group(2))
    if op == "==":
        return count == n
    if op == ">=":
        return count >= n
    if op == "<=":
        return count <= n
    if op == ">":
        return count > n
    if op == "<":
        return count < n
    return False


def transition_allowed(
    *, kind: str, prior_state: Optional[str], state_after: str, count: int
) -> bool:
    for row in _load_state_machine():
        if row["kind"] != kind:
            continue
        ps = row["prior_state"]
        if ps != "*" and ps != prior_state:
            continue
        if row["state_after"] != state_after:
            continue
        if not _check_count_constraint(row.get("count_constraint", ">=1"), count):
            continue
        return True
    return False


def append_record(ledger_path: Path, record: dict) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    existing = (
        ledger_path.read_text(encoding="utf-8") if ledger_path.exists() else ""
    )
    if existing and not existing.endswith("\n"):
        existing += "\n"
    new_body = existing + json.dumps(record, ensure_ascii=False) + "\n"
    tmp = ledger_path.with_suffix(ledger_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(new_body)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, ledger_path)


def _read_existing_records(ledger_path: Path) -> list[dict]:
    if not ledger_path.exists():
        return []
    out: list[dict] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def build_record(
    *,
    text: str,
    kind: str,
    pr_ref: str,
    owner: Optional[str],
    attempt_ref: Optional[str],
    review_ref: Optional[str],
    impossibility_ref: Optional[str],
    state_after: str,
    occurrence_count: int,
    ts: Optional[str] = None,
) -> dict:
    if kind not in RECORD_KINDS:
        raise SystemExit(
            f"sticky-caveats: kind {kind!r} not in {sorted(RECORD_KINDS)}"
        )
    if state_after not in CAVEAT_STATES:
        raise SystemExit(
            f"sticky-caveats: state_after {state_after!r} not in "
            f"{sorted(CAVEAT_STATES)}"
        )
    canonical = canonicalize(text)
    fp = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    record: dict = {
        "ts": ts or _now_iso(),
        "kind": kind,
        "fingerprint": fp,
        "text": text,
        "canonical_text": canonical,
        "state_after": state_after,
        "occurrence_count": occurrence_count,
        "pr_ref": pr_ref,
    }
    if owner:
        record["owner"] = owner
    if attempt_ref:
        record["attempt_ref"] = attempt_ref
    if review_ref:
        record["review_ref"] = review_ref
    if impossibility_ref:
        record["impossibility_ref"] = impossibility_ref

    if kind == "caveat_promote_sticky" and not owner:
        raise SystemExit(
            "sticky-caveats: caveat_promote_sticky requires --owner"
        )
    if kind == "caveat_attempt_recorded" and not attempt_ref:
        raise SystemExit(
            "sticky-caveats: caveat_attempt_recorded requires --attempt-ref"
        )
    if kind == "caveat_review_recorded" and not review_ref:
        raise SystemExit(
            "sticky-caveats: caveat_review_recorded requires --review-ref"
        )
    if kind == "caveat_impossibility" and not impossibility_ref:
        raise SystemExit(
            "sticky-caveats: caveat_impossibility requires --impossibility-ref"
        )

    record["crc32"] = compute_crc32(record)
    return record


def derive_count_and_state(
    *, kind: str, prior: Optional[dict]
) -> tuple[int, str]:
    """Derive occurrence_count and state_after for the new record from prior state."""
    prior_count = prior["count"] if prior else 0
    prior_state = prior["state"] if prior else None

    if kind == "caveat_open":
        return 1, "disclosed"
    if kind == "caveat_recur":
        new_count = prior_count + 1
        if new_count <= 2:
            return new_count, "disclosed"
        if prior_state == "sticky" and new_count == 3:
            return new_count, "attempt_required"
        if prior_state == "attempt_required" and new_count >= 4:
            return new_count, "review_required"
        return new_count, prior_state or "disclosed"
    if kind == "caveat_promote_sticky":
        return max(prior_count, 2), "sticky"
    if kind == "caveat_attempt_recorded":
        return prior_count, "attempt_required"
    if kind == "caveat_review_recorded":
        return prior_count, "review_required"
    if kind == "caveat_close":
        return prior_count, "closed_evidence"
    if kind == "caveat_impossibility":
        return prior_count, "closed_impossibility"
    raise SystemExit(f"sticky-caveats: unknown kind {kind!r}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--text", required=True, help="Caveat text as written.")
    parser.add_argument(
        "--kind", required=True, choices=sorted(RECORD_KINDS)
    )
    parser.add_argument("--pr-ref", required=True)
    parser.add_argument("--owner", default=None)
    parser.add_argument("--attempt-ref", default=None)
    parser.add_argument("--review-ref", default=None)
    parser.add_argument("--impossibility-ref", default=None)
    parser.add_argument(
        "--ledger-path",
        default="out/sticky-caveats.jsonl",
        help="Path to the ledger file (default: out/sticky-caveats.jsonl).",
    )
    parser.add_argument("--ts", default=None)
    args = parser.parse_args(argv)

    ledger_path = Path(args.ledger_path)
    existing = _read_existing_records(ledger_path)
    states = replay(existing)
    fp = fingerprint_of(args.text)
    prior = states.get(fp)

    occurrence_count, state_after = derive_count_and_state(
        kind=args.kind, prior=prior
    )

    if not transition_allowed(
        kind=args.kind,
        prior_state=prior["state"] if prior else None,
        state_after=state_after,
        count=occurrence_count,
    ):
        print(
            f"sticky-caveats: illegal transition kind={args.kind} "
            f"prior_state={prior['state'] if prior else None} "
            f"state_after={state_after} count={occurrence_count}",
            file=sys.stderr,
        )
        return 2

    record = build_record(
        text=args.text,
        kind=args.kind,
        pr_ref=args.pr_ref,
        owner=args.owner or (prior["owner"] if prior else None),
        attempt_ref=args.attempt_ref,
        review_ref=args.review_ref,
        impossibility_ref=args.impossibility_ref,
        state_after=state_after,
        occurrence_count=occurrence_count,
        ts=args.ts,
    )
    append_record(ledger_path, record)

    line_count = len(ledger_path.read_text(encoding="utf-8").splitlines())
    print(
        f"sticky-caveats: appended line {line_count} to {ledger_path} "
        f"(fingerprint={fp[:8]} state={state_after} count={occurrence_count})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
