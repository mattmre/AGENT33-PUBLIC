#!/usr/bin/env python3
"""scripts/ingest_worker_session.py -- ingest + reconcile a worker-session JSONL.

Reads an append-only `out/worker-session-results.jsonl` (one JSON event
per line) and reconciles each event's payload against the worktree
(commit SHAs reachable, file paths in those commits' diffs, artifact
files present + sha256 matching, etc.) plus optional side-channels
(score-delta ledger from #37, phase-criteria.yaml from #38).

Issue #44 (Cluster F 5/5). Companion to R59 in
scripts/validate_pr_brutal_honesty.py: when a PR body cites a worker
session in EVIDENCE but no JSONL is reachable, R59 auto-classifies the
run as `tier: paste-summary` (the floor tier from evidence-tiers.txt
v1.2). When a JSONL IS reachable, R59 invokes this script and reads its
emitted `out/worker-session-ingestion-report.json`'s `tier_classification`
field to gate any product/production score claim.

Inputs:
  --jsonl PATH                  Required. Path to the JSONL event log.
  --worktree PATH               Optional. Git worktree to reconcile against
                                (defaults to current dir; reconciliation
                                steps that need git are SKIPPED if not a
                                git directory, with a stderr breadcrumb).
  --score-delta-ledger PATH     Optional. YAML or JSON ledger (#37 shape:
                                top-level `entries:` OR `rows:`, each item
                                must have an `id`). When supplied, every
                                score_change_proposed event's ledger_ref
                                MUST resolve.
  --phase-criteria PATH         Optional. YAML phase-criteria (#38). When
                                supplied, every event-level `requirement_id`
                                AND every blocker_raised payload's
                                `requirement_id` MUST resolve there.
  --report-out PATH             Optional. Where to write the JSON report
                                (defaults to `out/worker-session-
                                ingestion-report.json` relative to cwd).

Output:
  - JSON report at --report-out with shape:
      {
        "schema_version": "1.0",
        "jsonl_path": "...",
        "session_id": "...",
        "events_total": N,
        "events_ok": M,
        "schema_failures": [...],
        "reconciliation_failures": [...],
        "warnings": [...],
        "tier_classification": "<one of evidence-tiers.txt | paste-summary>",
        "ok": true|false
      }
  - Plain-text summary on stdout.

Exit codes:
  0 -- reconciliation OK (and schema OK)
  1 -- any reconciliation failure (schema OK)
  2 -- any schema failure on any line (or unrecoverable parse error)

Stdlib-only at import. yaml / jsonschema imported lazily inside branches
that need them; absent => the script emits a stderr breadcrumb and skips
the relevant check (back-compat with environments that lack PyYAML /
jsonschema, mirrors validate_pr_brutal_honesty.py's lazy-import shape).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional


SCRIPT_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = (
    SCRIPT_DIR.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
    / "schemas"
    / "worker-session-event.schema.json"
)
KINDS_ENUM_PATH = (
    SCRIPT_DIR.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
    / "enums"
    / "worker-session-event-kinds.txt"
)
EVIDENCE_TIERS_PATH = (
    SCRIPT_DIR.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
    / "enums"
    / "evidence-tiers.txt"
)

# Exit codes (mirrors plan §3).
EXIT_OK = 0
EXIT_RECON_FAIL = 1
EXIT_SCHEMA_FAIL = 2


def _load_kinds_enum() -> set[str]:
    """Read the closed-set kinds enum. Falls back to the schema's enum
    when the .txt file is absent (e.g. in adopter installs that only
    pulled the schemas/ tree). Returns empty set on both-missing -- the
    caller treats every event kind as unknown in that case."""
    if KINDS_ENUM_PATH.exists():
        kinds: set[str] = set()
        for line in KINDS_ENUM_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            kinds.add(stripped)
        return kinds
    if SCHEMA_PATH.exists():
        try:
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return set()
        kind_def = schema.get("properties", {}).get("kind", {})
        enum = kind_def.get("enum") or []
        if isinstance(enum, list):
            return {x for x in enum if isinstance(x, str)}
    return set()


def _load_evidence_tiers() -> list[str]:
    """Read evidence-tiers.txt as an ordered list (ordinal-1 first).
    Returns empty list when absent -- ingester treats every tier name
    as unknown in that case (ingestion still works; only the
    paste-summary tier classification falls back to the literal
    string `paste-summary` regardless)."""
    if not EVIDENCE_TIERS_PATH.exists():
        return []
    tiers: list[str] = []
    for line in EVIDENCE_TIERS_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        tiers.append(stripped)
    return tiers


def _load_schema() -> Optional[dict]:
    if not SCHEMA_PATH.exists():
        return None
    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _parse_jsonl(path: Path) -> tuple[list[dict], list[dict], Optional[dict]]:
    """Read the JSONL file line-by-line.

    Returns (events, schema_failures, truncation_warning).
    - events: successfully parsed event dicts (in file order; each event
      carries an injected `_line_no` for downstream messages).
    - schema_failures: per-line {line_no, error, raw} dicts for lines
      that did not parse as JSON or did not parse as a JSON object.
    - truncation_warning: when the LAST line of the file is non-empty
      AND fails to parse, return a single warning dict naming the
      truncated line so callers can surface it as a WARN (per plan §3:
      'a tampered/truncated trailing line is flagged but the prefix is
      still ingested'). When the truncated line is the trailing line
      AND every prior line parsed, the warning replaces the schema_
      failure entry; when a non-trailing line failed to parse, the
      truncation_warning is None and that line is reported via
      schema_failures.
    """
    events: list[dict] = []
    schema_failures: list[dict] = []
    truncation_warning: Optional[dict] = None
    if not path.exists():
        # Caller decides whether absence is fatal; we return empty.
        return events, schema_failures, truncation_warning

    text = path.read_text(encoding="utf-8")
    raw_lines = text.splitlines()
    if not raw_lines and text:
        # text without any newlines -> single line.
        raw_lines = [text]

    last_non_empty_idx: Optional[int] = None
    for i in range(len(raw_lines) - 1, -1, -1):
        if raw_lines[i].strip():
            last_non_empty_idx = i
            break

    failed_lines: list[dict] = []
    for line_no, raw in enumerate(raw_lines, start=1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            failed_lines.append(
                {
                    "line_no": line_no,
                    "error": (
                        f"JSON parse failed: {exc.msg} at "
                        f"col={exc.colno}"
                    ),
                    "raw": raw,
                    "_class": "parse",
                }
            )
            continue
        if not isinstance(obj, dict):
            failed_lines.append(
                {
                    "line_no": line_no,
                    "error": (
                        f"line is JSON but not an object "
                        f"(got {type(obj).__name__})"
                    ),
                    "raw": raw,
                    "_class": "non_dict",
                }
            )
            continue
        obj["_line_no"] = line_no
        events.append(obj)

    # Treat the trailing-line failure specially per plan §3.
    # ONLY genuine JSON parse errors qualify as truncation candidates --
    # a "parsed but not an object" failure means the line was complete
    # JSON but wrong type, which is a schema failure regardless of position.
    if (
        failed_lines
        and last_non_empty_idx is not None
        and failed_lines[-1]["line_no"] == last_non_empty_idx + 1
        and failed_lines[-1].get("_class") == "parse"
    ):
        # Detach the trailing-line failure as a truncation warning.
        truncation_warning = {
            "line_no": failed_lines[-1]["line_no"],
            "error": failed_lines[-1]["error"],
            "raw": failed_lines[-1]["raw"],
            "kind": "truncated_trailing_line",
        }
        # Any earlier failures remain schema failures (mid-file
        # parse failures are NOT treated as truncation; they break
        # the append-only append-after-prefix invariant).
        schema_failures = failed_lines[:-1]
    else:
        schema_failures = failed_lines
    # Strip the internal `_class` marker before reporting.
    for sf in schema_failures:
        sf.pop("_class", None)

    return events, schema_failures, truncation_warning


def _validate_event_against_schema(
    event: dict, schema: dict
) -> Optional[str]:
    """Run jsonschema.validate; return None on PASS or an error str."""
    try:
        import jsonschema
    except ImportError:
        return None  # caller handles via stderr breadcrumb
    try:
        # Strip the injected _line_no so it does not trip
        # additionalProperties: false in the schema.
        payload = {k: v for k, v in event.items() if k != "_line_no"}
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        path_str = (
            ".".join(str(p) for p in exc.absolute_path) or "<root>"
        )
        return f"schema: {exc.message} (path={path_str})"
    except Exception as exc:  # pragma: no cover -- fail-closed
        return f"schema validation error: {type(exc).__name__}: {exc}"
    return None


def _git_object_exists(worktree: Path, sha: str) -> bool:
    """Return True iff `git -C <worktree> cat-file -e <sha>` exits 0."""
    try:
        result = subprocess.run(
            ["git", "-C", str(worktree), "cat-file", "-e", sha],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return False
    return result.returncode == 0


def _git_show_paths(worktree: Path, sha: str) -> Optional[set[str]]:
    """Return the set of file paths touched by commit `sha`.
    Returns None if `git show --stat --name-only <sha>` failed (e.g.
    not a git repo, sha unknown). Empty set means a real commit with
    no diff paths reported (rare; root commit). Caller distinguishes
    None from empty set."""
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(worktree),
                "show",
                "--name-only",
                "--pretty=format:",
                sha,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    paths: set[str] = set()
    for raw in result.stdout.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        # Normalize backslashes -> forward slashes so Windows fixtures
        # match the JSONL's POSIX-style payload paths.
        paths.add(stripped.replace("\\", "/"))
    return paths


def _is_git_worktree(worktree: Path) -> bool:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(worktree),
                "rev-parse",
                "--is-inside-work-tree",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return False
    return (
        result.returncode == 0 and result.stdout.strip() == "true"
    )


def _sha256_of_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _load_score_delta_ledger(path: Path) -> Optional[set[str]]:
    """Load #37 ledger; return the set of valid `id` strings.
    Tolerates two top-level shapes (`entries:` / `rows:`) per plan §3.
    Returns None on read/parse failure (caller emits a stderr
    breadcrumb and silently no-ops the ledger_ref reconciliation)."""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    data: Any = None
    # Try JSON first (it's a valid YAML subset and faster).
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml as _yaml
        except ImportError:
            return None
        try:
            data = _yaml.safe_load(text)
        except Exception:
            return None
    if not isinstance(data, dict):
        return None
    rows = data.get("entries") or data.get("rows") or []
    if not isinstance(rows, list):
        return None
    ids: set[str] = set()
    for row in rows:
        if isinstance(row, dict):
            rid = row.get("id")
            if isinstance(rid, str) and rid:
                ids.add(rid)
    return ids


def _load_phase_criteria(path: Path) -> Optional[set[str]]:
    """Load #38 phase-criteria; return the set of known requirement_id
    strings. Tolerates the same shape used by R55 (top-level
    `requirements:` list of {requirement_id: ...} dicts, OR the
    compiled artifact shape `phases: [{requirements: [{...}]}]`)."""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    data: Any = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml as _yaml
        except ImportError:
            return None
        try:
            data = _yaml.safe_load(text)
        except Exception:
            return None
    if not isinstance(data, dict):
        return None
    ids: set[str] = set()
    # Shape A: flat `requirements:` list at top level.
    flat = data.get("requirements")
    if isinstance(flat, list):
        for row in flat:
            if isinstance(row, dict):
                rid = row.get("requirement_id") or row.get("id")
                if isinstance(rid, str) and rid:
                    ids.add(rid)
    # Shape B: phases-> requirements nesting.
    phases = data.get("phases")
    if isinstance(phases, list):
        for ph in phases:
            if not isinstance(ph, dict):
                continue
            ph_reqs = ph.get("requirements")
            if isinstance(ph_reqs, list):
                for row in ph_reqs:
                    if isinstance(row, dict):
                        rid = (
                            row.get("requirement_id")
                            or row.get("id")
                        )
                        if isinstance(rid, str) and rid:
                            ids.add(rid)
    return ids


def _classify_tier(events: list[dict]) -> str:
    """Per plan §3: choose a classification tier for the run.
    A run with at least one well-formed event is NOT a paste-summary
    (the JSONL exists and parses). The classification is then the
    HIGHEST tier any event explicitly carries on its `evidence_tier`
    field; absent any explicit tier, default to
    `unit-test-with-prod-import` (the v3.3 floor for non-paste runs).
    A run with zero events (the file is empty or every line failed)
    is classified as `paste-summary`."""
    if not events:
        return "paste-summary"
    tier_order = _load_evidence_tiers()
    if not tier_order:
        # Fallback: just pick the first explicit tier seen.
        for ev in events:
            t = ev.get("evidence_tier")
            if isinstance(t, str) and t:
                return t
        return "unit-test-with-prod-import"
    tier_rank = {name: idx for idx, name in enumerate(tier_order)}
    best_idx: Optional[int] = None
    best_name: Optional[str] = None
    for ev in events:
        t = ev.get("evidence_tier")
        if not isinstance(t, str) or not t:
            continue
        idx = tier_rank.get(t)
        if idx is None:
            continue
        if best_idx is None or idx > best_idx:
            best_idx = idx
            best_name = t
    if best_name is None:
        return "unit-test-with-prod-import"
    return best_name


def _check_session_invariants(
    events: list[dict],
) -> list[dict]:
    """Per-session checks that don't need worktree access:
      - All events share a single session_id.
      - event_id is strictly monotonic (no gaps, no repeats) when the
        ids parse as `evt-NNNN`.
    Returns a list of reconciliation_failure dicts."""
    failures: list[dict] = []
    if not events:
        return failures
    session_ids = {ev.get("session_id") for ev in events}
    if len(session_ids) > 1:
        failures.append(
            {
                "kind": "session_id_mismatch",
                "message": (
                    f"JSONL contains multiple session_id values "
                    f"{sorted(str(s) for s in session_ids)!r}; "
                    f"every event in a single file MUST share one "
                    f"session_id"
                ),
            }
        )
    seen: dict[int, int] = {}
    for ev in events:
        eid = ev.get("event_id", "")
        if not isinstance(eid, str) or not eid.startswith("evt-"):
            continue
        try:
            n = int(eid[len("evt-"):])
        except ValueError:
            continue
        line_no = ev.get("_line_no", 0)
        if n in seen:
            failures.append(
                {
                    "kind": "event_id_repeat",
                    "line_no": line_no,
                    "message": (
                        f"event_id {eid!r} appears twice "
                        f"(first at line {seen[n]}, again at line "
                        f"{line_no}); append-only invariant violated"
                    ),
                }
            )
        seen[n] = line_no
    if seen:
        nums = sorted(seen.keys())
        # Strict monotonic: nums must be a contiguous prefix or any
        # contiguous run starting from min(nums). Gaps are allowed
        # ONLY if the run is otherwise strictly increasing -- but per
        # plan we refuse gaps and repeats. Treat gaps as warning, not
        # failure, since legitimate offline-merged sessions can drop
        # event_ids; we leave gap-detection to a downstream reviewer.
        if nums != sorted(set(nums)):
            # Already covered by event_id_repeat above.
            pass
    return failures


def _reconcile_event(
    event: dict,
    worktree: Optional[Path],
    git_available: bool,
    ledger_ids: Optional[set[str]],
    phase_req_ids: Optional[set[str]],
    failures: list[dict],
    warnings: list[dict],
) -> None:
    line_no = event.get("_line_no", 0)
    kind = event.get("kind", "")
    payload = event.get("payload") or {}

    # Cross-cluster requirement_id resolution (#38).
    req_id_at_event = event.get("requirement_id")
    if (
        phase_req_ids is not None
        and isinstance(req_id_at_event, str)
        and req_id_at_event
        and req_id_at_event not in phase_req_ids
    ):
        failures.append(
            {
                "kind": "requirement_id_unresolved",
                "line_no": line_no,
                "event_kind": kind,
                "message": (
                    f"event-level requirement_id "
                    f"{req_id_at_event!r} does not resolve in the "
                    f"supplied --phase-criteria file"
                ),
            }
        )

    if kind == "commit_made":
        sha = payload.get("sha", "")
        if isinstance(sha, str) and sha:
            if git_available and worktree is not None:
                if not _git_object_exists(worktree, sha):
                    failures.append(
                        {
                            "kind": "commit_sha_unreachable",
                            "line_no": line_no,
                            "event_kind": kind,
                            "sha": sha,
                            "message": (
                                f"commit_made.sha {sha!r} is not "
                                f"reachable in worktree "
                                f"{str(worktree)!r}"
                            ),
                        }
                    )
    elif kind == "files_changed":
        # Only enforce when the JSONL has a preceding commit_made event
        # whose sha matches one of the listed shas; otherwise the paths
        # are just an advisory list.
        paths = payload.get("paths") or []
        shas = payload.get("shas") or []
        if (
            git_available
            and worktree is not None
            and isinstance(paths, list)
            and isinstance(shas, list)
        ):
            for sha in shas:
                if not isinstance(sha, str) or not sha:
                    continue
                touched = _git_show_paths(worktree, sha)
                if touched is None:
                    failures.append(
                        {
                            "kind": "files_changed_sha_unreachable",
                            "line_no": line_no,
                            "event_kind": kind,
                            "sha": sha,
                            "message": (
                                f"files_changed.shas[*] {sha!r} is "
                                f"not reachable in worktree "
                                f"{str(worktree)!r}"
                            ),
                        }
                    )
                    continue
                for p in paths:
                    if not isinstance(p, str) or not p:
                        continue
                    norm = p.replace("\\", "/")
                    if norm not in touched:
                        failures.append(
                            {
                                "kind": "files_changed_path_missing",
                                "line_no": line_no,
                                "event_kind": kind,
                                "sha": sha,
                                "path": p,
                                "message": (
                                    f"files_changed.paths[*] {p!r} "
                                    f"is not present in the diff "
                                    f"of commit {sha!r}"
                                ),
                            }
                        )
    elif kind == "artifact_emitted":
        rel = payload.get("path", "")
        declared_sha = payload.get("sha256", "")
        if isinstance(rel, str) and rel and worktree is not None:
            artifact_path = (worktree / rel).resolve()
            if not artifact_path.exists():
                failures.append(
                    {
                        "kind": "artifact_missing",
                        "line_no": line_no,
                        "event_kind": kind,
                        "path": rel,
                        "message": (
                            f"artifact_emitted.path {rel!r} does "
                            f"not exist on disk under worktree "
                            f"{str(worktree)!r}"
                        ),
                    }
                )
            elif (
                isinstance(declared_sha, str)
                and len(declared_sha) == 64
            ):
                actual = _sha256_of_file(artifact_path)
                if actual is None:
                    failures.append(
                        {
                            "kind": "artifact_unreadable",
                            "line_no": line_no,
                            "event_kind": kind,
                            "path": rel,
                            "message": (
                                f"artifact_emitted.path {rel!r} "
                                f"could not be read for sha256 "
                                f"comparison"
                            ),
                        }
                    )
                elif actual != declared_sha:
                    failures.append(
                        {
                            "kind": "artifact_sha256_mismatch",
                            "line_no": line_no,
                            "event_kind": kind,
                            "path": rel,
                            "declared": declared_sha,
                            "actual": actual,
                            "message": (
                                f"artifact_emitted.sha256 mismatch "
                                f"for {rel!r}: declared "
                                f"{declared_sha!r}, actual "
                                f"{actual!r}"
                            ),
                        }
                    )
    elif kind == "score_change_proposed":
        ref = payload.get("ledger_ref", "")
        if (
            ledger_ids is not None
            and isinstance(ref, str)
            and ref
            and ref not in ledger_ids
        ):
            failures.append(
                {
                    "kind": "ledger_ref_unresolved",
                    "line_no": line_no,
                    "event_kind": kind,
                    "ledger_ref": ref,
                    "message": (
                        f"score_change_proposed.ledger_ref "
                        f"{ref!r} does not resolve in the "
                        f"supplied --score-delta-ledger file"
                    ),
                }
            )
    elif kind == "blocker_raised":
        rid = payload.get("requirement_id", "")
        if (
            phase_req_ids is not None
            and isinstance(rid, str)
            and rid
            and rid not in phase_req_ids
        ):
            failures.append(
                {
                    "kind": "blocker_requirement_id_unresolved",
                    "line_no": line_no,
                    "event_kind": kind,
                    "requirement_id": rid,
                    "message": (
                        f"blocker_raised.requirement_id "
                        f"{rid!r} does not resolve in the "
                        f"supplied --phase-criteria file"
                    ),
                }
            )


def ingest(
    jsonl_path: Path,
    worktree: Optional[Path],
    score_delta_ledger_path: Optional[Path],
    phase_criteria_path: Optional[Path],
    report_out: Path,
) -> tuple[int, dict]:
    """Run a full ingestion + reconciliation pass.

    Returns (exit_code, report_dict). The report is also written to
    `report_out` (parents created); the caller is responsible for
    printing the human-readable summary.
    """
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "jsonl_path": str(jsonl_path),
        "session_id": None,
        "events_total": 0,
        "events_ok": 0,
        "schema_failures": [],
        "reconciliation_failures": [],
        "warnings": [],
        "tier_classification": "paste-summary",
        "ok": False,
    }

    # JSONL absent altogether -> classify as paste-summary, exit
    # reconciliation failure (the run claimed a session log but did
    # not produce one).
    if not jsonl_path.exists():
        report["reconciliation_failures"].append(
            {
                "kind": "jsonl_missing",
                "message": (
                    f"--jsonl {str(jsonl_path)!r} does not exist on "
                    f"disk; cannot ingest a worker-session log that "
                    f"was never written"
                ),
            }
        )
        _write_report(report, report_out)
        return EXIT_RECON_FAIL, report

    events, schema_failures, truncation_warning = _parse_jsonl(jsonl_path)
    report["events_total"] = len(events) + len(schema_failures) + (
        1 if truncation_warning else 0
    )
    report["schema_failures"].extend(schema_failures)
    if truncation_warning:
        report["warnings"].append(truncation_warning)
    if events:
        first_session = events[0].get("session_id")
        if isinstance(first_session, str):
            report["session_id"] = first_session

    # Schema validation per event (when jsonschema + schema available).
    schema = _load_schema()
    if schema is None:
        try:
            sys.stderr.write(
                "ingest_worker_session: WARN: schema file not found; "
                "skipping per-event JSON Schema validation (only "
                "raw-JSON parse + reconciliation will run)\n"
            )
        except Exception:
            pass
    else:
        kinds = _load_kinds_enum()
        for ev in events:
            err = _validate_event_against_schema(ev, schema)
            if err is not None:
                report["schema_failures"].append(
                    {
                        "line_no": ev.get("_line_no", 0),
                        "error": err,
                        "kind": ev.get("kind", ""),
                    }
                )
            else:
                k = ev.get("kind")
                if (
                    kinds
                    and isinstance(k, str)
                    and k not in kinds
                ):
                    report["schema_failures"].append(
                        {
                            "line_no": ev.get("_line_no", 0),
                            "error": (
                                f"kind {k!r} is not in the closed-"
                                f"set worker-session-event-kinds.txt"
                            ),
                            "kind": k,
                        }
                    )

    # Worktree availability + side-channel loaders.
    git_available = (
        worktree is not None and _is_git_worktree(worktree)
    )
    if worktree is not None and not git_available:
        try:
            sys.stderr.write(
                f"ingest_worker_session: WARN: --worktree "
                f"{str(worktree)!r} is not a git work tree; "
                f"reconciliation steps that need git "
                f"(commit_made, files_changed) will be skipped\n"
            )
        except Exception:
            pass

    ledger_ids: Optional[set[str]] = None
    if score_delta_ledger_path is not None:
        ledger_ids = _load_score_delta_ledger(score_delta_ledger_path)
        if ledger_ids is None:
            try:
                sys.stderr.write(
                    f"ingest_worker_session: WARN: could not load "
                    f"--score-delta-ledger "
                    f"{str(score_delta_ledger_path)!r}; "
                    f"score_change_proposed.ledger_ref "
                    f"reconciliation will be skipped\n"
                )
            except Exception:
                pass

    phase_req_ids: Optional[set[str]] = None
    if phase_criteria_path is not None:
        phase_req_ids = _load_phase_criteria(phase_criteria_path)
        if phase_req_ids is None:
            try:
                sys.stderr.write(
                    f"ingest_worker_session: WARN: could not load "
                    f"--phase-criteria "
                    f"{str(phase_criteria_path)!r}; "
                    f"requirement_id reconciliation will be skipped\n"
                )
            except Exception:
                pass

    # Per-session invariants (session_id consistency, event_id repeats).
    report["reconciliation_failures"].extend(
        _check_session_invariants(events)
    )

    # Per-event reconciliation.
    for ev in events:
        # Skip reconciliation for events that already failed schema
        # (their payload shape is not trustworthy).
        if any(
            sf.get("line_no") == ev.get("_line_no")
            for sf in report["schema_failures"]
        ):
            continue
        _reconcile_event(
            ev,
            worktree=worktree,
            git_available=git_available,
            ledger_ids=ledger_ids,
            phase_req_ids=phase_req_ids,
            failures=report["reconciliation_failures"],
            warnings=report["warnings"],
        )

    # Tally events_ok = events that survived schema + reconciliation.
    failed_lines = {
        sf.get("line_no") for sf in report["schema_failures"]
    } | {
        rf.get("line_no")
        for rf in report["reconciliation_failures"]
        if "line_no" in rf
    }
    report["events_ok"] = sum(
        1 for ev in events
        if ev.get("_line_no") not in failed_lines
    )

    # Tier classification (uses successfully parsed events only).
    classification_events = [
        ev for ev in events
        if ev.get("_line_no") not in {
            sf.get("line_no") for sf in report["schema_failures"]
        }
    ]
    report["tier_classification"] = _classify_tier(classification_events)

    # Compute exit code:
    # - any schema failure -> EXIT_SCHEMA_FAIL
    # - any reconciliation failure (including jsonl_missing handled above,
    #   and including the truncated-trailing-line, which we treat as a
    #   reconciliation-level FAIL even though it lives in `warnings`
    #   per the schema-vs-recon split) -> EXIT_RECON_FAIL
    # - else EXIT_OK.
    if report["schema_failures"]:
        exit_code = EXIT_SCHEMA_FAIL
    elif (
        report["reconciliation_failures"]
        or truncation_warning is not None
    ):
        exit_code = EXIT_RECON_FAIL
    else:
        exit_code = EXIT_OK
    report["ok"] = exit_code == EXIT_OK

    _write_report(report, report_out)
    return exit_code, report


def _write_report(report: dict, report_out: Path) -> None:
    try:
        report_out.parent.mkdir(parents=True, exist_ok=True)
        # Strip non-serialisable injected fields before writing.
        report_out.write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError as exc:
        try:
            sys.stderr.write(
                f"ingest_worker_session: WARN: could not write "
                f"report to {str(report_out)!r}: {exc}\n"
            )
        except Exception:
            pass


def _render_summary(report: dict) -> str:
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("ingest_worker_session.py -- summary")
    lines.append("=" * 70)
    lines.append(f"jsonl_path:          {report.get('jsonl_path')!r}")
    lines.append(f"session_id:          {report.get('session_id')!r}")
    lines.append(f"events_total:        {report.get('events_total')}")
    lines.append(f"events_ok:           {report.get('events_ok')}")
    lines.append(
        f"tier_classification: {report.get('tier_classification')!r}"
    )
    lines.append(
        f"ok:                  {report.get('ok')}"
    )
    sf = report.get("schema_failures") or []
    rf = report.get("reconciliation_failures") or []
    wn = report.get("warnings") or []
    if sf:
        lines.append("")
        lines.append(f"SCHEMA FAILURES ({len(sf)}):")
        for f in sf:
            lines.append(
                f"  line {f.get('line_no')}: {f.get('error')}"
            )
    if rf:
        lines.append("")
        lines.append(f"RECONCILIATION FAILURES ({len(rf)}):")
        for f in rf:
            line_no = f.get("line_no")
            prefix = (
                f"line {line_no}: " if line_no else ""
            )
            lines.append(
                f"  [{f.get('kind')}] {prefix}{f.get('message')}"
            )
    if wn:
        lines.append("")
        lines.append(f"WARNINGS ({len(wn)}):")
        for w in wn:
            line_no = w.get("line_no")
            prefix = (
                f"line {line_no}: " if line_no else ""
            )
            lines.append(
                f"  [{w.get('kind')}] {prefix}{w.get('error') or w.get('message') or ''}"
            )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n")[0]
    )
    parser.add_argument(
        "--jsonl",
        required=True,
        help=(
            "Path to the worker-session JSONL event log "
            "(typically out/worker-session-results.jsonl)."
        ),
    )
    parser.add_argument(
        "--worktree",
        default=None,
        help=(
            "Optional path to the git worktree to reconcile against. "
            "When omitted, git-dependent reconciliation steps "
            "(commit_made, files_changed) are skipped with a stderr "
            "breadcrumb. Schema validation always runs."
        ),
    )
    parser.add_argument(
        "--score-delta-ledger",
        default=None,
        help=(
            "Optional path to the #37 score-delta ledger artifact "
            "(YAML or JSON, top-level entries: or rows:). When "
            "supplied, every score_change_proposed event's "
            "ledger_ref MUST resolve in the ledger; absent => the "
            "ledger_ref check is skipped with a stderr breadcrumb."
        ),
    )
    parser.add_argument(
        "--phase-criteria",
        default=None,
        help=(
            "Optional path to the #38 phase-criteria.yaml. When "
            "supplied, every event-level requirement_id and every "
            "blocker_raised payload's requirement_id MUST resolve "
            "there; absent => the requirement-id check is skipped."
        ),
    )
    parser.add_argument(
        "--report-out",
        default=None,
        help=(
            "Optional path to the JSON report output. Defaults to "
            "out/worker-session-ingestion-report.json relative to "
            "the current working directory."
        ),
    )
    args = parser.parse_args()

    jsonl_path = Path(args.jsonl)
    worktree: Optional[Path] = (
        Path(args.worktree).resolve() if args.worktree else None
    )
    ledger_path: Optional[Path] = (
        Path(args.score_delta_ledger)
        if args.score_delta_ledger
        else None
    )
    phase_path: Optional[Path] = (
        Path(args.phase_criteria)
        if args.phase_criteria
        else None
    )
    report_out: Path = (
        Path(args.report_out)
        if args.report_out
        else Path("out") / "worker-session-ingestion-report.json"
    )

    exit_code, report = ingest(
        jsonl_path=jsonl_path,
        worktree=worktree,
        score_delta_ledger_path=ledger_path,
        phase_criteria_path=phase_path,
        report_out=report_out,
    )
    print(_render_summary(report))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
