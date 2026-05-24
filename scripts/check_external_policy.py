#!/usr/bin/env python3
"""scripts/check_external_policy.py -- the external cost / network /
license policy gate (issue #47 -- cluster G 2/3).

Reads --policy <yaml> (the operator-supplied policy at
external-policy-gates.yaml or the reference at
v3.5/docs/conventions/brutal-honesty-kit/v3.5/tables/external-policy-gates.yaml)
plus --body <md> (the PR body containing operator-declared external
decisions in a fenced ```external-decisions yaml block) and emits one
`decision_result` row per declared decision followed by a terminal
`run_summary` row to the JSONL file named by --report-out (default
v3.5/out/external-policy-decisions-report.jsonl). Each row carries an
8-hex CRC32 footer mirroring the bhs-trajectory.jsonl /
charter-merge-log.jsonl / endurance-run-report.jsonl /
workspace-hygiene-report.jsonl contract, plus a `crc32_prev` link
forming a hash chain (first row's crc32_prev is `00000000`).

Per cluster G hard rule 2 the R74 validator rule is INACTIVE when
external-policy-gates.yaml is absent at the repo root. This gate ITSELF
is callable in scan-only mode for ANY policy file the operator points
it at.

Operator commands:

    # Scan + emit report:
    python v3.5/scripts/check_external_policy.py \\
        --policy external-policy-gates.yaml \\
        --body docs/proposals/<your-pr>.md \\
        --report-out v3.5/out/external-policy-decisions-report.jsonl

    # Scan-only (prints decisions; does not write a report):
    python v3.5/scripts/check_external_policy.py \\
        --policy external-policy-gates.yaml \\
        --body docs/proposals/<your-pr>.md \\
        --report-out -

Exit codes (highest priority wins):
    0  evaluation completed; report written cleanly
    1  drift -- decisions evaluated, but the underlying policy file was
       absent / unparseable as a soft no-op (informational marker)
    2  schema invalid -- the policy YAML did not validate against
       external-policy-gates.schema.json
    3  enum unknown -- the policy / decisions referenced a decision-kind /
       outcome / egress-mode not in the closed enums
    4  chain break -- the gate's own emit-time chain self-check
       detected a CRC32 chain inconsistency (should never happen
       absent a coding bug)
    5  corruption -- a malformed PR-body decision block could not be
       parsed at all
"""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_SCRIPT_DIR = Path(__file__).resolve().parent
_V35_ROOT = _SCRIPT_DIR.parent
_REPO_ROOT = _V35_ROOT
_DEFAULT_POLICY = _REPO_ROOT / "external-policy-gates.yaml"
_REFERENCE_POLICY = (
    _V35_ROOT / "_internal" / "conventions" / "brutal-honesty-kit" / "v3.5"
    / "tables" / "external-policy-gates.yaml"
)
_DEFAULT_REPORT_OUT = _V35_ROOT / "out" / "external-policy-decisions-report.jsonl"
_DEFAULT_LANE_ID = "lane-external-policy-v35"
_DEFAULT_AGENT_SESSION_ID = "01HQ9X7P5K3J2NQHJZ4Y6POLICY00"
_SCHEMA_DIR = (
    _V35_ROOT / "_internal" / "conventions" / "brutal-honesty-kit" / "v3.5"
    / "schemas"
)
_ENUM_DIR = (
    _V35_ROOT / "_internal" / "conventions" / "brutal-honesty-kit" / "v3.5"
    / "enums"
)

# Module constants -- match the rule-prefixed naming pattern used by
# _R73_HYGIENE_CAP. The validator backstop is independent of the policy
# YAML's `cost.per_run_usd_cap` so a misconfigured policy cannot
# accidentally raise the cap above what the validator considers safe.
from scripts._r74_constants import R74_COST_USD_CAP_BACKSTOP as _R74_COST_USD_CAP_BACKSTOP
_R74_COST_USD_CLAMP = 100000.0

# Closed-set decision kinds. Mirror enums/external-policy-decision-kinds.txt
# verbatim; drift FAILs validate_v33_schema_drift.py via
# validate_external_policy_decision_kinds_parity. Tokens are lowercase
# kebab-case.
DECISION_KINDS: tuple[str, ...] = (
    "paid-api-call",
    "free-public-download",
    "cloud-service-invocation",
    "dependency-license-accept",
    "model-license-accept",
    "dataset-license-accept",
    "network-egress-new-host",
    "operator-approved-exception",
)

# Closed-set decision outcomes.
DECISION_OUTCOMES: tuple[str, ...] = (
    "allow",
    "deny",
    "require-approval",
    "warn",
)

# Closed-set network egress modes.
EGRESS_MODES: tuple[str, ...] = (
    "denylist",
    "allowlist",
    "unrestricted",
)

# License-decision kinds that share the SPDX acceptlist/denylist code
# path. Order matters for deterministic emit.
_LICENSE_DECISION_KINDS: tuple[str, ...] = (
    "dependency-license-accept",
    "model-license-accept",
    "dataset-license-accept",
)

# Approval-required-by-policy mapping: decision-kind -> policy key whose
# truthiness mandates an `approval_ref` field on the decision.
_APPROVAL_REQUIRED_KEY: dict[str, tuple[str, str]] = {
    "paid-api-call": ("cost", "paid_api_requires_approval"),
    "model-license-accept": (
        "license", "model_license_requires_approval",
    ),
    "dataset-license-accept": (
        "license", "dataset_license_requires_approval",
    ),
}

# Exit-code classes -- highest priority wins. Mirrors
# check_workspace_hygiene.py.
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
# CRC32 helpers (mirror check_workspace_hygiene / charter-merge-log).
# ---------------------------------------------------------------------------


def _serialize_for_crc(record: dict) -> bytes:
    """Mirror check_workspace_hygiene._serialize_for_crc verbatim."""
    return json.dumps(
        {k: v for k, v in record.items() if k != "crc32"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_crc32(record: dict) -> str:
    """Mirror check_workspace_hygiene.compute_crc32 verbatim."""
    return (
        f"{binascii.crc32(_serialize_for_crc(record)) & 0xFFFFFFFF:08x}"
    )


# ---------------------------------------------------------------------------
# YAML parser (stdlib-only). Same in-house strict-subset parser as
# check_workspace_hygiene.py; copied verbatim so this gate has no
# cross-script import dependency.
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
    # reference policy template).
    if s == "[]":
        return []
    if s == "{}":
        return {}
    # Inline-flow lists: bracketed, comma-separated, scalar-only.
    # Sufficient for `denylist_hosts: ["a.com", "b.com"]` and similar
    # one-line list literals seen in the reference policy template.
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
            # Inline-mapping list item: "- key: value" optionally followed
            # by sibling indented "  key: value" lines.
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
    # types unquoted scalars correctly (`1` -> int, `1.5` -> float, `"1"`
    # -> string). A blanket post-walk that re-coerces every digit-shaped
    # string would corrupt explicitly-quoted values like
    # `schema_version: "1"` (the schema pins it to const "1"; coercion
    # would break policy schema validation -- see Gate-1 regression
    # caught during #47 implementation).
    parsed: dict | None = None
    try:
        parsed = _builtin_yaml(text)
    except Exception:  # noqa: BLE001 -- defensive
        parsed = None
    if parsed is None:
        return {}
    return parsed


def _load_policy(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return _parse_yaml(text)


def _compute_policy_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_policy_schema() -> dict | None:
    p = _SCHEMA_DIR / "external-policy-gates.schema.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# PR-body decision-block extraction.
# ---------------------------------------------------------------------------


_BODY_FENCE_RE = re.compile(
    r"```external-decisions(?:\s*\n)(.*?)(?:\n```)",
    re.DOTALL,
)


def _extract_decision_block(body_text: str) -> list[dict]:
    """Pull ```external-decisions yaml fenced blocks out of the PR body
    and parse them. Multiple blocks are concatenated. Returns the
    `decisions:` list (empty when no block is present).
    """
    decisions: list[dict] = []
    for m in _BODY_FENCE_RE.finditer(body_text):
        body = m.group(1)
        parsed = _parse_yaml(body)
        if not isinstance(parsed, dict):
            continue
        block_decisions = parsed.get("decisions", [])
        if isinstance(block_decisions, list):
            for d in block_decisions:
                if isinstance(d, dict):
                    decisions.append(d)
    return decisions


# ---------------------------------------------------------------------------
# Decision evaluation.
# ---------------------------------------------------------------------------


@dataclass
class Decision:
    decision_kind: str
    decision_outcome: str
    match_value: str
    rationale: str
    estimated_cost_usd: float | None = None
    approval_ref: str | None = None
    spdx_id: str | None = None
    egress_mode: str | None = None


def _host_matches(host: str, patterns: list[str]) -> bool:
    """Match a hostname against a list of glob-shaped patterns. Lowercase
    only; a leading `*.` matches any subdomain.
    """
    h = host.lower()
    for pat in patterns:
        p = pat.lower()
        if p == h:
            return True
        if p.startswith("*."):
            suffix = p[1:]  # `.example.com`
            if h.endswith(suffix):
                return True
            if h == suffix[1:]:  # bare apex matches `*.example.com`
                return True
    return False


def _exception_for(
    decision: dict, exceptions: list[dict]
) -> dict | None:
    kind = decision.get("decision_kind")
    match = str(decision.get("match_value", ""))
    for exc in exceptions:
        if exc.get("decision_kind") != kind:
            continue
        if exc.get("match_value") == match:
            return exc
    return None


def _evaluate_one(
    decision: dict, policy: dict
) -> Decision:
    """Apply the policy to a single declared decision. Returns a
    Decision dataclass with the evaluated outcome + rationale. Unknown
    decision_kind values surface as outcome=`deny` with a clear
    rationale (R74c FAILs).
    """
    kind = decision.get("decision_kind")
    raw_match = decision.get("match_value", "")
    match_value = str(raw_match) if raw_match is not None else ""
    raw_cost = decision.get("estimated_cost_usd")
    estimated_cost: float | None
    if raw_cost is None:
        estimated_cost = None
    else:
        try:
            estimated_cost = float(raw_cost)
            estimated_cost = max(0.0, min(estimated_cost, _R74_COST_USD_CLAMP))
        except (TypeError, ValueError):
            estimated_cost = None
    approval_ref_raw = decision.get("approval_ref")
    approval_ref: str | None
    if approval_ref_raw is None or approval_ref_raw == "":
        approval_ref = None
    else:
        approval_ref = str(approval_ref_raw)
    raw_spdx = decision.get("spdx_id")
    spdx_id: str | None
    if raw_spdx is None or raw_spdx == "":
        spdx_id = None
    else:
        spdx_id = str(raw_spdx)

    if kind not in DECISION_KINDS:
        return Decision(
            decision_kind="operator-approved-exception"
            if kind == "operator-approved-exception" else (
                kind if kind in DECISION_KINDS else "paid-api-call"
            ),
            decision_outcome="deny",
            match_value=match_value,
            rationale=(
                f"unknown decision_kind {kind!r}; closed enum is "
                f"external-policy-decision-kinds.txt"
            ),
            estimated_cost_usd=estimated_cost,
            approval_ref=approval_ref,
            spdx_id=spdx_id,
        )

    # Operator exception SHORT-CIRCUITS (always allow, audit row written
    # by caller).
    exceptions = policy.get("exceptions", []) or []
    exc = _exception_for(decision, exceptions)
    if exc is not None:
        return Decision(
            decision_kind=kind,
            decision_outcome="allow",
            match_value=match_value,
            rationale=(
                f"matched operator exception "
                f"approval_ref={exc.get('approval_ref')!r}"
            ),
            estimated_cost_usd=estimated_cost,
            approval_ref=str(
                exc.get("approval_ref")
            ) if exc.get("approval_ref") is not None else approval_ref,
            spdx_id=spdx_id,
        )

    # License decisions.
    if kind in _LICENSE_DECISION_KINDS:
        license_block = policy.get("license", {}) or {}
        denylist = license_block.get("denylist_spdx", []) or []
        acceptlist = license_block.get("acceptlist_spdx", []) or []
        spdx = spdx_id or match_value
        if spdx in denylist:
            return Decision(
                decision_kind=kind,
                decision_outcome="deny",
                match_value=match_value,
                rationale=(
                    f"spdx {spdx!r} matches denylist entry"
                ),
                estimated_cost_usd=estimated_cost,
                approval_ref=approval_ref,
                spdx_id=spdx_id,
            )
        # Approval-required gate.
        approval_section, approval_key = (
            _APPROVAL_REQUIRED_KEY.get(kind, (None, None))
        )
        if approval_section is not None:
            sec = policy.get(approval_section, {}) or {}
            if sec.get(approval_key) and approval_ref is None:
                return Decision(
                    decision_kind=kind,
                    decision_outcome="require-approval",
                    match_value=match_value,
                    rationale=(
                        f"policy.{approval_section}."
                        f"{approval_key}=true and no approval_ref"
                    ),
                    estimated_cost_usd=estimated_cost,
                    approval_ref=approval_ref,
                    spdx_id=spdx_id,
                )
        if kind == "dependency-license-accept" and spdx in acceptlist:
            return Decision(
                decision_kind=kind,
                decision_outcome="allow",
                match_value=match_value,
                rationale=(
                    f"spdx {spdx!r} matches acceptlist entry"
                ),
                estimated_cost_usd=estimated_cost,
                approval_ref=approval_ref,
                spdx_id=spdx_id,
            )
        # Not on either list AND no approval gate trip -> warn.
        return Decision(
            decision_kind=kind,
            decision_outcome="warn",
            match_value=match_value,
            rationale=(
                f"spdx {spdx!r} not on acceptlist or denylist"
            ),
            estimated_cost_usd=estimated_cost,
            approval_ref=approval_ref,
            spdx_id=spdx_id,
        )

    # Network-egress decision.
    if kind == "network-egress-new-host":
        net = policy.get("network", {}) or {}
        mode = net.get("egress_mode", "denylist")
        host = match_value.lower()
        denylist = net.get("denylist_hosts", []) or []
        allowlist = net.get("allowlist_hosts", []) or []
        warn_on_new = bool(net.get("warn_on_new_host", True))
        if mode == "allowlist":
            if _host_matches(host, allowlist):
                return Decision(
                    decision_kind=kind,
                    decision_outcome="allow",
                    match_value=match_value,
                    rationale=(
                        f"host {host!r} matches allowlist entry "
                        f"under egress_mode=allowlist"
                    ),
                    estimated_cost_usd=estimated_cost,
                    approval_ref=approval_ref,
                    egress_mode=mode,
                )
            return Decision(
                decision_kind=kind,
                decision_outcome="deny",
                match_value=match_value,
                rationale=(
                    f"host {host!r} not on allowlist under "
                    f"egress_mode=allowlist"
                ),
                estimated_cost_usd=estimated_cost,
                approval_ref=approval_ref,
                egress_mode=mode,
            )
        if mode == "denylist":
            if _host_matches(host, denylist):
                return Decision(
                    decision_kind=kind,
                    decision_outcome="deny",
                    match_value=match_value,
                    rationale=(
                        f"host {host!r} matches denylist entry "
                        f"under egress_mode=denylist"
                    ),
                    estimated_cost_usd=estimated_cost,
                    approval_ref=approval_ref,
                    egress_mode=mode,
                )
            outcome = "warn" if warn_on_new else "allow"
            return Decision(
                decision_kind=kind,
                decision_outcome=outcome,
                match_value=match_value,
                rationale=(
                    f"host {host!r} not on denylist under "
                    f"egress_mode=denylist (warn_on_new_host="
                    f"{warn_on_new})"
                ),
                estimated_cost_usd=estimated_cost,
                approval_ref=approval_ref,
                egress_mode=mode,
            )
        # unrestricted
        return Decision(
            decision_kind=kind,
            decision_outcome="warn" if warn_on_new else "allow",
            match_value=match_value,
            rationale=(
                f"host {host!r} under egress_mode=unrestricted"
            ),
            estimated_cost_usd=estimated_cost,
            approval_ref=approval_ref,
            egress_mode=mode,
        )

    # paid-api-call / cloud-service-invocation: cost + approval gates.
    if kind == "paid-api-call":
        approval_section, approval_key = (
            _APPROVAL_REQUIRED_KEY["paid-api-call"]
        )
        sec = policy.get(approval_section, {}) or {}
        if sec.get(approval_key) and approval_ref is None:
            return Decision(
                decision_kind=kind,
                decision_outcome="require-approval",
                match_value=match_value,
                rationale=(
                    f"policy.{approval_section}.{approval_key}=true "
                    f"and no approval_ref"
                ),
                estimated_cost_usd=estimated_cost,
                approval_ref=approval_ref,
            )
        return Decision(
            decision_kind=kind,
            decision_outcome="allow",
            match_value=match_value,
            rationale=(
                f"approval present (or not required) for paid-api-call"
            ),
            estimated_cost_usd=estimated_cost,
            approval_ref=approval_ref,
        )

    if kind == "cloud-service-invocation":
        return Decision(
            decision_kind=kind,
            decision_outcome="warn",
            match_value=match_value,
            rationale=(
                f"cloud-service-invocation logged informationally"
            ),
            estimated_cost_usd=estimated_cost,
            approval_ref=approval_ref,
        )

    if kind == "free-public-download":
        return Decision(
            decision_kind=kind,
            decision_outcome="allow",
            match_value=match_value,
            rationale=f"free-public-download {match_value!r}",
            estimated_cost_usd=estimated_cost,
            approval_ref=approval_ref,
        )

    if kind == "operator-approved-exception":
        # Stand-alone audit-trail row (operator declared an exception
        # outside the policy.exceptions list).
        return Decision(
            decision_kind=kind,
            decision_outcome="allow" if approval_ref else "require-approval",
            match_value=match_value,
            rationale=(
                f"operator-approved-exception with approval_ref="
                f"{approval_ref!r}"
            ),
            estimated_cost_usd=estimated_cost,
            approval_ref=approval_ref,
        )

    # Defensive fallthrough -- closed enum guarantees this cannot fire.
    return Decision(
        decision_kind=kind,
        decision_outcome="deny",
        match_value=match_value,
        rationale=f"no rule matched decision_kind {kind!r}",
        estimated_cost_usd=estimated_cost,
        approval_ref=approval_ref,
        spdx_id=spdx_id,
    )


def _sort_decisions(decisions: list[Decision]) -> list[Decision]:
    return sorted(
        decisions,
        key=lambda d: (
            d.decision_kind,
            d.match_value,
            d.decision_outcome,
            d.rationale[:80],
        ),
    )


# ---------------------------------------------------------------------------
# JSONL emitter (mirror check_workspace_hygiene).
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
# Schema validation (defensive -- jsonschema may be absent).
# ---------------------------------------------------------------------------


def _validate_policy_against_schema(
    policy: dict, schema: dict
) -> tuple[bool, str]:
    try:
        import jsonschema  # type: ignore

        jsonschema.validate(instance=policy, schema=schema)
        return True, ""
    except ImportError:
        return _validate_policy_minimal(policy, schema)
    except Exception as exc:  # noqa: BLE001 -- bound to validator
        return False, f"{type(exc).__name__}: {exc}"


def _validate_policy_minimal(
    policy: dict, schema: dict
) -> tuple[bool, str]:
    required = schema.get("required", [])
    for key in required:
        if key not in policy:
            return False, f"missing required top-level key: {key!r}"
    if policy.get("schema_version") != "1":
        return False, (
            f"schema_version must be \"1\"; got "
            f"{policy.get('schema_version')!r}"
        )
    network = policy.get("network", {})
    if network.get("egress_mode") not in EGRESS_MODES:
        return False, (
            f"network.egress_mode must be one of {list(EGRESS_MODES)}; "
            f"got {network.get('egress_mode')!r}"
        )
    cost = policy.get("cost", {})
    for k in ("per_run_usd_cap", "paid_api_requires_approval",
              "free_quota_warn_pct"):
        if k not in cost:
            return False, f"cost missing required key: {k!r}"
    license_block = policy.get("license", {})
    for k in ("acceptlist_spdx", "denylist_spdx",
              "model_license_requires_approval",
              "dataset_license_requires_approval"):
        if k not in license_block:
            return False, f"license missing required key: {k!r}"
    return True, ""


def _check_enums(policy: dict) -> tuple[bool, str]:
    network = policy.get("network", {}) or {}
    mode = network.get("egress_mode")
    if mode is not None and mode not in EGRESS_MODES:
        return False, (
            f"network.egress_mode references unknown mode: {mode!r}"
        )
    for exc in policy.get("exceptions", []) or []:
        kind = exc.get("decision_kind")
        if kind is not None and kind not in DECISION_KINDS:
            return False, (
                f"exceptions[*].decision_kind references unknown kind: "
                f"{kind!r}"
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
# Main run.
# ---------------------------------------------------------------------------


def run_evaluation(
    *,
    policy: dict,
    policy_path: Path,
    policy_sha256: str,
    body_decisions: list[dict],
    report_out: Path | None,
    lane_id: str,
    agent_session_id: str,
    cost_usd_cap: float,
) -> tuple[int, dict]:
    """Drive the policy evaluation + emit. Returns (exit_code,
    run_summary_dict).
    """
    if report_out is not None and report_out.exists():
        report_out.unlink()

    state = _EmitState()
    run_started = _wallclock_iso8601()
    started_ms = int(time.time() * 1000)

    decisions: list[Decision] = []
    for raw in body_decisions:
        decisions.append(_evaluate_one(raw, policy))

    decisions = _sort_decisions(decisions)

    for d in decisions:
        rec: dict = {
            "ts": run_started,
            "kind": "decision_result",
            "lane_id": lane_id,
            "decision_kind": d.decision_kind,
            "decision_outcome": d.decision_outcome,
            "match_value": d.match_value,
            "rationale": d.rationale,
            "computed_by_agent_session_id": agent_session_id,
        }
        if d.estimated_cost_usd is not None:
            rec["estimated_cost_usd"] = d.estimated_cost_usd
        if d.approval_ref is not None:
            rec["approval_ref"] = d.approval_ref
        if d.spdx_id is not None:
            rec["spdx_id"] = d.spdx_id
        if d.egress_mode is not None:
            rec["egress_mode"] = d.egress_mode
        _emit_record(rec, report_out, state)

    decisions_by_kind = {k: 0 for k in DECISION_KINDS}
    decisions_by_outcome = {o: 0 for o in DECISION_OUTCOMES}
    cost_total = 0.0
    deny_total = 0
    require_approval_total = 0
    for d in decisions:
        decisions_by_kind[d.decision_kind] = (
            decisions_by_kind.get(d.decision_kind, 0) + 1
        )
        decisions_by_outcome[d.decision_outcome] = (
            decisions_by_outcome.get(d.decision_outcome, 0) + 1
        )
        if d.estimated_cost_usd is not None:
            cost_total += d.estimated_cost_usd
        if d.decision_outcome == "deny":
            deny_total += 1
        elif d.decision_outcome == "require-approval":
            require_approval_total += 1
    cost_total = max(0.0, min(cost_total, _R74_COST_USD_CLAMP))

    finished_ms = int(time.time() * 1000)
    run_finished = _wallclock_iso8601()
    wallclock = max(0, finished_ms - started_ms)

    summary = {
        "ts": run_finished,
        "kind": "run_summary",
        "lane_id": lane_id,
        "decisions_total": len(decisions),
        "decisions_by_kind": decisions_by_kind,
        "decisions_by_outcome": decisions_by_outcome,
        "cost_usd_total": cost_total,
        "cost_usd_cap": cost_usd_cap,
        "cost_cap_breached": cost_total > cost_usd_cap,
        "deny_total": deny_total,
        "require_approval_total": require_approval_total,
        "policy_sha256": policy_sha256,
        "policy_path": _to_posix_repo_rel(policy_path),
        "run_started_at_iso8601": run_started,
        "run_finished_at_iso8601": run_finished,
        "wallclock_ms": wallclock,
        "computed_by_agent_session_id": agent_session_id,
    }
    _emit_record(summary, report_out, state)
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
            "External cost / network / license policy gate (issue "
            "#47 -- cluster G 2/3)."
        )
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=_DEFAULT_POLICY,
        help=(
            "Path to the external-policy-gates.yaml file "
            f"(default: {_DEFAULT_POLICY})."
        ),
    )
    parser.add_argument(
        "--body",
        type=Path,
        default=None,
        help=(
            "Path to the PR body markdown file (containing one or more "
            "```external-decisions fenced YAML blocks). When omitted, the "
            "gate evaluates against an empty decision list."
        ),
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=_DEFAULT_REPORT_OUT,
        help=(
            "Path to write the JSONL run report "
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

    # Policy presence -- per cluster G hard rule 2 the validator's R74
    # is INACTIVE when external-policy-gates.yaml is absent, but the
    # gate ITSELF is still callable; emit a soft drift exit so smoke
    # pipelines can reason about presence.
    if not args.policy.exists():
        if not args.quiet:
            sys.stderr.write(
                f"check_external_policy: policy file does not exist: "
                f"{args.policy}\n"
            )
        return EXIT_DRIFT

    policy = _load_policy(args.policy)
    if policy is None or not isinstance(policy, dict):
        sys.stderr.write(
            f"check_external_policy: policy file is empty or "
            f"unparseable: {args.policy}\n"
        )
        return EXIT_SCHEMA

    schema = _load_policy_schema()
    if schema is not None:
        ok, err = _validate_policy_against_schema(policy, schema)
        if not ok:
            sys.stderr.write(
                f"check_external_policy: policy schema validation "
                f"failed: {err}\n"
            )
            return EXIT_SCHEMA

    ok, err = _check_enums(policy)
    if not ok:
        sys.stderr.write(
            f"check_external_policy: policy enum check failed: {err}\n"
        )
        return EXIT_ENUM

    policy_sha256 = _compute_policy_sha256(args.policy)

    if args.rebuild:
        _rebuild_fixture_catalog()

    # Body decisions.
    body_decisions: list[dict] = []
    if args.body is not None:
        try:
            body_text = args.body.read_text(encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(
                f"check_external_policy: read failed for "
                f"--body {args.body}: {type(exc).__name__}: {exc}\n"
            )
            return EXIT_CORRUPTION
        try:
            body_decisions = _extract_decision_block(body_text)
        except Exception as exc:  # noqa: BLE001 -- defensive
            sys.stderr.write(
                f"check_external_policy: PR-body decision block "
                f"unparseable: {type(exc).__name__}: {exc}\n"
            )
            return EXIT_CORRUPTION

    cost_block = policy.get("cost", {}) or {}
    raw_cap = cost_block.get("per_run_usd_cap", 0.0)
    try:
        cost_usd_cap = float(raw_cap)
    except (TypeError, ValueError):
        cost_usd_cap = 0.0

    report_out: Path | None
    if str(args.report_out) == "-":
        report_out = None
    else:
        report_out = args.report_out

    exit_code, _ = run_evaluation(
        policy=policy,
        policy_path=args.policy,
        policy_sha256=policy_sha256,
        body_decisions=body_decisions,
        report_out=report_out,
        lane_id=args.lane_id,
        agent_session_id=args.agent_session_id,
        cost_usd_cap=cost_usd_cap,
    )

    if exit_code == EXIT_OK and report_out is not None:
        if not _self_check_chain(report_out):
            sys.stderr.write(
                f"check_external_policy: emit-time chain self-check "
                f"failed against {report_out}\n"
            )
            return EXIT_CHAIN

    return exit_code


def _rebuild_fixture_catalog() -> None:
    import importlib.util

    builder_path = (
        _V35_ROOT / "tests" / "fixtures" / "external-policy"
        / "_build_fixtures.py"
    )
    if not builder_path.exists():
        return
    spec = importlib.util.spec_from_file_location(
        "_external_policy_build_fixtures", builder_path
    )
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules["_external_policy_build_fixtures"] = module
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


def decision_kind_names() -> list[str]:
    """Closed-set decision kinds in canonical order."""
    return list(DECISION_KINDS)


def decision_outcome_names() -> list[str]:
    """Closed-set decision outcomes in canonical order."""
    return list(DECISION_OUTCOMES)


def egress_mode_names() -> list[str]:
    """Closed-set network egress modes in canonical order."""
    return list(EGRESS_MODES)


if __name__ == "__main__":
    sys.exit(main())
