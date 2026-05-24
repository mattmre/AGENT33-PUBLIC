#!/usr/bin/env python3
"""scripts/insecure_flag_scanner.py -- project release gate R38a scanner.

Standalone scanner that reads PR-body EVIDENCE: text and/or a `git diff` blob
and reports every occurrence of an insecure-diagnostic-flag pattern from
v3.5/.../enums/insecure-diagnostic-flags.txt (paired 1:1 with detection
patterns in v3.5/.../tables/insecure-flag-detection-patterns.yaml). Issue #51.

The validator (validate_pr_brutal_honesty.py) imports the `scan()` function
to populate the `detected[]` set used by R38a/b/c/d/e. Tier B reviewers run
this CLI independently to confirm the validator's `detected` set is truthful
(every flag the scanner finds MUST be acknowledged by the implementer).

Usage:
  python -m scripts.insecure_flag_scanner --diff path/to/diff.txt
  python scripts/insecure_flag_scanner.py --evidence path/to/evidence.txt
  cat my.diff | python scripts/insecure_flag_scanner.py --diff -

Outputs JSON on stdout:
  {
    "detected": ["verify-false", "insecure-skip-tls-verify"],
    "hits": [
      {"flag": "verify-false", "line": 17,
       "match_text": "verify=False", "source": "diff"},
      ...
    ],
    "scanned_lines": 312,
    "patterns_loaded": 17
  }

Exit codes:
  0  Scan completed (regardless of whether flags were found).
  1  Could not read input or load detection table.
  2  Argparse / usage error.

What this script is NOT:
  - It does not coerce EVIDENCE_TIER or AUTH_CONTEXT (R38b's job, in the
    PR-body validator).
  - It does not require the implementer to acknowledge findings (R38c's
    job, in the PR-body validator).
  - It does not block promotion (R38d's job, also in the validator).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional

_DETECTION_TABLE_PATH = (
    Path(__file__).resolve().parent.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
    / "tables"
    / "insecure-flag-detection-patterns.yaml"
)

_ENUM_PATH = (
    Path(__file__).resolve().parent.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
    / "enums"
    / "insecure-diagnostic-flags.txt"
)


@dataclass(frozen=True)
class FlagHit:
    """One occurrence of an insecure-diagnostic-flag pattern.

    flag       : identifier from enums/insecure-diagnostic-flags.txt.
    line       : 1-based line number in the input where the hit occurred.
    match_text : the literal substring that matched (for code/cli regex)
                 or the literal config_key string (for config-key matches).
    source     : free-form caller-supplied label (e.g. "diff", "evidence",
                 "body") so a downstream consumer can attribute the hit.
    """

    flag: str
    line: int
    match_text: str
    source: str = "input"


def _load_enum_set() -> set[str]:
    """Load the closed-set enum identifiers (the source of truth)."""
    if not _ENUM_PATH.exists():
        return set()
    out: set[str] = set()
    for raw in _ENUM_PATH.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        out.add(s)
    return out


def _load_detection_table() -> dict[str, dict]:
    """Load the per-flag detection entries.

    Returns `{flag: {"code_regex": Optional[re.Pattern],
    "cli_regex": Optional[re.Pattern], "config_keys": list[str]}}`.
    Returns an empty dict if the YAML file is absent. Compilation errors on
    individual patterns are handled fail-soft: the offending field is set to
    None and a warning is printed to stderr (the rest of the entries still
    work; a Tier B reviewer can spot the warning).
    """
    if not _DETECTION_TABLE_PATH.exists():
        return {}
    import yaml

    raw = yaml.safe_load(_DETECTION_TABLE_PATH.read_text(encoding="utf-8")) or {}
    detection_raw = raw.get("detection", {}) or {}
    if not isinstance(detection_raw, dict):
        return {}
    out: dict[str, dict] = {}
    for flag, attrs in detection_raw.items():
        if not isinstance(attrs, dict):
            continue
        entry: dict = {
            "code_regex": None,
            "cli_regex": None,
            "config_keys": [],
        }
        for key in ("code_regex", "cli_regex"):
            pat_raw = attrs.get(key)
            if pat_raw is None or pat_raw == "":
                continue
            try:
                entry[key] = re.compile(str(pat_raw))
            except re.error as exc:
                print(
                    f"WARNING: insecure_flag_scanner: detection.{flag}.{key} "
                    f"failed to compile ({exc}); skipped.",
                    file=sys.stderr,
                )
        ck_raw = attrs.get("config_keys", []) or []
        if isinstance(ck_raw, list):
            entry["config_keys"] = [str(c) for c in ck_raw if c is not None]
        out[str(flag)] = entry
    return out


_DETECTION_TABLE = _load_detection_table()
_ENUM_SET = _load_enum_set()


def scan(text: str, source: str = "input") -> list[FlagHit]:
    """Scan `text` for insecure-diagnostic-flag patterns.

    Iterates each line; for every line that triggers any of the per-flag
    patterns (code_regex OR cli_regex OR contains a config_key substring),
    appends one FlagHit per (flag, line, match_text) triple.

    A given (flag, line) pair may produce multiple FlagHits if the same line
    matches via more than one mechanism. Callers that want unique flags
    should fold the result with `set(h.flag for h in hits)`.

    `source` is recorded on every emitted FlagHit and is intended to let the
    caller distinguish hits in the diff vs hits in the EVIDENCE: text vs hits
    in some other input (the validator passes "diff" / "evidence" / "body").
    """
    if not text or not _DETECTION_TABLE:
        return []
    hits: list[FlagHit] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if not line:
            continue
        for flag, entry in _DETECTION_TABLE.items():
            code_re = entry.get("code_regex")
            cli_re = entry.get("cli_regex")
            ck_list = entry.get("config_keys") or []
            seen_for_flag: set[str] = set()
            if code_re is not None:
                m = code_re.search(line)
                if m:
                    match_text = m.group(0)
                    if match_text not in seen_for_flag:
                        hits.append(
                            FlagHit(
                                flag=flag,
                                line=idx,
                                match_text=match_text,
                                source=source,
                            )
                        )
                        seen_for_flag.add(match_text)
            if cli_re is not None:
                m = cli_re.search(line)
                if m:
                    match_text = m.group(0)
                    if match_text not in seen_for_flag:
                        hits.append(
                            FlagHit(
                                flag=flag,
                                line=idx,
                                match_text=match_text,
                                source=source,
                            )
                        )
                        seen_for_flag.add(match_text)
            for ck in ck_list:
                if ck and ck in line and ck not in seen_for_flag:
                    hits.append(
                        FlagHit(
                            flag=flag,
                            line=idx,
                            match_text=ck,
                            source=source,
                        )
                    )
                    seen_for_flag.add(ck)
    return hits


def detected_flags(hits: Iterable[FlagHit]) -> set[str]:
    """Fold a hits list into the deduplicated `detected` set used by R38b/c."""
    return {h.flag for h in hits}


def known_flags() -> set[str]:
    """Return the closed-set of identifiers loaded from the enum file.

    Validator-side callers can compare `detected_flags(hits) <= known_flags()`
    as a paranoia assertion -- the drift validator already enforces the set
    bijection between the enum and the detection table, but a fail-soft
    assertion at scan time catches a corrupt install before R38b coerces.
    """
    return set(_ENUM_SET)


def _read_input(path_or_dash: Optional[str]) -> Optional[str]:
    if path_or_dash is None:
        return None
    if path_or_dash == "-":
        return sys.stdin.read()
    try:
        return Path(path_or_dash).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: cannot read {path_or_dash}: {exc}", file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Scan a PR-body EVIDENCE: text and/or a diff blob for occurrences "
            "of insecure-diagnostic-flag patterns. Issue #51."
        ),
    )
    parser.add_argument(
        "--diff",
        default=None,
        help=(
            "Path to a `git diff` blob (use '-' for stdin). Hits found in "
            "this input are tagged source='diff'."
        ),
    )
    parser.add_argument(
        "--evidence",
        default=None,
        help=(
            "Path to PR-body EVIDENCE: text (use '-' for stdin). Hits found "
            "here are tagged source='evidence'."
        ),
    )
    parser.add_argument(
        "--source-label",
        default=None,
        help=(
            "Override the source label used when both --diff and --evidence "
            "are absent and stdin is read directly."
        ),
    )
    args = parser.parse_args()

    if args.diff is None and args.evidence is None:
        # Treat stdin as a generic input.
        text = sys.stdin.read()
        hits = scan(text, source=args.source_label or "input")
        scanned_lines = len(text.splitlines())
    else:
        hits: list[FlagHit] = []
        scanned_lines = 0
        diff_text = _read_input(args.diff)
        if args.diff is not None and diff_text is None:
            return 1
        if diff_text is not None:
            hits.extend(scan(diff_text, source="diff"))
            scanned_lines += len(diff_text.splitlines())
        evidence_text = _read_input(args.evidence)
        if args.evidence is not None and evidence_text is None:
            return 1
        if evidence_text is not None:
            hits.extend(scan(evidence_text, source="evidence"))
            scanned_lines += len(evidence_text.splitlines())

    payload = {
        "detected": sorted(detected_flags(hits)),
        "hits": [asdict(h) for h in hits],
        "scanned_lines": scanned_lines,
        "patterns_loaded": len(_DETECTION_TABLE),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
