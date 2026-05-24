#!/usr/bin/env python3
"""scripts/redact_evidence.py -- project release gate redaction helper.

Stdlib-only redactor that reuses the pattern table from
`scan_evidence_secrets.py` and replaces every match with the literal
placeholder `<REDACTED:pattern-name:LEN=N>` (where N is the byte length of
the original match). Issue #31.

Usage:
  python scripts/redact_evidence.py --path FILE                # writes to stdout
  python scripts/redact_evidence.py --path FILE --in-place     # writes <FILE>.pre-redact.bak then overwrites
  python scripts/redact_evidence.py --path FILE --output OUT   # writes to OUT (creates parents)

Profiles:
  --profile all       (default) -- every named pattern.
  --profile high      -- high-severity patterns only.
  --profile medium    -- high + medium.

The .pre-redact.bak backup is itself a side-effect-tracked artifact (per
issue #35 / R45). When the original file is OUTSIDE HARNESS_OUTPUT_DIR,
the operator MUST list the .bak in RESOURCE_LEDGER as
`type: file-outside-output-dir`. The .bak file is `.gitignore`'d in the kit
because committing the un-redacted backup would defeat the gate (R47 +
R47g would silently pass while the original secret remains in git
history).

Exit codes:
  0  Redaction completed (regardless of whether any pattern fired).
  1  Source file unreadable, output path unwritable, or backup creation
     failed. Stderr describes the failure.
  2  Argparse / usage error (handled by argparse).

Encoding contract:
  The redactor reads the source file as strict UTF-8 (`encoding="utf-8"`).
  - Multi-byte UTF-8 sequences round-trip losslessly through the regex
    pass and re-encode unchanged.
  - Null bytes (0x00) embedded inside an otherwise valid UTF-8 stream
    are passed through unchanged (Python str preserves them).
  - Files in latin-1, UTF-16, or any other non-UTF-8 encoding (and true
    binaries that contain bytes invalid as UTF-8) raise
    `UnicodeDecodeError` and exit 1 with a stderr line naming the
    failing path. The redactor never silently corrupts a file by
    forcing a wrong-encoding decode.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

# Re-use the scanner's compiled patterns so this redactor and the gate
# scanner stay byte-identical on what they recognise. The scanner lives
# next to this file in v3.5/scripts/; v3.5/scripts/ is not a package
# (no __init__.py), so we add the script directory to sys.path and do a
# top-level import. This keeps the script runnable as a CLI from any cwd.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
from scan_evidence_secrets import _COMPILED, _ALLOWLIST  # type: ignore  # noqa: E402


_SEVERITY_BY_NAME: dict[str, str] = {n: s for (n, _, s) in (
    (name, pat, sev) for (name, pat, sev) in _COMPILED
)}


def _profile_filter(profile: str) -> set[str]:
    if profile == "all":
        return {n for (n, _, _) in _COMPILED}
    if profile == "high":
        return {n for (n, _, s) in _COMPILED if s == "high"}
    if profile == "medium":
        return {n for (n, _, s) in _COMPILED if s in ("high", "medium")}
    raise ValueError(f"unknown profile: {profile!r}")


def redact_text(text: str, profile: str = "all") -> str:
    """Return a copy of `text` with each pattern hit replaced.

    Patterns are applied in PATTERN_TABLE order; later rules see the output
    of earlier rules. Allowlisted matches are NOT redacted (the scanner's
    own fixtures intentionally leak the allowlisted credentials so R47e /
    R47g have something to fingerprint against).
    """
    enabled = _profile_filter(profile)
    out = text
    for name, pat, _sev in _COMPILED:
        if name not in enabled:
            continue
        def _sub(m: "re.Match[str]") -> str:  # noqa: F821 -- forward type
            match_text = m.group(0)
            stripped = match_text.strip()
            if stripped in _ALLOWLIST:
                return match_text
            for token in _ALLOWLIST:
                if "\n" in token and stripped and stripped in token:
                    return match_text
            return f"<REDACTED:{name}:LEN={len(match_text)}>"
        out = pat.sub(_sub, out)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Redact credential patterns in an evidence file. Reuses the "
            "scan_evidence_secrets.py pattern table so detection and "
            "redaction stay aligned. Issue #31."
        ),
    )
    parser.add_argument("--path", required=True, help="File to redact.")
    parser.add_argument(
        "--profile",
        choices=["all", "high", "medium"],
        default="all",
        help="Pattern subset to redact. Default `all`.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help=(
            "Write back to --path. Creates <PATH>.pre-redact.bak first; "
            ".gitignore must cover *.pre-redact.bak in this repo."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Write redacted output to this path instead of stdout. "
            "Mutually exclusive with --in-place."
        ),
    )
    args = parser.parse_args(argv)
    if args.in_place and args.output:
        sys.stderr.write(
            "ERROR: --in-place and --output are mutually exclusive.\n"
        )
        return 1
    src = Path(args.path)
    try:
        text = src.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write(
            f"ERROR: cannot read {args.path}: {type(exc).__name__}: {exc}\n"
        )
        return 1
    redacted = redact_text(text, args.profile)
    if args.in_place:
        bak = src.with_suffix(src.suffix + ".pre-redact.bak")
        try:
            bak.write_text(text, encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(
                f"ERROR: cannot write backup {bak}: {exc}\n"
            )
            return 1
        try:
            src.write_text(redacted, encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(
                f"ERROR: cannot overwrite {src}: {exc}\n"
            )
            return 1
        return 0
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            out_path.write_text(redacted, encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(
                f"ERROR: cannot write {args.output}: {exc}\n"
            )
            return 1
        return 0
    sys.stdout.write(redacted)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
