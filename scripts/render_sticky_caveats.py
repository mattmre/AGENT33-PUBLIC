#!/usr/bin/env python3
"""scripts/render_sticky_caveats.py — render docs/sticky-caveats.md from JSONL.

Issue #11: out/sticky-caveats.jsonl is the source of truth; the rendered
markdown table is for human review. Replays the JSONL via the same
state-machine the validator uses, then emits a markdown table listing every
caveat in a non-closed_* state.

Exit code 0 always (the validator is the gate; rendering should not block).
Reports zero rows as 'no active sticky caveats.' to keep the output stable
in adopter installs that have not yet promoted any caveats.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))
from sticky_caveats_append import replay  # noqa: E402


_HEADER = (
    "| Fingerprint | State | Count | Owner | Attempt | Review | Text |\n"
    "|-------------|-------|-------|-------|---------|--------|------|\n"
)


def render(records: list[dict]) -> str:
    states = replay(records)
    lines: list[str] = []
    last_text: dict[str, str] = {}
    for rec in records:
        last_text[rec["fingerprint"]] = rec.get("text", "")
    for fp, s in sorted(states.items()):
        if s["state"] in ("closed_evidence", "closed_impossibility",
                          "closed_scope_waiver"):
            continue
        lines.append(
            f"| `{fp[:8]}` | {s['state']} | {s['count']} | "
            f"{s['owner'] or '—'} | "
            f"{s['attempt_ref'] or '—'} | "
            f"{s['review_ref'] or '—'} | "
            f"{last_text.get(fp, '').replace('|', '\\|')} |"
        )
    if not lines:
        return (
            "# Sticky caveats\n\n"
            "_no active sticky caveats._\n"
        )
    return (
        "# Sticky caveats\n\n"
        + _HEADER
        + "\n".join(lines)
        + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--in", dest="ledger", default="out/sticky-caveats.jsonl",
    )
    parser.add_argument(
        "--out", dest="out", default="docs/sticky-caveats.md",
    )
    args = parser.parse_args(argv)

    in_path = Path(args.ledger)
    records: list[dict] = []
    if in_path.exists():
        for line in in_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(records), encoding="utf-8")
    print(f"sticky-caveats: rendered {out_path} from {in_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
