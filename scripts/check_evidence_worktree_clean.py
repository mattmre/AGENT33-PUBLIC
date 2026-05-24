#!/usr/bin/env python3
"""Issue #24 / R44e -- Tier B worktree-clean helper.

Runs `git status --porcelain` against --repo-root and exits non-zero if
any dirty path lies OUTSIDE the declared --output-dir. Wired into the
Tier B reviewer brief (rulebook §6.4); deliberately NOT wired into
validate_pr_brutal_honesty.py so the per-PR validator stays pure-text
(no subprocess, no git I/O).

Exit codes:
  0   worktree is clean (or all dirty paths lie inside --output-dir)
  1   argparse / IO failure (stderr explains)
  2   one or more dirty paths lie outside --output-dir; one violation
      line per offending path is printed to stdout

The check is path-textual: --output-dir is normalised + treated as a
repo-relative directory, and Path.is_relative_to is used to decide
whether a dirty path is "inside" it. The intent is to confirm that a
mutating-harness rerun touched ONLY its declared output dir; a
non-mutating harness in declared `HARNESS_MUTATES: no` mode is expected
to leave the worktree fully clean and will trip exit-2 on the first
dirty path.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


EXIT_OK = 0
EXIT_USAGE = 1
EXIT_DIRTY = 2


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--output-dir",
        required=True,
        help=(
            "Repo-relative directory the mutating harness is permitted "
            "to write to. Must match the HARNESS_OUTPUT_DIR field on "
            "the PR body that declared this harness."
        ),
    )
    p.add_argument(
        "--repo-root",
        default=".",
        help=(
            "Repo root to run `git status --porcelain` against. Defaults "
            "to the current working directory."
        ),
    )
    return p.parse_args(argv)


def _porcelain_paths(repo_root: Path) -> list[str]:
    """Return the list of paths reported by `git status --porcelain`.

    Each porcelain line is `XY <path>` (X/Y = status codes). Rename
    lines are `R  old -> new` -- we keep the new path.
    """
    # `--untracked-files=all` so we list `out/tier-b-rerun/foo.log`
    # individually instead of collapsing to the parent dir `out/` -- the
    # parent-collapse default would mis-classify in-output-dir untracked
    # files as "outside" because `out/` is not is_relative_to
    # `out/tier-b-rerun/`.
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git status --porcelain exited {proc.returncode} "
            f"in {repo_root!s}; stderr: {proc.stderr.strip()!r}"
        )
    paths: list[str] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        # Porcelain lines are `XY ` (3 leading chars) then path.
        body = line[3:] if len(line) > 3 else ""
        if " -> " in body:
            # Rename: take the destination.
            body = body.split(" -> ", 1)[1]
        # Quoted paths (when core.quotepath=true) come wrapped in
        # double-quotes; strip them for the textual check.
        if body.startswith('"') and body.endswith('"') and len(body) >= 2:
            body = body[1:-1]
        paths.append(body)
    return paths


def _is_inside(path_str: str, output_dir: Path, repo_root: Path) -> bool:
    """True iff `path_str` (repo-relative, from porcelain) lies inside
    `output_dir` (also repo-relative). Path.is_relative_to is the
    Python 3.9+ way; the project floor is 3.11 so it is safe to use.
    """
    try:
        path = (repo_root / path_str).resolve()
    except (OSError, RuntimeError):
        # Resolve can raise on weird paths; treat as outside.
        return False
    try:
        out_resolved = (repo_root / output_dir).resolve()
    except (OSError, RuntimeError):
        return False
    try:
        return path.is_relative_to(out_resolved)
    except AttributeError:
        # Python < 3.9 fallback. Project floor is 3.11; this branch is
        # belt-and-braces only.
        try:
            path.relative_to(out_resolved)
            return True
        except ValueError:
            return False


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    repo_root = Path(args.repo_root).resolve()
    if not repo_root.is_dir():
        print(
            f"ERROR: --repo-root {args.repo_root!r} is not a directory",
            file=sys.stderr,
        )
        return EXIT_USAGE
    output_dir = Path(args.output_dir)

    try:
        paths = _porcelain_paths(repo_root)
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE

    violations = [
        p for p in paths if not _is_inside(p, output_dir, repo_root)
    ]
    if not violations:
        return EXIT_OK
    for v in violations:
        print(
            f"R44e: dirty path outside HARNESS_OUTPUT_DIR="
            f"{args.output_dir!r}: {v}"
        )
    return EXIT_DIRTY


if __name__ == "__main__":
    sys.exit(main())
