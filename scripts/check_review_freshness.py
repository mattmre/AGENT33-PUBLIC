#!/usr/bin/env python3
"""scripts/check_review_freshness.py -- live cross-check for R48 (issue #23).

Standalone helper that mirrors validate_pr_brutal_honesty.py R48c's
freshness gate but without dragging in the full PR-body validator. Tier
B reviewers can run it independently to confirm a PR body's
BHS_TIER_B_REVIEW_SHA equals the current HEAD before signing off on a
score raise.

Inputs:
  --body PATH        Path to PR body file (use '-' for stdin).
  --head-sha SHA     40-hex commit SHA naming HEAD. Optional. When
                     omitted, falls back to `git rev-parse HEAD`.

Output (one line on stdout):
  fresh: BHS_TIER_B_REVIEW_SHA equals HEAD; safe to raise the score.
  stale: SHA mismatch; re-run the Tier B review at HEAD.
  ambiguous: HEAD unresolvable OR a required field is missing/malformed.

Exit codes:
  0 -- fresh
  1 -- stale
  2 -- ambiguous (cannot tell)

Stdlib only -- no imports beyond argparse / re / subprocess / sys.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


_FIELD_RE = re.compile(
    r"^\s*>?\s*([A-Z][A-Z0-9_]+)\s*:[ \t]*(.*?)[ \t]*$",
    re.MULTILINE,
)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def parse_fields(body: str) -> dict:
    fields: dict = {}
    for m in _FIELD_RE.finditer(body):
        fields[m.group(1)] = m.group(2)
    return fields


def resolve_head_sha(head_sha_arg: Optional[str]) -> Optional[str]:
    if head_sha_arg:
        candidate = head_sha_arg.strip().lower()
        return candidate if _SHA_RE.match(candidate) else None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, OSError):
        return None
    candidate = result.stdout.strip().lower()
    return candidate if _SHA_RE.match(candidate) else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--body", required=True,
        help="Path to PR body file (use '-' for stdin).",
    )
    parser.add_argument(
        "--head-sha", default=None,
        help="40-hex HEAD commit SHA. Falls back to `git rev-parse HEAD`.",
    )
    args = parser.parse_args()

    if args.body == "-":
        body = sys.stdin.read()
    else:
        try:
            body = Path(args.body).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"ambiguous: cannot read body {args.body!r}: {exc}")
            return 2

    fields = parse_fields(body)
    review_sha_raw = fields.get("BHS_TIER_B_REVIEW_SHA", "").strip()
    if not review_sha_raw:
        print("ambiguous: BHS_TIER_B_REVIEW_SHA missing from body")
        return 2

    review_sha = review_sha_raw.lower()
    if not _SHA_RE.match(review_sha):
        print(
            f"ambiguous: BHS_TIER_B_REVIEW_SHA={review_sha_raw!r} "
            "is not 40-hex"
        )
        return 2

    head_resolved = resolve_head_sha(args.head_sha)
    if head_resolved is None:
        print(
            "ambiguous: cannot resolve HEAD SHA (no --head-sha and "
            "`git rev-parse HEAD` failed)"
        )
        return 2

    if review_sha == head_resolved:
        print(
            f"fresh: BHS_TIER_B_REVIEW_SHA equals HEAD ({head_resolved}); "
            "safe to raise the score"
        )
        return 0

    print(
        f"stale: BHS_TIER_B_REVIEW_SHA={review_sha} != HEAD="
        f"{head_resolved}; re-run the Tier B review at HEAD"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
