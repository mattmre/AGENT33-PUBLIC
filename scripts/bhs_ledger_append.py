#!/usr/bin/env python3
"""scripts/bhs_ledger_append.py — append one record to out/bhs-ledger.jsonl.

Issue #37: every BHS score change MUST be backed by a structured ledger
record. This script is the only sanctioned writer. It refuses any delta
larger than 10 in a single record (rulebook §6.2 mechanical rule that
replaces the v3.2 ">95 self-score is suspicious" prose bullet).

Write protocol mirrors the v3.3 carried-debt.jsonl pattern: write
tmp + fsync + atomic rename. crc32 is computed over the JSON-serialized
record body excluding the crc32 field itself, per
v3.5/docs/conventions/brutal-honesty-kit/v3.5/tables/bhs-ledger-write-protocol.yaml.

v3.7 carry-debt #3a (chain-CRC write-side support):
  The optional `--chain` flag makes the appender chain-aware. When ON,
  the new row's `crc32_prev` is set to the prior row's `crc32` (or the
  sentinel "00000000" if the ledger is empty), and the new row's own
  `crc32` is recomputed over the chained body. v3.6 Lane 7 already
  taught `validate_bhs_ledger.py` how to walk that chain; this lane
  closes the bootstrap loop by giving the official appender a way to
  emit chained rows in the first place.

  Two guards protect operators from accidentally breaking an in-flight
  chain (or seeding a chain on top of a legacy non-chained file):

    * `--chain` OFF appending to a chained ledger ⇒ exit 4 (CHAIN). The
      next chain-aware reader would have flagged this as a silent
      mid-history deletion; refusing up-front is friendlier.
    * `--chain` ON appending to a non-empty non-chained ledger ⇒ exit 4
      unless `--migrate-on-first-chain-write` is also passed. The flag
      back-fills `crc32_prev` over the existing rows (via the one-shot
      `migrate_bhs_ledger_chain.py` migration tool) so the appended row
      lands on top of a freshly-chained base.

Exit codes:
  0 — appended cleanly
  1 — argparse / IO error
  2 — delta exceeds max (10 points in a single record)
  3 — enum violation (record_kind, criterion, or evidence_kind not in the
       canonical lists)
  4 — CHAIN error (v3.6 5-class policy, v3.7 #3a): `--chain` off against
       a chained ledger, or `--chain` on against a non-chained ledger
       without `--migrate-on-first-chain-write`
"""

from __future__ import annotations

import argparse
import binascii
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Iterable


_ENUM_DIR = (
    Path(__file__).resolve().parent.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
    / "enums"
)


def _load_enum(filename: str) -> set[str]:
    values: set[str] = set()
    for line in (_ENUM_DIR / filename).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            values.add(stripped)
    return values


RECORD_KINDS = _load_enum("bhs-ledger-record-kinds.txt")
CRITERIA = _load_enum("bhs-ledger-criteria.txt")
EVIDENCE_KINDS = _load_enum("bhs-ledger-evidence-kinds.txt")

MAX_DELTA_IN_SINGLE_RECORD = 10

# v3.7 #3a -- canonical seed for the first row of a chained ledger.
CHAIN_SEED = "00000000"

# v3.6 5-class exit-code policy alias (Lane 2 standardized; restated
# here so a downstream change to the policy table does not silently
# desync this script). The legacy 0/1/2/3 codes above stay put for
# back-compat with existing callers; 4 is the new CHAIN class.
EXIT_OK = 0
EXIT_IO = 1
EXIT_MAX_DELTA = 2
EXIT_ENUM = 3
EXIT_CHAIN = 4


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
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{_dt.datetime.now(_dt.timezone.utc).microsecond // 1000:03d}Z"
    )


def append_record(
    ledger_path: Path,
    record: dict,
) -> None:
    """Append `record` to `ledger_path` via tmp+fsync+atomic-rename."""
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    existing = ledger_path.read_text(encoding="utf-8") if ledger_path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    new_body = existing + json.dumps(record, ensure_ascii=False) + "\n"
    tmp = ledger_path.with_suffix(ledger_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(new_body)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, ledger_path)


def _read_existing_rows(ledger_path: Path) -> list[dict]:
    """Parse all non-blank lines of `ledger_path` as JSON records.

    Returns an empty list if the file does not exist. Used by the
    chain-aware code path to inspect the last row before appending.
    """
    if not ledger_path.exists():
        return []
    rows: list[dict] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def _write_rows_atomic(ledger_path: Path, rows: list[dict]) -> None:
    """Overwrite `ledger_path` with `rows`, one JSON object per line.

    Uses the same tmp + fsync + atomic-rename protocol as `append_record`.
    Used by `--migrate-on-first-chain-write` after the migration tool
    rewrites the ledger in-memory so we never leave a half-written file
    on disk.
    """
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    tmp = ledger_path.with_suffix(ledger_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(body)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, ledger_path)


def _is_chained_row(row: dict) -> bool:
    """A row "participates in the chain" iff it carries `crc32_prev`.

    Legacy rows written before v3.7 #3a (or by `--chain` OFF callers)
    do NOT carry the field; chain-aware appenders / the migration tool
    always do.
    """
    return "crc32_prev" in row


def _chain_for_next_row(last_row: dict | None) -> str:
    """Return the `crc32_prev` value the NEXT chained row should carry.

    On an empty ledger this is the sentinel ``"00000000"``. Otherwise
    it is the prior row's ``crc32`` -- which the prior row either
    declared directly or we recompute defensively if a callsite stripped
    it (the appender always emits it, but the migration tool may have
    just rebuilt it in-place).
    """
    if last_row is None:
        return CHAIN_SEED
    declared = last_row.get("crc32")
    if declared:
        return declared
    return compute_crc32(last_row)


def build_record(
    *,
    pr_ref: str,
    record_kind: str,
    criterion: str,
    delta_from: int,
    delta_to: int,
    evidence_kind: str,
    evidence_ref: str,
    why_other_unchanged: Iterable[str],
    reviewer_agent: str,
    ts: str | None = None,
    crc32_prev: str | None = None,
) -> dict:
    if record_kind not in RECORD_KINDS:
        raise SystemExit(
            f"bhs-ledger: record_kind {record_kind!r} not in {sorted(RECORD_KINDS)}"
        )
    if criterion not in CRITERIA:
        raise SystemExit(
            f"bhs-ledger: criterion {criterion!r} not in {sorted(CRITERIA)}"
        )
    if evidence_kind not in EVIDENCE_KINDS:
        raise SystemExit(
            f"bhs-ledger: evidence_kind {evidence_kind!r} not in {sorted(EVIDENCE_KINDS)}"
        )
    if record_kind == "score_init" and delta_from != 0:
        raise SystemExit(
            f"bhs-ledger: score_init requires delta_from == 0; got {delta_from}"
        )
    if record_kind == "score_unchanged_iteration" and delta_from != delta_to:
        raise SystemExit(
            "bhs-ledger: score_unchanged_iteration requires delta_from == delta_to; "
            f"got {delta_from} → {delta_to}"
        )
    if record_kind == "score_raise" and delta_to <= delta_from:
        raise SystemExit(
            f"bhs-ledger: score_raise requires delta_to > delta_from; "
            f"got {delta_from} → {delta_to}"
        )
    if record_kind == "score_lower" and delta_to >= delta_from:
        raise SystemExit(
            f"bhs-ledger: score_lower requires delta_to < delta_from; "
            f"got {delta_from} → {delta_to}"
        )
    if record_kind in ("score_raise", "score_lower"):
        if abs(delta_to - delta_from) > MAX_DELTA_IN_SINGLE_RECORD:
            print(
                f"bhs-ledger: refusing to append; delta "
                f"{abs(delta_to - delta_from)} > max {MAX_DELTA_IN_SINGLE_RECORD} "
                "in a single record. Split across multiple records, each citing "
                "distinct evidence.",
                file=sys.stderr,
            )
            raise SystemExit(2)

    record: dict = {
        "ts": ts or _now_iso(),
        "record_kind": record_kind,
        "pr_ref": pr_ref,
        "criterion": criterion,
        "delta_from": delta_from,
        "delta_to": delta_to,
        "evidence_kind": evidence_kind,
        "evidence_ref": evidence_ref,
        "why_other_unchanged": list(why_other_unchanged),
        "reviewer_agent": reviewer_agent,
    }
    if crc32_prev is not None:
        # Insert chain link BEFORE the crc32 hash so the canonical
        # serialization (compute_crc32 excludes only `crc32`) covers it.
        record["crc32_prev"] = crc32_prev
    record["crc32"] = compute_crc32(record)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pr-ref", required=True)
    parser.add_argument(
        "--record-kind", required=True, choices=sorted(RECORD_KINDS)
    )
    parser.add_argument(
        "--criterion", required=True, choices=sorted(CRITERIA)
    )
    parser.add_argument("--delta-from", type=int, required=True)
    parser.add_argument("--delta-to", type=int, required=True)
    parser.add_argument(
        "--evidence-kind", required=True, choices=sorted(EVIDENCE_KINDS)
    )
    parser.add_argument("--evidence-ref", required=True)
    parser.add_argument(
        "--why-other-unchanged",
        action="append",
        default=[],
        help="One-line reason per unchanged criterion; may be passed multiple times.",
    )
    parser.add_argument("--reviewer-agent", required=True)
    parser.add_argument(
        "--ledger-path",
        default="out/bhs-ledger.jsonl",
        help="Path to the ledger file (default: out/bhs-ledger.jsonl, CWD-relative).",
    )
    parser.add_argument(
        "--ts",
        default=None,
        help="Override timestamp (ISO-8601 UTC, ms precision). Default: now.",
    )
    parser.add_argument(
        "--chain",
        action="store_true",
        help=(
            "Emit a chained row (carries `crc32_prev` pointing at the prior "
            "row's `crc32`, or '00000000' on an empty ledger). v3.7 #3a."
        ),
    )
    parser.add_argument(
        "--migrate-on-first-chain-write",
        action="store_true",
        help=(
            "Permitted only with --chain. When the existing ledger is "
            "non-empty and NOT yet chained, back-fill `crc32_prev` over "
            "every existing row first (delegates to "
            "scripts/migrate_bhs_ledger_chain.py), then append the new "
            "chained row. No-op if the ledger is empty or already chained."
        ),
    )
    args = parser.parse_args(argv)

    ledger_path = Path(args.ledger_path)

    # v3.7 #3a: chain-aware preflight.
    # Both guards run BEFORE build_record so we never compute a crc32 on
    # a row we are going to refuse to write.
    existing_rows = _read_existing_rows(ledger_path)
    last_row = existing_rows[-1] if existing_rows else None
    last_is_chained = last_row is not None and _is_chained_row(last_row)

    if not args.chain and last_is_chained:
        # Guard 1: silent chain break -- appending an un-chained row on
        # top of a chained ledger would trip the validator's mixed-mode
        # check at read time. Refuse loudly here instead.
        print(
            f"bhs-ledger: refusing to append; ledger {ledger_path} is "
            "chain-aware (last row carries `crc32_prev`) but --chain was "
            "not passed. Re-run with --chain to extend the chain. "
            "(v3.7 #3a)",
            file=sys.stderr,
        )
        return EXIT_CHAIN

    if args.migrate_on_first_chain_write and not args.chain:
        print(
            "bhs-ledger: --migrate-on-first-chain-write requires --chain.",
            file=sys.stderr,
        )
        return EXIT_IO

    if args.chain and existing_rows and not last_is_chained:
        # Guard 2: bootstrapping the chain on top of legacy rows MUST be
        # opt-in. Without --migrate-on-first-chain-write the operator
        # gets a clear error pointing them at the migration tool; WITH
        # the flag we back-fill in-place first.
        if not args.migrate_on_first_chain_write:
            print(
                f"bhs-ledger: refusing to append; ledger {ledger_path} "
                "has existing rows without `crc32_prev`. Either re-run "
                "with --migrate-on-first-chain-write to back-fill the "
                "chain before appending, or run "
                "`python -m scripts.migrate_bhs_ledger_chain --ledger "
                f"{ledger_path} --in-place` first. (v3.7 #3a)",
                file=sys.stderr,
            )
            return EXIT_CHAIN

        # Back-fill in-place via the migration tool. We import lazily so
        # this script still works if the migration tool is uninstalled
        # in a non-chain workflow.
        import importlib.util

        migrate_path = Path(__file__).resolve().parent / (
            "migrate_bhs_ledger_chain.py"
        )
        spec = importlib.util.spec_from_file_location(
            "_bhs_migrate_chain", migrate_path
        )
        if spec is None or spec.loader is None:  # pragma: no cover
            print(
                "bhs-ledger: cannot locate migrate_bhs_ledger_chain.py "
                "(required by --migrate-on-first-chain-write).",
                file=sys.stderr,
            )
            return EXIT_IO
        migrate_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migrate_mod)
        migrated = migrate_mod.build_migrated_rows(existing_rows)
        _write_rows_atomic(ledger_path, migrated)
        # Refresh in-memory view so the new row links to the freshly
        # back-filled tail.
        existing_rows = migrated
        last_row = existing_rows[-1]

    crc32_prev: str | None = None
    if args.chain:
        crc32_prev = _chain_for_next_row(last_row)

    record = build_record(
        pr_ref=args.pr_ref,
        record_kind=args.record_kind,
        criterion=args.criterion,
        delta_from=args.delta_from,
        delta_to=args.delta_to,
        evidence_kind=args.evidence_kind,
        evidence_ref=args.evidence_ref,
        why_other_unchanged=args.why_other_unchanged,
        reviewer_agent=args.reviewer_agent,
        ts=args.ts,
        crc32_prev=crc32_prev,
    )
    append_record(ledger_path, record)

    existing_count = len(
        ledger_path.read_text(encoding="utf-8").splitlines()
    )
    print(f"bhs-ledger: appended line {existing_count} to {ledger_path}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
