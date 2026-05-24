#!/usr/bin/env python3
"""scripts/compile_phase_criteria.py -- Compile a markdown phase-criteria
document into a deterministic, schema-validated YAML/JSON artifact.

Issue #38 (Cluster F 3/5). The compiler exists so agents that drift after
context compaction can mechanically reconstruct the per-phase punch list
from a structured artifact rather than from thin prose summaries.

What this compiler IS:
  - A line-oriented markdown parser for an INTENTIONALLY-NARROW grammar
    (H2 = phase scope; H3 starting with `R-...` = one requirement row;
    `- key: value` bullets carry the row fields).
  - A deterministic emitter: re-running the compiler on the same input
    MUST produce byte-identical output (LF endings, sorted keys, single
    trailing newline). The byte-equality property is the load-bearing
    audit guarantee -- a non-deterministic emitter would let the same
    input drift the committed artifact silently.
  - A schema self-check: the compiled document is validated against
    schemas/phase-criteria.schema.json before write. A schema failure
    aborts the compile (exit code 1) so a malformed row never ships.

What this compiler is NOT:
  - A general markdown processor. The grammar is the union of H2, H3,
    HTML phase-id comment, and `key: value` bullet (no inline markdown,
    no nested bullets, no fenced code). Anything outside this grammar
    is silently skipped (lines between sections, prose paragraphs,
    blank lines, `<!-- ... -->` comments other than `phase-id`).
  - A drift-vs-source reconciler. Hand-edited phase-criteria.yaml files
    are not auto-reconciled back to the markdown source; that drift is
    operator-owned (deferred to #45 phase-corpus, per plan §10).

Inputs:
  --doc PATH    Markdown file to compile. REQUIRED.
  --out PATH    Output artifact path. REQUIRED. Suffix decides format:
                `.yaml` / `.yml` -> YAML; `.json` -> JSON.
  --emit FORMAT Optional explicit format override (`yaml` or `json`). If
                supplied, beats the suffix.

Output:
  - Writes the compiled artifact to --out.
  - Prints a one-line summary on stdout (rows compiled, artifact path).
  - Exits 0 on success, 1 on parse/schema failure, 2 on unknown CLI flag
    or missing dependency (PyYAML / jsonschema).

Reuses the canonical requirement-id regex from
  v3.5/docs/conventions/brutal-honesty-kit/v3.5/enums/requirement-id-format.txt
(read at runtime, NOT hardcoded). Mirrors the regex-source-of-truth
discipline #46 introduced for cluster F.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

__version__ = "1.0"

# Locate the v3.5 enums + schemas relative to this script. The compiler
# can be invoked from any cwd; the artifacts live at a known offset
# under the repo (mirrors validate_pr_brutal_honesty.py's _ENUM_DIR).
_SCRIPT_DIR = Path(__file__).resolve().parent
_V35_ROOT = (
    _SCRIPT_DIR.parent
    / "_internal"
    / "conventions"
    / "brutal-honesty-kit"
    / "v3.5"
)
_ENUM_DIR = _V35_ROOT / "enums"
_SCHEMA_PATH = _V35_ROOT / "schemas" / "phase-criteria.schema.json"

# Closed set of well-known bullet keys. Each H3-row collects key/value
# pairs from subsequent `- key: value` bullets; an unknown key aborts
# the compile (so a typo does not silently drop a field).
_KNOWN_KEYS = frozenset(
    {
        "source",
        "source_doc",
        "source_line",
        "source_section",
        "phase_id",
        "evidence_tier_min",
        "local_vs_production",
        "test_harness_path",
        "acceptance_evidence",
        "status",
        "blocker_type",
        "downstream",
        "downstream_dependencies",
        "unit",
        "unit_source",
    }
)

# Markdown-grammar regexes. Kept narrow on purpose; see module docstring
# "What this compiler is NOT" section.
_H2_RE = re.compile(r"^##\s+(.+?)\s*$")
_H3_RE = re.compile(r"^###\s+(\S+)(?:\s+(.+?))?\s*$")
_PHASE_ID_COMMENT_RE = re.compile(
    r"^<!--\s*phase-id:\s*([A-Za-z0-9_.\-]+)\s*-->\s*$"
)
_BULLET_RE = re.compile(r"^-\s+([a-z_]+)\s*:\s*(.*?)\s*$")


def _load_requirement_id_regex() -> re.Pattern[str]:
    """Read the canonical requirement-id regex from
    enums/requirement-id-format.txt (issue #46). Failing to read the
    file is fatal -- the compiler MUST NOT hardcode the regex (the file
    is the source of truth and the drift validator checks parity)."""
    path = _ENUM_DIR / "requirement-id-format.txt"
    if not path.exists():
        raise SystemExit(
            f"ERROR: missing requirement-id-format.txt at {path}; "
            f"compiler cannot validate row ids without the canonical "
            f"regex (issue #46)."
        )
    pattern_lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not pattern_lines:
        raise SystemExit(
            f"ERROR: requirement-id-format.txt at {path} carried no "
            f"non-comment regex literal."
        )
    try:
        return re.compile(pattern_lines[0])
    except re.error as exc:
        raise SystemExit(
            f"ERROR: requirement-id-format.txt regex {pattern_lines[0]!r} "
            f"is not a valid Python re-pattern: {exc}"
        )


def _load_schema() -> dict:
    """Read the JSON Schema once. Failing to read is fatal -- the
    compiler refuses to emit an unvalidated artifact."""
    if not _SCHEMA_PATH.exists():
        raise SystemExit(
            f"ERROR: phase-criteria.schema.json missing at "
            f"{_SCHEMA_PATH}; compiler cannot self-check (issue #38)."
        )
    try:
        return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"ERROR: phase-criteria.schema.json parse failed: {exc}"
        )


def _parse_csv_ids(value: str) -> list[str]:
    """Parse a `downstream:` bullet's CSV-of-ids into a sorted list.
    Empty / `none` collapses to []. Whitespace tolerant."""
    if not value:
        return []
    cleaned = value.strip()
    if cleaned.lower() in {"none", "n/a", "empty", "[]"}:
        return []
    return [tok.strip() for tok in cleaned.split(",") if tok.strip()]


def _compile_markdown(
    doc_path: Path,
    requirement_id_re: re.Pattern[str],
) -> list[dict[str, Any]]:
    """Parse the markdown into a list of compiled rows. Raises
    SystemExit(1) on any parse error so the CLI surface stays
    consistent (`exit code 1 = parse/schema failure`)."""
    if not doc_path.exists():
        raise SystemExit(
            f"ERROR: --doc {doc_path} does not exist."
        )
    text = doc_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    rows: list[dict[str, Any]] = []
    current_phase_id: str = ""
    current_h2_title: str = ""
    current_row: Optional[dict[str, Any]] = None

    def _flush_current_row() -> None:
        nonlocal current_row
        if current_row is None:
            return
        rows.append(current_row)
        current_row = None

    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\r")

        # H2 -- phase scope. Resets phase-id to empty until a
        # `<!-- phase-id: ... -->` comment is found.
        h2_match = _H2_RE.match(line)
        if h2_match:
            _flush_current_row()
            current_h2_title = h2_match.group(1).strip()
            current_phase_id = ""
            continue

        # phase-id HTML comment (only meaningful right under an H2).
        pid_match = _PHASE_ID_COMMENT_RE.match(line.strip())
        if pid_match:
            current_phase_id = pid_match.group(1).strip()
            continue

        # H3 -- candidate row open. Token must match the canonical
        # requirement-id regex; a non-matching H3 fails the compile so
        # a typo does not drop a row silently.
        h3_match = _H3_RE.match(line)
        if h3_match:
            _flush_current_row()
            token = h3_match.group(1).strip()
            title_tail = (h3_match.group(2) or "").strip()
            if not requirement_id_re.match(token):
                raise SystemExit(
                    f"ERROR: {doc_path}:{line_no}: H3 token {token!r} "
                    f"does not match the requirement-id format regex "
                    f"(see enums/requirement-id-format.txt). Each H3 "
                    f"that opens a phase-criteria row MUST start with "
                    f"a canonical R-... id. Issue #38 / R55."
                )
            section_title = current_h2_title
            if title_tail:
                section_title = (
                    f"{current_h2_title} / {token} {title_tail}"
                    if current_h2_title
                    else f"{token} {title_tail}"
                )
            elif current_h2_title:
                section_title = f"{current_h2_title} / {token}"
            else:
                section_title = token
            current_row = {
                "requirement_id": token,
                "phase_id": current_phase_id,
                "source_doc": str(doc_path).replace("\\", "/"),
                "source_line": line_no,
                "source_section": section_title,
            }
            continue

        # Bullet -- key/value pair. Only meaningful inside an open row.
        bullet_match = _BULLET_RE.match(line)
        if bullet_match and current_row is not None:
            key = bullet_match.group(1)
            value = bullet_match.group(2).strip()
            if key not in _KNOWN_KEYS:
                raise SystemExit(
                    f"ERROR: {doc_path}:{line_no}: bullet key {key!r} "
                    f"is not in the closed set "
                    f"{sorted(_KNOWN_KEYS)}. Unknown keys are rejected "
                    f"so a typo does not silently drop a field. "
                    f"Issue #38 / R55."
                )
            # Normalise a few aliases / shapes.
            if key == "source":
                # Legacy alias for source_doc + source_section combined
                # in one bullet. We treat it as additional source_section
                # context (does not override the H2/H3-derived section).
                current_row.setdefault("source_section", value)
                continue
            if key in {"downstream", "downstream_dependencies"}:
                current_row["downstream_dependencies"] = (
                    _parse_csv_ids(value)
                )
                # Validate every cited id matches the regex too.
                for cited in current_row["downstream_dependencies"]:
                    if not requirement_id_re.match(cited):
                        raise SystemExit(
                            f"ERROR: {doc_path}:{line_no}: downstream "
                            f"id {cited!r} does not match the "
                            f"requirement-id format regex."
                        )
                continue
            if key == "source_line":
                # Allow operator override of the auto-derived line. Cast
                # to int when possible; otherwise leave as-is and let
                # the schema reject.
                try:
                    current_row[key] = int(value)
                except ValueError:
                    current_row[key] = value
                continue
            # Empty / sentinel collapses to None so the schema's
            # nullable fields parse cleanly.
            if value == "" or value.lower() in {"none", "null", "n/a"}:
                current_row[key] = None
            else:
                current_row[key] = value
            continue

        # Anything else (blank lines, prose, unrelated comments) is
        # silently skipped. We deliberately tolerate prose between
        # rows so the source doc reads as a normal markdown document.

    _flush_current_row()
    return rows


def _emit_yaml(payload: dict, out_path: Path) -> None:
    try:
        import yaml  # type: ignore
    except ImportError:
        raise SystemExit(
            "ERROR: PyYAML is required to emit YAML. "
            "Install with `pip install pyyaml` (exit 2)."
        )
    text = yaml.safe_dump(
        payload,
        sort_keys=True,
        default_flow_style=False,
        width=1000,
        allow_unicode=True,
    )
    # safe_dump already terminates with a single newline; normalise
    # line endings to LF to keep byte-equality cross-platform.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text = text + "\n"
    # Write in binary mode with explicit LF so Windows newline
    # translation does not perturb determinism.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(text.encode("utf-8"))


def _emit_json(payload: dict, out_path: Path) -> None:
    text = (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False)
        + "\n"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(text.encode("utf-8"))


def _validate(payload: dict, schema: dict) -> None:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        raise SystemExit(
            "ERROR: jsonschema is required for compile-time self-check. "
            "Install with `pip install jsonschema` (exit 2)."
        )
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        # Surface the offending path so the operator can find the row.
        path_str = "/".join(str(p) for p in exc.absolute_path)
        raise SystemExit(
            f"ERROR: phase-criteria self-check failed at /{path_str}: "
            f"{exc.message}"
        )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compile a markdown phase-criteria doc into a "
            "deterministic, schema-validated YAML/JSON artifact "
            "(issue #38)."
        ),
    )
    parser.add_argument(
        "--doc",
        required=True,
        help="Markdown input file (path).",
    )
    parser.add_argument(
        "--out",
        required=True,
        help=(
            "Output artifact path. Suffix decides format unless "
            "--emit overrides: .yaml/.yml -> YAML; .json -> JSON."
        ),
    )
    parser.add_argument(
        "--emit",
        default=None,
        choices=("yaml", "json"),
        help="Explicit format override.",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        # argparse exits 2 on unknown flags; preserve that behaviour.
        raise

    doc_path = Path(args.doc)
    out_path = Path(args.out)

    requirement_id_re = _load_requirement_id_regex()
    schema = _load_schema()

    rows = _compile_markdown(doc_path, requirement_id_re)
    if not rows:
        raise SystemExit(
            f"ERROR: {doc_path} produced zero rows. A phase-criteria "
            f"doc with no R-... H3s is L9 doc-as-implementation; "
            f"compile refuses (issue #38)."
        )

    payload = {
        "schema_version": "1.0",
        "compiler_version": __version__,
        "rows": rows,
    }

    _validate(payload, schema)

    fmt = args.emit
    if fmt is None:
        suffix = out_path.suffix.lower()
        if suffix in {".yaml", ".yml"}:
            fmt = "yaml"
        elif suffix == ".json":
            fmt = "json"
        else:
            raise SystemExit(
                f"ERROR: cannot infer output format from suffix "
                f"{suffix!r}; pass --emit yaml|json explicitly."
            )

    if fmt == "yaml":
        _emit_yaml(payload, out_path)
    else:
        _emit_json(payload, out_path)

    print(
        f"compile_phase_criteria: wrote {len(rows)} row(s) to "
        f"{out_path} ({fmt})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
