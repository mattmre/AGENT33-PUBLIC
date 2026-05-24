#!/usr/bin/env python3
"""scripts/detect_platform_profile.py -- v3.5 platform-profile detector.

Issue #10 (cluster D, 1/4). Emits a `PlatformProfile` record (as defined
by docs/conventions/brutal-honesty-kit/v3.5/schemas/model-adapter-contract.schema.json)
for the current runtime, based on environment fingerprints + repo
markers. Designed to be called from R40 (validate_pr_brutal_honesty.py)
and from cluster-D #9/#33/#52 rules; the v3.5 shipping contract is
detect-only -- the real adapter wiring is v3.6 / OCR_LOCAL.

CLI:

    python scripts/detect_platform_profile.py                # human report
    python scripts/detect_platform_profile.py --json         # JSON to stdout
    python scripts/detect_platform_profile.py --json --root <dir>

Exit code:
    0 always (a degraded-mode profile is still a valid record;
      callers gate on `degraded_mode` / `model_stack_present`).
    2 on CLI tooling error (unknown flag, etc.).

The detector NEVER silently returns `model_stack_present: false` when
detection fails -- detection failure (PermissionError, FileNotFoundError,
chmod-locked file) sets `degraded_mode: true` + `degraded_reason:
"<reason>"` and emits `model_stack_present: false` only when ALL three
detection rules cleanly returned False. This is the L13 close called out
in the issue plan §3.

Detection rules for `model_stack_present == True` (any one suffices):

  1. `<root>/models/` directory exists AND is non-empty.
  2. `<root>/.gitignore` contains a non-comment line matching
     ^(?:.*/)?(models?|model_cache|out/translation_models)/?$
     AND that path exists on disk relative to root.
  3. An environment variable matching ^MODEL_[A-Z0-9_]+$ is set to a
     non-empty value (e.g. MODEL_PATH, MODEL_CACHE_DIR).

Platform identity inference (sets `platform_name`):

  * `CLAUDE_*` env vars OR `.claude/` dir       -> claude
  * `CODEX_*` env vars                          -> codex
  * `GEMINI_*` env vars                         -> gemini
  * `COPILOT_*` env vars                        -> copilot
  * `OPENCODE_*` env vars                       -> opencode
  * none of the above                           -> unknown
                                                  (degraded_mode=true,
                                                  degraded_reason set)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional


# ----- Closed-set capability defaults ----------------------------------
# When the detector cannot prove a capability one way or the other, it
# emits `unknown` (NOT `available` -- that would be the L13 close).
_DEFAULT_CAPABILITIES: Dict[str, str] = {
    "shell_access": "unknown",
    "filesystem_access": "unknown",
    "network_access": "unknown",
    "scm_access": "unknown",
    "browser_automation": "unknown",
    "spawn_fresh_agent": "unknown",
    "different_model_family": "unknown",
    "schedule_long_haul": "unknown",
    "approval_escalation": "unknown",
    "artifact_persistence": "unknown",
}


# ----- model_stack regex (issue plan §3 + adaptation #9) ---------------
_MODEL_STACK_GITIGNORE_RE = re.compile(
    r"^(?:.*/)?(models?|model_cache|out/translation_models)/?$"
)
_MODEL_ENV_RE = re.compile(r"^MODEL_[A-Z0-9_]+$")


# ----- Platform inference rules ----------------------------------------
# (env-var prefix, marker-dir, platform_name) tuples in priority order.
_PLATFORM_PROBES = (
    ("CLAUDE_", ".claude", "claude"),
    ("CODEX_", ".codex", "codex"),
    ("GEMINI_", ".gemini", "gemini"),
    ("COPILOT_", ".copilot", "copilot"),
    ("OPENCODE_", ".opencode", "opencode"),
)


def _detect_model_stack(
    root: Path,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Return ``{"present": bool, "reason": Optional[str], "degraded": bool,
    "degraded_reason": Optional[str]}``. Never silently returns False on
    a detection failure -- chmod-locked .gitignore / unreadable models/
    sets degraded=True with the cause."""

    env = dict(os.environ if env is None else env)

    # Rule 3: MODEL_* env var -- cheapest, no I/O.
    for var_name, var_val in env.items():
        if not var_val:
            continue
        if _MODEL_ENV_RE.match(var_name):
            return {
                "present": True,
                "reason": f"MODEL_* env var set: {var_name}",
                "degraded": False,
                "degraded_reason": None,
            }

    # Rule 1: <root>/models/ exists AND is non-empty.
    models_dir = root / "models"
    try:
        if models_dir.is_dir():
            try:
                contents = list(models_dir.iterdir())
                if contents:
                    return {
                        "present": True,
                        "reason": (
                            f"models/ directory present with "
                            f"{len(contents)} entries"
                        ),
                        "degraded": False,
                        "degraded_reason": None,
                    }
            except PermissionError as exc:
                return {
                    "present": False,
                    "reason": None,
                    "degraded": True,
                    "degraded_reason": (
                        f"PermissionError listing models/: {exc}"
                    ),
                }
    except OSError as exc:
        return {
            "present": False,
            "reason": None,
            "degraded": True,
            "degraded_reason": f"OSError stat'ing models/: {exc}",
        }

    # Rule 2: .gitignore line matching the model-cache pattern AND that
    # path exists on disk relative to root.
    gitignore = root / ".gitignore"
    if gitignore.exists():
        try:
            text = gitignore.read_text(encoding="utf-8", errors="replace")
        except PermissionError as exc:
            return {
                "present": False,
                "reason": None,
                "degraded": True,
                "degraded_reason": (
                    f"PermissionError reading .gitignore: {exc}"
                ),
            }
        except OSError as exc:
            return {
                "present": False,
                "reason": None,
                "degraded": True,
                "degraded_reason": f"OSError reading .gitignore: {exc}",
            }
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip leading `!` (gitignore negation) and leading `/`.
            cleaned = line.lstrip("!").lstrip("/")
            if not _MODEL_STACK_GITIGNORE_RE.match(cleaned):
                continue
            candidate = root / cleaned.rstrip("/")
            try:
                if candidate.exists():
                    return {
                        "present": True,
                        "reason": (
                            f".gitignore'd model cache present: "
                            f"{cleaned}"
                        ),
                        "degraded": False,
                        "degraded_reason": None,
                    }
            except OSError as exc:
                return {
                    "present": False,
                    "reason": None,
                    "degraded": True,
                    "degraded_reason": (
                        f"OSError stat'ing .gitignore'd path "
                        f"{cleaned!r}: {exc}"
                    ),
                }

    # No signal in any of the three rules -- clean negative.
    return {
        "present": False,
        "reason": None,
        "degraded": False,
        "degraded_reason": None,
    }


def _detect_platform_name(
    root: Path,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Return ``{"name": PlatformName, "degraded": bool,
    "degraded_reason": Optional[str], "matched_signal": Optional[str]}``."""

    env = dict(os.environ if env is None else env)

    for prefix, marker, name in _PLATFORM_PROBES:
        # env-var probe.
        for var_name in env:
            if var_name.startswith(prefix):
                return {
                    "name": name,
                    "degraded": False,
                    "degraded_reason": None,
                    "matched_signal": f"env var {var_name}",
                }
        # marker-dir probe.
        marker_path = root / marker
        try:
            if marker_path.is_dir():
                return {
                    "name": name,
                    "degraded": False,
                    "degraded_reason": None,
                    "matched_signal": f"marker dir {marker}",
                }
        except OSError:
            # Don't fail the detector on a single marker stat failure;
            # try the next probe and let the final fallthrough explain.
            continue

    return {
        "name": "unknown",
        "degraded": True,
        "degraded_reason": (
            "platform_name unknown; no env or marker file recognized"
        ),
        "matched_signal": None,
    }


def detect_platform_profile(
    root: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build a PlatformProfile record. Returns a plain dict matching the
    JSON Schema (see model-adapter-contract.schema.json) -- caller is
    responsible for validating it against the schema if strict gating is
    needed (the schema is the contract; this function is the producer).

    NEVER returns ``model_stack_present=False`` silently when detection
    failed. Detection failure sets degraded_mode=True + a non-empty
    degraded_reason. The L13 self-check from the plan.
    """

    if root is None:
        root = Path.cwd()
    root = Path(root)

    # Capability defaults: every flag is `unknown` until something
    # definite is known. Inferring `available` would itself be L13.
    capabilities = dict(_DEFAULT_CAPABILITIES)

    platform = _detect_platform_name(root, env=env)
    stack = _detect_model_stack(root, env=env)

    degraded = bool(platform["degraded"]) or bool(stack["degraded"])
    degraded_reason: Optional[str] = None
    if degraded:
        # Concatenate non-null causes; never emit empty string when
        # degraded_mode=True (the schema's allOf clause would reject it).
        bits = []
        if platform["degraded_reason"]:
            bits.append(str(platform["degraded_reason"]))
        if stack["degraded_reason"]:
            bits.append(str(stack["degraded_reason"]))
        if not bits:
            # Defensive: should never trigger because we set degraded=True
            # only when at least one bit is truthy, but keeps the schema
            # contract intact even on logic regression.
            bits.append("degraded_mode set without an explicit reason")
        degraded_reason = "; ".join(bits)

    profile: Dict[str, Any] = {
        "platform_name": platform["name"],
        "platform_version": None,
        "model_family": None,
        "capabilities": capabilities,
        "model_stack_present": bool(stack["present"]),
        "degraded_mode": degraded,
        "degraded_reason": degraded_reason,
    }
    return profile


def _human_report(profile: Dict[str, Any]) -> str:
    lines = [
        "PlatformProfile (v3.5 model-adapter contract)",
        "=" * 47,
        f"  platform_name:        {profile.get('platform_name')!r}",
        f"  platform_version:     {profile.get('platform_version')!r}",
        f"  model_family:         {profile.get('model_family')!r}",
        f"  model_stack_present:  {profile.get('model_stack_present')}",
        f"  degraded_mode:        {profile.get('degraded_mode')}",
        f"  degraded_reason:      {profile.get('degraded_reason')!r}",
        "  capabilities:",
    ]
    for cap, state in sorted((profile.get("capabilities") or {}).items()):
        lines.append(f"    {cap:<24} = {state}")
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Emit a PlatformProfile JSON record for the current runtime."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the PlatformProfile as JSON (one object) to stdout.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help=(
            "Repo root for marker-file detection. Defaults to the "
            "current working directory."
        ),
    )
    args = parser.parse_args(argv)

    profile = detect_platform_profile(root=args.root)
    if args.json:
        sys.stdout.write(json.dumps(profile, sort_keys=True) + "\n")
    else:
        sys.stdout.write(_human_report(profile))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
