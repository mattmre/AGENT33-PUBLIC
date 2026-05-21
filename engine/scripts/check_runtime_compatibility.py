"""Check pinned upstream runtime protocol sources for compatibility drift."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[1]
LOCKFILE_PATH = ENGINE_ROOT / "runtime_compatibility.lock.json"
_FETCH_ATTEMPTS = 3
_FETCH_TIMEOUT_SECONDS = 30
_FETCH_BACKOFF_BASE_SECONDS = 1.0


def _normalize_text(raw_bytes: bytes) -> str:
    return raw_bytes.decode("utf-8", "ignore").replace("\r\n", "\n")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_lockfile(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fetch_source(url: str) -> str:
    last_exc: Exception | None = None
    for attempt in range(_FETCH_ATTEMPTS):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "agent33-runtime-compat/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT_SECONDS) as response:
                return _normalize_text(response.read())
        except (HTTPError, URLError) as exc:
            last_exc = exc
            if attempt == _FETCH_ATTEMPTS - 1:
                break
            time.sleep(_FETCH_BACKOFF_BASE_SECONDS * (2**attempt))
    raise RuntimeError(
        f"Failed to fetch compatibility source '{url}' after {_FETCH_ATTEMPTS} attempts: "
        f"{last_exc}"
    ) from last_exc


def _snapshot_path(source: dict[str, Any]) -> Path:
    return ENGINE_ROOT / str(source["snapshot"])


def _extract_openai_path_operation(raw_text: str, source: dict[str, Any]) -> str:
    document = yaml.safe_load(raw_text)
    operation = document["paths"][source["path"]][source["method"]]
    return json.dumps(operation, indent=2, sort_keys=True) + "\n"


def _extract_markdown_section(raw_text: str, source: dict[str, Any]) -> str:
    heading = str(source["heading"])
    start = raw_text.find(heading)
    if start == -1:
        raise RuntimeError(f"{source['id']}: heading '{heading}' not found in upstream source")
    next_heading = raw_text.find("\n## ", start + len(heading))
    if next_heading == -1:
        next_heading = len(raw_text)
    return raw_text[start:next_heading].strip() + "\n"


def _extract_snapshot(raw_text: str, source: dict[str, Any]) -> str:
    extractor = source["extractor"]
    if extractor == "openai_path_operation":
        return _extract_openai_path_operation(raw_text, source)
    if extractor == "markdown_section":
        return _extract_markdown_section(raw_text, source)
    raise RuntimeError(f"{source['id']}: unsupported extractor '{extractor}'")


def _validate_required_substrings(
    *,
    source_id: str,
    text: str,
    required_substrings: list[str],
) -> None:
    missing = [needle for needle in required_substrings if needle not in text]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(f"{source_id}: missing required upstream markers: {joined}")


def _refresh_lock(lockfile: dict[str, Any]) -> dict[str, Any]:
    refreshed = json.loads(json.dumps(lockfile))
    for source in refreshed["sources"]:
        text = _extract_snapshot(_fetch_source(source["url"]), source)
        _validate_required_substrings(
            source_id=source["id"],
            text=text,
            required_substrings=list(source.get("required_substrings", [])),
        )
        snapshot_path = _snapshot_path(source)
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(text, encoding="utf-8")
        source["sha256"] = _sha256_text(text)
    return refreshed


def _check_snapshots(lockfile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for source in lockfile["sources"]:
        snapshot_path = _snapshot_path(source)
        if not snapshot_path.exists():
            errors.append(
                f"{source['id']}: snapshot file is missing\n"
                f"  expected at: {snapshot_path}\n"
                "  refresh with: python scripts/check_runtime_compatibility.py --write-lock"
            )
            continue
        text = snapshot_path.read_text(encoding="utf-8")
        _validate_required_substrings(
            source_id=source["id"],
            text=text,
            required_substrings=list(source.get("required_substrings", [])),
        )
        actual_hash = _sha256_text(text)
        expected_hash = source.get("sha256", "")
        if actual_hash != expected_hash:
            errors.append(
                f"{source['id']}: upstream compatibility source drifted\n"
                f"  url: {source['url']}\n"
                f"  expected: {expected_hash}\n"
                f"  actual:   {actual_hash}\n"
                "  refresh with: python scripts/check_runtime_compatibility.py --write-lock"
            )
    return errors


def _check_upstream(lockfile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for source in lockfile["sources"]:
        text = _extract_snapshot(_fetch_source(source["url"]), source)
        _validate_required_substrings(
            source_id=source["id"],
            text=text,
            required_substrings=list(source.get("required_substrings", [])),
        )
        actual_hash = _sha256_text(text)
        expected_hash = source.get("sha256", "")
        if actual_hash != expected_hash:
            errors.append(
                f"{source['id']}: upstream compatibility source drifted\n"
                f"  url: {source['url']}\n"
                f"  snapshot: {_snapshot_path(source)}\n"
                f"  expected: {expected_hash}\n"
                f"  actual:   {actual_hash}\n"
                "  refresh with: python scripts/check_runtime_compatibility.py --write-lock"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write-lock",
        action="store_true",
        help="Refresh runtime_compatibility.lock.json to the current upstream hashes.",
    )
    parser.add_argument(
        "--check-upstream",
        action="store_true",
        help="Fetch upstream sources and compare extracted contract snapshots to the lock file.",
    )
    args = parser.parse_args()

    lockfile = _load_lockfile(LOCKFILE_PATH)
    if args.write_lock:
        refreshed = _refresh_lock(lockfile)
        LOCKFILE_PATH.write_text(
            json.dumps(refreshed, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"updated {LOCKFILE_PATH}")
        return 0

    errors = _check_upstream(lockfile) if args.check_upstream else _check_snapshots(lockfile)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    if args.check_upstream:
        print("runtime compatibility lock matches upstream extracted contracts")
    else:
        print("runtime compatibility snapshots match the checked-in lock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
