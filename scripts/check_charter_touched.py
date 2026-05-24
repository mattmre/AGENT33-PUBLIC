#!/usr/bin/env python3
"""scripts/check_charter_touched.py — return 0 if a PR diff touches the
charter (issue #43, cluster E 3/7).

The per-PR validator (validate_pr_brutal_honesty.py R65a/R65b) is pure-
text and never invokes git directly. The orchestrator wires the
charter-touched signal through the `--charter-touched 1|0` side-channel
argument; this helper produces that 0/1 by running `git diff
--name-only <base>..<head>` and checking whether either of the two
charter-bearing paths appears in the result.

Touched paths (any one match -> charter touched):
  - out/lane-charter.md
  - out/phase-punchlist.json

Exit codes:
  0 -- charter touched (validator should pass --charter-touched 1)
  1 -- charter NOT touched (validator should pass --charter-touched 0)
  2 -- git error (caller should treat as 'unknown'; default to 0 for
       safety -- a charter PR that the helper failed to detect would
       otherwise silently bypass R65a)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


CHARTER_PATHS = (
    "out/lane-charter.md",
    "out/phase-punchlist.json",
)


def diff_touches_charter(
    base: str,
    head: str,
    cwd: Path | None = None,
) -> int:
    """Run `git diff --name-only <base>..<head>` and return 0/1/2.

    cwd is None -> use the current working directory; tests pass an
    explicit Path to a fixture repo.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base}..{head}"],
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print(
            "ERROR: `git` not found on PATH; cannot determine charter "
            "touch state.",
            file=sys.stderr,
        )
        return 2
    if result.returncode != 0:
        stderr_msg = (result.stderr or "").strip()
        print(
            f"ERROR: `git diff --name-only {base}..{head}` failed: "
            f"{stderr_msg}",
            file=sys.stderr,
        )
        return 2
    changed = {
        line.strip().replace("\\", "/")
        for line in result.stdout.splitlines()
        if line.strip()
    }
    for path in CHARTER_PATHS:
        if path in changed:
            return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--base",
        required=True,
        help="Base git ref (e.g. origin/main, the merge-base SHA).",
    )
    parser.add_argument(
        "--head",
        required=True,
        help="Head git ref (e.g. HEAD, the PR's tip SHA).",
    )
    parser.add_argument(
        "--cwd",
        default=None,
        help=(
            "Optional working directory for the git invocation "
            "(tests use this to point at a fixture repo)."
        ),
    )
    args = parser.parse_args(argv)
    cwd = Path(args.cwd) if args.cwd else None
    return diff_touches_charter(args.base, args.head, cwd=cwd)


if __name__ == "__main__":
    sys.exit(main())
