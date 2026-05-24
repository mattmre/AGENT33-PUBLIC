#!/usr/bin/env python3
"""scripts/validate_lane_consistency.py -- long-haul artifact
cross-consistency validator (issue #7, cluster E 5/7).

Reads every long-haul lane artifact (lane-history.jsonl,
carried-debt.jsonl, charter-merge-log.jsonl, lane-charter.md,
phase-punchlist.json, orchestrator.heartbeat.json, return-digest.md,
phase-alignment-phase<N>.md, exhaustion-packets/*.md,
parent-resumption-packet.md) and FAILs on cross-artifact disagreement.

Each individual schema validator already passes; this validator catches
the case where every artifact is internally consistent but the LANE
lies (digest claims 12 PRs merged while lane-history shows 11; an
exhaustion-packet claims evidence absent while Tier B scored 87; a
sidecar resumption packet's `sidecar_charter_close_sha` is stale).

The 20 LC-NNN drift checks are listed in
v3.5/docs/conventions/brutal-honesty-kit/v3.5/lane-consistency-checks.md
(operator-facing index) and enumerated in
v3.5/docs/conventions/brutal-honesty-kit/v3.5/enums/lc-codes.txt.
The drift validator (validate_v33_schema_drift.py via
validate_lc_codes_parity) cross-checks the .txt file against this
script's `LC_CODES` tuple verbatim.

Exit codes (operator-spec 5-class policy, highest-priority wins,
5 > 4 > 3 > 2 > 1; v3.6 #101 reconciliation):
  0 clean -- every cross-artifact assertion holds
  1 cross-artifact data drift (core class -- counts/scores/status)
  2 schema failure (one underlying artifact does not validate)
  3 enum drift (closed-set vocabulary disagrees between artifact
    and the on-disk enum file -- e.g. lane-classification token not
    listed in lane-classifications.txt)
  4 chain integrity failure (lane-history / merge-log chain break,
    OR a required artifact is missing so the chain cannot even be
    walked -- missing-artifact collapses into chain class because
    both signal the lane's evidence tree is structurally incomplete)
  5 F11 corruption (CRC32 fail / truncation / unreadable; the
    most load-bearing failure -- the bytes on disk are wrong)

Performance budget: < 5s on a 30-PR fixture (~600 lane-history events,
~50 charter-merge-log rows, ~20 phase-alignment files). Algorithm is a
single forward-walk of each JSONL into in-memory dicts; cross-checks
operate on dicts. No quadratic scans.

This CLI is invoked OUT-OF-BAND by orchestrators / the endurance
benchmark (#41) / the BHS_TRAJECTORY consumer (#6). It does NOT add new
rules to validate_pr_brutal_honesty.py and does NOT gate per-PR ship.
"""

from __future__ import annotations

import argparse
import binascii
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Closed set of LC-NNN codes. MUST mirror
# v3.5/docs/conventions/brutal-honesty-kit/v3.5/enums/lc-codes.txt
# verbatim. Drift is enforced by validate_v33_schema_drift.py via
# validate_lc_codes_parity (back-compat for fresh-kit checkouts: the
# parity check is .exists()-gated on the enum file).
# ---------------------------------------------------------------------------

LC_CODES: tuple[str, ...] = (
    "LC-001",
    "LC-002",
    "LC-003",
    "LC-004",
    "LC-005",
    "LC-006",
    "LC-007",
    "LC-008",
    "LC-009",
    "LC-010",
    "LC-011",
    "LC-012",
    "LC-013",
    "LC-014",
    "LC-015",
    "LC-016",
    "LC-017",
    "LC-018",
    "LC-019",
    "LC-020",
)


# Exit-code constants -- operator-spec 5-class policy (v3.6 #101).
# Highest-priority wins: 5 > 4 > 3 > 2 > 1 (larger code is more
# load-bearing, scanned first by choose_exit_code).
EXIT_CLEAN = 0
# Back-compat alias for any cross-gate harness or downstream importer
# that expects the EXIT_OK spelling instead of EXIT_CLEAN. The two
# names refer to the same integer (0) and the same Python binding via
# direct assignment (not a copy). This is a single-site, single-file
# back-compat alias -- v3.7-final HP-I D7 (pass-3 R2) verified that
# none of the three cluster-E sibling gates (validate_v33_schema_drift.py,
# validate_bhs_ledger.py, validate_pr_brutal_honesty.py) actually expose
# a top-level EXIT_OK = ... constant on the v3.7-final tip, so the
# previous claim that this alias "matched" sibling-gate EXIT_OK
# constants was aspirational rather than factual. The alias is still
# useful for back-compat with adopters who imported the old name from
# this module, which is why it is retained.
EXIT_OK = EXIT_CLEAN
EXIT_DRIFT = 1
EXIT_SCHEMA = 2
EXIT_ENUM = 3
EXIT_CHAIN = 4
EXIT_CORRUPTION = 5
# MISSING-required-artifact collapses into EXIT_CHAIN under the
# operator-spec 5-class policy: a missing required artifact prevents
# the lane-history / merge-log chain from being walked, so it surfaces
# at the same severity as a chain break.
EXIT_MISSING = EXIT_CHAIN
# Priority order: 5 > 4 > 3 > 2 > 1. The driver scans largest-first.
_EXIT_PRIORITY: tuple[int, ...] = (
    EXIT_CORRUPTION,
    EXIT_CHAIN,
    EXIT_ENUM,
    EXIT_SCHEMA,
    EXIT_DRIFT,
)

# Map LC code -> exit-code class. Keep in sync with §3.2 of the plan
# AND with lane-consistency-checks.md.
#
# v3.6 #101 reconciliation: the operator-spec 5-class policy adds
# EXIT_ENUM (3); LC-002 (lane-history kind enum closed-set), LC-016
# (charter false_stop_conditions enum vocabulary), and LC-020 (charter
# phases[].punchlist[].id format vs plan-id closed pattern) are
# vocabulary-class drifts and map to EXIT_ENUM. LC-013 schema-class
# drift (digest sha references resolve to commits in lane-history)
# maps to EXIT_SCHEMA so the SCHEMA class is no longer dead.
LC_EXIT_CLASS: dict[str, int] = {
    "LC-001": EXIT_DRIFT,
    "LC-002": EXIT_ENUM,
    "LC-003": EXIT_DRIFT,
    "LC-004": EXIT_DRIFT,
    "LC-005": EXIT_DRIFT,
    "LC-006": EXIT_DRIFT,
    "LC-007": EXIT_DRIFT,
    "LC-008": EXIT_DRIFT,
    "LC-009": EXIT_DRIFT,
    "LC-010": EXIT_DRIFT,
    "LC-011": EXIT_DRIFT,
    "LC-012": EXIT_CHAIN,
    "LC-013": EXIT_SCHEMA,
    "LC-014": EXIT_DRIFT,
    "LC-015": EXIT_DRIFT,
    "LC-016": EXIT_ENUM,
    "LC-017": EXIT_DRIFT,
    "LC-018": EXIT_DRIFT,
    "LC-019": EXIT_DRIFT,
    "LC-020": EXIT_ENUM,
}


# ---------------------------------------------------------------------------
# Issue dataclass -- mirrors validate_v33_schema_drift.Issue shape so
# downstream consumers (#6, #41) can ingest both validators uniformly.
# ---------------------------------------------------------------------------


@dataclass
class Issue:
    code: str  # LC-NNN OR a symbolic non-LC code (e.g. "F11", "MISSING")
    category: str  # cross_artifact_drift | schema | chain | missing | corruption
    artifacts_involved: list[str] = field(default_factory=list)
    field_pointers: list[str] = field(default_factory=list)
    expected: Any = None
    actual: Any = None
    message: str = ""
    exit_code_class: int = EXIT_DRIFT

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "category": self.category,
            "artifacts_involved": list(self.artifacts_involved),
            "field_pointers": list(self.field_pointers),
            "expected": self.expected,
            "actual": self.actual,
            "message": self.message,
            "exit_code_class": self.exit_code_class,
        }


def _make_issue(
    code: str,
    *,
    category: str | None = None,
    artifacts: Iterable[str] = (),
    pointers: Iterable[str] = (),
    expected: Any = None,
    actual: Any = None,
    message: str = "",
    exit_class: int | None = None,
) -> Issue:
    if exit_class is None:
        exit_class = LC_EXIT_CLASS.get(code, EXIT_DRIFT)
    if category is None:
        # Derive from exit class. EXIT_MISSING is an alias for
        # EXIT_CHAIN under the operator-spec 5-class policy, so the
        # category lookup omits it (missing -> chain).
        category = {
            EXIT_DRIFT: "cross_artifact_drift",
            EXIT_SCHEMA: "schema",
            EXIT_ENUM: "enum",
            EXIT_CHAIN: "chain",
            EXIT_CORRUPTION: "corruption",
        }[exit_class]
    return Issue(
        code=code,
        category=category,
        artifacts_involved=list(artifacts),
        field_pointers=list(pointers),
        expected=expected,
        actual=actual,
        message=message,
        exit_code_class=exit_class,
    )


# ---------------------------------------------------------------------------
# CRC32 helper (mirrors scripts/validate_charter_merge_log.compute_crc32
# verbatim so the same record hashes identically here).
# ---------------------------------------------------------------------------


def _serialize_for_crc(record: dict) -> bytes:
    return json.dumps(
        {k: v for k, v in record.items() if k != "crc32"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_crc32(record: dict) -> str:
    return f"{binascii.crc32(_serialize_for_crc(record)) & 0xFFFFFFFF:08x}"


# ---------------------------------------------------------------------------
# Generic JSONL loader. Returns (records, issues). On invalid JSON or
# CRC mismatch (when the record carries a `crc32` field), surfaces an
# Issue with exit-class 5 (corruption). Schema validation is the
# caller's responsibility -- this loader only enforces parseability +
# CRC integrity.
# ---------------------------------------------------------------------------


def _load_jsonl(
    path: Path,
    artifact_label: str,
    issues: list[Issue],
    *,
    enforce_crc_when_present: bool = True,
) -> list[dict]:
    records: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        issues.append(
            _make_issue(
                "F11",
                exit_class=EXIT_CORRUPTION,
                artifacts=[str(path)],
                message=f"{artifact_label}: cannot read file: {exc}",
            )
        )
        return records
    for idx, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            issues.append(
                _make_issue(
                    "F11",
                    exit_class=EXIT_CORRUPTION,
                    artifacts=[str(path)],
                    pointers=[f"line {idx}"],
                    message=(
                        f"{artifact_label}: line {idx}: invalid JSON "
                        f"({exc}). Treating as F11 corruption / truncation."
                    ),
                )
            )
            return records
        if (
            enforce_crc_when_present
            and isinstance(rec, dict)
            and "crc32" in rec
        ):
            stored = rec.get("crc32")
            actual = compute_crc32(rec)
            if stored != actual:
                issues.append(
                    _make_issue(
                        "F11",
                        exit_class=EXIT_CORRUPTION,
                        artifacts=[str(path)],
                        pointers=[f"line {idx}"],
                        expected=stored,
                        actual=actual,
                        message=(
                            f"{artifact_label}: line {idx}: CRC32 "
                            f"mismatch (stored={stored!r}, "
                            f"computed={actual!r}). F11 corruption."
                        ),
                    )
                )
                return records
        records.append(rec)
    return records


# ---------------------------------------------------------------------------
# YAML front-matter parser. The artifacts that ship a YAML front-matter
# (lane-charter.md, phase-alignment-phase<N>.md, exhaustion-packets/*.md,
# parent-resumption-packet.md) follow the same convention: a leading
# `---\n` line, then YAML, then a closing `---\n` line, then markdown
# narrative. We avoid the PyYAML dependency by parsing the strict
# subset we actually use (key: value pairs + nested maps + lists). This
# keeps the validator dependency-free per architecture §5.4.
# ---------------------------------------------------------------------------


_FRONT_MATTER_RE = re.compile(
    r"\A---\s*\r?\n(.*?)\r?\n---\s*\r?\n(.*)\Z",
    re.DOTALL,
)


def _parse_front_matter(
    path: Path, artifact_label: str, issues: list[Issue]
) -> tuple[dict | None, str | None]:
    """Return (front_matter_dict, body_text). On error, surfaces an
    Issue with exit-class 5 (corruption) and returns (None, None)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        issues.append(
            _make_issue(
                "F11",
                exit_class=EXIT_CORRUPTION,
                artifacts=[str(path)],
                message=f"{artifact_label}: cannot read file: {exc}",
            )
        )
        return None, None
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        issues.append(
            _make_issue(
                "F11",
                exit_class=EXIT_CORRUPTION,
                artifacts=[str(path)],
                message=(
                    f"{artifact_label}: missing or malformed YAML "
                    f"front-matter (expected leading and trailing "
                    f"`---` fences)."
                ),
            )
        )
        return None, None
    fm_text, body = m.group(1), m.group(2)
    try:
        data = _parse_simple_yaml(fm_text)
    except _YamlError as exc:
        issues.append(
            _make_issue(
                "F11",
                exit_class=EXIT_CORRUPTION,
                artifacts=[str(path)],
                message=(
                    f"{artifact_label}: cannot parse front-matter YAML: "
                    f"{exc}"
                ),
            )
        )
        return None, None
    return data, body


class _YamlError(Exception):
    pass


def _parse_simple_yaml(text: str) -> dict:
    """Strict-subset YAML parser: top-level scalar + list + nested map.
    Supports:
      key: scalar
      key:           (then indented children)
        sub: scalar
      key:
        - listitem
        - listitem
      "string with spaces"   (quoted scalars)

    Does NOT support: anchors, aliases, multi-line strings, flow style.
    Used for lane-charter / phase-alignment / exhaustion-packet front-
    matter which all follow the same simple shape.
    """
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    return _parse_block(lines, 0, 0)[0]


def _indent_of(line: str) -> int:
    i = 0
    while i < len(line) and line[i] == " ":
        i += 1
    return i


def _parse_scalar(raw: str) -> Any:
    s = raw.strip()
    if not s:
        return None
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    if s in ("null", "~"):
        return None
    if (s.startswith('"') and s.endswith('"')) or (
        s.startswith("'") and s.endswith("'")
    ):
        return s[1:-1]
    # Integer
    if re.fullmatch(r"-?\d+", s):
        try:
            return int(s)
        except ValueError:
            return s
    return s


def _parse_block(
    lines: list[str], start: int, indent: int
) -> tuple[dict | list, int]:
    """Parse a YAML block at the given indent. Returns (value, next_idx)."""
    # Decide whether this is a list block or a mapping block by peeking
    # the first non-blank/comment line at this indent.
    i = start
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s or s.startswith("#"):
            i += 1
            continue
        if _indent_of(ln) != indent:
            # Empty block at this indent.
            return {}, start
        if s.startswith("- "):
            return _parse_list(lines, i, indent)
        return _parse_map(lines, i, indent)
    return {}, i


def _parse_list(
    lines: list[str], start: int, indent: int
) -> tuple[list, int]:
    out: list = []
    i = start
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s or s.startswith("#"):
            i += 1
            continue
        if _indent_of(ln) < indent:
            break
        if _indent_of(ln) > indent:
            # Should have been consumed by a child; defensive.
            i += 1
            continue
        if not s.startswith("- "):
            break
        item_text = s[2:].strip()
        # If the item is a key:value, treat the list element as a map.
        if (
            ":" in item_text
            and not item_text.startswith('"')
            and not item_text.startswith("'")
        ):
            # Inline-mapping list element. Build a one-line map and
            # extend with following indented lines.
            key, _, val = item_text.partition(":")
            element: dict = {}
            element[key.strip()] = _parse_scalar(val) if val.strip() else None
            i += 1
            # Look for additional keys at child_indent.
            child_indent = indent + 2
            while i < len(lines):
                nl = lines[i]
                ns = nl.strip()
                if not ns or ns.startswith("#"):
                    i += 1
                    continue
                if _indent_of(nl) < child_indent:
                    break
                if _indent_of(nl) != child_indent:
                    i += 1
                    continue
                if ns.startswith("- "):
                    break
                k2, _, v2 = ns.partition(":")
                if v2.strip() == "":
                    nested, i = _parse_block(
                        lines, i + 1, child_indent + 2
                    )
                    element[k2.strip()] = nested
                else:
                    element[k2.strip()] = _parse_scalar(v2)
                    i += 1
            out.append(element)
        else:
            out.append(_parse_scalar(item_text))
            i += 1
    return out, i


def _parse_map(
    lines: list[str], start: int, indent: int
) -> tuple[dict, int]:
    out: dict = {}
    i = start
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s or s.startswith("#"):
            i += 1
            continue
        cur_indent = _indent_of(ln)
        if cur_indent < indent:
            break
        if cur_indent != indent:
            # Child of a previous key without explicit `:` line --
            # malformed in our subset.
            raise _YamlError(
                f"unexpected indent at line: {ln!r}"
            )
        if s.startswith("- "):
            # A list at this indent without a parent key is invalid
            # here; defer to caller.
            break
        if ":" not in s:
            raise _YamlError(f"missing ':' on line: {ln!r}")
        key, _, val = s.partition(":")
        key = key.strip()
        val_stripped = val.strip()
        if val_stripped == "":
            # Could be a nested map or list at deeper indent.
            child, next_i = _parse_block(lines, i + 1, indent + 2)
            out[key] = child
            i = next_i
        else:
            out[key] = _parse_scalar(val_stripped)
            i += 1
    return out, i


# ---------------------------------------------------------------------------
# Per-artifact loaders. Each returns a domain-specific dict + the issues
# accumulated during loading. Loaders never raise; corruption surfaces
# as exit-class-5 issues.
# ---------------------------------------------------------------------------


def _load_lane_history(
    path: Path | None, issues: list[Issue]
) -> list[dict] | None:
    if path is None:
        return None
    if not path.exists():
        issues.append(
            _make_issue(
                "MISSING",
                exit_class=EXIT_MISSING,
                artifacts=[str(path)],
                message=(
                    f"lane-history.jsonl required artifact missing: "
                    f"{path}"
                ),
            )
        )
        return None
    return _load_jsonl(
        path,
        "lane-history.jsonl",
        issues,
        enforce_crc_when_present=True,
    )


def _load_carried_debt(
    path: Path | None, issues: list[Issue]
) -> list[dict] | None:
    if path is None:
        return None
    if not path.exists():
        # Optional artifact -- not present is a no-op for related
        # checks; only LC-010 / LC-011 / LC-014 use it.
        return None
    return _load_jsonl(
        path,
        "carried-debt.jsonl",
        issues,
        enforce_crc_when_present=True,
    )


def _load_charter_merge_log(
    path: Path | None, issues: list[Issue]
) -> list[dict] | None:
    if path is None:
        return None
    if not path.exists():
        return None
    return _load_jsonl(
        path,
        "charter-merge-log.jsonl",
        issues,
        enforce_crc_when_present=True,
    )


def _load_lane_charter(
    path: Path | None, issues: list[Issue]
) -> dict | None:
    if path is None:
        return None
    if not path.exists():
        return None
    fm, _body = _parse_front_matter(path, "lane-charter.md", issues)
    if fm is None:
        return None
    return fm


def _load_phase_punchlist(
    path: Path | None, issues: list[Issue]
) -> dict | None:
    if path is None:
        return None
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(
            _make_issue(
                "F11",
                exit_class=EXIT_CORRUPTION,
                artifacts=[str(path)],
                message=f"phase-punchlist.json: parse error: {exc}",
            )
        )
        return None


def _load_heartbeat(
    path: Path | None, issues: list[Issue]
) -> dict | None:
    if path is None:
        return None
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(
            _make_issue(
                "F11",
                exit_class=EXIT_CORRUPTION,
                artifacts=[str(path)],
                message=(
                    f"orchestrator.heartbeat.json: parse error: {exc}"
                ),
            )
        )
        return None


# return-digest.md is a structured-table markdown artifact. The
# convention used by the digest writer (cluster F) is a YAML front-
# matter block followed by markdown sections containing fenced
# `<!-- digest:KEY=VALUE -->` HTML comments for machine-readable
# claims. The validator parses the front-matter (for headline counts /
# weakest_phase / per-PR scores) and falls back to comment-scanning the
# body for older digests. This keeps the writer side free to render
# whatever prose it wants while the cross-artifact assertions still
# operate on a closed set of structured fields.


def _load_return_digest(
    path: Path | None, issues: list[Issue]
) -> dict | None:
    if path is None:
        return None
    if not path.exists():
        # Required by the CLI signature; surface MISSING.
        issues.append(
            _make_issue(
                "MISSING",
                exit_class=EXIT_MISSING,
                artifacts=[str(path)],
                message=f"return-digest.md required artifact missing: {path}",
            )
        )
        return None
    fm, _body = _parse_front_matter(path, "return-digest.md", issues)
    if fm is None:
        return None
    return fm


def _load_phase_alignment_dir(
    dir_path: Path | None, issues: list[Issue]
) -> dict[str, dict]:
    """Return {phase_id: front_matter_dict} for every phase-alignment
    file in dir_path (matching `phase-alignment-phase<N>.md`)."""
    out: dict[str, dict] = {}
    if dir_path is None or not dir_path.exists() or not dir_path.is_dir():
        return out
    for child in sorted(dir_path.iterdir()):
        if not child.is_file():
            continue
        m = re.fullmatch(
            r"phase-alignment-phase([0-9]+)\.md", child.name
        )
        if not m:
            continue
        phase_num = m.group(1)
        fm, _body = _parse_front_matter(
            child, f"phase-alignment-phase{phase_num}.md", issues
        )
        if fm is None:
            continue
        out[f"phase-{phase_num}"] = fm
    return out


def _load_exhaustion_packets(
    dir_path: Path | None, issues: list[Issue]
) -> list[dict]:
    out: list[dict] = []
    if dir_path is None or not dir_path.exists() or not dir_path.is_dir():
        return out
    for child in sorted(dir_path.iterdir()):
        if not child.is_file() or not child.name.endswith(".md"):
            continue
        fm, _body = _parse_front_matter(
            child, f"exhaustion-packets/{child.name}", issues
        )
        if fm is None:
            continue
        fm["_packet_filename"] = child.name
        out.append(fm)
    return out


def _load_parent_resumption_packet(
    path: Path | None, issues: list[Issue]
) -> dict | None:
    if path is None:
        return None
    if not path.exists():
        return None
    fm, _body = _parse_front_matter(
        path, "parent-resumption-packet.md", issues
    )
    return fm


# ---------------------------------------------------------------------------
# Loaded-artifact bundle.
# ---------------------------------------------------------------------------


@dataclass
class Bundle:
    lane_history: list[dict] | None = None
    carried_debt: list[dict] | None = None
    charter_merge_log: list[dict] | None = None
    lane_charter: dict | None = None
    phase_punchlist: dict | None = None
    heartbeat: dict | None = None
    return_digest: dict | None = None
    phase_alignments: dict[str, dict] = field(default_factory=dict)
    exhaustion_packets: list[dict] = field(default_factory=list)
    parent_resumption_packet: dict | None = None
    paths: dict[str, Path | None] = field(default_factory=dict)


def _load_bundle(args: argparse.Namespace, issues: list[Issue]) -> Bundle:
    paths = {
        "lane_history": Path(args.lane_history) if args.lane_history else None,
        "digest": Path(args.digest) if args.digest else None,
        "charter": Path(args.charter) if args.charter else None,
        "punchlist": Path(args.punchlist) if args.punchlist else None,
        "heartbeat": Path(args.heartbeat) if args.heartbeat else None,
        "carried_debt": Path(args.carried_debt) if args.carried_debt else None,
        "charter_merge_log": (
            Path(args.charter_merge_log)
            if args.charter_merge_log
            else None
        ),
        "phase_alignment_dir": (
            Path(args.phase_alignment_dir)
            if args.phase_alignment_dir
            else None
        ),
        "exhaustion_packet_dir": (
            Path(args.exhaustion_packet_dir)
            if args.exhaustion_packet_dir
            else None
        ),
        "parent_resumption_packet": (
            Path(args.parent_resumption_packet)
            if args.parent_resumption_packet
            else None
        ),
    }
    bundle = Bundle(paths=paths)
    bundle.lane_history = _load_lane_history(paths["lane_history"], issues)
    bundle.return_digest = _load_return_digest(paths["digest"], issues)
    bundle.lane_charter = _load_lane_charter(paths["charter"], issues)
    bundle.phase_punchlist = _load_phase_punchlist(
        paths["punchlist"], issues
    )
    bundle.heartbeat = _load_heartbeat(paths["heartbeat"], issues)
    bundle.carried_debt = _load_carried_debt(
        paths["carried_debt"], issues
    )
    bundle.charter_merge_log = _load_charter_merge_log(
        paths["charter_merge_log"], issues
    )
    bundle.phase_alignments = _load_phase_alignment_dir(
        paths["phase_alignment_dir"], issues
    )
    bundle.exhaustion_packets = _load_exhaustion_packets(
        paths["exhaustion_packet_dir"], issues
    )
    bundle.parent_resumption_packet = _load_parent_resumption_packet(
        paths["parent_resumption_packet"], issues
    )
    return bundle


# ---------------------------------------------------------------------------
# Helpers used by multiple checks.
# ---------------------------------------------------------------------------


def _events_by_kind(
    history: list[dict] | None, kind: str
) -> list[dict]:
    if not history:
        return []
    return [e for e in history if e.get("kind") == kind]


def _latest_tier_b_per_pr(
    history: list[dict] | None,
) -> dict[int, dict]:
    """For each pr number, return the most-recent (by ts) tier_b_run."""
    out: dict[int, dict] = {}
    for ev in history or []:
        if ev.get("kind") != "tier_b_run":
            continue
        pr = ev.get("pr")
        if not isinstance(pr, int):
            continue
        prev = out.get(pr)
        if prev is None or ev.get("ts", "") >= prev.get("ts", ""):
            out[pr] = ev
    return out


def _merge_event_per_pr(
    history: list[dict] | None,
) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for ev in history or []:
        if ev.get("kind") != "merge":
            continue
        pr = ev.get("pr")
        if isinstance(pr, int):
            out[pr] = ev
    return out


def _digest_per_pr_scores(digest: dict | None) -> dict[int, int]:
    """Read `per_pr_scores` from the digest front-matter."""
    if not isinstance(digest, dict):
        return {}
    raw = digest.get("per_pr_scores", {})
    out: dict[int, int] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                out[int(k)] = int(v)
            except (TypeError, ValueError):
                pass
    return out


def _digest_per_pr_merge_sha(digest: dict | None) -> dict[int, str]:
    if not isinstance(digest, dict):
        return {}
    raw = digest.get("per_pr_merge_sha", {})
    out: dict[int, str] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                out[int(k)] = str(v)
            except (TypeError, ValueError):
                pass
    return out


# ---------------------------------------------------------------------------
# LC-NNN check functions. Each returns a list of Issues. Driver
# aggregates and computes the highest-priority exit code.
# ---------------------------------------------------------------------------


def check_lc001_merge_count(bundle: Bundle) -> list[Issue]:
    """LC-001 -- merge event count vs digest claimed merged-PR count."""
    history = bundle.lane_history
    digest = bundle.return_digest
    if history is None or digest is None:
        return []
    actual = len(_events_by_kind(history, "merge"))
    claimed = digest.get("merged_pr_count")
    if not isinstance(claimed, int):
        return []
    if actual != claimed:
        return [
            _make_issue(
                "LC-001",
                artifacts=[
                    str(bundle.paths.get("lane_history")),
                    str(bundle.paths.get("digest")),
                ],
                pointers=[
                    "lane-history.jsonl#kind=merge",
                    "return-digest.md#merged_pr_count",
                ],
                expected=actual,
                actual=claimed,
                message=(
                    f"LC-001: digest claims {claimed} merged PR(s) but "
                    f"lane-history.jsonl shows {actual} merge event(s)."
                ),
            )
        ]
    return []


def check_lc002_pivot_count(bundle: Bundle) -> list[Issue]:
    history = bundle.lane_history
    digest = bundle.return_digest
    if history is None or digest is None:
        return []
    actual = len(_events_by_kind(history, "pivot"))
    claimed = digest.get("pivoted_pr_count")
    if not isinstance(claimed, int):
        return []
    if actual != claimed:
        return [
            _make_issue(
                "LC-002",
                artifacts=[
                    str(bundle.paths.get("lane_history")),
                    str(bundle.paths.get("digest")),
                ],
                pointers=[
                    "lane-history.jsonl#kind=pivot",
                    "return-digest.md#pivoted_pr_count",
                ],
                expected=actual,
                actual=claimed,
                message=(
                    f"LC-002: digest claims {claimed} pivot(s) but "
                    f"lane-history.jsonl shows {actual}."
                ),
            )
        ]
    return []


def check_lc003_pause_count(bundle: Bundle) -> list[Issue]:
    history = bundle.lane_history
    digest = bundle.return_digest
    if history is None or digest is None:
        return []
    actual = len(_events_by_kind(history, "lane_pause"))
    claimed = digest.get("pause_count")
    if not isinstance(claimed, int):
        return []
    if actual != claimed:
        return [
            _make_issue(
                "LC-003",
                artifacts=[
                    str(bundle.paths.get("lane_history")),
                    str(bundle.paths.get("digest")),
                ],
                pointers=[
                    "lane-history.jsonl#kind=lane_pause",
                    "return-digest.md#pause_count",
                ],
                expected=actual,
                actual=claimed,
                message=(
                    f"LC-003: digest claims {claimed} pause(s) but "
                    f"lane-history.jsonl shows {actual}."
                ),
            )
        ]
    return []


def check_lc004_per_pr_score(bundle: Bundle) -> list[Issue]:
    """LC-004 -- most-recent tier_b_run.bhs_official per pr matches the
    digest's per-PR score table."""
    history = bundle.lane_history
    digest = bundle.return_digest
    if history is None or digest is None:
        return []
    latest = _latest_tier_b_per_pr(history)
    digest_scores = _digest_per_pr_scores(digest)
    issues: list[Issue] = []
    for pr, claimed in digest_scores.items():
        ev = latest.get(pr)
        if ev is None:
            issues.append(
                _make_issue(
                    "LC-004",
                    artifacts=[
                        str(bundle.paths.get("lane_history")),
                        str(bundle.paths.get("digest")),
                    ],
                    pointers=[
                        f"return-digest.md#per_pr_scores.{pr}",
                    ],
                    expected="<some tier_b_run for pr>",
                    actual=None,
                    message=(
                        f"LC-004: digest lists per-PR score for PR-{pr} "
                        f"but lane-history.jsonl has no tier_b_run for "
                        f"that PR."
                    ),
                )
            )
            continue
        actual = ev.get("bhs_official")
        if actual != claimed:
            issues.append(
                _make_issue(
                    "LC-004",
                    artifacts=[
                        str(bundle.paths.get("lane_history")),
                        str(bundle.paths.get("digest")),
                    ],
                    pointers=[
                        f"lane-history.jsonl#tier_b_run.pr={pr}.bhs_official",
                        f"return-digest.md#per_pr_scores.{pr}",
                    ],
                    expected=actual,
                    actual=claimed,
                    message=(
                        f"LC-004: PR-{pr} digest score is {claimed} but "
                        f"most-recent tier_b_run.bhs_official is "
                        f"{actual}."
                    ),
                )
            )
    return issues


def check_lc005_heartbeat_progress(bundle: Bundle) -> list[Issue]:
    history = bundle.lane_history
    hb = bundle.heartbeat
    if history is None or hb is None:
        return []
    if not history:
        return []
    last = history[-1]
    pr = last.get("pr")
    kind = last.get("kind")
    marker = hb.get("progress_marker")
    if not isinstance(marker, str):
        return []
    expected_substrings = []
    if isinstance(pr, int):
        expected_substrings.append(f"pr-{pr}")
    if isinstance(kind, str):
        expected_substrings.append(kind)
    if expected_substrings and not all(
        s in marker for s in expected_substrings
    ):
        return [
            _make_issue(
                "LC-005",
                artifacts=[
                    str(bundle.paths.get("lane_history")),
                    str(bundle.paths.get("heartbeat")),
                ],
                pointers=[
                    "orchestrator.heartbeat.json#progress_marker",
                    "lane-history.jsonl[-1]",
                ],
                expected=" + ".join(expected_substrings),
                actual=marker,
                message=(
                    f"LC-005: heartbeat progress_marker {marker!r} does "
                    f"not reference latest lane-history event "
                    f"(kind={kind!r}, pr={pr!r})."
                ),
            )
        ]
    return []


def check_lc006_charter_punchlist_sha(bundle: Bundle) -> list[Issue]:
    if bundle.lane_charter is None or bundle.phase_punchlist is None:
        return []
    charter_sha = bundle.lane_charter.get("charter_sha")
    punchlist_sha = bundle.phase_punchlist.get("charter_sha")
    if (
        isinstance(charter_sha, str)
        and isinstance(punchlist_sha, str)
        and charter_sha != punchlist_sha
    ):
        return [
            _make_issue(
                "LC-006",
                artifacts=[
                    str(bundle.paths.get("charter")),
                    str(bundle.paths.get("punchlist")),
                ],
                pointers=[
                    "lane-charter.md#charter_sha",
                    "phase-punchlist.json#charter_sha",
                ],
                expected=charter_sha,
                actual=punchlist_sha,
                message=(
                    f"LC-006: phase-punchlist.json#charter_sha "
                    f"({punchlist_sha!r}) does not equal "
                    f"lane-charter.md#charter_sha ({charter_sha!r}). "
                    f"Punchlist was not regenerated after charter "
                    f"rewrite."
                ),
            )
        ]
    return []


def check_lc007_charter_done_has_event(bundle: Bundle) -> list[Issue]:
    """LC-007 -- every punchlist item with status 'done' in the charter
    has a matching lane-history event AFTER the charter's
    written_at_iso8601."""
    charter = bundle.lane_charter
    history = bundle.lane_history
    if charter is None or history is None:
        return []
    written = charter.get("written_at_iso8601")
    if not isinstance(written, str):
        return []
    phases = charter.get("phases")
    if not isinstance(phases, list):
        return []
    issues: list[Issue] = []
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        for item in phase.get("punchlist", []) or []:
            if not isinstance(item, dict):
                continue
            if item.get("status") != "done":
                continue
            item_id = item.get("id")
            text = item.get("text", "")
            # Look for a merge / pr_open event AFTER `written` whose
            # intent string mentions the item id OR text.
            found = False
            for ev in history:
                if ev.get("kind") not in ("merge", "pr_open"):
                    continue
                if ev.get("ts", "") < written:
                    continue
                intent = ev.get("intent", "") or ""
                if (
                    isinstance(item_id, str)
                    and item_id
                    and item_id in intent
                ):
                    found = True
                    break
                if isinstance(text, str) and text and text[:20] in intent:
                    found = True
                    break
            if not found:
                issues.append(
                    _make_issue(
                        "LC-007",
                        artifacts=[
                            str(bundle.paths.get("charter")),
                            str(bundle.paths.get("lane_history")),
                        ],
                        pointers=[
                            f"lane-charter.md#phases[].punchlist[id={item_id}]",
                        ],
                        expected="matching merge/pr_open event after charter written_at",
                        actual="no matching event",
                        message=(
                            f"LC-007: charter marks punchlist item "
                            f"{item_id!r} as done but no lane-history "
                            f"merge/pr_open event after "
                            f"{written} references it."
                        ),
                    )
                )
    return issues


def check_lc008_phase_boundary_alignment(
    bundle: Bundle,
) -> list[Issue]:
    history = bundle.lane_history
    if history is None:
        return []
    issues: list[Issue] = []
    align_dir = bundle.paths.get("phase_alignment_dir")
    for ev in history:
        if ev.get("kind") != "phase_boundary":
            continue
        path_claim = ev.get("phase_alignment_path", "")
        if not isinstance(path_claim, str) or not path_claim:
            continue
        # The path is repo-relative (out/phase-alignment-phaseN.md);
        # check existence relative to align_dir's parent if possible,
        # else relative to align_dir.
        if align_dir is None:
            continue
        # path_claim looks like "out/phase-alignment-phaseN.md"; the
        # actual file lives at align_dir / "phase-alignment-phaseN.md"
        # (align_dir is `out/`).
        candidate = Path(align_dir) / Path(path_claim).name
        if not candidate.exists():
            issues.append(
                _make_issue(
                    "LC-008",
                    artifacts=[
                        str(bundle.paths.get("lane_history")),
                        str(candidate),
                    ],
                    pointers=[
                        "lane-history.jsonl#phase_boundary.phase_alignment_path",
                    ],
                    expected=str(candidate),
                    actual="<missing file>",
                    message=(
                        f"LC-008: lane-history phase_boundary "
                        f"references {path_claim!r} but the file does "
                        f"not exist at {candidate}."
                    ),
                )
            )
    return issues


def check_lc009_phase_alignment_parses(
    bundle: Bundle,
) -> list[Issue]:
    """LC-009 -- every phase-alignment file referenced via
    phase_alignment_path exists AND parses (front-matter present + a
    `recommendation:` field from the closed set)."""
    history = bundle.lane_history
    if history is None:
        return []
    issues: list[Issue] = []
    legal_recs = {"continue", "pivot", "pause", "stop"}
    for phase_id, fm in bundle.phase_alignments.items():
        rec = fm.get("recommendation") if isinstance(fm, dict) else None
        if not isinstance(rec, str) or rec not in legal_recs:
            issues.append(
                _make_issue(
                    "LC-009",
                    artifacts=[
                        str(bundle.paths.get("phase_alignment_dir")),
                    ],
                    pointers=[
                        f"{phase_id}#recommendation",
                    ],
                    expected=f"one of {sorted(legal_recs)}",
                    actual=rec,
                    message=(
                        f"LC-009: phase-alignment file for {phase_id} "
                        f"has invalid recommendation {rec!r}."
                    ),
                )
            )
    return issues


def check_lc010_orphan_cd_open(bundle: Bundle) -> list[Issue]:
    cd = bundle.carried_debt
    history = bundle.lane_history
    if cd is None or history is None:
        return []
    issues: list[Issue] = []
    for rec in cd:
        if rec.get("kind") != "cd_open":
            continue
        ref = rec.get("lane_history_ref", "")
        if (
            not isinstance(ref, str)
            or not ref.startswith("lane-history.jsonl:")
        ):
            continue
        try:
            line_idx = int(ref.split(":", 1)[1])
        except (ValueError, IndexError):
            continue
        # 1-based index into the history list (ignoring blank lines --
        # _load_jsonl skips blanks; we treat the index as into the
        # records list directly).
        if line_idx < 1 or line_idx > len(history):
            issues.append(
                _make_issue(
                    "LC-010",
                    artifacts=[
                        str(bundle.paths.get("carried_debt")),
                        str(bundle.paths.get("lane_history")),
                    ],
                    pointers=[f"carried-debt.jsonl cd_id={rec.get('cd_id')}"],
                    expected=f"line in 1..{len(history)}",
                    actual=line_idx,
                    message=(
                        f"LC-010: cd_open {rec.get('cd_id')!r} "
                        f"lane_history_ref={ref!r} is out of range."
                    ),
                )
            )
            continue
        ev = history[line_idx - 1]
        if ev.get("kind") != "lane_pause":
            issues.append(
                _make_issue(
                    "LC-010",
                    artifacts=[
                        str(bundle.paths.get("carried_debt")),
                        str(bundle.paths.get("lane_history")),
                    ],
                    pointers=[f"carried-debt.jsonl cd_id={rec.get('cd_id')}"],
                    expected="lane_pause:merge_authority:post_merge_invariant_violated",
                    actual=ev.get("kind"),
                    message=(
                        f"LC-010: cd_open {rec.get('cd_id')!r} points at "
                        f"lane-history line {line_idx} which is "
                        f"kind={ev.get('kind')!r}, not lane_pause."
                    ),
                )
            )
            continue
        cause = ev.get("cause", "")
        if cause != "merge_authority:post_merge_invariant_violated":
            issues.append(
                _make_issue(
                    "LC-010",
                    artifacts=[
                        str(bundle.paths.get("carried_debt")),
                        str(bundle.paths.get("lane_history")),
                    ],
                    pointers=[f"carried-debt.jsonl cd_id={rec.get('cd_id')}"],
                    expected="merge_authority:post_merge_invariant_violated",
                    actual=cause,
                    message=(
                        f"LC-010: cd_open {rec.get('cd_id')!r} points at "
                        f"a lane_pause whose cause is {cause!r}, not "
                        f"the required post_merge_invariant_violated "
                        f"namespace."
                    ),
                )
            )
    return issues


def check_lc011_digest_cd_ids(bundle: Bundle) -> list[Issue]:
    history = bundle.lane_history
    cd = bundle.carried_debt
    if history is None or cd is None:
        return []
    open_ids = {
        rec.get("cd_id")
        for rec in cd
        if rec.get("kind") == "cd_open" and isinstance(rec.get("cd_id"), str)
    }
    issues: list[Issue] = []
    for ev in history:
        if ev.get("kind") != "digest_emit":
            continue
        ids = ev.get("carried_debt_ids_written", []) or []
        if not isinstance(ids, list):
            continue
        for cd_id in ids:
            if cd_id not in open_ids:
                issues.append(
                    _make_issue(
                        "LC-011",
                        artifacts=[
                            str(bundle.paths.get("lane_history")),
                            str(bundle.paths.get("carried_debt")),
                        ],
                        pointers=[
                            f"digest_emit.carried_debt_ids_written={cd_id}",
                        ],
                        expected=f"cd_open record for {cd_id}",
                        actual="<missing>",
                        message=(
                            f"LC-011: digest_emit lists cd_id "
                            f"{cd_id!r} but no cd_open record exists "
                            f"for it in carried-debt.jsonl."
                        ),
                    )
                )
    return issues


def check_lc012_merge_log_chain(bundle: Bundle) -> list[Issue]:
    """LC-012 -- charter merge-log chain integrity AND tail equals live
    lane-charter.md#charter_sha."""
    log = bundle.charter_merge_log
    charter = bundle.lane_charter
    if log is None:
        return []
    issues: list[Issue] = []
    head_per_lane: dict[str, str | None] = {}
    closed_per_lane: dict[str, bool] = {}
    indexed = sorted(
        enumerate(log), key=lambda p: (p[1].get("ts", ""), p[0])
    )
    for orig_idx, rec in indexed:
        lane_id = rec.get("lane_id")
        kind = rec.get("kind")
        if not isinstance(lane_id, str) or not isinstance(kind, str):
            continue
        if kind in ("charter_open", "lane_open_sidecar"):
            head_per_lane[lane_id] = rec.get("charter_sha")
            closed_per_lane[lane_id] = False
            continue
        if kind == "charter_close":
            head_per_lane[lane_id] = rec.get("final_charter_sha")
            closed_per_lane[lane_id] = True
            continue
        prior = rec.get("prior_charter_sha")
        new = rec.get("new_charter_sha")
        head = head_per_lane.get(lane_id)
        if (
            isinstance(prior, str)
            and isinstance(head, str)
            and prior != head
        ):
            issues.append(
                _make_issue(
                    "LC-012",
                    artifacts=[
                        str(bundle.paths.get("charter_merge_log")),
                    ],
                    pointers=[
                        f"charter-merge-log.jsonl[{orig_idx + 1}]",
                    ],
                    expected=head,
                    actual=prior,
                    message=(
                        f"LC-012: chain break at "
                        f"charter-merge-log.jsonl line "
                        f"{orig_idx + 1}: prior_charter_sha "
                        f"({prior!r}) does not equal current head "
                        f"({head!r}) for lane_id {lane_id!r}."
                    ),
                )
            )
        if isinstance(new, str):
            head_per_lane[lane_id] = new
    # Tail equals live charter sha.
    if charter is not None:
        live_sha = charter.get("charter_sha")
        live_lane = charter.get("lane_id")
        if (
            isinstance(live_sha, str)
            and isinstance(live_lane, str)
            and live_lane in head_per_lane
            and not closed_per_lane.get(live_lane, False)
            and head_per_lane[live_lane] != live_sha
        ):
            issues.append(
                _make_issue(
                    "LC-012",
                    artifacts=[
                        str(bundle.paths.get("charter")),
                        str(bundle.paths.get("charter_merge_log")),
                    ],
                    pointers=[
                        "lane-charter.md#charter_sha",
                        "charter-merge-log.jsonl<tail>",
                    ],
                    expected=head_per_lane[live_lane],
                    actual=live_sha,
                    message=(
                        f"LC-012: live lane-charter.md#charter_sha "
                        f"({live_sha!r}) does not equal merge-log "
                        f"chain tail ({head_per_lane[live_lane]!r}) "
                        f"for lane_id {live_lane!r}."
                    ),
                )
            )
    return issues


def check_lc013_sidecar_classification(
    bundle: Bundle,
) -> list[Issue]:
    """LC-013 -- every lane_open_sidecar row references a sidecar
    charter (when present) whose lane_classification starts with
    `sidecar_`."""
    log = bundle.charter_merge_log
    charter = bundle.lane_charter
    if log is None:
        return []
    issues: list[Issue] = []
    for rec in log:
        if rec.get("kind") != "lane_open_sidecar":
            continue
        sidecar_class = rec.get("sidecar_classification", "")
        if (
            not isinstance(sidecar_class, str)
            or not sidecar_class.startswith("sidecar_")
        ):
            issues.append(
                _make_issue(
                    "LC-013",
                    artifacts=[
                        str(bundle.paths.get("charter_merge_log")),
                    ],
                    pointers=[
                        "charter-merge-log.jsonl#lane_open_sidecar.sidecar_classification",
                    ],
                    expected="<sidecar_*>",
                    actual=sidecar_class,
                    message=(
                        f"LC-013: lane_open_sidecar row's "
                        f"sidecar_classification {sidecar_class!r} "
                        f"does not start with 'sidecar_'."
                    ),
                )
            )
            continue
        # If the sidecar's own charter is loaded AND its lane_id matches
        # this row's sidecar_lane_id, also confirm the charter agrees.
        if charter is not None:
            charter_lane_id = charter.get("lane_id")
            charter_class = charter.get("lane_classification", "parent")
            if (
                charter_lane_id == rec.get("sidecar_lane_id")
                and isinstance(charter_class, str)
                and not charter_class.startswith("sidecar_")
            ):
                issues.append(
                    _make_issue(
                        "LC-013",
                        artifacts=[
                            str(bundle.paths.get("charter_merge_log")),
                            str(bundle.paths.get("charter")),
                        ],
                        pointers=[
                            "lane-charter.md#lane_classification",
                        ],
                        expected="<sidecar_*>",
                        actual=charter_class,
                        message=(
                            f"LC-013: lane_open_sidecar row references "
                            f"sidecar_lane_id={rec.get('sidecar_lane_id')!r} "
                            f"but the matching charter declares "
                            f"lane_classification={charter_class!r} "
                            f"(must start with 'sidecar_')."
                        ),
                    )
                )
    return issues


def check_lc014_exhaustion_open_cd(bundle: Bundle) -> list[Issue]:
    cd = bundle.carried_debt
    packets = bundle.exhaustion_packets
    if cd is None or not packets:
        return []
    state_per_id = _cd_state_per_id(cd)
    issues: list[Issue] = []
    for packet in packets:
        cd_id = packet.get("cd_id")
        if not isinstance(cd_id, str):
            continue
        state = state_per_id.get(cd_id)
        if state not in ("blocked", "closed"):
            issues.append(
                _make_issue(
                    "LC-014",
                    artifacts=[
                        str(bundle.paths.get("exhaustion_packet_dir")),
                        str(bundle.paths.get("carried_debt")),
                    ],
                    pointers=[
                        f"exhaustion-packets/{packet.get('_packet_filename')}",
                    ],
                    expected="blocked or closed",
                    actual=state,
                    message=(
                        f"LC-014: exhaustion packet "
                        f"{packet.get('_packet_filename')!r} references "
                        f"cd_id={cd_id!r} whose forward-walked state "
                        f"is {state!r} (not blocked/closed)."
                    ),
                )
            )
    return issues


def _cd_state_per_id(cd: list[dict]) -> dict[str, str]:
    """Forward-walk carried-debt records, returning the final state
    per cd_id."""
    out: dict[str, str] = {}
    for rec in cd:
        cd_id = rec.get("cd_id")
        kind = rec.get("kind")
        if not isinstance(cd_id, str):
            continue
        if kind == "cd_open":
            out[cd_id] = "open"
        elif kind == "cd_close":
            out[cd_id] = "closed"
        elif kind == "cd_block":
            out[cd_id] = "blocked"
    return out


def check_lc015_exhaustion_evidence_absent(
    bundle: Bundle,
) -> list[Issue]:
    """LC-015 -- exhaustion packet's `evidence_absent: true` claim is
    contradicted if any tier_b_run for the same pr scored > 0."""
    history = bundle.lane_history
    packets = bundle.exhaustion_packets
    if history is None or not packets:
        return []
    issues: list[Issue] = []
    for packet in packets:
        if not packet.get("evidence_absent"):
            continue
        pr = packet.get("pr")
        if not isinstance(pr, int):
            continue
        for ev in history:
            if ev.get("kind") != "tier_b_run":
                continue
            if ev.get("pr") != pr:
                continue
            score = ev.get("bhs_tier_b")
            if isinstance(score, int) and score > 0:
                issues.append(
                    _make_issue(
                        "LC-015",
                        artifacts=[
                            str(bundle.paths.get("exhaustion_packet_dir")),
                            str(bundle.paths.get("lane_history")),
                        ],
                        pointers=[
                            f"exhaustion-packets/{packet.get('_packet_filename')}",
                            f"lane-history.jsonl#tier_b_run.pr={pr}",
                        ],
                        expected="evidence_absent: true contradicts tier_b > 0",
                        actual=f"bhs_tier_b={score}",
                        message=(
                            f"LC-015: exhaustion packet for PR-{pr} "
                            f"claims evidence_absent: true but a "
                            f"tier_b_run scored {score}. "
                            f"(translation-swarm bug class)."
                        ),
                    )
                )
                break
    return issues


def check_lc016_weakest_phase(bundle: Bundle) -> list[Issue]:
    history = bundle.lane_history
    digest = bundle.return_digest
    if history is None or digest is None:
        return []
    claimed = digest.get("weakest_phase")
    if not isinstance(claimed, str):
        return []
    # Compute lowest avg bhs_official per phase across tier_b_run events.
    # Phase is derived from pr_open events: walk history mapping pr ->
    # phase, then aggregate tier_b_run.bhs_official by phase.
    pr_to_phase: dict[int, str] = {}
    for ev in history:
        if ev.get("kind") == "pr_open":
            pr = ev.get("pr")
            phase = ev.get("phase")
            if isinstance(pr, int) and isinstance(phase, str):
                pr_to_phase[pr] = phase
    sums: dict[str, list[int]] = {}
    for ev in history:
        if ev.get("kind") != "tier_b_run":
            continue
        pr = ev.get("pr")
        score = ev.get("bhs_official")
        if not isinstance(pr, int) or not isinstance(score, int):
            continue
        phase = pr_to_phase.get(pr)
        if not phase:
            continue
        sums.setdefault(phase, []).append(score)
    if not sums:
        return []
    averages = {p: sum(s) / len(s) for p, s in sums.items()}
    computed = min(averages, key=lambda p: averages[p])
    if computed != claimed:
        return [
            _make_issue(
                "LC-016",
                artifacts=[
                    str(bundle.paths.get("digest")),
                    str(bundle.paths.get("lane_history")),
                ],
                pointers=[
                    "return-digest.md#weakest_phase",
                ],
                expected=computed,
                actual=claimed,
                message=(
                    f"LC-016: digest names weakest_phase={claimed!r}; "
                    f"computed weakest is {computed!r} "
                    f"(per-phase avg bhs_official: {averages})."
                ),
            )
        ]
    return []


# Closed set of evidence tiers that count as `local-dev` (cluster C1).
# A PR that merged with one of these tiers MUST NOT satisfy any
# acceptance criterion the lane-charter marks with a
# `production-tier:` prefix. The closed set mirrors the synthetic /
# local subset of v3.5/enums/evidence-tiers.txt.
_LOCAL_DEV_EVIDENCE_TIERS: frozenset[str] = frozenset({
    "local-dev-smoke",
    "synthetic-corpus",
    "generated-but-reviewed",
    "harness-shim",
    "positive-fixture",
    "unit-test-with-prod-import",
    "contract-test-in-process",
    "diagnostic-only",
})


def check_lc017_mock_vs_live(bundle: Bundle) -> list[Issue]:
    """LC-017 -- a merged PR with a local-dev evidence tier MUST NOT be
    cited as satisfying a production-tier acceptance row in the
    lane-charter. The validator looks for charter acceptance rows
    starting with the prose marker `production-tier:` (matches the
    cluster C1 `acceptance:` tag convention)."""
    history = bundle.lane_history
    charter = bundle.lane_charter
    if history is None or charter is None:
        return []
    phases = charter.get("phases")
    if not isinstance(phases, list):
        return []
    issues: list[Issue] = []
    # Build pr -> evidence_tier map for merged PRs.
    pr_tier: dict[int, str] = {}
    for ev in history:
        if ev.get("kind") != "merge":
            continue
        pr = ev.get("pr")
        tier = ev.get("evidence_tier")
        if isinstance(pr, int) and isinstance(tier, str):
            pr_tier[pr] = tier
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        phase_id = phase.get("id")
        acceptances = phase.get("acceptance", []) or []
        for accept_idx, accept in enumerate(acceptances):
            # Acceptance rows can be plain strings ("PR-1 satisfies ...")
            # OR YAML inline mappings ("- production-tier: PR-3 ..."
            # parses as {"production-tier": "PR-3 ..."}). Normalize both
            # into a probe string the substring + regex search can scan.
            if isinstance(accept, str):
                probe = accept
            elif isinstance(accept, dict):
                probe = " ".join(
                    f"{k}: {v}"
                    for k, v in accept.items()
                    if isinstance(v, str)
                )
            else:
                continue
            if "production-tier:" not in probe:
                continue
            # The row mentions a PR (e.g. "PR-3 satisfies ..."); look for
            # PR-N tokens.
            for m in re.finditer(r"PR-(\d+)", probe):
                pr = int(m.group(1))
                tier = pr_tier.get(pr)
                if tier and tier in _LOCAL_DEV_EVIDENCE_TIERS:
                    issues.append(
                        _make_issue(
                            "LC-017",
                            artifacts=[
                                str(bundle.paths.get("charter")),
                                str(bundle.paths.get("lane_history")),
                            ],
                            pointers=[
                                f"lane-charter.md#phases[id={phase_id}].acceptance[{accept_idx}]",
                            ],
                            expected="<production-tier evidence>",
                            actual=tier,
                            message=(
                                f"LC-017: charter acceptance row "
                                f"({probe!r}) cites PR-{pr} which "
                                f"merged with local-dev evidence_tier "
                                f"{tier!r}. Local-dev evidence cannot "
                                f"satisfy a production-tier criterion."
                            ),
                        )
                    )
    return issues


def check_lc018_resumption_sha(bundle: Bundle) -> list[Issue]:
    """LC-018 -- parent-resumption-packet#sidecar_charter_close_sha
    matches the charter-merge-log charter_close.final_charter_sha."""
    packet = bundle.parent_resumption_packet
    log = bundle.charter_merge_log
    if packet is None or log is None:
        return []
    claimed_sha = packet.get("sidecar_charter_close_sha")
    sidecar_lane_id = packet.get("sidecar_lane_id")
    if claimed_sha is None or not isinstance(sidecar_lane_id, str):
        return []
    # All-digit SHAs parse as int via the dependency-free YAML loader;
    # coerce to str so the comparison below is type-safe.
    claimed_sha = str(claimed_sha)
    actual_sha: str | None = None
    for rec in log:
        if (
            rec.get("kind") == "charter_close"
            and rec.get("lane_id") == sidecar_lane_id
        ):
            actual_sha = rec.get("final_charter_sha")
            break
    if actual_sha is not None and str(actual_sha) != claimed_sha:
        return [
            _make_issue(
                "LC-018",
                artifacts=[
                    str(bundle.paths.get("parent_resumption_packet")),
                    str(bundle.paths.get("charter_merge_log")),
                ],
                pointers=[
                    "parent-resumption-packet.md#sidecar_charter_close_sha",
                    "charter-merge-log.jsonl#charter_close.final_charter_sha",
                ],
                expected=actual_sha,
                actual=claimed_sha,
                message=(
                    f"LC-018: parent-resumption-packet "
                    f"sidecar_charter_close_sha ({claimed_sha!r}) does "
                    f"not match charter_close.final_charter_sha "
                    f"({actual_sha!r}) for sidecar lane_id "
                    f"{sidecar_lane_id!r}."
                ),
            )
        ]
    return []


def check_lc019_stale_tier_b(bundle: Bundle) -> list[Issue]:
    """LC-019 -- for every PR with a merge event, the latest tier_b_run
    ts must be after the latest tier_a_iter ts for the same pr."""
    history = bundle.lane_history
    if history is None:
        return []
    merged_prs = {
        ev.get("pr")
        for ev in history
        if ev.get("kind") == "merge" and isinstance(ev.get("pr"), int)
    }
    last_tier_a_per_pr: dict[int, str] = {}
    last_tier_b_per_pr: dict[int, str] = {}
    for ev in history:
        pr = ev.get("pr")
        ts = ev.get("ts", "")
        if not isinstance(pr, int):
            continue
        if ev.get("kind") == "tier_a_iter":
            if ts > last_tier_a_per_pr.get(pr, ""):
                last_tier_a_per_pr[pr] = ts
        elif ev.get("kind") == "tier_b_run":
            if ts > last_tier_b_per_pr.get(pr, ""):
                last_tier_b_per_pr[pr] = ts
    issues: list[Issue] = []
    for pr in merged_prs:
        ta = last_tier_a_per_pr.get(pr)
        tb = last_tier_b_per_pr.get(pr)
        if ta and tb and tb < ta:
            issues.append(
                _make_issue(
                    "LC-019",
                    artifacts=[
                        str(bundle.paths.get("lane_history")),
                    ],
                    pointers=[
                        f"lane-history.jsonl#tier_b_run.pr={pr}",
                        f"lane-history.jsonl#tier_a_iter.pr={pr}",
                    ],
                    expected=f"tier_b ts >= tier_a ts (pr={pr})",
                    actual=f"tier_b={tb} < tier_a={ta}",
                    message=(
                        f"LC-019: PR-{pr} merged but its latest "
                        f"tier_b_run ({tb}) precedes its latest "
                        f"tier_a_iter ({ta}). Stale Tier B."
                    ),
                )
            )
    return issues


def check_lc020_merge_sha(bundle: Bundle) -> list[Issue]:
    history = bundle.lane_history
    digest = bundle.return_digest
    if history is None or digest is None:
        return []
    digest_shas = _digest_per_pr_merge_sha(digest)
    if not digest_shas:
        return []
    history_shas = {
        ev.get("pr"): ev.get("merge_sha")
        for ev in history
        if ev.get("kind") == "merge"
    }
    issues: list[Issue] = []
    for pr, claimed_sha in digest_shas.items():
        actual_sha = history_shas.get(pr)
        if (
            isinstance(actual_sha, str)
            and isinstance(claimed_sha, str)
            and actual_sha != claimed_sha
        ):
            issues.append(
                _make_issue(
                    "LC-020",
                    artifacts=[
                        str(bundle.paths.get("digest")),
                        str(bundle.paths.get("lane_history")),
                    ],
                    pointers=[
                        f"return-digest.md#per_pr_merge_sha.{pr}",
                        f"lane-history.jsonl#merge.pr={pr}.merge_sha",
                    ],
                    expected=actual_sha,
                    actual=claimed_sha,
                    message=(
                        f"LC-020: PR-{pr} merge_sha disagreement: "
                        f"digest says {claimed_sha!r}, lane-history "
                        f"says {actual_sha!r}."
                    ),
                )
            )
    return issues


# ---------------------------------------------------------------------------
# Driver -- runs every check, aggregates issues, computes highest-
# priority exit code.
# ---------------------------------------------------------------------------


_CHECKS: tuple[tuple[str, Any], ...] = (
    ("LC-001", check_lc001_merge_count),
    ("LC-002", check_lc002_pivot_count),
    ("LC-003", check_lc003_pause_count),
    ("LC-004", check_lc004_per_pr_score),
    ("LC-005", check_lc005_heartbeat_progress),
    ("LC-006", check_lc006_charter_punchlist_sha),
    ("LC-007", check_lc007_charter_done_has_event),
    ("LC-008", check_lc008_phase_boundary_alignment),
    ("LC-009", check_lc009_phase_alignment_parses),
    ("LC-010", check_lc010_orphan_cd_open),
    ("LC-011", check_lc011_digest_cd_ids),
    ("LC-012", check_lc012_merge_log_chain),
    ("LC-013", check_lc013_sidecar_classification),
    ("LC-014", check_lc014_exhaustion_open_cd),
    ("LC-015", check_lc015_exhaustion_evidence_absent),
    ("LC-016", check_lc016_weakest_phase),
    ("LC-017", check_lc017_mock_vs_live),
    ("LC-018", check_lc018_resumption_sha),
    ("LC-019", check_lc019_stale_tier_b),
    ("LC-020", check_lc020_merge_sha),
)


def run_checks(bundle: Bundle) -> list[Issue]:
    out: list[Issue] = []
    for _code, fn in _CHECKS:
        out.extend(fn(bundle))
    return out


def choose_exit_code(
    issues: list[Issue], warn_only: frozenset[str] = frozenset()
) -> int:
    """Highest-priority-wins driver over Issue.exit_code_class.

    Empty issues (or all-warn_only) returns EXIT_CLEAN. Any
    unrecognised non-zero exit class (not in _EXIT_PRIORITY) is
    treated as EXIT_DRIFT (the lowest non-zero severity) so that a
    future LC-NNN check whose exit_code_class is added without also
    being added to _EXIT_PRIORITY can NEVER silently mask as a
    clean pass. Mirrors validate_score_trajectory.choose_exit_code
    + validate_charter_merge_log.choose_exit_code + the
    run_endurance_benchmark cousin under the
    operator-spec 5-class policy. (PR #55 HP-O remediation: closes
    the silent-EXIT_CLEAN fallthrough flagged by Agent A.)
    """
    if not issues:
        return EXIT_CLEAN
    codes_present: set[int] = set()
    for issue in issues:
        if issue.code in warn_only:
            continue
        codes_present.add(issue.exit_code_class)
    if not codes_present:
        return EXIT_CLEAN
    for code in _EXIT_PRIORITY:
        if code in codes_present:
            return code
    # Any non-zero exit_code_class not in _EXIT_PRIORITY -> treat as
    # DRIFT (least-severe non-zero). Never silently EXIT_CLEAN.
    return EXIT_DRIFT


def render_human_report(
    issues: list[Issue], exit_code: int
) -> str:
    lines = [
        "=" * 72,
        "BHS lane-consistency validator (issue #7)",
        "=" * 72,
        f"Exit code: {exit_code}",
        "",
    ]
    if not issues:
        lines.append("RESULT: PASS -- no cross-artifact drift detected.")
        return "\n".join(lines)
    by_code: dict[str, list[Issue]] = {}
    for issue in issues:
        by_code.setdefault(issue.code, []).append(issue)
    for code in sorted(by_code):
        grouped = by_code[code]
        lines.append(f"{code} ({len(grouped)}):")
        for issue in grouped:
            lines.append(f"  - {issue.message}")
            if issue.artifacts_involved:
                lines.append(
                    f"    artifacts: "
                    f"{', '.join(issue.artifacts_involved)}"
                )
            if issue.field_pointers:
                lines.append(
                    f"    pointers: {', '.join(issue.field_pointers)}"
                )
            if issue.expected is not None or issue.actual is not None:
                lines.append(
                    f"    expected={issue.expected!r} "
                    f"actual={issue.actual!r}"
                )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n")[0]
    )
    parser.add_argument(
        "--lane-history",
        required=True,
        help="Path to out/lane-history.jsonl (required).",
    )
    parser.add_argument(
        "--digest",
        required=True,
        help="Path to out/return-digest.md (required).",
    )
    parser.add_argument(
        "--charter",
        default=None,
        help="Path to out/lane-charter.md (optional).",
    )
    parser.add_argument(
        "--punchlist",
        default=None,
        help="Path to out/phase-punchlist.json (optional).",
    )
    parser.add_argument(
        "--heartbeat",
        default=None,
        help="Path to out/orchestrator.heartbeat.json (optional).",
    )
    parser.add_argument(
        "--carried-debt",
        default=None,
        help="Path to out/carried-debt.jsonl (optional).",
    )
    parser.add_argument(
        "--charter-merge-log",
        default=None,
        help="Path to out/charter-merge-log.jsonl (optional).",
    )
    parser.add_argument(
        "--phase-alignment-dir",
        default=None,
        help=(
            "Directory holding phase-alignment-phase<N>.md files "
            "(typically out/)."
        ),
    )
    parser.add_argument(
        "--exhaustion-packet-dir",
        default=None,
        help="Directory holding exhaustion-packet *.md files.",
    )
    parser.add_argument(
        "--parent-resumption-packet",
        default=None,
        help="Path to out/parent-resumption-packet.md (optional).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=True,
        help="(Default ON) every drift class is FAIL.",
    )
    parser.add_argument(
        "--warn-only",
        default="",
        help=(
            "Comma-separated list of LC-NNN codes to demote from FAIL to "
            "WARN (escape hatch for transient races; not for production)."
        ),
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help=(
            "Optional path; when given, write the full Issue list as "
            "JSONL for the issue-#41 endurance benchmark to consume."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the human-readable report on stderr.",
    )
    args = parser.parse_args(argv)

    warn_only = frozenset(
        c.strip() for c in args.warn_only.split(",") if c.strip()
    )

    issues: list[Issue] = []
    bundle = _load_bundle(args, issues)
    issues.extend(run_checks(bundle))

    exit_code = choose_exit_code(issues, warn_only=warn_only)

    if args.json_out:
        # Single JSON object payload: {"exit_code": N, "issues":
        # [...]}. The previous JSONL-per-issue shape required the
        # consumer to also know the exit code via process exit; this
        # shape is friendlier for #6 / #41 ingestion. `--json-out -`
        # writes to stdout; any other value is a path.
        payload = {
            "exit_code": exit_code,
            "issues": [issue.to_dict() for issue in issues],
        }
        rendered = json.dumps(payload, sort_keys=True) + "\n"
        if args.json_out == "-":
            sys.stdout.write(rendered)
        else:
            Path(args.json_out).write_text(rendered, encoding="utf-8")

    if not args.quiet:
        print(render_human_report(issues, exit_code), file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
