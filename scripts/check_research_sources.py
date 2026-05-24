#!/usr/bin/env python3
"""scripts/check_research_sources.py -- the research-source ledger gate
with asymmetric backing rule (issue #48 -- cluster G 3/3, the LAST
issue in cluster G).

Reads --rule <yaml> (the operator-supplied source-tier-backing rule at
source-tier-backing-rule.yaml or the reference at
v3.5/docs/conventions/brutal-honesty-kit/v3.5/tables/source-tier-backing-rule.yaml)
plus --body <md> (the PR body containing operator-declared sources +
claims in a fenced ```research-sources yaml block) and emits one
`source_record` row per declared source followed by a terminal
`run_summary` row to the JSONL file named by --report-out (default
v3.5/out/research-source-ledger.jsonl). Each row carries an 8-hex
CRC32 footer mirroring the bhs-trajectory.jsonl /
charter-merge-log.jsonl / endurance-run-report.jsonl /
workspace-hygiene-report.jsonl / external-policy-decisions-report.jsonl
contract, plus a `crc32_prev` link forming a hash chain (first row's
crc32_prev is `00000000`).

Per cluster G hard rule 2 the R75 validator rule is INACTIVE when
source-tier-backing-rule.yaml is absent at the repo root. This gate
ITSELF is callable in scan-only mode for ANY rule file the operator
points it at.

Asymmetric backing contract (R75c): every claim whose evidence_tier is
in the production set (production-like-sanitized,
operator-approved-release, human-curated-corpus -- the three top tiers
per v3.5/enums/evidence-tiers.txt) MUST be backed by at least one
source whose source_tier is in the production-allowed set
(authoritative-spec, vendor-doc, peer-reviewed). The validator's
_R75_PROD_TIER_BACKSTOP frozenset overrides whatever the YAML rule
says for these production tiers as a safety floor.

Operator commands:

    # Scan + emit ledger:
    python v3.5/scripts/check_research_sources.py \\
        --rule source-tier-backing-rule.yaml \\
        --body docs/proposals/<your-pr>.md \\
        --report-out v3.5/out/research-source-ledger.jsonl

    # Scan-only (prints; does not write a report):
    python v3.5/scripts/check_research_sources.py \\
        --rule source-tier-backing-rule.yaml \\
        --body docs/proposals/<your-pr>.md \\
        --report-out -

Exit codes (highest priority wins):
    0  evaluation completed; report written cleanly
    1  drift -- claims evaluated, but at least one production-tier
       claim was unbacked OR at least one claim referenced a
       dangling source_id
    2  schema invalid -- the rule YAML did not validate against
       the rule schema OR the PR-body block did not validate against
       research-sources-block.schema.json
    3  enum unknown -- the block referenced a source_tier or
       evidence_tier not in the closed enums
    4  chain break -- the gate's own emit-time chain self-check
       detected a CRC32 chain inconsistency (should never happen
       absent a coding bug)
    5  corruption -- the PR-body block could not be parsed at all
"""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_SCRIPT_DIR = Path(__file__).resolve().parent
_V35_ROOT = _SCRIPT_DIR.parent
_REPO_ROOT = _V35_ROOT
_DEFAULT_RULE = _REPO_ROOT / "source-tier-backing-rule.yaml"
_REFERENCE_RULE = (
    _V35_ROOT / "_internal" / "conventions" / "brutal-honesty-kit" / "v3.5"
    / "tables" / "source-tier-backing-rule.yaml"
)
_DEFAULT_REPORT_OUT = (
    _V35_ROOT / "out" / "research-source-ledger.jsonl"
)
_DEFAULT_LANE_ID = "lane-research-sources-v35"
_DEFAULT_AGENT_SESSION_ID = "01HQ9X7P5K3J2NQHJZ4Y6RESEARCH00"
_SCHEMA_DIR = (
    _V35_ROOT / "_internal" / "conventions" / "brutal-honesty-kit" / "v3.5"
    / "schemas"
)
_ENUM_DIR = (
    _V35_ROOT / "_internal" / "conventions" / "brutal-honesty-kit" / "v3.5"
    / "enums"
)


# Closed-set source-tiers. Mirror enums/research-source-tiers.txt
# verbatim; drift FAILs validate_v33_schema_drift.py via
# validate_research_source_tiers_parity. Tokens are lowercase kebab-case.
RESEARCH_SOURCE_TIERS: tuple[str, ...] = (
    "authoritative-spec",
    "vendor-doc",
    "peer-reviewed",
    "blog-post",
    "forum-thread",
    "unknown",
)


# Closed-set evidence-tiers. Mirror enums/evidence-tiers.txt verbatim
# for membership; the gate uses this for evidence_tier validation.
EVIDENCE_TIERS: tuple[str, ...] = (
    "paste-summary",
    "runtime-production-trace",
    "runtime-staging-trace",
    "runtime-local-deployed-stack",
    "local-dev-smoke",
    "unit-test-with-prod-import",
    "contract-test-in-process",
    "harness-shim",
    "harness-prod-stack",
    "positive-fixture",
    "endpoint-inventory",
    "model-card-only",
    "synthetic-corpus",
    "generated-but-reviewed",
    "public-benchmark",
    "curated-domain-fixture",
    "production-like-sanitized",
    "operator-approved-release",
    "human-curated-corpus",
    "diagnostic-only",
)


# The three production evidence tiers that trigger R75c's asymmetric
# backing rule.
PRODUCTION_EVIDENCE_TIERS: frozenset[str] = frozenset({
    "production-like-sanitized",
    "operator-approved-release",
    "human-curated-corpus",
})


# The validator-side safety backstop. Production-tier claims MUST be
# backed by at least one source whose source_tier is in this set,
# regardless of what the YAML rule says. Mirrors R74's
# _R74_COST_USD_CAP_BACKSTOP pattern.
#
# v3.7-final HP Lane A (H-1 / CV-1): the literal frozenset lives in
# scripts/_r75_constants.py so the gate and the validator import the
# SAME Python object. The drift-trap test
# `test_r75_prod_tier_backstop_constants_are_identical_across_modules`
# in v3.5/tests/test_check_research_sources.py pins all consumers to
# the same object via `is`-identity (not just value-equality), the
# same way v3.7 Lane 1+2 did for R74. The bare-name
# `_R75_PROD_TIER_BACKSTOP` continues to resolve from this module so
# existing imports / monkeypatches keep working.
from scripts._r75_constants import _R75_PROD_TIER_BACKSTOP  # noqa: E402


# Exit-code classes -- highest priority wins. Mirrors
# check_external_policy.py.
EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_SCHEMA = 2
EXIT_ENUM = 3
EXIT_CHAIN = 4
EXIT_CORRUPTION = 5
_EXIT_PRIORITY: tuple[int, ...] = (
    EXIT_CORRUPTION,
    EXIT_CHAIN,
    EXIT_ENUM,
    EXIT_SCHEMA,
    EXIT_DRIFT,
    EXIT_OK,
)


# ---------------------------------------------------------------------------
# CRC32 helpers (mirror check_external_policy / check_workspace_hygiene).
# ---------------------------------------------------------------------------


def _serialize_for_crc(record: dict) -> bytes:
    """Mirror check_external_policy._serialize_for_crc verbatim."""
    return json.dumps(
        {k: v for k, v in record.items() if k != "crc32"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_crc32(record: dict) -> str:
    """Mirror check_external_policy.compute_crc32 verbatim."""
    return (
        f"{binascii.crc32(_serialize_for_crc(record)) & 0xFFFFFFFF:08x}"
    )


# ---------------------------------------------------------------------------
# YAML parser (stdlib-only). Same in-house strict-subset parser as
# check_external_policy.py; copied verbatim so this gate has no
# cross-script import dependency. NOTE: post-fix version -- no
# `_coerce_numeric_strings` post-walk (would corrupt schema_version: "1");
# inline-flow `[]` / `{}` / `[a, b, c]` support included.
# ---------------------------------------------------------------------------


def _builtin_yaml(text: str) -> dict:
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    return _yaml_block(lines, 0, 0)[0]


def _yaml_indent(line: str) -> int:
    i = 0
    while i < len(line) and line[i] == " ":
        i += 1
    return i


_YAML_DOUBLE_QUOTE_ESCAPES = {
    "\\": "\\",
    '"': '"',
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "0": "\0",
}


def _yaml_unescape_double_quoted(body: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in _YAML_DOUBLE_QUOTE_ESCAPES:
                out.append(_YAML_DOUBLE_QUOTE_ESCAPES[nxt])
                i += 2
                continue
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _yaml_scalar(raw: str) -> Any:
    s = raw.strip()
    if not s:
        return None
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    if s in ("null", "~"):
        return None
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        return _yaml_unescape_double_quoted(s[1:-1])
    if s.startswith("'") and s.endswith("'") and len(s) >= 2:
        return s[1:-1].replace("''", "'")
    # Inline-empty flow forms (operators copy-paste these from the
    # reference rule template).
    if s == "[]":
        return []
    if s == "{}":
        return {}
    # Inline-flow lists: bracketed, comma-separated, scalar-only.
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_yaml_scalar(part) for part in _split_flow(inner)]
    if re.fullmatch(r"-?\d+", s):
        try:
            return int(s)
        except ValueError:
            return s
    if re.fullmatch(r"-?\d+\.\d+", s):
        try:
            return float(s)
        except ValueError:
            return s
    return s


def _split_flow(inner: str) -> list[str]:
    """Comma-split a YAML inline-flow body, honoring quoted scalars."""
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for ch in inner:
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            buf.append(ch)
            continue
        if ch == ",":
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts]


def _yaml_block(
    lines: list[str], start: int, indent: int
) -> tuple[Any, int]:
    i = start
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s or s.startswith("#"):
            i += 1
            continue
        if _yaml_indent(ln) != indent:
            return {}, start
        if s.startswith("- "):
            return _yaml_list(lines, i, indent)
        return _yaml_map(lines, i, indent)
    return {}, i


def _yaml_list(
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
        if _yaml_indent(ln) < indent:
            break
        if not s.startswith("- "):
            break
        rest = s[2:]
        if ":" in rest and not (
            rest.startswith('"') or rest.startswith("'")
        ):
            # Inline-mapping list item.
            item_map: dict = {}
            key, _, val = rest.partition(":")
            key = key.strip()
            val_stripped = val.strip()
            if val_stripped == "":
                child, next_i = _yaml_block(
                    lines, i + 1, indent + 4
                )
                if isinstance(child, dict):
                    item_map[key] = child
                else:
                    item_map[key] = None
                i = next_i
            else:
                item_map[key] = _yaml_scalar(val_stripped)
                i += 1
            # Continue collecting subsequent indented siblings.
            while i < len(lines):
                ln2 = lines[i]
                s2 = ln2.strip()
                if not s2 or s2.startswith("#"):
                    i += 1
                    continue
                cur2 = _yaml_indent(ln2)
                if cur2 < indent + 2:
                    break
                if cur2 != indent + 2:
                    i += 1
                    continue
                if s2.startswith("- "):
                    break
                if ":" not in s2:
                    i += 1
                    continue
                k2, _, v2 = s2.partition(":")
                k2 = k2.strip()
                v2_stripped = v2.strip()
                if v2_stripped == "":
                    child, next_i = _yaml_block(
                        lines, i + 1, indent + 4
                    )
                    item_map[k2] = child
                    i = next_i
                else:
                    item_map[k2] = _yaml_scalar(v2_stripped)
                    i += 1
            out.append(item_map)
        else:
            out.append(_yaml_scalar(rest))
            i += 1
    return out, i


def _yaml_map(
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
        cur = _yaml_indent(ln)
        if cur < indent:
            break
        if cur != indent:
            i += 1
            continue
        if ":" not in s:
            i += 1
            continue
        key, _, val = s.partition(":")
        key = key.strip()
        val_stripped = val.strip()
        if val_stripped == "":
            child, next_i = _yaml_block(lines, i + 1, indent + 2)
            out[key] = child
            i = next_i
        else:
            out[key] = _yaml_scalar(val_stripped)
            i += 1
    return out, i


def _parse_yaml(text: str) -> dict:
    # NOTE: No post-process numeric coercion -- `_yaml_scalar` already
    # types unquoted scalars correctly. Mirrors the post-fix version of
    # check_external_policy._parse_yaml (see Gate-1 regression caught
    # during #47 implementation).
    parsed: dict | None = None
    try:
        parsed = _builtin_yaml(text)
    except Exception:  # noqa: BLE001 -- defensive
        parsed = None
    if parsed is None:
        return {}
    return parsed


def _load_rule(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return _parse_yaml(text)


def _compute_rule_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_block_schema() -> dict | None:
    p = _SCHEMA_DIR / "research-sources-block.schema.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# PR-body research-sources block extraction.
# ---------------------------------------------------------------------------


_BODY_FENCE_RE = re.compile(
    r"```research-sources(?:\s*\n)(.*?)(?:\n```)",
    re.DOTALL,
)


def _extract_block(body_text: str) -> dict:
    """Pull the ```research-sources fenced YAML block out of the PR
    body and parse it. When multiple blocks are present the LAST one
    wins (operators MAY append a corrected block above the earlier
    draft). Returns a dict with `sources` and `claims` keys (each may
    be empty); returns an empty dict when no block is present.
    """
    last: dict = {}
    for m in _BODY_FENCE_RE.finditer(body_text):
        body = m.group(1)
        parsed = _parse_yaml(body)
        if isinstance(parsed, dict):
            last = parsed
    return last


# ---------------------------------------------------------------------------
# Schema validation (defensive -- jsonschema may be absent).
# ---------------------------------------------------------------------------


def _validate_block_against_schema(
    block: dict, schema: dict
) -> tuple[bool, str]:
    try:
        import jsonschema  # type: ignore

        jsonschema.validate(instance=block, schema=schema)
        return True, ""
    except ImportError:
        return _validate_block_minimal(block, schema)
    except Exception as exc:  # noqa: BLE001 -- bound to validator
        return False, f"{type(exc).__name__}: {exc}"


def _validate_block_minimal(
    block: dict, schema: dict
) -> tuple[bool, str]:
    required = schema.get("required", [])
    for key in required:
        if key not in block:
            return False, f"missing required top-level key: {key!r}"
    sources = block.get("sources", [])
    claims = block.get("claims", [])
    if not isinstance(sources, list):
        return False, "sources must be a list"
    if not isinstance(claims, list):
        return False, "claims must be a list"
    for s in sources:
        if not isinstance(s, dict):
            return False, "every source entry must be a mapping"
        for k in (
            "source_id", "source_tier", "source_url",
            "accessed_iso8601", "citation_summary",
        ):
            if k not in s:
                return False, (
                    f"source missing required key: {k!r}"
                )
    for c in claims:
        if not isinstance(c, dict):
            return False, "every claim entry must be a mapping"
        for k in (
            "claim_id", "evidence_tier", "claim_summary", "backed_by",
        ):
            if k not in c:
                return False, (
                    f"claim missing required key: {k!r}"
                )
        if not isinstance(c.get("backed_by"), list) or not c["backed_by"]:
            return False, (
                "claim.backed_by must be a non-empty list"
            )
    return True, ""


def _check_enums(block: dict) -> tuple[bool, str]:
    for s in block.get("sources", []) or []:
        tier = s.get("source_tier")
        if tier is not None and tier not in RESEARCH_SOURCE_TIERS:
            return False, (
                f"source.source_tier references unknown tier: {tier!r}"
            )
    for c in block.get("claims", []) or []:
        ev = c.get("evidence_tier")
        if ev is not None and ev not in EVIDENCE_TIERS:
            return False, (
                f"claim.evidence_tier references unknown tier: {ev!r}"
            )
    return True, ""


# ---------------------------------------------------------------------------
# Wallclock helpers.
# ---------------------------------------------------------------------------


def _wallclock_iso8601() -> str:
    epoch_ms = int(time.time() * 1000)
    secs, ms = divmod(epoch_ms, 1000)
    tm = time.gmtime(secs)
    return (
        f"{tm.tm_year:04d}-{tm.tm_mon:02d}-{tm.tm_mday:02d}T"
        f"{tm.tm_hour:02d}:{tm.tm_min:02d}:{tm.tm_sec:02d}.{ms:03d}Z"
    )


# ---------------------------------------------------------------------------
# JSONL emitter (mirror check_external_policy).
# ---------------------------------------------------------------------------


@dataclass
class _EmitState:
    prev_crc32: str = "00000000"
    rows_written: int = 0


def _emit_record(
    record: dict,
    out_path: Path | None,
    state: _EmitState,
) -> dict:
    record_with_chain = dict(record)
    record_with_chain["crc32_prev"] = state.prev_crc32
    record_with_chain["crc32"] = compute_crc32(record_with_chain)
    line = json.dumps(
        record_with_chain,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    state.prev_crc32 = record_with_chain["crc32"]
    state.rows_written += 1
    return record_with_chain


# ---------------------------------------------------------------------------
# Main run.
# ---------------------------------------------------------------------------


@dataclass
class _RunCounters:
    sources_total: int = 0
    sources_by_tier: dict = field(default_factory=dict)
    claims_total: int = 0
    claims_by_evidence_tier: dict = field(default_factory=dict)
    prod_tier_claims_total: int = 0
    prod_tier_claims_well_backed_total: int = 0
    prod_tier_claims_unbacked_total: int = 0
    dangling_source_id_total: int = 0


def _evaluate_claims(
    sources: list[dict], claims: list[dict]
) -> _RunCounters:
    counters = _RunCounters()
    for tier in RESEARCH_SOURCE_TIERS:
        counters.sources_by_tier[tier] = 0
    known_source_ids: dict[str, str] = {}
    for s in sources:
        sid = s.get("source_id")
        tier = s.get("source_tier")
        if not isinstance(sid, str) or not isinstance(tier, str):
            continue
        if tier not in RESEARCH_SOURCE_TIERS:
            continue
        known_source_ids[sid] = tier
        counters.sources_by_tier[tier] = (
            counters.sources_by_tier.get(tier, 0) + 1
        )
        counters.sources_total += 1

    for c in claims:
        ev = c.get("evidence_tier")
        backed = c.get("backed_by", []) or []
        if not isinstance(ev, str):
            continue
        counters.claims_total += 1
        counters.claims_by_evidence_tier[ev] = (
            counters.claims_by_evidence_tier.get(ev, 0) + 1
        )
        if not isinstance(backed, list):
            backed = []
        # Dangling source-id check: every named source_id MUST resolve.
        for sid in backed:
            if not isinstance(sid, str):
                continue
            if sid not in known_source_ids:
                counters.dangling_source_id_total += 1
        # Asymmetric production-tier backing check.
        if ev in PRODUCTION_EVIDENCE_TIERS:
            counters.prod_tier_claims_total += 1
            backing_tiers: set[str] = set()
            for sid in backed:
                if isinstance(sid, str) and sid in known_source_ids:
                    backing_tiers.add(known_source_ids[sid])
            # The validator's _R75_PROD_TIER_BACKSTOP frozenset is the
            # load-bearing safety floor regardless of YAML rule.
            if backing_tiers & _R75_PROD_TIER_BACKSTOP:
                counters.prod_tier_claims_well_backed_total += 1
            else:
                counters.prod_tier_claims_unbacked_total += 1
    return counters


def run_evaluation(
    *,
    block: dict,
    rule_path: Path,
    rule_yaml_sha256: str,
    report_out: Path | None,
    lane_id: str,
    agent_session_id: str,
) -> tuple[int, dict]:
    """Drive the ledger evaluation + emit. Returns (exit_code,
    run_summary_dict).
    """
    if report_out is not None and report_out.exists():
        report_out.unlink()

    state = _EmitState()
    run_started = _wallclock_iso8601()
    started_ms = int(time.time() * 1000)

    sources = block.get("sources", []) or []
    claims = block.get("claims", []) or []
    if not isinstance(sources, list):
        sources = []
    if not isinstance(claims, list):
        claims = []
    # Sort sources for deterministic emit (by source_id then tier).
    sorted_sources = sorted(
        [s for s in sources if isinstance(s, dict)],
        key=lambda s: (
            str(s.get("source_id", "")),
            str(s.get("source_tier", "")),
        ),
    )
    for s in sorted_sources:
        rec: dict = {
            "ts": run_started,
            "kind": "source_record",
            "lane_id": lane_id,
            "source_id": str(s.get("source_id", "")),
            "source_tier": str(s.get("source_tier", "")),
            "source_url": str(s.get("source_url", "")),
            "accessed_iso8601": str(
                s.get("accessed_iso8601", run_started)
            ),
            "citation_summary": str(
                s.get("citation_summary", "")
            ),
            "computed_by_agent_session_id": agent_session_id,
        }
        _emit_record(rec, report_out, state)

    counters = _evaluate_claims(sorted_sources, claims)

    finished_ms = int(time.time() * 1000)
    run_finished = _wallclock_iso8601()
    wallclock = max(0, finished_ms - started_ms)

    summary = {
        "ts": run_finished,
        "kind": "run_summary",
        "lane_id": lane_id,
        "sources_total": counters.sources_total,
        "sources_by_tier": dict(counters.sources_by_tier),
        "claims_total": counters.claims_total,
        "claims_by_evidence_tier": dict(
            counters.claims_by_evidence_tier
        ),
        "prod_tier_claims_total": counters.prod_tier_claims_total,
        "prod_tier_claims_well_backed_total":
            counters.prod_tier_claims_well_backed_total,
        "prod_tier_claims_unbacked_total":
            counters.prod_tier_claims_unbacked_total,
        "dangling_source_id_total":
            counters.dangling_source_id_total,
        "rule_yaml_sha256": rule_yaml_sha256,
        "rule_yaml_path": _to_posix_repo_rel(rule_path),
        "run_started_at_iso8601": run_started,
        "run_finished_at_iso8601": run_finished,
        "wallclock_ms": wallclock,
        "computed_by_agent_session_id": agent_session_id,
    }
    _emit_record(summary, report_out, state)

    # Exit code: drift if any production-tier claim is unbacked OR any
    # dangling source-id reference exists.
    if (
        counters.prod_tier_claims_unbacked_total > 0
        or counters.dangling_source_id_total > 0
    ):
        return EXIT_DRIFT, summary
    return EXIT_OK, summary


def _to_posix_repo_rel(path: Path) -> str:
    try:
        p = Path(path).resolve()
    except OSError:
        p = Path(path)
    repo_root = _V35_ROOT.parent
    try:
        rel = p.relative_to(repo_root)
        return rel.as_posix()
    except ValueError:
        return p.as_posix()


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Research-source ledger gate with asymmetric backing rule "
            "(issue #48 -- cluster G 3/3, the LAST issue in cluster G)."
        )
    )
    parser.add_argument(
        "--rule",
        type=Path,
        default=_DEFAULT_RULE,
        help=(
            "Path to the source-tier-backing-rule.yaml file "
            f"(default: {_DEFAULT_RULE})."
        ),
    )
    parser.add_argument(
        "--body",
        type=Path,
        default=None,
        help=(
            "Path to the PR body markdown file (containing one "
            "```research-sources fenced YAML block). When omitted, the "
            "gate evaluates against an empty sources+claims pair."
        ),
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=_DEFAULT_REPORT_OUT,
        help=(
            "Path to write the JSONL ledger "
            f"(default: {_DEFAULT_REPORT_OUT}). Use `-` for stdout-only."
        ),
    )
    parser.add_argument(
        "--lane-id",
        default=_DEFAULT_LANE_ID,
        help=(
            "lane_id stamp for every emitted row "
            f"(default: {_DEFAULT_LANE_ID})."
        ),
    )
    parser.add_argument(
        "--agent-session-id",
        default=_DEFAULT_AGENT_SESSION_ID,
        help=(
            "computed_by_agent_session_id stamp for every emitted "
            f"row (default: {_DEFAULT_AGENT_SESSION_ID})."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress informational stderr breadcrumbs.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help=(
            "Force rebuild of the canonical fixture catalog before "
            "running. Idempotent."
        ),
    )
    args = parser.parse_args(argv)

    # Rule presence -- per cluster G hard rule 2 the validator's R75 is
    # INACTIVE when source-tier-backing-rule.yaml is absent, but the
    # gate ITSELF is still callable; emit a soft drift exit so smoke
    # pipelines can reason about presence.
    if not args.rule.exists():
        if not args.quiet:
            sys.stderr.write(
                f"check_research_sources: rule file does not exist: "
                f"{args.rule}\n"
            )
        return EXIT_DRIFT

    rule = _load_rule(args.rule)
    if rule is None or not isinstance(rule, dict):
        sys.stderr.write(
            f"check_research_sources: rule file is empty or "
            f"unparseable: {args.rule}\n"
        )
        return EXIT_SCHEMA

    rule_sha256 = _compute_rule_sha256(args.rule)

    if args.rebuild:
        _rebuild_fixture_catalog()

    # Body block extraction.
    block: dict = {"sources": [], "claims": []}
    if args.body is not None:
        try:
            body_text = args.body.read_text(encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(
                f"check_research_sources: read failed for "
                f"--body {args.body}: {type(exc).__name__}: {exc}\n"
            )
            return EXIT_CORRUPTION
        try:
            extracted = _extract_block(body_text)
        except Exception as exc:  # noqa: BLE001 -- defensive
            sys.stderr.write(
                f"check_research_sources: PR-body block "
                f"unparseable: {type(exc).__name__}: {exc}\n"
            )
            return EXIT_CORRUPTION
        if extracted:
            block = {
                "sources": extracted.get("sources", []) or [],
                "claims": extracted.get("claims", []) or [],
            }

    # Block schema validation (defensive -- jsonschema may be absent).
    schema = _load_block_schema()
    if schema is not None:
        ok, err = _validate_block_against_schema(block, schema)
        if not ok:
            sys.stderr.write(
                f"check_research_sources: block schema validation "
                f"failed: {err}\n"
            )
            return EXIT_SCHEMA

    # Enum check.
    ok, err = _check_enums(block)
    if not ok:
        sys.stderr.write(
            f"check_research_sources: block enum check failed: {err}\n"
        )
        return EXIT_ENUM

    report_out: Path | None
    if str(args.report_out) == "-":
        report_out = None
    else:
        report_out = args.report_out

    exit_code, _ = run_evaluation(
        block=block,
        rule_path=args.rule,
        rule_yaml_sha256=rule_sha256,
        report_out=report_out,
        lane_id=args.lane_id,
        agent_session_id=args.agent_session_id,
    )

    if exit_code == EXIT_OK and report_out is not None:
        if not _self_check_chain(report_out):
            sys.stderr.write(
                f"check_research_sources: emit-time chain self-check "
                f"failed against {report_out}\n"
            )
            return EXIT_CHAIN

    return exit_code


def _rebuild_fixture_catalog() -> None:
    import importlib.util

    builder_path = (
        _V35_ROOT / "tests" / "fixtures" / "research-sources"
        / "_build_fixtures.py"
    )
    if not builder_path.exists():
        return
    spec = importlib.util.spec_from_file_location(
        "_research_sources_build_fixtures", builder_path
    )
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules["_research_sources_build_fixtures"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 -- defensive
        return
    if hasattr(module, "build_all_fixtures"):
        try:
            module.build_all_fixtures()
        except Exception:  # noqa: BLE001 -- defensive
            return


def _self_check_chain(report_path: Path) -> bool:
    if not report_path.exists():
        return False
    prev = "00000000"
    try:
        for raw in report_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("crc32_prev") != prev:
                return False
            recomputed = compute_crc32(row)
            if recomputed != row.get("crc32"):
                return False
            prev = row["crc32"]
    except (json.JSONDecodeError, OSError):
        return False
    return True


# ---------------------------------------------------------------------------
# Public API for tests + sister tooling.
# ---------------------------------------------------------------------------


def research_source_tier_names() -> list[str]:
    """Closed-set source-tiers in canonical order."""
    return list(RESEARCH_SOURCE_TIERS)


def production_evidence_tiers() -> list[str]:
    """Three production evidence tiers that trigger R75c."""
    return list(PRODUCTION_EVIDENCE_TIERS)


def production_allowed_source_tiers() -> list[str]:
    """Validator-side production-allowed source-tier set used by
    _R75_PROD_TIER_BACKSTOP. Sorted for deterministic test output.
    """
    return sorted(_R75_PROD_TIER_BACKSTOP)


if __name__ == "__main__":
    sys.exit(main())
