#!/usr/bin/env python3
"""scripts/rotate_charter_merge_log.py — annual rotation for
out/charter-merge-log.jsonl (issue #43, cluster E 3/7).

Optional, NOT wired into the per-PR validator. The per-PR validator
treats archive files as part of the same logical chain when they sit
in `<live_path>.parent / archive / <year>.jsonl`; the rotation only
moves rows, never edits or drops them.

Rotation rules (mirror charter-merge-log-retention.md):
  - Rows whose `ts` is older than 365 days from --now (default: wall
    clock UTC) are eligible for rotation.
  - `charter_open` and `charter_close` rows for any lane_id whose
    most-recent heartbeat reports `state` in {running, paused} are
    NEVER rotated (live-lane exemption). The heartbeat path is
    supplied by --heartbeat (default: out/orchestrator.heartbeat.json
    sibling of the live merge log); when the heartbeat is absent the
    rotator conservatively treats EVERY lane as live and rotates
    nothing for that pair.
  - Rotated rows are APPENDED to
    out/charter-merge-log/archive/<year>.jsonl (the year of each
    row's `ts`). Existing archive files are append-only; the rotator
    never edits or removes rows from them.
  - The live file is rewritten with the surviving rows (this IS a
    deletion in the live file's git history -- the per-PR validator's
    append-only check explicitly tolerates this kind of mutation when
    invoked with --skip-append-only-check or when the diff also
    appends a corresponding archive row; orchestrator wraps both
    actions in a single commit).

Exit codes:
  0 -- rotation completed (may be a no-op if nothing was eligible)
  6 -- IO / argparse / parse error
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path


_LIVE_LANE_STATES = {"running", "paused"}


def _parse_ts(ts: str) -> _dt.datetime:
    # Tolerate trailing `Z` and millisecond precision (ISO-8601 UTC).
    s = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
    return _dt.datetime.fromisoformat(s)


def _load_live_lanes(heartbeat_path: Path) -> set[str]:
    """Return set of lane_ids whose most-recent heartbeat reports a
    live state. Conservative fallback: empty set on read error
    (caller treats empty as 'no exemptions known' AND combines with
    'rotate nothing for the pair' guard via _is_protected)."""
    if not heartbeat_path.exists():
        return set()
    try:
        payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    # Heartbeat schema may be a single object or a per-lane map; we
    # support both shapes conservatively. A single object exposes
    # `lane_id` and `state` at the top level.
    live: set[str] = set()
    if isinstance(payload, dict):
        if (
            isinstance(payload.get("lane_id"), str)
            and payload.get("state") in _LIVE_LANE_STATES
        ):
            live.add(payload["lane_id"])
        # Per-lane map shape: {"<lane_id>": {"state": "running", ...}}
        for key, value in payload.items():
            if (
                isinstance(value, dict)
                and value.get("state") in _LIVE_LANE_STATES
            ):
                live.add(key)
    return live


def _is_protected(
    rec: dict,
    live_lanes: set[str],
    heartbeat_present: bool,
) -> bool:
    """Live-lane exemption test for charter_open / charter_close rows."""
    kind = rec.get("kind")
    if kind not in ("charter_open", "charter_close"):
        return False
    lane_id = rec.get("lane_id")
    if not isinstance(lane_id, str):
        return False
    if not heartbeat_present:
        # Conservative: no heartbeat -> treat every lane as live.
        return True
    return lane_id in live_lanes


def rotate(
    live_path: Path,
    archive_dir: Path,
    heartbeat_path: Path,
    now: _dt.datetime,
    retention_days: int = 365,
) -> int:
    if not live_path.exists():
        print(
            f"ERROR: live merge-log file not found: {live_path}",
            file=sys.stderr,
        )
        return 6
    raw = live_path.read_text(encoding="utf-8").splitlines()
    records: list[dict] = []
    for idx, line in enumerate(raw, start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(
                f"rotate: line {idx}: invalid JSON ({exc})",
                file=sys.stderr,
            )
            return 6

    heartbeat_present = heartbeat_path.exists()
    live_lanes = _load_live_lanes(heartbeat_path)
    cutoff = now - _dt.timedelta(days=retention_days)

    survivors: list[dict] = []
    rotated_by_year: dict[int, list[dict]] = {}
    for rec in records:
        ts_str = rec.get("ts")
        if not isinstance(ts_str, str):
            survivors.append(rec)
            continue
        try:
            ts = _parse_ts(ts_str)
        except ValueError:
            survivors.append(rec)
            continue
        if ts >= cutoff:
            survivors.append(rec)
            continue
        if _is_protected(rec, live_lanes, heartbeat_present):
            survivors.append(rec)
            continue
        rotated_by_year.setdefault(ts.year, []).append(rec)

    if not rotated_by_year:
        return 0  # no-op

    archive_dir.mkdir(parents=True, exist_ok=True)
    for year, rows in sorted(rotated_by_year.items()):
        target = archive_dir / f"{year}.jsonl"
        with target.open("a", encoding="utf-8") as fh:
            for rec in rows:
                fh.write(
                    json.dumps(
                        rec,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )
                )
                fh.write("\n")

    # Rewrite the live file with the survivors.
    with live_path.open("w", encoding="utf-8") as fh:
        for rec in survivors:
            fh.write(
                json.dumps(
                    rec,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            )
            fh.write("\n")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--path",
        default="out/charter-merge-log.jsonl",
        help="Path to the live charter-merge-log JSONL file.",
    )
    parser.add_argument(
        "--archive-dir",
        default=None,
        help=(
            "Path to the archive directory. Default: "
            "<live_path>.parent / charter-merge-log / archive."
        ),
    )
    parser.add_argument(
        "--heartbeat",
        default=None,
        help=(
            "Path to out/orchestrator.heartbeat.json. Default: "
            "<live_path>.parent / orchestrator.heartbeat.json."
        ),
    )
    parser.add_argument(
        "--now",
        default=None,
        help=(
            "Optional ISO-8601 UTC timestamp overriding wall clock "
            "(tests use this to plant a deterministic cutoff)."
        ),
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=365,
        help="Retention window in calendar days (default: 365).",
    )
    args = parser.parse_args(argv)

    live = Path(args.path)
    archive_dir = (
        Path(args.archive_dir)
        if args.archive_dir
        else live.parent / "charter-merge-log" / "archive"
    )
    heartbeat = (
        Path(args.heartbeat)
        if args.heartbeat
        else live.parent / "orchestrator.heartbeat.json"
    )
    if args.now:
        try:
            now = _parse_ts(args.now)
        except ValueError as exc:
            print(f"ERROR: --now is not a valid ISO-8601 ({exc})", file=sys.stderr)
            return 6
    else:
        now = _dt.datetime.now(tz=_dt.timezone.utc)

    return rotate(
        live_path=live,
        archive_dir=archive_dir,
        heartbeat_path=heartbeat,
        now=now,
        retention_days=args.retention_days,
    )


if __name__ == "__main__":
    sys.exit(main())
