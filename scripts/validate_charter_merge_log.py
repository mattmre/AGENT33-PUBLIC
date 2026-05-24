#!/usr/bin/env python3
"""scripts/validate_charter_merge_log.py -- verify
out/charter-merge-log.jsonl integrity (issue #43, cluster E 3/7).

Four checks, run to completion under HIGHEST-PRIORITY-WINS semantics
(v3.6 #101 reconciliation across all 4 cluster-E gates). Every check
runs against every record; the most load-bearing failure observed is
returned.

CRC32 contract (v3.6 #101 clarification of cluster-E finding #8):
charter-merge-log.jsonl ships PER-ROW CRC32 ONLY. Each row's `crc32`
footer is computed over the JSON body of THAT SAME ROW with the
`crc32` field excluded (sort_keys + (',', ':') + binascii.crc32
hex8). There is no `crc32_prev` chained-prev field on this artifact;
chain integrity is enforced separately via the per-lane
`prior_charter_sha` -> `new_charter_sha` SHA-DAG walked by
_walk_chain. The chained-prev hash pattern (where row N's `crc32`
covers row N-1's `crc32`) is shipped by cluster G artifacts
(workspace-hygiene, external-policy, research-sources); cluster E
explicitly uses the per-row pattern so a chain-mid CRC corruption
surfaces immediately at that row rather than masquerading as a
downstream chain integrity break.

  1. Schema       -- every line parses as JSON and validates against
                     charter-merge-log.schema.json. Per-record; all
                     violations are reported, then the highest-class
                     code is returned.
  2. CRC          -- every row's `crc32` matches the recomputed
                     per-row CRC32 over the JSON body excluding the
                     `crc32` field. Per-row, NOT chained-prev.
  3. Append-only  -- file's git history shows ONLY additions at
                     end-of-file. Implementation: `git log --numstat
                     --follow -- <path>`; for every commit touching
                     the file, `deletions == 0`. Skipped silently
                     when --skip-append-only-check is supplied OR
                     when the path is not inside a git repository.
  4. Chain        -- walk records in `ts` order; for every row past
                     the first `charter_open` of a `lane_id`, assert
                     `prior_charter_sha` equals the most recent row's
                     `new_charter_sha`. Two `charter_open` rows for
                     the same lane_id are L4. A non-charter_open row
                     after `charter_close` for the same lane_id is L4.

Exit codes -- operator-spec 5-class policy, highest-priority wins
(5 > 4 > 3 > 2 > 1; v3.6 #101 reconciliation):
  0 ok          every record valid
  1 drift       cross-artifact data drift (reserved; no single-file
                check in this gate emits 1 directly)
  2 schema      schema violation on a parseable record
  3 enum        closed-set vocabulary disagreement (reserved here;
                charter-merge-log enum drift is detected by the
                drift validator, not by this per-file gate)
  4 chain       chain integrity failure: per-row CRC mismatch,
                charter SHA-DAG break, second-charter_open per
                lane_id, kind-after-charter_close, or append-only
                history violation. All collapse here because each
                breaks the linear per-lane merge-log chain.
  5 corruption  F11 corruption: file not found, invalid-JSON record
                (raw bytes wrong), or IO / missing-dependency error.

Back-compat (legacy code may reference these): the previous mapping
(1=schema, 2=CRC, 3=append-only, 4=chain, 6=missing) is REPLACED by
the operator-spec mapping above. External callers that pinned the
old integers must migrate to the EXIT_* constants exported below.
"""

from __future__ import annotations

import argparse
import binascii
import json
import subprocess
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover -- back-compat probe
    print(
        "ERROR: jsonschema is required (pip install jsonschema). "
        "See v3.5/INSTALL.md.",
        file=sys.stderr,
    )
    # EXIT_CORRUPTION (5) under the operator-spec 5-class policy: a
    # missing required dependency is a structural corruption of the
    # toolchain that prevents the validator from running.
    sys.exit(5)


# Exit codes -- operator-spec 5-class policy (v3.6 #101 reconciliation
# across all 4 cluster-E gates). Highest-priority wins: 5 > 4 > 3 > 2 > 1.
EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_SCHEMA = 2
EXIT_ENUM = 3
EXIT_CHAIN = 4
EXIT_CORRUPTION = 5

# Back-compat aliases. Under the old 6-class mapping, append-only
# violations had their own exit code (3); under the v3.6 #101 5-class
# policy they collapse into EXIT_CHAIN(4) because an append-only
# violation breaks the linear merge-log chain. CRC mismatch also
# collapses into EXIT_CHAIN. IO errors collapse into EXIT_CORRUPTION.
EXIT_APPEND_ONLY = EXIT_CHAIN
EXIT_CRC = EXIT_CHAIN
EXIT_IO = EXIT_CORRUPTION

# Priority order: 5 > 4 > 3 > 2 > 1 (largest first).
_EXIT_PRIORITY: tuple[int, ...] = (
    EXIT_CORRUPTION,
    EXIT_CHAIN,
    EXIT_ENUM,
    EXIT_SCHEMA,
    EXIT_DRIFT,
)


def choose_exit_code(codes: list[int]) -> int:
    """Highest-priority wins across a list of observed exit codes.

    Empty list (or only-zeros) returns EXIT_OK. Any unrecognized
    non-zero code is treated as EXIT_DRIFT (the lowest non-zero
    severity) so future code-class additions never silently pass.
    """
    if not codes:
        return EXIT_OK
    present: set[int] = {c for c in codes if c != EXIT_OK}
    if not present:
        return EXIT_OK
    for priority_code in _EXIT_PRIORITY:
        if priority_code in present:
            return priority_code
    return EXIT_DRIFT

_SCRIPTS_DIR = Path(__file__).resolve().parent
_SCHEMA_PATH = (
    _SCRIPTS_DIR.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
    / "schemas"
    / "charter-merge-log.schema.json"
)


def _load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _serialize_for_crc(record: dict) -> bytes:
    """Mirror sticky_caveats_append._serialize_for_crc verbatim."""
    return json.dumps(
        {k: v for k, v in record.items() if k != "crc32"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_crc32(record: dict) -> str:
    """Mirror sticky_caveats_append.compute_crc32 verbatim."""
    return f"{binascii.crc32(_serialize_for_crc(record)) & 0xFFFFFFFF:08x}"


def _check_append_only(ledger_path: Path) -> tuple[int, str | None]:
    """Return (exit_code, error_message). 0 means PASS or SKIP.

    Walks `git log --numstat --follow -- <path>` for the file. If ANY
    commit touching the file shows deletions > 0, the file was edited
    in-place at some point -- exit code 3. A `git mv` shows deletions
    == previous_line_count and is also disallowed for this artifact.

    Skipped silently (returns 0) when:
      - the path is not inside a git repository
      - `git` is not on PATH
      - the path has never been committed (numstat is empty)
    """
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--numstat",
                "--follow",
                "--format=%H",
                "--",
                str(ledger_path),
            ],
            cwd=str(ledger_path.parent),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return EXIT_OK, None  # git not installed; back-compat skip
    if result.returncode != 0:
        # Not in a git repo, or git error; back-compat skip.
        return EXIT_OK, None
    if not result.stdout.strip():
        return EXIT_OK, None  # never committed; back-compat skip

    current_commit: str | None = None
    for line in result.stdout.splitlines():
        line = line.rstrip()
        if not line:
            continue
        # `git log --format=%H --numstat` emits the SHA on its own line
        # followed by one numstat line per file in the commit. Detect
        # 40-hex-digit lines as commit SHAs.
        if len(line) == 40 and all(c in "0123456789abcdef" for c in line):
            current_commit = line
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted, _path = parts[0], parts[1], parts[2]
        # Binary files render `-\t-`; we treat them as a violation
        # (the merge log is JSONL, never binary).
        if added == "-" or deleted == "-":
            return EXIT_CHAIN, (
                f"charter-merge-log: append-only check failed: commit "
                f"{current_commit} recorded a binary diff for "
                f"{ledger_path} (the artifact MUST be JSONL)"
            )
        try:
            deleted_int = int(deleted)
        except ValueError:
            continue
        if deleted_int > 0:
            return EXIT_CHAIN, (
                f"charter-merge-log: append-only check failed: commit "
                f"{current_commit} deleted {deleted_int} line(s) from "
                f"{ledger_path}. Append-only artifacts MUST only grow; "
                f"in-place edits, line removals, and `git mv` are L4 "
                f"(issue #43)."
            )
    return EXIT_OK, None


def _walk_chain(records: list[dict]) -> tuple[int, str | None]:
    """Walk records in `ts` order, asserting per-lane chain integrity.

    Returns (exit_code, error_message). 0 means PASS.
    """
    # Stable sort by (ts, original_index) so equal-ts rows preserve file
    # order. ts is required by the schema; if any row is missing ts the
    # schema check would already have failed.
    indexed = list(enumerate(records))
    indexed.sort(key=lambda pair: (pair[1].get("ts", ""), pair[0]))

    # Per-lane state: latest seen new_charter_sha (or charter_sha for
    # charter_open / final_charter_sha for charter_close), plus a flag
    # for whether the lane has been closed.
    lane_state: dict[str, dict] = {}

    for original_idx, rec in indexed:
        lane_id = rec.get("lane_id")
        kind = rec.get("kind")
        if not isinstance(lane_id, str) or not isinstance(kind, str):
            continue  # schema check would have caught it
        line_no = original_idx + 1
        state = lane_state.get(lane_id)

        if kind == "charter_open":
            if state is not None:
                return EXIT_CHAIN, (
                    f"charter-merge-log: line {line_no}: chain "
                    f"violation: second `charter_open` for lane_id "
                    f"{lane_id!r} (the first was at line "
                    f"{state['first_line']}). One charter_open per "
                    f"lane_id is L4 (issue #43)."
                )
            lane_state[lane_id] = {
                "head_sha": rec.get("charter_sha"),
                "closed": False,
                "first_line": line_no,
            }
            continue

        if state is None:
            return EXIT_CHAIN, (
                f"charter-merge-log: line {line_no}: chain violation: "
                f"row of kind {kind!r} for lane_id {lane_id!r} appears "
                f"before any `charter_open` for that lane (issue #43)."
            )
        if state["closed"]:
            return EXIT_CHAIN, (
                f"charter-merge-log: line {line_no}: chain violation: "
                f"row of kind {kind!r} for lane_id {lane_id!r} appears "
                f"after `charter_close` for that lane (issue #43)."
            )

        if kind == "charter_close":
            final = rec.get("final_charter_sha")
            head = state["head_sha"]
            if isinstance(final, str) and isinstance(head, str) and final != head:
                return EXIT_CHAIN, (
                    f"charter-merge-log: line {line_no}: chain "
                    f"violation: `charter_close.final_charter_sha` "
                    f"({final!r}) for lane_id {lane_id!r} does not "
                    f"equal the most recent head charter_sha "
                    f"({head!r}) (issue #43)."
                )
            state["closed"] = True
            continue

        # All other kinds carry prior_charter_sha + new_charter_sha.
        prior = rec.get("prior_charter_sha")
        new = rec.get("new_charter_sha")
        head = state["head_sha"]
        if isinstance(prior, str) and isinstance(head, str) and prior != head:
            return EXIT_CHAIN, (
                f"charter-merge-log: line {line_no}: chain violation: "
                f"`prior_charter_sha` ({prior!r}) for lane_id "
                f"{lane_id!r} does not equal the most recent head "
                f"charter_sha ({head!r}). The merge log MUST form a "
                f"linear chain per lane_id; skip-ahead or branched "
                f"history is L4 (issue #43)."
            )
        if isinstance(new, str):
            state["head_sha"] = new

    return EXIT_OK, None


def validate_file(
    ledger_path: Path,
    skip_append_only_check: bool = False,
) -> int:
    """Validate the charter-merge-log file against the operator-spec
    5-class exit-code policy (v3.6 #101 reconciliation across all 4
    cluster-E gates).

    Highest-priority-wins semantics: every check runs to completion
    (no fail-fast); the most load-bearing failure observed across
    every check is returned. See module docstring for the full class
    matrix; in this gate, schema-class drift maps to EXIT_SCHEMA(2);
    per-row CRC + append-only + chain SHA-DAG all collapse into
    EXIT_CHAIN(4); file-not-found / invalid-JSON map to
    EXIT_CORRUPTION(5).
    """
    observed_codes: list[int] = []
    if not ledger_path.exists():
        print(
            f"ERROR: charter-merge-log file not found: {ledger_path}",
            file=sys.stderr,
        )
        return EXIT_CORRUPTION

    schema = _load_schema()
    validator = Draft202012Validator(schema)

    raw = ledger_path.read_text(encoding="utf-8").splitlines()
    records: list[dict] = []
    saw_invalid_json = False
    for idx, line in enumerate(raw, start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            print(
                f"charter-merge-log: line {idx}: invalid JSON ({exc}) "
                f"-- F11 corruption",
                file=sys.stderr,
            )
            observed_codes.append(EXIT_CORRUPTION)
            saw_invalid_json = True
            continue
        records.append(rec)

    # When invalid-JSON corruption is present, downstream checks are
    # not meaningfully runnable on the partial record set; surface the
    # corruption directly so the operator fixes the bytes first.
    if saw_invalid_json:
        return choose_exit_code(observed_codes)

    # 1. Schema -- run every record; collect every violation.
    for idx, rec in enumerate(records, start=1):
        errors = sorted(validator.iter_errors(rec), key=lambda e: list(e.path))
        if errors:
            for err in errors:
                path_repr = (
                    "/".join(str(p) for p in err.absolute_path)
                    or "<root>"
                )
                print(
                    f"charter-merge-log: line {idx}: schema violation: "
                    f"{path_repr}: {err.message}",
                    file=sys.stderr,
                )
            observed_codes.append(EXIT_SCHEMA)

    # 2. CRC -- run every record (per-row CRC contract; see module
    # docstring). Each mismatch surfaces EXIT_CHAIN -- a per-row CRC
    # mismatch is a chain-class failure under the operator-spec
    # 5-class policy because it breaks the row's place in the linear
    # per-lane chain.
    for idx, rec in enumerate(records, start=1):
        actual = compute_crc32(rec)
        stored = rec.get("crc32")
        if actual != stored:
            print(
                f"charter-merge-log: line {idx}: crc32 mismatch "
                f"(stored={stored!r}, computed={actual!r})",
                file=sys.stderr,
            )
            observed_codes.append(EXIT_CHAIN)

    # 3. Append-only -- single-shot check; emits at most one code.
    if not skip_append_only_check:
        code, msg = _check_append_only(ledger_path)
        if code != 0:
            if msg:
                print(msg, file=sys.stderr)
            observed_codes.append(code)

    # 4. Chain integrity -- single-shot SHA-DAG walker.
    code, msg = _walk_chain(records)
    if code != 0:
        if msg:
            print(msg, file=sys.stderr)
        observed_codes.append(code)

    return choose_exit_code(observed_codes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--path",
        required=True,
        help=(
            "Path to the charter-merge-log JSONL file (typically "
            "out/charter-merge-log.jsonl)."
        ),
    )
    parser.add_argument(
        "--skip-append-only-check",
        action="store_true",
        help=(
            "Skip the git-history append-only check. Useful for "
            "validating a fixture file that lives outside a git repo "
            "or has not been committed yet."
        ),
    )
    args = parser.parse_args(argv)
    return validate_file(
        Path(args.path),
        skip_append_only_check=args.skip_append_only_check,
    )


if __name__ == "__main__":
    sys.exit(main())
