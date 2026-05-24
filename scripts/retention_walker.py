#!/usr/bin/env python3
"""scripts/retention_walker.py -- project release gate R39 walker.

Standalone walker that reads a `git diff` blob (and optionally the working
tree) and emits a retention-claim digest matching the schema at
v3.5/.../schemas/retention-claim.schema.json. Issue #50.

The validator (validate_pr_brutal_honesty.py) imports the `walk()` function to
cross-check the implementer-declared RETENTION: block against the actual
diff. Tier B reviewers run this CLI independently to confirm the validator's
per_artifact list and digest_summary are truthful.

Usage:
  python -m scripts.retention_walker --diff path/to/diff.txt
  python -m scripts.retention_walker --diff - --evidence-tier local-dev-smoke
  python scripts/retention_walker.py --diff my.diff --repo-root .

Outputs JSON on stdout matching the retention-claim schema:
  {
    "per_artifact": [
      {"path": "out/example.jsonl", "retention_class": "commit",
       "size_kb": 12, "sha256": "<64-hex>", "published_at": null},
      ...
    ],
    "digest_summary": {
      "committed_count": 1, "local_only_count": 0, "hash_only_count": 0,
      "redacted_count": 0, "external_count": 0, "total_kb": 12
    },
    "evidence_tier": "local-dev-smoke",
    "scanned_files": 1,
    "tiers_loaded": <int>  # runtime: len(_RETENTION_TABLE) — example, not a contract value
  }

Exit codes:
  0  Walk completed (regardless of whether artifacts were found).
  1  Could not read input or load retention table.
  2  Argparse / usage error.

What this script is NOT:
  - It does not enforce R39a/b/c/d (the validator does).
  - It does not check publication-safety against intended_score_category
    (R39c, in the validator).
  - It does not require redaction markers in the body (R39a, in the validator).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Iterable, Optional


_RETENTION_TABLE_PATH = (
    Path(__file__).resolve().parent.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
    / "tables"
    / "evidence-retention.yaml"
)

_TIERS_ENUM_PATH = (
    Path(__file__).resolve().parent.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
    / "enums"
    / "evidence-tiers.txt"
)

# Closed set of retention classes -- mirrored in the JSON schema enum and in
# the drift validator. Walker uses this only for output-shape validation.
RETENTION_CLASSES: frozenset[str] = frozenset(
    {
        "commit",
        "local-only",
        "hash-only",
        "redacted-summary",
        "external-artifact",
    }
)

# The walker treats files under these prefixes as candidate evidence
# artifacts. Adopters with non-standard layouts can pass --extra-prefix to
# extend this set at the CLI; the in-process API accepts an `extra_prefixes`
# list on walk().
DEFAULT_EVIDENCE_PREFIXES: tuple[str, ...] = ("out/", "tests/fixtures/")


@dataclass(frozen=True)
class ArtifactEntry:
    """One artifact discovered in the diff.

    path           : repo-relative path (always forward-slash separated).
    retention_class: the implied class -- looked up from the active
                     EVIDENCE_TIER:'s row in evidence-retention.yaml when
                     known; otherwise 'commit' as the safe-default.
    size_kb        : ceil(body_size_bytes / 1024). For deletion-only diff
                     hunks (no `+` body), 0.
    sha256         : hex SHA-256 of the reconstructed body (the concatenation
                     of all `+` content lines in the file's diff hunks). For a
                     deletion-only entry, the SHA of the empty bytestring.
    published_at   : always None from the walker (the walker has no concept
                     of publication state); the validator merges in the
                     implementer-declared value when cross-checking.
    """

    path: str
    retention_class: str
    size_kb: int
    sha256: str
    published_at: Optional[str] = None


@dataclass(frozen=True)
class RetentionReport:
    """Walker output -- mirrors the retention-claim schema 1:1."""

    per_artifact: tuple[ArtifactEntry, ...]
    digest_summary: dict
    evidence_tier: Optional[str] = None
    scanned_files: int = 0
    tiers_loaded: int = 0

    def to_jsonable(self) -> dict:
        return {
            "per_artifact": [asdict(a) for a in self.per_artifact],
            "digest_summary": dict(self.digest_summary),
            "evidence_tier": self.evidence_tier,
            "scanned_files": self.scanned_files,
            "tiers_loaded": self.tiers_loaded,
        }


def _load_tiers_enum_set() -> set[str]:
    """Load evidence-tiers.txt as a closed set."""
    if not _TIERS_ENUM_PATH.exists():
        return set()
    out: set[str] = set()
    for raw in _TIERS_ENUM_PATH.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        out.add(s)
    return out


def load_retention_table() -> dict[str, dict]:
    """Load tables/evidence-retention.yaml.

    Returns `{tier: {"retention_class": str, "warn_kb": int, "hard_kb": int,
    "keep_days": int, "publication_safe": bool}}`. Empty dict if the YAML
    file is absent (back-compat with pre-#50 trees -- the walker becomes a
    no-op shape).
    """
    if not _RETENTION_TABLE_PATH.exists():
        return {}
    import yaml

    raw = yaml.safe_load(_RETENTION_TABLE_PATH.read_text(encoding="utf-8")) or {}
    retention_raw = raw.get("retention", {}) or {}
    if not isinstance(retention_raw, dict):
        return {}
    out: dict[str, dict] = {}
    for tier, attrs in retention_raw.items():
        if not isinstance(attrs, dict):
            continue
        try:
            out[str(tier)] = {
                "retention_class": str(attrs.get("retention_class", "commit")),
                "warn_kb": int(attrs.get("warn_kb", 0) or 0),
                "hard_kb": int(attrs.get("hard_kb", 0) or 0),
                "keep_days": int(attrs.get("keep_days", 0) or 0),
                "publication_safe": bool(attrs.get("publication_safe", False)),
            }
        except (TypeError, ValueError):
            continue
    return out


_RETENTION_TABLE = load_retention_table()
_TIERS_ENUM = _load_tiers_enum_set()


# Diff parsing -----------------------------------------------------------

# `diff --git a/<path> b/<path>` form.
_DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)\s*$")
# `+++ b/<path>` form (fallback for `git diff` without --git, or unified diffs).
_DIFF_PLUS_RE = re.compile(r"^\+\+\+\s+b/(.+?)\s*$")
# Hunk header.
_DIFF_HUNK_RE = re.compile(r"^@@ ")
# `new file mode <octal>` indicates an addition.
_DIFF_NEW_FILE_RE = re.compile(r"^new file mode\s+\d+\s*$")
# `deleted file mode <octal>` indicates a deletion.
_DIFF_DEL_FILE_RE = re.compile(r"^deleted file mode\s+\d+\s*$")


@dataclass
class _PerFileDiff:
    path: str
    is_deletion: bool = False
    plus_lines: list[str] = field(default_factory=list)


def _parse_diff(diff_text: str) -> list[_PerFileDiff]:
    """Parse a unified diff into per-file `+` line bodies.

    Walks line by line; for each `diff --git` (or `+++ b/`) header begins a
    new per-file accumulator. `+` content lines (NOT `+++` headers) are
    appended to the current accumulator. Deletion markers (`deleted file
    mode`) flag the entry so the walker can treat the artifact as removed.
    """
    if not diff_text:
        return []
    files: list[_PerFileDiff] = []
    current: Optional[_PerFileDiff] = None
    in_hunk = False
    for raw_line in diff_text.splitlines():
        m_git = _DIFF_GIT_RE.match(raw_line)
        if m_git:
            if current is not None:
                files.append(current)
            current = _PerFileDiff(path=m_git.group(2))
            in_hunk = False
            continue
        if current is None:
            m_plus = _DIFF_PLUS_RE.match(raw_line)
            if m_plus:
                current = _PerFileDiff(path=m_plus.group(1))
                in_hunk = False
            continue
        if _DIFF_DEL_FILE_RE.match(raw_line):
            current.is_deletion = True
            continue
        if _DIFF_NEW_FILE_RE.match(raw_line):
            current.is_deletion = False
            continue
        if _DIFF_HUNK_RE.match(raw_line):
            in_hunk = True
            continue
        if in_hunk and raw_line.startswith("+") and not raw_line.startswith("+++"):
            current.plus_lines.append(raw_line[1:])
    if current is not None:
        files.append(current)
    # Dedupe entries that share a path (multiple hunks across a multi-file
    # diff already collapse into one _PerFileDiff via the header tracking;
    # this is a paranoia fold).
    by_path: dict[str, _PerFileDiff] = {}
    for entry in files:
        existing = by_path.get(entry.path)
        if existing is None:
            by_path[entry.path] = entry
        else:
            existing.plus_lines.extend(entry.plus_lines)
            existing.is_deletion = existing.is_deletion and entry.is_deletion
    return list(by_path.values())


def _is_evidence_path(path: str, prefixes: Iterable[str]) -> bool:
    n = path.replace("\\", "/")
    for p in prefixes:
        if n.startswith(p):
            return True
    return False


def _ceil_div(a: int, b: int) -> int:
    return (a + b - 1) // b if a > 0 else 0


def _build_entry(
    path: str,
    body_bytes: bytes,
    retention_class: str,
) -> ArtifactEntry:
    sha = hashlib.sha256(body_bytes).hexdigest()
    size_kb = _ceil_div(len(body_bytes), 1024)
    return ArtifactEntry(
        path=path.replace("\\", "/"),
        retention_class=retention_class,
        size_kb=size_kb,
        sha256=sha,
        published_at=None,
    )


def _build_digest(entries: Iterable[ArtifactEntry]) -> dict:
    counts = {
        "commit": 0,
        "local-only": 0,
        "hash-only": 0,
        "redacted-summary": 0,
        "external-artifact": 0,
    }
    total_kb = 0
    for e in entries:
        if e.retention_class in counts:
            counts[e.retention_class] += 1
        total_kb += e.size_kb
    return {
        "committed_count": counts["commit"],
        "local_only_count": counts["local-only"],
        "hash_only_count": counts["hash-only"],
        "redacted_count": counts["redacted-summary"],
        "external_count": counts["external-artifact"],
        "total_kb": total_kb,
    }


def walk(
    diff_text: str,
    evidence_tier: Optional[str] = None,
    repo_root: Optional[Path] = None,
    extra_prefixes: Optional[Iterable[str]] = None,
) -> RetentionReport:
    """Walk a unified-diff blob and produce a RetentionReport.

    `diff_text` is the raw output of `git diff`. `evidence_tier` is the
    PR-body's declared EVIDENCE_TIER:; the walker uses it to look up the
    default retention_class for every discovered artifact. `repo_root`, if
    supplied and the diff is a deletion-only one, lets the walker fall back
    to the tracked file body (currently unused; reserved for future
    behaviour). `extra_prefixes` lets adopters declare additional candidate
    evidence roots beyond out/ and tests/fixtures/.

    The walker is deliberately fail-soft: a malformed diff returns an empty
    report; an unknown tier defaults to retention_class=commit so the
    validator still has something to cross-check.
    """
    prefixes: tuple[str, ...] = DEFAULT_EVIDENCE_PREFIXES
    if extra_prefixes:
        prefixes = tuple(list(DEFAULT_EVIDENCE_PREFIXES) + [str(p) for p in extra_prefixes])
    parsed = _parse_diff(diff_text)
    tier_row = _RETENTION_TABLE.get(str(evidence_tier or "")) if evidence_tier else None
    default_class = (tier_row or {}).get("retention_class", "commit")
    entries: list[ArtifactEntry] = []
    for pf in parsed:
        if not _is_evidence_path(pf.path, prefixes):
            continue
        body = ("\n".join(pf.plus_lines) + ("\n" if pf.plus_lines else "")).encode("utf-8")
        if pf.is_deletion and not pf.plus_lines:
            body = b""
        entries.append(_build_entry(pf.path, body, default_class))
    digest = _build_digest(entries)
    return RetentionReport(
        per_artifact=tuple(entries),
        digest_summary=digest,
        evidence_tier=evidence_tier,
        scanned_files=len(parsed),
        tiers_loaded=len(_RETENTION_TABLE),
    )


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
            "Walk a `git diff` blob and emit a retention-claim digest. "
            "Issue #50."
        ),
    )
    parser.add_argument(
        "--diff",
        default=None,
        help=(
            "Path to a `git diff` blob (use '-' for stdin). Required."
        ),
    )
    parser.add_argument(
        "--evidence-tier",
        default=None,
        help=(
            "Active EVIDENCE_TIER: from the PR body. Used to look up the "
            "default retention_class for discovered artifacts."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help=(
            "Path to the repo root (default: cwd). Reserved for future "
            "deletion-fallback behaviour."
        ),
    )
    parser.add_argument(
        "--extra-prefix",
        action="append",
        default=None,
        help=(
            "Extra path prefix to treat as evidence root (in addition to "
            "out/ and tests/fixtures/). Repeatable."
        ),
    )
    args = parser.parse_args()

    if args.diff is None:
        print("ERROR: --diff is required (use '-' for stdin)", file=sys.stderr)
        return 2
    diff_text = _read_input(args.diff)
    if diff_text is None:
        return 1
    repo_root = Path(args.repo_root).resolve() if args.repo_root else None
    report = walk(
        diff_text=diff_text,
        evidence_tier=args.evidence_tier,
        repo_root=repo_root,
        extra_prefixes=args.extra_prefix,
    )
    print(json.dumps(report.to_jsonable(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
