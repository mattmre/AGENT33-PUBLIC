#!/usr/bin/env python3
"""scripts/validate_carry_forward.py — project release gate CARRY_FORWARD validator.

Standalone validator for the `CARRY_FORWARD:` line in a PR body. Pinned by
issue #16 so adopters cannot quietly drop the `(category=<id>)` annotation
or reference a CD-### that does not exist in the carried-debt ledger.

Companion to scripts/validate_pr_brutal_honesty.py (R17/R18). This script
runs the same regex on the PR body line, then cross-checks each entry
against:
  - v3.5/docs/conventions/brutal-honesty-kit/v3.5/enums/bhs-core-categories.txt
    for the closed-set core_category vocabulary,
  - out/carried-debt.jsonl (if present) so a CD-### in the PR body matches
    a real ledger row,
  - the carry-forward-entry.schema.json for entry shape.

Inputs:
  --pr-body PATH   Path to PR body file.
  --ledger PATH    Path to carried-debt.jsonl (default: out/carried-debt.jsonl).

Exit codes:
  0 — all entries clean.
  1 — malformed entry (regex did not match `^CD-\\d{3,5}(\\(category=...\\))?$`).
  2 — unknown core_category (not 'none' and not in the enum).
  3 — cd_id not present in the carried-debt ledger.
  4 — category-vs-ledger mismatch (entry annotates category=X but ledger row
      has category=Y).
  5 — tooling error (file not found, malformed JSON ledger row).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


_ENUM_DIR = (
    Path(__file__).resolve().parent.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
    / "enums"
)


def _load_enum(filename: str) -> set[str]:
    path = _ENUM_DIR / filename
    values: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        values.add(stripped)
    return values


CORE_CATEGORIES = _load_enum("bhs-core-categories.txt")

# load-bearing: keep CORE_CATEGORIES digit-free — ENTRY_RE category subgroup is `[a-z_]+`,
# so a future enum addition with digits would silently fail to parse here.
ENTRY_RE = re.compile(r"^(CD-\d{3,5})(?:\(category=([a-z_]+)\))?$")
CARRY_LINE_RE = re.compile(
    r"^\s*>?\s*CARRY_FORWARD\s*:\s*(.*?)\s*$",
    re.MULTILINE,
)


def parse_entries(raw: str) -> list[tuple[str, str]]:
    """Return [(cd_id, category)] from a raw CARRY_FORWARD value.

    Empty / 'none' / 'empty' / 'n/a' returns []. Returns [(cd_id, '')] for
    a chunk that did not parse — the caller decides whether to FAIL.
    """
    if not raw or raw.strip().lower() in ("none", "empty", "n/a", ""):
        return []
    entries: list[tuple[str, str]] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = ENTRY_RE.match(chunk)
        if not m:
            entries.append((chunk, ""))  # caller flags as malformed
        else:
            entries.append((m.group(1), m.group(2) or "none"))
    return entries


def _read_ledger(path: Path) -> dict[str, str]:
    """Return {cd_id: core_category} from carried-debt.jsonl, or {} if absent."""
    if not path.exists():
        return {}
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            print(
                f"ERROR: ledger row not JSON: {exc}; line={line!r}",
                file=sys.stderr,
            )
            sys.exit(5)
        cd = obj.get("cd_id")
        if not isinstance(cd, str):
            continue
        rows[cd] = obj.get("core_category", "none")
    return rows


def validate_file(pr_body_path: Path, ledger_path: Path) -> int:
    if not pr_body_path.exists():
        print(f"ERROR: PR body not found: {pr_body_path}", file=sys.stderr)
        return 5
    body = pr_body_path.read_text(encoding="utf-8")
    m = CARRY_LINE_RE.search(body)
    if not m:
        print(
            f"ERROR: no CARRY_FORWARD: line in {pr_body_path}",
            file=sys.stderr,
        )
        return 1
    raw = m.group(1).strip()
    entries = parse_entries(raw)
    if not entries:
        # 'none' / empty — clean.
        print(f"PASS: CARRY_FORWARD is empty/none in {pr_body_path}")
        return 0

    ledger = _read_ledger(ledger_path)

    for cd_id, category in entries:
        if not category:
            print(
                f"FAIL [exit 1]: malformed CARRY_FORWARD entry "
                f"{cd_id!r} — expected 'CD-NNN' or "
                f"'CD-NNN(category=<id>)'.",
                file=sys.stderr,
            )
            return 1
        if category != "none" and category not in CORE_CATEGORIES:
            print(
                f"FAIL [exit 2]: {cd_id} core_category={category!r} not in "
                f"bhs-core-categories.txt and not 'none'. Allowed: "
                f"{sorted(CORE_CATEGORIES) + ['none']}.",
                file=sys.stderr,
            )
            return 2
        if ledger:
            if cd_id not in ledger:
                print(
                    f"FAIL [exit 3]: {cd_id} referenced in PR body but not "
                    f"present in {ledger_path}. Add the ledger row before "
                    f"opening the PR.",
                    file=sys.stderr,
                )
                return 3
            ledger_cat = ledger[cd_id]
            if ledger_cat != category:
                print(
                    f"FAIL [exit 4]: {cd_id} PR-body annotates "
                    f"category={category!r} but ledger row has "
                    f"category={ledger_cat!r}. The two must match.",
                    file=sys.stderr,
                )
                return 4

    print(
        f"PASS: {len(entries)} CARRY_FORWARD entr{'y' if len(entries)==1 else 'ies'} "
        f"validated against bhs-core-categories.txt"
        f"{' + carried-debt.jsonl' if ledger else ''}."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--pr-body", required=True, type=Path, help="Path to PR body file."
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path("out/carried-debt.jsonl"),
        help="Path to carried-debt.jsonl (default: out/carried-debt.jsonl).",
    )
    args = parser.parse_args()
    return validate_file(args.pr_body, args.ledger)


if __name__ == "__main__":
    sys.exit(main())
