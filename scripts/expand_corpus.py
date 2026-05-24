#!/usr/bin/env python3
"""scripts/expand_corpus.py -- compute the minimal PR window that covers
every `phase_id` declared in a CORPUS_SELECTION block.

Issue #45 (Cluster F 4/5). Companion to R57 / R58 in
scripts/validate_pr_brutal_honesty.py: when R58 reports `last-N` coverage
as insufficient (some claimed phase_id has zero PRs in the last-N window),
this helper prints a concrete `phase-range` window that WOULD cover the
missing phases. The output is a SUGGESTION (read-only, no side effects);
the operator decides whether to widen the window in the PR body or to
narrow the claim.

Inputs:
  --phase-corpus PATH   Path to the phase-corpus.yaml artifact (issue #45).
  --selection PATH      Path to a file containing a CORPUS_SELECTION block
                        (e.g. the PR body itself). The script extracts the
                        block via the same markers used by the validator
                        (`CORPUS_SELECTION:` / `CORPUS_SELECTION_END`).
  --pr-list PATH        Optional path to a JSON file listing the most
                        recent merged PRs (the same shape `gh pr list
                        --json number` emits). Used only to pin the upper
                        bound of the suggested window when the selection
                        is `mode: last-n`. When omitted, the upper bound
                        is the maximum PR number observed in the corpus
                        for the union of claimed phases.

Output:
  - Prints a single line `suggested_pr_window: <lo>..<hi>` to stdout when
    a covering window can be computed; prints `suggested_pr_window:
    none -- coverage is already sufficient` when every claimed phase
    already has at least one PR in the implicit window.
  - Exits 0 on successful suggestion (including the no-op path); exits
    1 only on missing/malformed inputs.

This script intentionally does NOT modify any file on disk. Its only
side effect is the stdout print -- the operator pastes the suggested
window back into the PR body's CORPUS_SELECTION block.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional


_SELECTION_OPEN_RE = re.compile(
    r"^\s*>?\s*CORPUS_SELECTION\s*:\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_SELECTION_END_RE = re.compile(
    r"^\s*>?\s*CORPUS_SELECTION_END\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def _extract_selection_block(text: str) -> Optional[dict]:
    """Pull the CORPUS_SELECTION block out of a free-form file (PR body
    or selection-only fixture). Returns the parsed YAML mapping, or None
    when the block markers are absent."""
    open_m = _SELECTION_OPEN_RE.search(text)
    if open_m is None:
        return None
    end_m = _SELECTION_END_RE.search(text, pos=open_m.end())
    if end_m is None:
        return None
    inner = text[open_m.end():end_m.start()]
    cleaned: list[str] = []
    for line in inner.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("> "):
            cleaned.append(line[line.index("> ") + 2:])
        elif stripped.startswith(">"):
            cleaned.append(line[line.index(">") + 1:])
        else:
            cleaned.append(line)
    import textwrap

    body = textwrap.dedent("\n".join(cleaned)).strip()
    if not body:
        return {}
    try:
        import yaml
    except ImportError:
        print(
            "ERROR: PyYAML required (pip install pyyaml).",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        parsed = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        print(
            f"ERROR: CORPUS_SELECTION block parse failed: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _load_phase_corpus(path: Path) -> dict:
    """Load phase-corpus.yaml and normalise into {phase_id -> {prs:set,
    requirement_ids:set}}."""
    if not path.exists():
        print(
            f"ERROR: --phase-corpus {str(path)!r} does not exist.",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        import yaml
    except ImportError:
        print(
            "ERROR: PyYAML required (pip install pyyaml).",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(
            f"ERROR: phase-corpus parse failed: {exc}", file=sys.stderr
        )
        sys.exit(1)
    if not isinstance(raw, dict):
        print(
            "ERROR: phase-corpus must be a top-level mapping.",
            file=sys.stderr,
        )
        sys.exit(1)
    by_phase: dict[str, dict] = {}
    for row in raw.get("phases", []) or []:
        if not isinstance(row, dict):
            continue
        phase_id = row.get("phase_id")
        if not isinstance(phase_id, str) or not phase_id:
            continue
        prs = {
            int(p) for p in (row.get("prs") or []) if isinstance(p, int)
        }
        rids = {
            r for r in (row.get("requirement_ids") or [])
            if isinstance(r, str) and r
        }
        by_phase[phase_id] = {"prs": prs, "requirement_ids": rids}
    return by_phase


def _load_pr_list(path: Optional[Path]) -> list[int]:
    if path is None:
        return []
    if not path.exists():
        print(
            f"ERROR: --pr-list {str(path)!r} does not exist.",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(
            f"ERROR: --pr-list parse failed: {exc}", file=sys.stderr
        )
        sys.exit(1)
    if isinstance(raw, list):
        out: list[int] = []
        for item in raw:
            if isinstance(item, int):
                out.append(item)
            elif isinstance(item, dict) and isinstance(
                item.get("number"), int
            ):
                out.append(item["number"])
        return out
    return []


def compute_suggested_window(
    phase_corpus: dict[str, dict],
    selection: dict,
    pr_list: list[int],
) -> Optional[tuple[int, int]]:
    """Pure function: given the loaded phase-corpus + the parsed
    CORPUS_SELECTION block + the (possibly empty) recent-PR list,
    compute the smallest `lo..hi` PR window that covers every claimed
    phase_id's `prs` list. Returns None when the input is degenerate
    (no PRs in the union of claimed phases) or when coverage is already
    sufficient (every phase has at least one PR in the implied window).
    """
    phase_ids = selection.get("phase_ids") or []
    if not isinstance(phase_ids, list) or not phase_ids:
        return None
    union_prs: set[int] = set()
    per_phase_prs: dict[str, set[int]] = {}
    for pid in phase_ids:
        if not isinstance(pid, str):
            continue
        row = phase_corpus.get(pid)
        if not row:
            continue
        prs = row.get("prs") or set()
        per_phase_prs[pid] = prs
        union_prs |= prs
    if not union_prs:
        return None

    # If mode is last-n, check whether the implied window already covers
    # every claimed phase. If yes, no suggestion is needed.
    mode = selection.get("mode", "")
    if mode == "last-n" and pr_list:
        try:
            n = int(selection.get("pr_window") or 0)
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            window = set(pr_list[:n])
            if all(
                bool(per_phase_prs.get(pid, set()) & window)
                for pid in phase_ids
                if pid in per_phase_prs
            ):
                return None
    return (min(union_prs), max(union_prs))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--phase-corpus", required=True, help="Path to phase-corpus.yaml"
    )
    parser.add_argument(
        "--selection",
        required=True,
        help=(
            "Path to a file containing a CORPUS_SELECTION block (e.g. "
            "the PR body)."
        ),
    )
    parser.add_argument(
        "--pr-list",
        default=None,
        help=(
            "Optional path to a JSON list of recent merged PR numbers "
            "(matches `gh pr list --json number` shape). Used to pin "
            "the upper bound when mode is last-n."
        ),
    )
    args = parser.parse_args()

    phase_corpus = _load_phase_corpus(Path(args.phase_corpus))
    selection_text = Path(args.selection).read_text(encoding="utf-8")
    selection = _extract_selection_block(selection_text)
    if selection is None:
        print(
            "ERROR: no CORPUS_SELECTION block found in "
            f"{args.selection!r}.",
            file=sys.stderr,
        )
        return 1
    pr_list = _load_pr_list(
        Path(args.pr_list) if args.pr_list else None
    )
    window = compute_suggested_window(phase_corpus, selection, pr_list)
    if window is None:
        print(
            "suggested_pr_window: none -- coverage is already "
            "sufficient (or no PRs found for the claimed phases)."
        )
        return 0
    lo, hi = window
    print(f"suggested_pr_window: {lo}..{hi}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
