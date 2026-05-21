import json
import os
from pathlib import Path
import sys


def _session_base_dir() -> Path:
    value = os.environ.get("AGENT33_SESSION_BASE_DIR", "").strip()
    if value:
        return Path(value)
    return Path.home() / ".agent33" / "sessions"


def main() -> None:
    payload = json.load(sys.stdin)
    metadata = payload.get("metadata", {})
    session_id = str(metadata.get("session_id", "")).strip()
    if not session_id:
        print(json.dumps({"metadata": {"status_line": "session:unknown"}}))
        return

    session_file = _session_base_dir() / session_id / "session.json"
    if not session_file.exists():
        print(json.dumps({"metadata": {"status_line": f"session:{session_id[:8]}"}}))
        return

    try:
        session = json.loads(session_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(json.dumps({"metadata": {"status_line": f"session:{session_id[:8]} status:unreadable"}}))
        return

    cache = session.get("cache", {})
    status_line = cache.get("status_line", {})
    rendered = status_line.get("rendered", f"session:{session_id[:8]}")
    print(json.dumps({"metadata": {"status_line": rendered}}))


if __name__ == "__main__":
    main()
