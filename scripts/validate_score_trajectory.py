#!/usr/bin/env python3
"""scripts/validate_score_trajectory.py — verify
out/bhs-trajectory.jsonl integrity AND classify trailing-N=5 BHS
trajectory windows from out/bhs-ledger.jsonl (issue #6, cluster E
6/7).

Five checks (the trajectory file is JSONL with the same CRC32 +
append-only + chain discipline as charter-merge-log.jsonl), plus an
optional classifier mode that re-derives windows from the bhs-ledger
and reports the canonical pattern token:

  1. Schema       -- every line parses as JSON and validates against
                     bhs-trajectory.schema.json.
  2. CRC          -- every row's `crc32` matches the recomputed CRC32
                     over the JSON body excluding the `crc32` field
                     (mirrors validate_charter_merge_log.compute_crc32).
  3. Append-only  -- file's git history shows ONLY additions at end-of-
                     file (mirrors validate_charter_merge_log).
  4. Chain        -- walk records in `ts` order; for every
                     trajectory_window row past the first per lane_id,
                     assert window_size matches the array lengths AND
                     window_pr_refs forms a non-decreasing prefix when
                     consecutive windows overlap (a window that starts
                     before the previous window's last pr_ref is L4 --
                     the trajectory walker emits monotonically advancing
                     windows).
  5. Classifier   -- optional. Given --classify-from-ledger PATH +
                     --window-size N (default 5), read the trailing N
                     bhs_official rows from the bhs-ledger, classify
                     the pattern, and either PRINT the canonical row
                     (default: --emit-row=stdout) OR APPEND it to the
                     trajectory JSONL when --append-to PATH is given.

Pattern classifier (closed-set: see bhs-trajectory-patterns.txt):

  converging              -- monotonically non-decreasing AND
                             (last - first) >= 5
  oscillating             -- direction changes >= 2 times across the
                             window
  regressing              -- monotonically non-increasing AND
                             (first - last) >= 5
  plateau_after_late_pr   -- max - min <= 3 AND last < 100 AND >= 1
                             entry was a score_unchanged_iteration

A window that fits NONE of the above is reported as `converging` by
default (the healthy fallback) -- a flat 100-100-100-100-100 window
is converging-at-ceiling, not regressing.

Exit codes -- operator-spec 5-class policy, highest-priority wins
(5 > 4 > 3 > 2 > 1; v3.6 #101 reconciliation across all 4 cluster-E
gates):
  0 ok          every check passed (and, in classifier mode, a row was
                emitted successfully)
  1 drift       cross-artifact data drift (reserved; no single-file
                check in this gate emits 1 directly)
  2 schema      schema violation on a parseable record
  3 enum        closed-set vocabulary disagrees (pattern enum drift
                between schema and bhs-trajectory-patterns.txt OR
                classifier failure due to ledger schema error)
  4 chain       chain integrity failure: per-row CRC mismatch,
                window-advance violation, or append-only history
                violation all collapse here because each breaks the
                linear trajectory chain
  5 corruption  F11 corruption: file unreadable, invalid-JSON record
                (raw bytes wrong), or IO / missing-dependency error

Back-compat aliases (kept so external callers that reference the old
names keep working): EXIT_CRC=EXIT_CHAIN(4), EXIT_APPEND_ONLY=
EXIT_CHAIN(4), EXIT_CLASSIFIER=EXIT_ENUM(3), EXIT_IO=
EXIT_CORRUPTION(5).
"""

from __future__ import annotations

import argparse
import binascii
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

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
    # toolchain that prevents the validator from even running.
    sys.exit(5)

_SCRIPTS_DIR = Path(__file__).resolve().parent
_SCHEMA_PATH = (
    _SCRIPTS_DIR.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
    / "schemas"
    / "bhs-trajectory.schema.json"
)
_PATTERN_ENUM_PATH = (
    _SCRIPTS_DIR.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
    / "enums"
    / "bhs-trajectory-patterns.txt"
)

DEFAULT_WINDOW_SIZE = 5
MIN_WINDOW_SIZE = 2
MAX_WINDOW_SIZE = 5

# Exit codes -- operator-spec 5-class policy (v3.6 #101 reconciliation
# across all 4 cluster-E gates).
# Highest-priority wins: 5 > 4 > 3 > 2 > 1 (larger code is more
# load-bearing; choose_exit_code scans largest-first).
#   0 ok               -- every record valid
#   1 drift            -- cross-artifact data drift (the core class:
#                         classifier disagreement is mapped here
#                         because the pattern is recomputed cross-
#                         artifact from the bhs-ledger)
#   2 schema           -- one underlying artifact does not validate
#   3 enum             -- closed-set vocabulary disagrees between
#                         artifact and the on-disk enum file (pattern
#                         enum drift between schema and
#                         bhs-trajectory-patterns.txt)
#   4 chain            -- chain integrity failure (window-advance
#                         monotonic invariant; per-row CRC mismatch
#                         on the JSONL chain; append-only violation
#                         all collapse here because each breaks the
#                         linear trajectory chain)
#   5 corruption       -- F11 corruption (file unreadable, JSON parse
#                         fails before schema can run, malformed
#                         bytes on disk). IO errors map here -- the
#                         consumer cannot proceed.
EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_SCHEMA = 2
EXIT_ENUM = 3
EXIT_CHAIN = 4
EXIT_CORRUPTION = 5
# Back-compat aliases for in-tree code that pre-dates the v3.6 #101
# reconciliation. New code should reference the operator-spec names.
EXIT_CRC = EXIT_CHAIN
EXIT_APPEND_ONLY = EXIT_CHAIN
EXIT_CLASSIFIER = EXIT_ENUM
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

    Returns EXIT_OK when codes is empty or contains only zeros. Any
    unrecognized non-zero code is treated as EXIT_DRIFT (the lowest
    non-zero severity) so future code-class additions never silently
    pass.
    """
    if not codes:
        return EXIT_OK
    present: set[int] = {c for c in codes if c != EXIT_OK}
    if not present:
        return EXIT_OK
    for priority_code in _EXIT_PRIORITY:
        if priority_code in present:
            return priority_code
    # Any non-zero code not in _EXIT_PRIORITY -> treat as DRIFT (the
    # least-severe non-zero class; never silently OK).
    return EXIT_DRIFT


# ---------------------------------------------------------------------------
# Helpers (CRC32 + schema load + enum load) -- mirror
# validate_charter_merge_log.py verbatim where possible.
# ---------------------------------------------------------------------------


def _load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_pattern_enum() -> list[str]:
    out: list[str] = []
    for raw in _PATTERN_ENUM_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def _serialize_for_crc(record: dict) -> bytes:
    """Mirror validate_charter_merge_log._serialize_for_crc verbatim."""
    return json.dumps(
        {k: v for k, v in record.items() if k != "crc32"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_crc32(record: dict) -> str:
    """Mirror validate_charter_merge_log.compute_crc32 verbatim."""
    return f"{binascii.crc32(_serialize_for_crc(record)) & 0xFFFFFFFF:08x}"


# ---------------------------------------------------------------------------
# Pattern classifier (the heart of R69).
# ---------------------------------------------------------------------------


def classify_pattern(
    scores: list[int],
    has_unchanged_iteration: bool,
) -> str:
    """Classify a list of bhs_official scores into one of the four
    canonical patterns from bhs-trajectory-patterns.txt.

    Args:
      scores: ordered list of integer scores (oldest -> newest), all in
        [0, 100]. Length must be in [MIN_WINDOW_SIZE, MAX_WINDOW_SIZE].
      has_unchanged_iteration: True iff at least one of the underlying
        bhs-ledger rows that produced this window was a
        score_unchanged_iteration record. Required for the
        plateau_after_late_pr classification.

    Returns one of: converging | oscillating | regressing |
    plateau_after_late_pr.

    Decision order (highest-priority pattern wins):
      1. plateau_after_late_pr  (max - min <= 3 AND last < 100 AND
                                 has_unchanged_iteration)
      2. regressing             (monotonic non-increasing AND
                                 (first - last) >= 5)
      3. oscillating            (direction changes >= 2 times)
      4. converging             (default / catch-all -- includes
                                 monotonic non-decreasing AND
                                 flat-at-ceiling)

    Rationale for the priority order: plateau_after_late_pr is the
    sneakiest failure mode (the lane *looks* converged but is stuck
    short of 100); we MUST classify it before falling through to
    converging. regressing dominates oscillating because a window that
    is both regressing AND oscillating (e.g. 90, 95, 90, 85, 80 -- one
    up-tick then four down-ticks) is mechanically regressing -- the
    direction-change count alone would mis-classify it as oscillating.
    """
    if len(scores) < MIN_WINDOW_SIZE or len(scores) > MAX_WINDOW_SIZE:
        raise ValueError(
            f"classify_pattern: scores length {len(scores)} not in "
            f"[{MIN_WINDOW_SIZE}, {MAX_WINDOW_SIZE}]"
        )
    if any(not isinstance(s, int) or s < 0 or s > 100 for s in scores):
        raise ValueError(
            f"classify_pattern: scores {scores!r} contain a value "
            f"outside [0, 100]"
        )

    first, last = scores[0], scores[-1]
    s_max = max(scores)
    s_min = min(scores)

    # Pattern 1: plateau_after_late_pr (max - min <= 3 AND last < 100
    # AND >= 1 unchanged iteration).
    if s_max - s_min <= 3 and last < 100 and has_unchanged_iteration:
        return "plateau_after_late_pr"

    # Pattern 2: regressing (monotonic non-increasing AND drop >= 5).
    monotonic_down = all(
        scores[i] >= scores[i + 1] for i in range(len(scores) - 1)
    )
    if monotonic_down and (first - last) >= 5:
        return "regressing"

    # Pattern 3: oscillating (>= 2 direction changes).
    direction_changes = 0
    last_dir = 0  # -1, 0, +1
    for i in range(1, len(scores)):
        diff = scores[i] - scores[i - 1]
        cur_dir = (diff > 0) - (diff < 0)
        if cur_dir != 0 and last_dir != 0 and cur_dir != last_dir:
            direction_changes += 1
        if cur_dir != 0:
            last_dir = cur_dir
    if direction_changes >= 2:
        return "oscillating"

    # Pattern 4: converging (default / catch-all).
    return "converging"


# ---------------------------------------------------------------------------
# Append-only check (mirrors validate_charter_merge_log._check_append_only).
# ---------------------------------------------------------------------------


def _check_append_only(ledger_path: Path) -> tuple[int, str | None]:
    """Return (exit_code, error_message). 0 means PASS or SKIP.

    SKIP semantics (returns EXIT_OK with a stderr-bound message):
      - git binary not on PATH (FileNotFoundError on subprocess.run)
      - git command returned non-zero (e.g. not a repo)
      - git log returned empty (ledger not committed yet)

    PR #55 HP-O remediation (LOW-1): the previous shape returned
    (EXIT_OK, None) for the three skip cases, silently disabling
    the append-only check whenever git was absent. Now each skip
    path returns a breadcrumb message so the caller can stderr-emit
    "append-only check SKIPPED because <reason>" and the operator
    can audit why the gate was a no-op rather than a real PASS.
    Exit semantics are preserved (EXIT_OK) to avoid breaking dev
    environments without git in PATH; the loudness change closes
    the silent-swallow class without false-positive churn.
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
        return EXIT_OK, (
            "bhs-trajectory: append-only check SKIPPED -- git binary "
            "not on PATH. Cannot verify append-only invariant. This "
            "is a SKIP, not a PASS: the ledger may contain hidden "
            "in-place edits."
        )
    if result.returncode != 0:
        return EXIT_OK, (
            f"bhs-trajectory: append-only check SKIPPED -- git "
            f"command returned {result.returncode} (not a git repo "
            f"or git error). Cannot verify append-only invariant. "
            f"This is a SKIP, not a PASS."
        )
    if not result.stdout.strip():
        return EXIT_OK, (
            "bhs-trajectory: append-only check SKIPPED -- git log "
            "returned no history for this ledger (not yet committed). "
            "Append-only invariant has nothing to check; PASS-by-vacuity."
        )

    current_commit: str | None = None
    for line in result.stdout.splitlines():
        line = line.rstrip()
        if not line:
            continue
        if len(line) == 40 and all(c in "0123456789abcdef" for c in line):
            current_commit = line
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted, _path = parts[0], parts[1], parts[2]
        if added == "-" or deleted == "-":
            return EXIT_APPEND_ONLY, (
                f"bhs-trajectory: append-only check failed: commit "
                f"{current_commit} recorded a binary diff for "
                f"{ledger_path} (the artifact MUST be JSONL)"
            )
        try:
            deleted_int = int(deleted)
        except ValueError:
            continue
        if deleted_int > 0:
            return EXIT_APPEND_ONLY, (
                f"bhs-trajectory: append-only check failed: commit "
                f"{current_commit} deleted {deleted_int} line(s) from "
                f"{ledger_path}. Append-only artifacts MUST only grow; "
                f"in-place edits, line removals, and `git mv` are L4 "
                f"(issue #6)."
            )
    return EXIT_OK, None


# ---------------------------------------------------------------------------
# Chain integrity walker.
# ---------------------------------------------------------------------------


def _walk_chain(records: list[dict]) -> tuple[int, str | None]:
    """Walk records in `ts` order, asserting per-lane window-advance
    invariant.

    Returns (exit_code, error_message). 0 means PASS.
    """
    indexed = list(enumerate(records))
    indexed.sort(key=lambda pair: (pair[1].get("ts", ""), pair[0]))

    # Per-lane state: most-recent window's newest pr_ref (to enforce
    # monotonic advancement).
    lane_state: dict[str, dict] = {}

    for original_idx, rec in indexed:
        lane_id = rec.get("lane_id")
        kind = rec.get("kind")
        if not isinstance(lane_id, str) or not isinstance(kind, str):
            continue  # schema check would have caught it
        line_no = original_idx + 1
        if kind != "trajectory_window":
            continue  # only one kind defined; future kinds skip the walk
        prs = rec.get("window_pr_refs")
        scores = rec.get("window_scores")
        wsize = rec.get("window_size")
        if (
            not isinstance(prs, list)
            or not isinstance(scores, list)
            or not isinstance(wsize, int)
        ):
            continue  # schema check would have caught it
        if len(prs) != wsize or len(scores) != wsize:
            return EXIT_CHAIN, (
                f"bhs-trajectory: line {line_no}: chain violation: "
                f"window_size={wsize} but window_pr_refs has "
                f"{len(prs)} entries and window_scores has "
                f"{len(scores)} entries (cross-array length mismatch). "
                f"The trajectory schema's prefixItems contract requires "
                f"all three to agree (issue #6)."
            )
        prev = lane_state.get(lane_id)
        if prev is not None:
            prev_last_pr = prev["last_pr_ref"]
            prev_prs: list[str] = prev["last_window_prs"]
            # Enforce monotonic advancement: the new window's first
            # pr_ref MUST be >= the previous window's first pr_ref in
            # the prev window's order. Concretely: the new window's
            # FIRST entry must appear in the previous window OR be
            # newer than every entry in the previous window. Cheapest
            # way to express that without a global ordering: assert
            # the new window's LAST pr_ref is NOT in the previous
            # window's strict-prefix (i.e. the new window cannot
            # terminate inside the previous window's body).
            if prev_last_pr in prs:
                # Overlap is fine; just track the new tail.
                pass
            elif prs[-1] in prev_prs[:-1]:
                return EXIT_CHAIN, (
                    f"bhs-trajectory: line {line_no}: chain violation: "
                    f"window {prs!r} for lane_id {lane_id!r} terminates "
                    f"inside the previous window's body "
                    f"({prev_prs!r}); trajectory windows MUST advance "
                    f"monotonically (issue #6)."
                )
        lane_state[lane_id] = {
            "last_pr_ref": prs[-1],
            "last_window_prs": prs,
        }

    return EXIT_OK, None


# ---------------------------------------------------------------------------
# Validation driver.
# ---------------------------------------------------------------------------


def validate_file(
    trajectory_path: Path,
    skip_append_only_check: bool = False,
) -> int:
    """Validate the bhs-trajectory file against the operator-spec
    5-class exit-code policy (v3.6 #101 reconciliation across all 4
    cluster-E gates).

    Highest-priority-wins semantics: every check runs to completion
    (no fail-fast); the most load-bearing failure observed across
    every check is returned. Sub-classes:
      EXIT_OK         0  -- every record valid
      EXIT_DRIFT      1  -- (reserved for cross-artifact drift; no
                            single-file check in this gate emits 1)
      EXIT_SCHEMA     2  -- schema violation OR pre-schema parse fail
                            on a non-corrupted JSON record
      EXIT_ENUM       3  -- closed-set vocabulary disagreement
                            (pattern enum drift schema vs on-disk
                            bhs-trajectory-patterns.txt)
      EXIT_CHAIN      4  -- chain integrity failure: per-row CRC
                            mismatch, window-advance violation, or
                            append-only history violation. All three
                            collapse here because each breaks the
                            linear trajectory chain.
      EXIT_CORRUPTION 5  -- F11 corruption: file unreadable or
                            invalid-JSON record (raw bytes wrong).
    """
    observed_codes: list[int] = []
    if not trajectory_path.exists():
        print(
            f"ERROR: bhs-trajectory file not found: {trajectory_path}",
            file=sys.stderr,
        )
        return EXIT_CORRUPTION

    schema = _load_schema()
    validator = Draft202012Validator(schema)

    # Drift cross-check: schema enum MUST equal the on-disk pattern
    # enum file (the drift validator does the full parity check; this
    # is a defensive guard for callers that bypass the drift gate).
    try:
        on_disk_enum = set(_load_pattern_enum())
    except OSError:
        on_disk_enum = set()
    schema_enum: set[str] = set()
    for definition in schema.get("$defs", {}).values():
        if isinstance(definition, dict) and "enum" in definition:
            schema_enum.update(definition["enum"])
    if on_disk_enum and not on_disk_enum.issubset(schema_enum):
        print(
            f"bhs-trajectory: pattern enum drift between schema "
            f"{sorted(schema_enum)!r} and on-disk file "
            f"{sorted(on_disk_enum)!r}",
            file=sys.stderr,
        )
        observed_codes.append(EXIT_ENUM)

    raw = trajectory_path.read_text(encoding="utf-8").splitlines()
    records: list[dict] = []
    saw_invalid_json = False
    for idx, line in enumerate(raw, start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            print(
                f"bhs-trajectory: line {idx}: invalid JSON ({exc}) -- "
                f"F11 corruption",
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
        errors = sorted(
            validator.iter_errors(rec), key=lambda e: list(e.path)
        )
        if errors:
            for err in errors:
                path_repr = (
                    "/".join(str(p) for p in err.absolute_path)
                    or "<root>"
                )
                print(
                    f"bhs-trajectory: line {idx}: schema violation: "
                    f"{path_repr}: {err.message}",
                    file=sys.stderr,
                )
            observed_codes.append(EXIT_SCHEMA)

    # 2. CRC -- run every record; collect every CRC mismatch.
    for idx, rec in enumerate(records, start=1):
        actual = compute_crc32(rec)
        stored = rec.get("crc32")
        if actual != stored:
            print(
                f"bhs-trajectory: line {idx}: crc32 mismatch "
                f"(stored={stored!r}, computed={actual!r})",
                file=sys.stderr,
            )
            observed_codes.append(EXIT_CHAIN)

    # 3. Append-only -- single-shot check; emits at most one code.
    # PR #55 HP-O remediation (LOW-1): emit msg whenever present so
    # SKIP breadcrumbs (returned with EXIT_OK when git is absent or
    # ledger is uncommitted) reach the operator, closing the silent
    # swallow class. Only non-zero codes contribute to the exit set.
    if not skip_append_only_check:
        code, msg = _check_append_only(trajectory_path)
        if msg:
            print(msg, file=sys.stderr)
        if code != 0:
            observed_codes.append(code)

    # 4. Chain integrity -- single-shot walker; emits at most one code.
    code, msg = _walk_chain(records)
    if code != 0:
        if msg:
            print(msg, file=sys.stderr)
        observed_codes.append(code)

    return choose_exit_code(observed_codes)


# ---------------------------------------------------------------------------
# Classifier driver (R69 mode).
# ---------------------------------------------------------------------------


def _read_bhs_ledger(ledger_path: Path) -> list[dict]:
    """Read and JSON-parse the bhs-ledger.jsonl. Does NOT schema-validate
    here -- the caller decides whether to enforce schema. Empty/blank
    lines are skipped silently."""
    out: list[dict] = []
    for raw in ledger_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _trailing_official_window(
    ledger_records: list[dict],
    window_size: int,
) -> tuple[list[str], list[int], bool, int, int]:
    """Return (pr_refs, scores, has_unchanged_iteration,
    first_line_no, last_line_no) for the trailing N=window_size
    bhs_official entries.

    Raises ValueError when fewer than window_size bhs_official rows
    exist.
    """
    indexed: list[tuple[int, dict]] = list(enumerate(ledger_records, start=1))
    official = [
        (line_no, rec)
        for line_no, rec in indexed
        if rec.get("criterion") == "bhs_official"
    ]
    if len(official) < window_size:
        raise ValueError(
            f"trailing window: bhs-ledger has only {len(official)} "
            f"bhs_official rows, need {window_size}"
        )
    tail = official[-window_size:]
    pr_refs = [rec.get("pr_ref", "") for _, rec in tail]
    scores = [rec.get("delta_to") for _, rec in tail]
    if any(not isinstance(s, int) for s in scores):
        raise ValueError(
            f"trailing window: at least one delta_to value is not an "
            f"integer: {scores!r}"
        )
    has_unchanged = any(
        rec.get("record_kind") == "score_unchanged_iteration"
        for _, rec in tail
    )
    first_line = tail[0][0]
    last_line = tail[-1][0]
    return pr_refs, scores, has_unchanged, first_line, last_line


def classify_from_ledger(
    ledger_path: Path,
    lane_id: str,
    window_size: int,
    agent_session_id: str,
    source_ledger_path: str | None = None,
) -> dict:
    """Build a canonical trajectory_window record from the trailing
    `window_size` bhs_official entries in `ledger_path`. Adds the
    crc32 footer.

    Returns the record as a dict (caller decides whether to PRINT or
    APPEND it).
    """
    if not ledger_path.exists():
        raise FileNotFoundError(str(ledger_path))
    if window_size < MIN_WINDOW_SIZE or window_size > MAX_WINDOW_SIZE:
        raise ValueError(
            f"window_size {window_size} not in "
            f"[{MIN_WINDOW_SIZE}, {MAX_WINDOW_SIZE}]"
        )
    records = _read_bhs_ledger(ledger_path)
    pr_refs, scores, has_unchanged, first_line, last_line = (
        _trailing_official_window(records, window_size)
    )
    pattern = classify_pattern(scores, has_unchanged)
    ts = (
        datetime.now(tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    record: dict = {
        "ts": ts,
        "kind": "trajectory_window",
        "lane_id": lane_id,
        "window_size": window_size,
        "window_pr_refs": pr_refs,
        "window_scores": scores,
        "pattern": pattern,
        "computed_by_agent_session_id": agent_session_id,
    }
    if source_ledger_path is not None:
        record["source_ledger_path"] = source_ledger_path
        record["source_ledger_line_first"] = first_line
        record["source_ledger_line_last"] = last_line
    record["crc32"] = compute_crc32(record)
    return record


def _emit_record(record: dict, dest: Path | None) -> None:
    """Print the record as a single-line JSON to stdout AND, if dest is
    not None, append the same line to dest (creating the file if it
    does not exist)."""
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=False)
    print(line)
    if dest is not None:
        with open(dest, "a", encoding="utf-8", newline="") as fh:
            fh.write(line)
            fh.write("\n")


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--path",
        required=False,
        default=None,
        help=(
            "Path to the bhs-trajectory JSONL file (typically "
            "out/bhs-trajectory.jsonl). When omitted AND "
            "--classify-from-ledger is given, the validator runs in "
            "classifier-only mode (no integrity checks)."
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
    parser.add_argument(
        "--classify-from-ledger",
        default=None,
        help=(
            "Optional path to a bhs-ledger.jsonl file. When supplied, "
            "the script enters CLASSIFIER mode: it reads the trailing "
            "--window-size bhs_official rows, classifies the pattern, "
            "and PRINTs a canonical trajectory_window row to stdout "
            "(JSON, single line, with CRC32 footer). Combine with "
            "--append-to to also write the row to a JSONL file."
        ),
    )
    parser.add_argument(
        "--lane-id",
        default=None,
        help=(
            "Required in classifier mode. Identifier of the lane the "
            "computed trajectory_window belongs to (matches the "
            "bhs-trajectory schema's lane_id pattern)."
        ),
    )
    parser.add_argument(
        "--window-size",
        type=int,
        default=DEFAULT_WINDOW_SIZE,
        help=(
            f"Number of trailing bhs_official rows to classify. "
            f"Default {DEFAULT_WINDOW_SIZE}; valid range "
            f"[{MIN_WINDOW_SIZE}, {MAX_WINDOW_SIZE}]."
        ),
    )
    parser.add_argument(
        "--agent-session-id",
        default="operator:trajectory-walker",
        help=(
            "Identifier to record as `computed_by_agent_session_id` "
            "on the emitted row. Defaults to "
            "`operator:trajectory-walker` for ad-hoc operator runs."
        ),
    )
    parser.add_argument(
        "--source-ledger-path",
        default=None,
        help=(
            "Optional value to record as the row's "
            "`source_ledger_path`. When supplied, the schema also "
            "requires source_ledger_line_first / source_ledger_line_last "
            "(the script computes both from the actual line numbers)."
        ),
    )
    parser.add_argument(
        "--append-to",
        default=None,
        help=(
            "Optional path to APPEND the classified row to. The file "
            "is created if it does not exist. Without this flag, the "
            "row is only PRINTed to stdout."
        ),
    )
    args = parser.parse_args(argv)

    classifier_mode = args.classify_from_ledger is not None

    if classifier_mode:
        if args.lane_id is None:
            print(
                "ERROR: --lane-id is required in classifier mode "
                "(--classify-from-ledger).",
                file=sys.stderr,
            )
            return EXIT_IO
        try:
            record = classify_from_ledger(
                Path(args.classify_from_ledger),
                lane_id=args.lane_id,
                window_size=args.window_size,
                agent_session_id=args.agent_session_id,
                source_ledger_path=args.source_ledger_path,
            )
        except FileNotFoundError as exc:
            print(
                f"ERROR: bhs-ledger file not found: {exc}",
                file=sys.stderr,
            )
            return EXIT_IO
        except ValueError as exc:
            print(
                f"ERROR: classifier failure: {exc}",
                file=sys.stderr,
            )
            return EXIT_CLASSIFIER
        _emit_record(
            record,
            Path(args.append_to) if args.append_to else None,
        )
        # If --path is also supplied, run the standard integrity
        # checks AFTER the row is appended (catches CRC drift introduced
        # by manual edits between append and verify).
        if args.path is None:
            return EXIT_OK
        return validate_file(
            Path(args.path),
            skip_append_only_check=args.skip_append_only_check,
        )

    # Standard integrity-only mode (no classifier).
    if args.path is None:
        print(
            "ERROR: either --path or --classify-from-ledger must be "
            "supplied.",
            file=sys.stderr,
        )
        return EXIT_IO
    return validate_file(
        Path(args.path),
        skip_append_only_check=args.skip_append_only_check,
    )


if __name__ == "__main__":
    sys.exit(main())
