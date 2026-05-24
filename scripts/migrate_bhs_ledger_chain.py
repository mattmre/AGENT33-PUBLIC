#!/usr/bin/env python3
"""scripts/migrate_bhs_ledger_chain.py — one-shot CRC32-chain back-fill.

v3.7 carry-debt #3b (chain-CRC migration tool):

The v3.6 carry-debt Lane 7 work taught `validate_bhs_ledger.py` to walk
an optional `crc32_prev` chain across every row of a ledger so a silent
mid-history deletion (which per-row CRC alone cannot detect) trips
exit-code 2. v3.7 #3a then taught `bhs_ledger_append.py` to EMIT chained
rows. But legacy ledgers written before v3.7 still carry no
`crc32_prev` fields. This one-shot tool back-fills the chain over an
existing legacy ledger so it can be extended via the chain-aware
appender going forward.

Chain semantics (must match validate_bhs_ledger.py and bhs_ledger_append.py):

  * Serialize each row with sorted keys, ``(",", ":")`` separators,
    excluding the ``crc32`` field itself.
  * ``binascii.crc32(serialized.encode("utf-8"))`` formatted as a
    lowercase 8-hex string.
  * First row's ``crc32_prev = "00000000"``.
  * Each subsequent row's ``crc32_prev`` == prior row's recomputed
    ``crc32``.

The tool is idempotent: a ledger that is already chained passes through
unchanged (each row's existing ``crc32_prev`` is overwritten with the
recomputed value, which by definition equals what was already there).

Modes:

  --dry-run           Print the proposed migrated content to stderr; do
                      not touch the file. Exits 0 even if changes would
                      be made (this is a "show diff" mode).
  --in-place          Rewrite the ledger in place; copy the pre-chain
                      original to ``<ledger>.pre-chain-bak`` first so
                      an operator can roll back if needed.
  (neither flag)      Print the migrated content to stdout; do not
                      touch the file. Useful for piping into `diff`.

Exit codes (v3.6 5-class policy):

  0  EXIT_OK         migration succeeded (or dry-run completed)
  1  EXIT_DRIFT      (reserved; not used by this tool)
  2  EXIT_SCHEMA     (reserved; not used by this tool)
  3  EXIT_ENUM       (reserved; not used by this tool)
  4  EXIT_CHAIN      (reserved; this tool cannot produce a chain error
                       because it BUILDS the chain)
  5  EXIT_CORRUPTION source ledger could not be parsed (invalid JSON on
                       any row, or argparse / IO error reaching the
                       file at all)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

# Reuse the canonical compute_crc32 / chain-seed constant from the
# appender so the two scripts can never drift on serialization rules.
_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))
from bhs_ledger_append import (  # noqa: E402
    CHAIN_SEED,
    compute_crc32,
)


EXIT_OK = 0
EXIT_CORRUPTION = 5


def build_migrated_rows(rows: list[dict]) -> list[dict]:
    """Return a new list of rows with `crc32_prev` + recomputed `crc32`.

    Idempotent: applying the function twice yields the same output as
    applying it once. The function does NOT validate enum membership,
    schema, or max-delta -- those are the validator's job and would
    risk refusing to migrate a ledger that is otherwise readable.
    """
    migrated: list[dict] = []
    prev_crc = CHAIN_SEED
    for row in rows:
        # Strip both the prior `crc32` and any stale `crc32_prev` so the
        # canonical serialization is deterministic regardless of how the
        # input row was authored.
        # Strip without re-validation: intentional per ``build_migrated_rows``
        # docstring (this function) -- enum / schema / max-delta checks are the
        # validator's job (``validate_bhs_ledger.py``); the downstream chain
        # rebuild below is the source of truth, and per-row CRC is recomputed
        # at emit so a previously-malformed crc32 field on input is fixed up.
        new_row = {k: v for k, v in row.items() if k not in ("crc32", "crc32_prev")}
        new_row["crc32_prev"] = prev_crc
        new_row["crc32"] = compute_crc32(new_row)
        migrated.append(new_row)
        prev_crc = new_row["crc32"]
    return migrated


def _read_source(ledger_path: Path) -> list[dict]:
    """Parse `ledger_path` into rows; raise SystemExit(5) on bad JSON."""
    if not ledger_path.exists():
        print(
            f"ERROR: ledger file not found: {ledger_path}",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_CORRUPTION)
    rows: list[dict] = []
    for idx, line in enumerate(
        ledger_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(
                f"ERROR: line {idx}: invalid JSON: {exc}",
                file=sys.stderr,
            )
            raise SystemExit(EXIT_CORRUPTION) from exc
    return rows


def _serialize(rows: list[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def _write_atomic(ledger_path: Path, body: str) -> None:
    """Write `body` to `ledger_path` via tmp + fsync + atomic rename."""
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = ledger_path.with_suffix(ledger_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(body)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, ledger_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--ledger",
        required=True,
        help="Path to the bhs-ledger.jsonl file to back-fill.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the proposed migrated content to stderr; do not "
            "touch the file. Exits 0."
        ),
    )
    mode.add_argument(
        "--in-place",
        action="store_true",
        help=(
            "Rewrite the ledger in place. Backs the original up to "
            "<ledger>.pre-chain-bak first."
        ),
    )
    args = parser.parse_args(argv)

    ledger_path = Path(args.ledger)
    try:
        rows = _read_source(ledger_path)
    except SystemExit as exc:
        # _read_source already printed the diagnostic.
        return int(exc.code) if exc.code is not None else EXIT_CORRUPTION

    migrated = build_migrated_rows(rows)
    body = _serialize(migrated)

    if args.dry_run:
        print(
            f"-- dry-run: would migrate {len(migrated)} row(s) in "
            f"{ledger_path} --",
            file=sys.stderr,
        )
        sys.stderr.write(body)
        return EXIT_OK

    if args.in_place:
        backup = ledger_path.with_suffix(
            ledger_path.suffix + ".pre-chain-bak"
        )
        if ledger_path.exists():
            shutil.copy2(ledger_path, backup)
        _write_atomic(ledger_path, body)
        print(
            f"migrate-bhs-ledger-chain: rewrote {ledger_path} "
            f"({len(migrated)} row(s)); backup at {backup}",
            file=sys.stderr,
        )
        return EXIT_OK

    # Default: stdout mode.
    sys.stdout.write(body)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
