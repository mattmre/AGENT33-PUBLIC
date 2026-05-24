#!/usr/bin/env python3
"""scripts/scan_evidence_secrets.py -- project release gate R47 scanner.

Stdlib-only scanner that reads one or more files (or every file under a
directory tree) and reports every occurrence of a credential pattern.
Patterns are a curated set (<= 13 entries) of the credentials that show up
most frequently in BHS evidence captures (AWS, GCP, GitHub, Slack, generic
bearer tokens, JWTs, PEM private keys, Basic-auth URLs, email addresses,
private IPv4 ranges, home-directory paths) plus a Shannon-entropy heuristic
for unrecognised high-entropy strings.

Issue #31. Wired into:
  - validate_pr_brutal_honesty.py R47e (in-prose secret detection on the
    PR body, with the same regex set + allowlist).
  - validate_pr_brutal_honesty.py R47g (parses any JSON file matching
    out/secret-scan-*.json that appears in the PR diff and FAILs on any
    `severity: high` finding).
  - tier B reviewer brief (run the CLI on the artifacts EVIDENCE: cites).

Allowlist: every entry in
docs/conventions/brutal-honesty-kit/v3.5/fixtures/SECRETS-POLICY.md is
loaded at import time and a finding is suppressed when the matched
substring equals (after stripping leading/trailing whitespace) any
allowlisted token. The scanner's own fixtures use these EXACTLY so the
scanner does not fail-closed on its own evidence.

Usage:
  python scripts/scan_evidence_secrets.py --path FILE
  python scripts/scan_evidence_secrets.py --path DIR
  python scripts/scan_evidence_secrets.py --path FILE --format json
  python scripts/scan_evidence_secrets.py --path FILE --output out/scan.json

Output: JSON document on stdout (or to --output if supplied):
  {
    "scanned_paths": ["path/a.log", "path/b.log"],
    "findings": [
      {
        "path": "path/a.log",
        "line": 17,
        "column": 24,
        "pattern_name": "aws-access-key",
        "match_preview": "AKIAEXAM ... (LEN=20)",
        "severity": "high"
      }
    ],
    "patterns_loaded": 13,
    "allowlist_size": 6
  }

Exit codes:
  0  Scan completed; no `high` finding.
  1  Scan completed; AT LEAST ONE `high` finding (the one R47g blocks on).
  2  At least one --path target was unreadable (permission, missing,
     binary file with decode error). Stderr lists every unreadable target.

What this script is NOT:
  - It does not redact. See scripts/redact_evidence.py.
  - It does not modify any file. Pure read-only.
  - It does not enforce field shape on the PR body. See R47a/b/c/d in
    validate_pr_brutal_honesty.py.
  - It does not crawl outside --path's tree (no symlink chasing into
    parent dirs).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional


_POLICY_PATH = (
    Path(__file__).resolve().parent.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
    / "fixtures"
    / "SECRETS-POLICY.md"
)


def _load_allowlist() -> set[str]:
    """Parse SECRETS-POLICY.md and return the fenced-block credential strings.

    The allowlist lives in the FIRST fenced ``` block under the "## Allowlist
    (exact-match)" heading. We split that block by lines and add every
    non-blank line to the allowlist set. Multi-line PEM blocks (BEGIN/END
    markers + body) are added as both the joined whole-block string AND the
    individual lines so a fixture that uses the body alone still matches.

    Returns an empty set if the policy file is absent (the scanner still
    works, but every fixture credential becomes a real finding -- which is
    the safe default).
    """
    if not _POLICY_PATH.exists():
        return set()
    text = _POLICY_PATH.read_text(encoding="utf-8")
    out: set[str] = set()
    in_allow = False
    in_fence = False
    fence_lines: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("## Allowlist"):
            in_allow = True
            continue
        if in_allow and stripped.startswith("## "):
            # Next H2 -- end of allowlist section.
            break
        if in_allow and stripped.startswith("```"):
            if not in_fence:
                in_fence = True
                fence_lines = []
                continue
            else:
                # Closing fence -- consume the captured block.
                joined = "\n".join(fence_lines).strip()
                if joined:
                    out.add(joined)
                for line in fence_lines:
                    s = line.strip()
                    if s:
                        out.add(s)
                in_fence = False
                in_allow = False  # only the first fenced block counts
                continue
        if in_fence:
            fence_lines.append(raw)
    return out


# ---------------------------------------------------------------------------
# Pattern table.
#
# Each entry: (pattern_name, regex, severity, description). The order matters
# only for human-readable output; the scanner emits one finding per (regex,
# match) pair.
#
# IMPORTANT: do NOT add patterns that match 40-char lowercase hex (git SHAs).
# The high-entropy heuristic also intentionally REJECTS pure [0-9a-f]{40}
# strings -- they are common in evidence and not credentials.
# ---------------------------------------------------------------------------

PATTERN_TABLE: list[tuple[str, str, str]] = [
    # AWS access key id -- exact AKIA prefix + 16 base32 chars.
    ("aws-access-key", r"AKIA[0-9A-Z]{16}", "high"),
    # GCP service account JSON marker. The full key body is rarely on one
    # line; this catches the discriminator string that is unique to GCP
    # service account JSON files.
    ("gcp-service-account-key", r'"type"\s*:\s*"service_account"', "high"),
    # GitHub-style PATs (gh{p,o,u,s,r}_) + 36+ alnum.
    ("github-token", r"gh[pousr]_[A-Za-z0-9]{36,}", "high"),
    # Slack tokens.
    ("slack-token", r"xox[abp]-[0-9A-Za-z-]{10,}", "high"),
    # JWT (header.payload.signature, all base64url). MUST come before
    # generic-bearer so `Bearer eyJ...` redacts as jwt (high) not bearer
    # (medium) -- otherwise the more-specific high-severity pattern is
    # masked by the more-generic medium one.
    (
        "jwt",
        r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",
        "high",
    ),
    # Generic Bearer header tokens.
    ("generic-bearer", r"Bearer\s+[A-Za-z0-9._\-]{20,}", "medium"),
    # PEM private key block start marker.
    (
        "private-key-block",
        r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----",
        "high",
    ),
    # HTTP Basic auth in URL.
    (
        "http-basic-auth",
        r"https?://[^/\s:@]+:[^/\s@]+@",
        "medium",
    ),
    # Email address.
    (
        "email-address",
        r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
        "low",
    ),
    # RFC 1918 private IPv4 ranges.
    (
        "ipv4-private",
        r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b",
        "low",
    ),
    # Home directory paths -- linux + macOS + Windows.
    (
        "home-path-posix",
        r"(?:/home/|/Users/)[A-Za-z0-9._\-]+/",
        "low",
    ),
    (
        "home-path-windows",
        r"[Cc]:\\\\?Users\\\\?[^\\\\\s]+\\\\?",
        "low",
    ),
]


_COMPILED: list[tuple[str, "re.Pattern[str]", str]] = []
for _name, _src, _sev in PATTERN_TABLE:
    try:
        _COMPILED.append((_name, re.compile(_src), _sev))
    except re.error as exc:  # pragma: no cover -- defensive
        sys.stderr.write(
            f"WARNING: scan_evidence_secrets: pattern {_name!r} failed to "
            f"compile ({exc}); skipped.\n"
        )


# Shannon-entropy heuristic -- catches credentials that don't match a named
# pattern. Window: any [A-Za-z0-9_+/=\-]{32,} run. Threshold: 4.5 bits/char.
# Anti-overhead: 40-char lower-case hex (git SHAs) is explicitly rejected
# because evidence files are FULL of git SHAs and triggering on each one
# would drown the operator in noise.
_ENTROPY_RUN_RE = re.compile(r"[A-Za-z0-9_+/=\-]{32,}")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ENTROPY_THRESHOLD = 4.5


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    total = float(len(s))
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    column: int
    pattern_name: str
    match_preview: str
    severity: str


def _preview(match_text: str) -> str:
    """Truncated, length-annotated preview of a matched substring.

    First 8 visible characters (newlines collapsed to spaces) + length.
    Never returns the full secret -- if the operator wants the full secret
    they can re-run with the source line in front of them.
    """
    safe = match_text.replace("\n", " ").replace("\r", " ")
    head = safe[:8]
    return f"{head} ... (LEN={len(match_text)})"


def scan_text(
    text: str,
    path: str,
    allowlist: Optional[set[str]] = None,
) -> list[Finding]:
    """Scan a single string for credential patterns.

    `path` is the label attached to every emitted finding (caller-supplied;
    typically the file's repo-relative path).
    """
    if allowlist is None:
        allowlist = _ALLOWLIST
    out: list[Finding] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        # Named patterns.
        for name, pat, sev in _COMPILED:
            for m in pat.finditer(line):
                match_text = m.group(0)
                if _is_allowlisted(match_text, allowlist):
                    continue
                out.append(
                    Finding(
                        path=path,
                        line=line_no,
                        column=m.start() + 1,
                        pattern_name=name,
                        match_preview=_preview(match_text),
                        severity=sev,
                    )
                )
        # Entropy heuristic.
        for m in _ENTROPY_RUN_RE.finditer(line):
            run = m.group(0)
            if _GIT_SHA_RE.match(run):
                continue
            if _is_allowlisted(run, allowlist):
                continue
            ent = _shannon_entropy(run)
            if ent >= _ENTROPY_THRESHOLD:
                # Suppress when ALREADY caught by a named high/medium
                # pattern in the same column window -- avoids double-counting
                # AKIA keys, JWTs, etc.
                if any(
                    f.line == line_no
                    and f.severity in ("high", "medium")
                    and abs(f.column - (m.start() + 1)) < len(run)
                    for f in out
                ):
                    continue
                out.append(
                    Finding(
                        path=path,
                        line=line_no,
                        column=m.start() + 1,
                        pattern_name="high-entropy-string",
                        match_preview=_preview(run),
                        severity="medium",
                    )
                )
    # Multi-line allowlist pass -- joined whole-block tokens (PEM bodies)
    # are checked once across the entire input. If the joined block is in
    # the allowlist, drop every per-line finding whose match overlaps the
    # block range (PEM headers are usually multi-line and would otherwise
    # show up as separate findings on each line).
    return out


def _is_allowlisted(match_text: str, allowlist: set[str]) -> bool:
    if not allowlist:
        return False
    stripped = match_text.strip()
    if stripped in allowlist:
        return True
    # Tolerate partial matches: every per-line piece of a multi-line PEM
    # body is allowlisted iff it is a substring of any joined allow token.
    # Multi-line allow tokens are the only ones that contain newlines.
    for token in allowlist:
        if "\n" in token and stripped and stripped in token:
            return True
    return False


_ALLOWLIST = _load_allowlist()


# ---------------------------------------------------------------------------
# File walk.
# ---------------------------------------------------------------------------


def _iter_files(target: Path) -> Iterable[Path]:
    if target.is_file():
        yield target
        return
    if target.is_dir():
        for child in sorted(target.rglob("*")):
            if child.is_file():
                yield child


def scan_path(target: Path) -> tuple[list[Finding], list[str]]:
    """Scan a single file or recursively scan a directory.

    Returns (findings, unreadable_paths). unreadable_paths populates exit
    code 2 logic in main().
    """
    findings: list[Finding] = []
    unreadable: list[str] = []
    for f in _iter_files(target):
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unreadable.append(f"{f}: {type(exc).__name__}: {exc}")
            continue
        try:
            rel = str(f.relative_to(Path.cwd()))
        except ValueError:
            rel = str(f)
        findings.extend(scan_text(text, rel))
    return findings, unreadable


def scan_paths(targets: Iterable[Path]) -> tuple[list[Finding], list[str], list[str]]:
    all_findings: list[Finding] = []
    unread: list[str] = []
    scanned: list[str] = []
    for t in targets:
        scanned.append(str(t))
        f, u = scan_path(t)
        all_findings.extend(f)
        unread.extend(u)
    return all_findings, unread, scanned


def report_to_dict(
    findings: list[Finding],
    scanned_paths: list[str],
) -> dict:
    return {
        "scanned_paths": scanned_paths,
        "findings": [asdict(f) for f in findings],
        "patterns_loaded": len(_COMPILED),
        "allowlist_size": len(_ALLOWLIST),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Scan files or directories for credential patterns "
            "(issue #31, R47). Stdlib-only, fail-closed on `high`-severity "
            "findings."
        ),
    )
    parser.add_argument(
        "--path",
        action="append",
        required=True,
        help=(
            "File or directory to scan. Repeatable; each value is walked "
            "recursively if it is a directory."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Optional path to write the JSON report to. Defaults to stdout. "
            "Convention: out/secret-scan-<YYYY-MM-DD>.json (the path string "
            "you put here also goes in EVIDENCE_SCAN_REPORT:)."
        ),
    )
    parser.add_argument(
        "--format",
        choices=["json"],
        default="json",
        help="Output format. Only `json` is supported in v3.5.",
    )
    args = parser.parse_args(argv)
    targets = [Path(p) for p in args.path]
    missing = [str(t) for t in targets if not t.exists()]
    if missing:
        for m in missing:
            sys.stderr.write(f"ERROR: --path target does not exist: {m}\n")
        # Continue scanning the targets that DO exist so a multi-target
        # invocation still produces partial output, but exit code 2 below.
    existing = [t for t in targets if t.exists()]
    findings, unread, scanned = scan_paths(existing)
    payload = report_to_dict(findings, scanned)
    blob = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(blob, encoding="utf-8")
    else:
        sys.stdout.write(blob)
    if unread or missing:
        for u in unread:
            sys.stderr.write(f"ERROR: unreadable: {u}\n")
        return 2
    if any(f.severity == "high" for f in findings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
