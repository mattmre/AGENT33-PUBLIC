#!/usr/bin/env python3
"""scripts/fixture_coverage_walker.py - Issue #21 fixture-coverage detector.

Walks a fixtures directory and reports how many fixtures look POSITIVE vs.
NEGATIVE vs. PLANTED-DRIFT. Used by validate_pr_brutal_honesty.py R33 to
enforce that high-tier evidence claims (per evidence-tier-scoring-caps.yaml
`requires_negative_fixture`) actually have negative coverage. A test suite
that contains only positive fixtures cannot be promoted above
`positive-fixture` tier, regardless of which production module it imports.

Detection signals (file-based; no AST scan in v1 - the walker is intended
to be cheap, deterministic, and reviewable line-by-line by Tier B):

  1. Filename token. Case-insensitive substring match against:
       drift, planted-drift, negative, malformed, invalid, rejection
     A token MUST be followed by a non-alphanumeric or end-of-name (so
     `validation` does not match `invalid` and `position` does not match
     `positive`). Filename basename without extension is checked.

  2. YAML/JSON `expects_rejection: true`. The walker opens .yaml/.yml/.json
     fixtures and looks for the top-level key `expects_rejection` set to
     boolean true. Other shapes (string "true", missing key) do not count.

  3. Sibling file `<basename>.expected_error.txt`. Mirrors the layout used
     by validate_v33_schema_drift.py's planted-drift fixtures. The sibling
     must be a regular file with non-empty contents.

A fixture is classified PLANTED_DRIFT if signal (1) hits the
`drift`/`planted-drift` token; NEGATIVE if signal (1) hits one of the
other tokens, or (2) or (3) match. Otherwise POSITIVE. Files with mixed
signals are PLANTED_DRIFT (the strongest classification wins).

Files that look like helpers, conftest, or non-fixtures are skipped:
  - filename starts with `_` or `conftest`
  - file is the sibling `.expected_error.txt` itself
  - extension not in {.yaml, .yml, .json, .jsonl, .pdf, .txt, .md, .csv,
    .png, .jpg, .jpeg, .bin, .py}

CLI:
  python -m scripts.fixture_coverage_walker <dir>            # human report
  python scripts/fixture_coverage_walker.py <dir> --json     # JSON report
  python scripts/fixture_coverage_walker.py <dir> --json -   # JSON to stdout

Exit codes:
  0 - walked successfully (regardless of coverage shape)
  2 - bad arguments / directory not found

Tier B independence: the walker is its own module. R33 calls walk(); a
reviewer running `python -m scripts.fixture_coverage_walker` against a
fixtures dir does NOT need to invoke the full PR-body validator. This
matches the fail-closed reviewer-tools pattern from #16/#17/#26/#36.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# Tokens that mark a fixture as planted-drift specifically (highest priority).
_DRIFT_TOKENS = ("planted-drift", "drift")

# Tokens that mark a fixture as a negative case (general rejection assertion).
_NEGATIVE_TOKENS = ("negative", "malformed", "invalid", "rejection")

# File extensions the walker considers fixture candidates. Anything else is
# skipped (test code lives in tests/, not tests/fixtures/).
_FIXTURE_EXTS = {
    ".yaml",
    ".yml",
    ".json",
    ".jsonl",
    ".pdf",
    ".txt",
    ".md",
    ".csv",
    ".png",
    ".jpg",
    ".jpeg",
    ".bin",
    ".py",
}

# Filenames that are scaffolding, not fixtures.
_SKIP_NAMES = {"conftest.py", "__init__.py", "README.md", "readme.md"}


@dataclass
class CoverageReport:
    """Per-fixtures-directory coverage result.

    Counts are non-overlapping: each fixture is classified into exactly one
    bucket (POSITIVE, NEGATIVE, PLANTED_DRIFT, or AMBIGUOUS - the last
    reserved for parse failures we do not want to silently coerce). The
    `fixtures_dir` is recorded so R33's failure messages can quote it.
    """

    fixtures_dir: str
    positive: int = 0
    negative: int = 0
    planted_drift: int = 0
    ambiguous: int = 0
    examined_files: int = 0
    skipped_files: int = 0
    detail: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["coverage_ok_for_high_tier"] = (self.negative + self.planted_drift) > 0
        return d


def _basename_no_ext(path: Path) -> str:
    return path.stem


def _has_token_match(basename: str, token: str) -> bool:
    """True iff `token` appears in `basename` flanked by non-alphanumeric
    boundaries (or start/end of string). Case-insensitive.

    Boundary means: either the previous character does not exist OR is not
    alphanumeric, AND the next character does not exist OR is not
    alphanumeric. This prevents `invalid` matching inside `validation` and
    prevents `position` from matching `positive`.
    """
    pattern = r"(?:^|[^A-Za-z0-9])" + re.escape(token) + r"(?:$|[^A-Za-z0-9])"
    return re.search(pattern, basename, flags=re.IGNORECASE) is not None


def _signal_filename(path: Path) -> Optional[str]:
    """Return 'planted_drift' / 'negative' / None based on filename token."""
    bn = _basename_no_ext(path)
    for tok in _DRIFT_TOKENS:
        if _has_token_match(bn, tok):
            return "planted_drift"
    for tok in _NEGATIVE_TOKENS:
        if _has_token_match(bn, tok):
            return "negative"
    return None


def _signal_expects_rejection(path: Path) -> bool:
    """True iff a YAML/JSON fixture has top-level `expects_rejection: true`."""
    if path.suffix.lower() not in {".yaml", ".yml", ".json"}:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return False
    else:
        try:
            import yaml

            data = yaml.safe_load(text)
        except Exception:
            return False
    if not isinstance(data, dict):
        return False
    val = data.get("expects_rejection")
    return val is True


def _signal_sibling_expected_error(path: Path) -> bool:
    """True iff a sibling `<basename>.expected_error.txt` exists, non-empty."""
    sibling = path.with_suffix("")
    sibling = sibling.with_name(sibling.name + ".expected_error.txt")
    if not sibling.is_file():
        return False
    try:
        return sibling.stat().st_size > 0
    except OSError:
        return False


def _classify(path: Path) -> tuple[str, list[str]]:
    """Return (bucket, reasons). bucket in
    {'positive','negative','planted_drift'}.
    """
    reasons: list[str] = []
    name_signal = _signal_filename(path)
    if name_signal == "planted_drift":
        reasons.append("filename-token=drift|planted-drift")
    elif name_signal == "negative":
        reasons.append("filename-token=negative|malformed|invalid|rejection")
    rej_signal = _signal_expects_rejection(path)
    if rej_signal:
        reasons.append("yaml/json expects_rejection=true")
    sibling_signal = _signal_sibling_expected_error(path)
    if sibling_signal:
        reasons.append("sibling .expected_error.txt present")

    if name_signal == "planted_drift":
        return ("planted_drift", reasons)
    if rej_signal or sibling_signal or name_signal == "negative":
        return ("negative", reasons)
    return ("positive", reasons)


def walk(fixtures_dir: Path) -> CoverageReport:
    """Walk `fixtures_dir` recursively and return a CoverageReport.

    Treats every file under the tree (recursively) as a fixture candidate
    UNLESS its name is in _SKIP_NAMES, starts with `_`, ends with
    `.expected_error.txt` (sibling marker, not a fixture), or its
    extension is not in _FIXTURE_EXTS.
    """
    report = CoverageReport(fixtures_dir=str(fixtures_dir))
    if not fixtures_dir.is_dir():
        return report

    for path in sorted(fixtures_dir.rglob("*")):
        if not path.is_file():
            continue
        name = path.name
        if name in _SKIP_NAMES or name.startswith("_"):
            report.skipped_files += 1
            continue
        if name.endswith(".expected_error.txt"):
            report.skipped_files += 1
            continue
        if path.suffix.lower() not in _FIXTURE_EXTS:
            report.skipped_files += 1
            continue
        report.examined_files += 1
        bucket, reasons = _classify(path)
        if bucket == "positive":
            report.positive += 1
        elif bucket == "negative":
            report.negative += 1
        elif bucket == "planted_drift":
            report.planted_drift += 1
        else:  # pragma: no cover - reserved for future ambiguity
            report.ambiguous += 1
        report.detail.append(
            {
                "path": str(path.relative_to(fixtures_dir)),
                "bucket": bucket,
                "reasons": reasons,
            }
        )
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fixture_coverage_walker",
        description=(
            "Issue #21 - walk a fixtures directory and report how many "
            "fixtures are positive vs. negative vs. planted-drift. R33 "
            "uses this to refuse high-tier EVIDENCE_TIER claims that ride "
            "on positive-only fixtures."
        ),
    )
    parser.add_argument(
        "fixtures_dir",
        type=Path,
        help="Path to a directory of fixtures (typically tests/fixtures/<area>/).",
    )
    parser.add_argument(
        "--json",
        nargs="?",
        const="-",
        default=None,
        help="Emit JSON report. Argument is the output path or `-` for stdout.",
    )
    args = parser.parse_args(argv)

    if not args.fixtures_dir.exists():
        print(
            f"fixture_coverage_walker: directory not found: {args.fixtures_dir}",
            file=sys.stderr,
        )
        return 2
    if not args.fixtures_dir.is_dir():
        print(
            f"fixture_coverage_walker: not a directory: {args.fixtures_dir}",
            file=sys.stderr,
        )
        return 2

    report = walk(args.fixtures_dir)
    payload = report.to_dict()

    if args.json is not None:
        out = json.dumps(payload, indent=2, sort_keys=True)
        if args.json == "-":
            print(out)
        else:
            Path(args.json).write_text(out + "\n", encoding="utf-8")
            print(f"fixture_coverage_walker: wrote {args.json}")
        return 0

    # Human-readable report.
    print(f"fixtures_dir: {report.fixtures_dir}")
    print(f"  examined: {report.examined_files}")
    print(f"  skipped:  {report.skipped_files}")
    print(f"  positive:      {report.positive}")
    print(f"  negative:      {report.negative}")
    print(f"  planted_drift: {report.planted_drift}")
    print(
        f"  coverage_ok_for_high_tier: "
        f"{'YES' if payload['coverage_ok_for_high_tier'] else 'NO'}"
    )
    if report.detail:
        print("  per-file:")
        for d in report.detail:
            reasons = ", ".join(d["reasons"]) if d["reasons"] else "no signals"
            print(f"    {d['bucket']:14s} {d['path']}  ({reasons})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
