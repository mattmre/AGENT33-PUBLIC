#!/usr/bin/env python3
"""scripts/validate_bhs_ledger.py — verify out/bhs-ledger.jsonl integrity.

Issue #37: enforce schema, crc32, max-delta-10, and enum membership on
every record in the ledger. The validator is the mechanical backstop
for rulebook §6.2's claim that BHS deltas are reviewable.

Exit codes (v3.7-final FULLY aligned with the 5-class operator policy
``0=ok / 1=drift / 2=schema / 3=enum / 4=chain / 5=corruption``; see
``v3.5/tier-b-bhs/pass-2-synthesis.md`` §M-2 and the v3.7-final HP-H
close-stamp at ``v3.5/tier-b-bhs/v3.7-final-hp-h-close-stamp.md``):

  0 — EXIT_OK         every record valid
  1 — EXIT_DRIFT      schema violation (missing required field, wrong
                      type, oneOf failure) OR max-delta exceeded in a
                      single record (rulebook §6.2). Both are
                      contract-shape drifts -- the ledger row is well
                      formed JSON whose values drift from the contract.
  2 — EXIT_SCHEMA     per-row crc32 mismatch -- the row body itself is
                      malformed because its declared `crc32` no longer
                      matches a recomputation over its serialized body.
                      Distinct from EXIT_DRIFT because no field is missing
                      or wrong type; the integrity check on the row body
                      failed.
  3 — EXIT_ENUM       enum violation (record_kind / criterion /
                      evidence_kind unknown). Was integer 4 prior to
                      v3.7-final HP-H; the prior overload of 4 between
                      ENUM and CHAIN was the R2 HP-C-N2 finding.
  4 — EXIT_CHAIN      chain-CRC violation (an optional `crc32_prev` link
                      does NOT match the prior row's `crc32` -- silent
                      mid-history deletion / tamper; first row's
                      `crc32_prev` is not the canonical seed; or a prior
                      row opted into the chain but this row dropped the
                      field).
  5 — EXIT_CORRUPTION expectation mismatch (--expect-* flags do not match
                      the ledger). Treated as corruption from the
                      orchestrator's perspective because the operator
                      asserted a fact about the ledger that the file
                      contradicts -- either the file was tampered with
                      or the orchestrator's claim is wrong; either way
                      the workflow cannot proceed.
  6 — IO / argparse error (out-of-band of the 5-class data policy).

The 5-class alignment is complete at v3.7-final HP-H. Prior to the
HP-H retrofit, max-delta returned 3 (overlapping with EXIT_ENUM in the
policy) and enum returned 4 (overlapping with EXIT_CHAIN). The R2
HP-C-N2 finding identified the cross-wire; HP-H closes it by routing
enum to integer 3 and max-delta to integer 1 (EXIT_DRIFT), matching
the policy table exactly.

Chain CRC verification (v3.6 carry-debt, MEDIUM-rollup cluster B;
v3.7-final M-2 retrofit, HP-H 5-class completion):

  When a ledger row carries an optional `crc32_prev` field, the validator
  walks the rows in file order and asserts each `crc32_prev` equals the
  prior row's `crc32` (the first row's `crc32_prev` MUST be `00000000`).
  This is the standard chained-CRC pattern shipped by check_research_sources
  / check_external_policy / check_workspace_hygiene — re-stated here so a
  silent mid-history deletion (which per-row CRC alone cannot detect) trips
  exit-code 4 (EXIT_CHAIN). The field is OPTIONAL for back-compat with v3.5
  ledgers written before the chain was wired; mixed-mode files (some rows
  with `crc32_prev`, some without) treat the absence as "chain break at
  this point" and FAIL with exit-code 4 (EXIT_CHAIN).

  v3.7-final M-2: chain-CRC violations previously returned exit-code 2
  (SCHEMA-class), conflating chain breaks with per-row CRC malformation.
  The retrofit aligns this validator with ``bhs_ledger_append.py`` and
  ``migrate_bhs_ledger_chain.py`` which already emit class 4 for chain
  errors. Per-row CRC stays at class 2 (SCHEMA) -- the row body is
  malformed in that case, which is by definition a schema concern.

  v3.7-final HP-H: integer 4 is now EXIT_CHAIN ONLY. Enum violations
  (previously also integer 4) move to integer 3 (EXIT_ENUM) so the
  policy table has no overloaded slots.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

try:
    from jsonschema import Draft202012Validator
except ImportError:
    print(
        "ERROR: jsonschema is required (pip install jsonschema). "
        "See v3.5/INSTALL.md.",
        file=sys.stderr,
    )
    sys.exit(6)

# Re-use crc32 + enum loading from the append helper so the two scripts
# share one definition.
_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))
from bhs_ledger_append import (  # noqa: E402
    CRITERIA,
    EVIDENCE_KINDS,
    EXIT_CHAIN,
    EXIT_ENUM,
    MAX_DELTA_IN_SINGLE_RECORD,
    RECORD_KINDS,
    compute_crc32,
)

# v3.7-final HP-H 5-class operator policy alignment
# (``0=ok / 1=drift / 2=schema / 3=enum / 4=chain / 5=corruption``).
# `bhs_ledger_append.py` is the cross-script source of truth for
# `EXIT_ENUM` (integer 3) and `EXIT_CHAIN` (integer 4); both are
# imported above so a future renumbering on either side trips an
# ImportError, not a silent semantic drift. `EXIT_DRIFT` (integer 1)
# and `EXIT_SCHEMA` (integer 2) are defined locally here because the
# appender does not emit those classes (its `EXIT_IO = 1` and
# `EXIT_MAX_DELTA = 2` are appender-side semantics; validation is a
# read-side concern with a different policy table). `EXIT_CORRUPTION`
# (integer 5) is the same shape as the constant of the same name in
# `migrate_bhs_ledger_chain.py:73`. The integers themselves match the
# canonical 5-class table used by every other gate; the gates carrying
# the same `EXIT_SCHEMA = 2` literal are (line-number-free per
# HP-L anti-drift convention — grep
# `^EXIT_SCHEMA\s*=\s*2$` under `v3.5/scripts/` to locate):
# `check_external_policy.py`, `check_research_sources.py`,
# `check_workspace_hygiene.py`, `validate_lane_consistency.py`,
# `validate_charter_merge_log.py`, `validate_score_trajectory.py`.
EXIT_DRIFT = 1
EXIT_SCHEMA = 2
EXIT_CORRUPTION = 5

_SCHEMA_PATH = (
    _SCRIPTS_DIR.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
    / "schemas"
    / "bhs-ledger.schema.json"
)


def _load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_file(
    ledger_path: Path,
    *,
    expect_pr_ref: Optional[str] = None,
    expect_line: Optional[int] = None,
    expect_delta_to: Optional[int] = None,
) -> int:
    if not ledger_path.exists():
        print(f"ERROR: ledger file not found: {ledger_path}", file=sys.stderr)
        return 6

    schema = _load_schema()
    validator = Draft202012Validator(schema)

    raw = ledger_path.read_text(encoding="utf-8").splitlines()
    records: list[dict] = []
    # Chain-CRC state: tracks the expected `crc32_prev` for the next row.
    # First row MUST have crc32_prev == "00000000" if the chain is in use.
    # `chain_active` flips to True the first time a row carries crc32_prev;
    # once active, every subsequent row MUST carry it (mixed-mode is L4).
    chain_prev_expected = "00000000"
    chain_active = False
    for idx, line in enumerate(raw, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            print(
                f"ERROR: line {idx}: invalid JSON: {exc}",
                file=sys.stderr,
            )
            return EXIT_DRIFT

        # Enum checks BEFORE schema validation so we can return a more
        # specific exit code for enum drift.
        # v3.7-final HP-H: enum violations route to EXIT_ENUM (integer 3)
        # per the 5-class operator policy. Was integer 4 prior to HP-H,
        # overlapping with EXIT_CHAIN -- the cross-wire R2 HP-C-N2 flagged.
        if record.get("record_kind") not in RECORD_KINDS:
            print(
                f"ERROR: line {idx}: record_kind "
                f"{record.get('record_kind')!r} not in {sorted(RECORD_KINDS)}",
                file=sys.stderr,
            )
            return EXIT_ENUM
        if record.get("criterion") not in CRITERIA:
            print(
                f"ERROR: line {idx}: criterion "
                f"{record.get('criterion')!r} not in {sorted(CRITERIA)}",
                file=sys.stderr,
            )
            return EXIT_ENUM
        if record.get("evidence_kind") not in EVIDENCE_KINDS:
            print(
                f"ERROR: line {idx}: evidence_kind "
                f"{record.get('evidence_kind')!r} not in {sorted(EVIDENCE_KINDS)}",
                file=sys.stderr,
            )
            return EXIT_ENUM

        errors = sorted(validator.iter_errors(record), key=lambda e: e.path)
        if errors:
            print(
                f"ERROR: line {idx}: schema violation: "
                f"{'; '.join(e.message for e in errors)}",
                file=sys.stderr,
            )
            return EXIT_DRIFT

        # crc32 check (per-row body): a row whose declared crc32 does
        # not match a recomputation over its serialized body is
        # malformed and trips EXIT_SCHEMA (5-class policy class 2).
        declared = record.get("crc32", "")
        recomputed = compute_crc32(record)
        if declared != recomputed:
            print(
                f"ERROR: line {idx}: crc32 mismatch "
                f"(declared {declared!r}, recomputed {recomputed!r})",
                file=sys.stderr,
            )
            return EXIT_SCHEMA

        # Chain CRC verification (v3.6 carry-debt, MEDIUM-rollup cluster B;
        # v3.7-final M-2 retrofit).
        # Detects silent mid-history record deletion that per-row CRC alone
        # cannot catch. The crc32_prev field is OPTIONAL on the first row's
        # absence (pre-chain ledgers stay valid), but the moment ANY row
        # carries it, every subsequent row in the file MUST also carry it
        # AND the link MUST match the prior row's crc32 (first row's
        # crc32_prev MUST be "00000000"). Mixed-mode is treated as a chain
        # break and FAILs with EXIT_CHAIN (5-class policy class 4) --
        # this aligns with bhs_ledger_append.py + migrate_bhs_ledger_chain.py
        # which already emit class 4 for chain-class errors.
        chain_prev = record.get("crc32_prev")
        if chain_prev is not None:
            if not chain_active and chain_prev != "00000000":
                # First row claiming chain participation MUST seed with
                # the canonical sentinel.
                print(
                    f"ERROR: line {idx}: chain CRC seed mismatch "
                    f"(declared crc32_prev={chain_prev!r}, expected "
                    f"'00000000' for first chained row)",
                    file=sys.stderr,
                )
                return EXIT_CHAIN
            if chain_prev != chain_prev_expected:
                print(
                    f"ERROR: line {idx}: chain CRC mismatch "
                    f"(declared crc32_prev={chain_prev!r}, expected "
                    f"{chain_prev_expected!r} -- a mid-history record "
                    f"may have been silently removed)",
                    file=sys.stderr,
                )
                return EXIT_CHAIN
            chain_active = True
            chain_prev_expected = declared
        elif chain_active:
            # A prior row opted into the chain; this row dropped the field.
            # That is structurally a chain break -- a deleted-then-replaced
            # row would look exactly like this.
            print(
                f"ERROR: line {idx}: chain CRC break "
                f"(prior row carried crc32_prev but this row does not; "
                f"mixed-mode ledgers are L4)",
                file=sys.stderr,
            )
            return EXIT_CHAIN

        # max-delta-10 check (only for raise/lower — schema invariants make
        # init/unchanged unconditional)
        # v3.7-final HP-H: max-delta routes to EXIT_DRIFT (integer 1) per
        # the 5-class operator policy. Was integer 3 prior to HP-H,
        # overlapping with EXIT_ENUM in the policy table. Max-delta is a
        # contract-bound drift -- the row is well-formed JSON whose
        # numeric value drifts past the rulebook §6.2 ceiling, which is
        # the canonical "drift" semantic in the 5-class table.
        if record["record_kind"] in ("score_raise", "score_lower"):
            delta = abs(record["delta_to"] - record["delta_from"])
            if delta > MAX_DELTA_IN_SINGLE_RECORD:
                print(
                    f"ERROR: line {idx}: delta {delta} > max "
                    f"{MAX_DELTA_IN_SINGLE_RECORD} in a single record",
                    file=sys.stderr,
                )
                return EXIT_DRIFT

        records.append(record)

    # --expect-* checks: confirm the referenced line is what the caller said
    # it would be. Used by validate_pr_brutal_honesty.py R12 cross-check.
    # v3.7-final HP-H: --expect-* mismatches route to EXIT_CORRUPTION
    # (integer 5) per the 5-class operator policy. Integer is unchanged
    # from the prior implementation; the rename ties the integer to the
    # canonical 5-class name so future readers see the policy-class
    # mapping without consulting the docstring table.
    if expect_line is not None:
        if not (1 <= expect_line <= len(records)):
            print(
                f"ERROR: --expect-line {expect_line} out of range "
                f"[1, {len(records)}]",
                file=sys.stderr,
            )
            return EXIT_CORRUPTION
        target = records[expect_line - 1]
        if expect_pr_ref is not None and target.get("pr_ref") != expect_pr_ref:
            print(
                f"ERROR: --expect-pr-ref mismatch on line {expect_line}: "
                f"got {target.get('pr_ref')!r}, want {expect_pr_ref!r}",
                file=sys.stderr,
            )
            return EXIT_CORRUPTION
        if expect_delta_to is not None and target.get("delta_to") != expect_delta_to:
            print(
                f"ERROR: --expect-delta-to mismatch on line {expect_line}: "
                f"got {target.get('delta_to')}, want {expect_delta_to}",
                file=sys.stderr,
            )
            return EXIT_CORRUPTION

    print(f"RESULT: PASS - {len(records)} ledger record(s) verified.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--file",
        default="out/bhs-ledger.jsonl",
        help="Path to the ledger file (default: out/bhs-ledger.jsonl).",
    )
    parser.add_argument("--expect-pr-ref", default=None)
    parser.add_argument("--expect-line", type=int, default=None)
    parser.add_argument("--expect-delta-to", type=int, default=None)
    args = parser.parse_args(argv)
    return validate_file(
        Path(args.file),
        expect_pr_ref=args.expect_pr_ref,
        expect_line=args.expect_line,
        expect_delta_to=args.expect_delta_to,
    )


if __name__ == "__main__":
    sys.exit(main())
