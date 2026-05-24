#!/usr/bin/env python3
"""Operator-side resource side-effect probe (issue #35).

Snapshots the local environment for the side-effect surfaces that R45
catalogues (Docker containers, kind/k3d/minikube clusters, bound ports,
GPU memory reservations, model caches, env-var keys) and emits one
JSON-Lines record per observed resource. The output schema mirrors the
RESOURCE_LEDGER format (schemas/resource-side-effects.schema.json) so
the same validator (R45e) can structurally diff a declared ledger
against the observed snapshot.

Usage:
    python scripts/probe_side_effects.py [--out PATH]
    python scripts/probe_side_effects.py --diff BEFORE_PATH

Modes:
    snapshot (default)  -- write one JSONL line per currently-observed
                           resource to --out (default: stdout). Exit 0.
    --diff BEFORE_PATH  -- read a previous snapshot from BEFORE_PATH,
                           take a fresh snapshot now, and write only
                           the (type, name) tuples that appear in NOW
                           but not in BEFORE -- the resources spawned
                           between the two snapshots. Exit 0.

This script is a HARNESS (it observes, never mutates). Its own
RESOURCE_LEDGER in any PR shipping it is `none` and its
HARNESS_MUTATES is `no`.

Stdlib only -- no third-party deps. Subprocesses to docker / kind /
k3d / minikube / lsof / netstat / nvidia-smi when present; gracefully
degrades when a tool is missing (the corresponding type just emits
zero records). Always exits 0 -- the validator (not this probe) is
the gate. A non-zero exit would conflate "the probe could not run"
with "side effects were detected", which is a category error.

The probe reads broadly available environment surfaces only -- no
private files, no credentials, no per-user state beyond what the
operator has already chosen to expose to their shell.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Closed-set type tokens (mirrors enums/resource-side-effect-types.txt).
# Kept in code as constants because the probe is operator-side and may
# ship without the enum directory present (e.g. in a CI image with only
# scripts/). The validator (R45d) is the authoritative closed-set check;
# this probe is best-effort emission.
# ---------------------------------------------------------------------------
TYPE_DOCKER_CONTAINER = "docker-container"
TYPE_KIND_CLUSTER = "kind-cluster"
TYPE_K3D_CLUSTER = "k3d-cluster"
TYPE_MINIKUBE_CLUSTER = "minikube-cluster"
TYPE_BOUND_PORT = "bound-port"
TYPE_BACKGROUND_PROCESS = "background-process"
TYPE_MODEL_CACHE = "model-cache"
TYPE_ENV_VAR_CHANGE = "env-var-change"
TYPE_GPU_MEMORY_RESERVATION = "gpu-memory-reservation"


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _have(cmd: str) -> bool:
    """Return True iff `cmd` is on PATH."""
    return shutil.which(cmd) is not None


def _run(cmd: list[str], timeout: int = 5) -> tuple[int, str, str]:
    """Run `cmd`, return (rc, stdout, stderr). Never raises."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except (subprocess.TimeoutExpired, OSError):
        return -1, "", ""


def _record(
    rtype: str,
    name: str,
    purpose: str = "observed by probe_side_effects.py",
    create_cmd: str = "n/a (observed, not created by this harness)",
    cleanup_cmd: str = "n/a (operator decides)",
    cleanup_status: str = "left-behind",
    cleanup_safety: str = "unknown",
    requires_operator_approval: str = "no",
) -> dict:
    """Build one observed-side-effect record. Defaults reflect probe semantics:
    the probe never created the resource (`n/a` create_cmd), classifies
    every observation as `left-behind` from the probe's point of view
    (the resource is alive at observation time), and marks safety as
    `unknown` because the probe cannot guess the operator's intent.
    """
    return {
        "type": rtype,
        "name": name,
        "purpose": purpose,
        "create_cmd": create_cmd,
        "cleanup_cmd": cleanup_cmd,
        "cleanup_status": cleanup_status,
        "cleanup_safety": cleanup_safety,
        "requires_operator_approval": requires_operator_approval,
        "observed_at_iso": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Per-surface probes. Each yields zero or more dict records. Each
# probe is independent -- one subprocess failing must not skip the
# others. All probes wrap their tool calls in `_run()` (which never
# raises) so a missing binary or a timeout simply yields no records.
# ---------------------------------------------------------------------------


def probe_docker_containers() -> Iterable[dict]:
    if not _have("docker"):
        return
    rc, out, _ = _run(["docker", "ps", "--format", "{{.Names}}"])
    if rc != 0:
        return
    for name in out.splitlines():
        n = name.strip()
        if n:
            yield _record(TYPE_DOCKER_CONTAINER, n)


def probe_kind_clusters() -> Iterable[dict]:
    if not _have("kind"):
        return
    rc, out, _ = _run(["kind", "get", "clusters"])
    if rc != 0:
        return
    for line in out.splitlines():
        n = line.strip()
        # kind prints "No kind clusters found." on stderr+stdout combos
        # depending on version -- skip the human message.
        if n and not n.lower().startswith("no kind"):
            yield _record(TYPE_KIND_CLUSTER, n)


def probe_k3d_clusters() -> Iterable[dict]:
    if not _have("k3d"):
        return
    rc, out, _ = _run(["k3d", "cluster", "list", "--no-headers"])
    if rc != 0:
        return
    for line in out.splitlines():
        parts = line.strip().split()
        if parts:
            yield _record(TYPE_K3D_CLUSTER, parts[0])


def probe_minikube_clusters() -> Iterable[dict]:
    if not _have("minikube"):
        return
    rc, out, _ = _run(["minikube", "profile", "list", "-o", "json"])
    if rc != 0:
        return
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        return
    profiles = []
    if isinstance(payload, dict):
        profiles = payload.get("valid", []) or []
    if isinstance(profiles, list):
        for p in profiles:
            if isinstance(p, dict) and p.get("Name"):
                yield _record(TYPE_MINIKUBE_CLUSTER, str(p["Name"]))


def probe_bound_ports() -> Iterable[dict]:
    """Best-effort listening port snapshot.

    Linux/macOS: `lsof -i -P -n` (filters to LISTEN).
    Windows: `netstat -ano` (filters to LISTENING).
    Both gracefully degrade when neither tool exists.
    """
    if sys.platform.startswith("win"):
        if not _have("netstat"):
            return
        rc, out, _ = _run(["netstat", "-ano"], timeout=10)
        if rc != 0:
            return
        seen: set[str] = set()
        for line in out.splitlines():
            up = line.upper()
            if "LISTENING" not in up:
                continue
            parts = line.split()
            # Typical columns: Proto LocalAddr ForeignAddr State PID
            if len(parts) < 4:
                continue
            local = parts[1]
            # Extract trailing port after last `:` (handles IPv6 [::]:80).
            colon = local.rfind(":")
            if colon == -1:
                continue
            port = local[colon + 1:]
            if port.isdigit() and port not in seen:
                seen.add(port)
                yield _record(TYPE_BOUND_PORT, port)
    else:
        if not _have("lsof"):
            return
        rc, out, _ = _run(["lsof", "-i", "-P", "-n"], timeout=10)
        if rc != 0:
            return
        seen_ports: set[str] = set()
        for line in out.splitlines():
            if "LISTEN" not in line:
                continue
            # Typical columns: COMMAND PID USER ... NAME ...trailing-state
            # NAME is e.g. "*:8080" or "127.0.0.1:5432" or "[::1]:5432" and
            # is followed by "(LISTEN)". Scan from the right for the first
            # token that LOOKS like an address:port (ends with `:NNN`).
            parts = line.split()
            if not parts:
                continue
            name_field = ""
            for token in reversed(parts):
                if re.search(r":\d+$", token):
                    name_field = token
                    break
            if not name_field:
                continue
            colon = name_field.rfind(":")
            if colon == -1:
                continue
            port = name_field[colon + 1:].split("(")[0]
            if port.isdigit() and port not in seen_ports:
                seen_ports.add(port)
                yield _record(TYPE_BOUND_PORT, port)


def probe_gpu_memory() -> Iterable[dict]:
    if not _have("nvidia-smi"):
        return
    rc, out, _ = _run(
        [
            "nvidia-smi",
            "--query-gpu=index,memory.used",
            "--format=csv,noheader,nounits",
        ]
    )
    if rc != 0:
        return
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 2:
            continue
        idx, mem = parts
        try:
            mem_mib = int(mem)
        except ValueError:
            continue
        if mem_mib > 0:
            yield _record(
                TYPE_GPU_MEMORY_RESERVATION,
                f"gpu{idx}:{mem_mib}MiB",
            )


# Common model-cache root locations. We list the IMMEDIATE children of
# each (model identifiers) rather than the entire tree -- the diff is
# meant to surface "a new model showed up between the two snapshots",
# not enumerate every file in the cache.
_MODEL_CACHE_ROOTS: tuple[Path, ...] = (
    Path.home() / ".cache" / "huggingface",
    Path.home() / ".ollama" / "models",
    Path.home() / ".cache" / "torch" / "hub",
)


def probe_model_caches() -> Iterable[dict]:
    for root in _MODEL_CACHE_ROOTS:
        if not root.exists() or not root.is_dir():
            continue
        try:
            children = sorted(p.name for p in root.iterdir())
        except OSError:
            continue
        for child in children:
            yield _record(
                TYPE_MODEL_CACHE,
                f"{root}/{child}",
                purpose=(
                    "observed in model-cache root by "
                    "probe_side_effects.py"
                ),
            )


# Env vars worth watching. Restricted on purpose -- the probe MUST NOT
# enumerate the operator's full env (privacy + token leakage). The
# observed records report ONLY which keys are SET, never the values.
_ENV_KEYS_OF_INTEREST: tuple[str, ...] = (
    "DOCKER_HOST",
    "KUBECONFIG",
    "HUGGINGFACE_HUB_TOKEN",
    "HF_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AWS_PROFILE",
    "AWS_DEFAULT_REGION",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "CUDA_VISIBLE_DEVICES",
)


def probe_env_var_changes() -> Iterable[dict]:
    for key in _ENV_KEYS_OF_INTEREST:
        if key in os.environ:
            yield _record(
                TYPE_ENV_VAR_CHANGE,
                key,
                purpose=(
                    "env var SET (value not recorded for privacy) "
                    "observed by probe_side_effects.py"
                ),
            )


def snapshot() -> list[dict]:
    """Run every probe in sequence; return a flat list of records.

    The probe table is a list of (registered-name, attribute-name) pairs.
    We resolve each callable by attribute lookup on this module so that
    test-time `monkeypatch.setattr(probe, "probe_X", ...)` is honored, and
    we report the registered name (not the callable's __name__) on failure
    so the breadcrumb stays stable even when a test swaps in an anonymous
    lambda.
    """
    records: list[dict] = []
    # Use this module's own globals dict so callers can monkeypatch
    # individual probe functions via `setattr(module, "probe_X", fn)` and
    # have their replacements honored here. We resolve by name on every
    # iteration so swap-after-import is supported.
    module_globals = globals()
    probes = (
        "probe_docker_containers",
        "probe_kind_clusters",
        "probe_k3d_clusters",
        "probe_minikube_clusters",
        "probe_bound_ports",
        "probe_gpu_memory",
        "probe_model_caches",
        "probe_env_var_changes",
    )
    for registered_name in probes:
        probe_fn = module_globals[registered_name]
        try:
            records.extend(probe_fn())
        except Exception as exc:  # pragma: no cover - defensive
            sys.stderr.write(
                f"probe_side_effects: {registered_name} raised "
                f"{type(exc).__name__}: {exc} (continuing)\n"
            )
    return records


def _key(rec: dict) -> tuple[str, str]:
    return (
        str(rec.get("type", "")).strip(),
        str(rec.get("name", "")).strip(),
    )


def diff_against(before_path: Path) -> list[dict]:
    """Return records observed NOW but not present in BEFORE_PATH."""
    before_keys: set[tuple[str, str]] = set()
    try:
        text = before_path.read_text(encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(
            f"probe_side_effects: cannot read --diff baseline "
            f"{before_path}: {exc}\n"
        )
        text = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            before_keys.add(_key(rec))
    now = snapshot()
    return [r for r in now if _key(r) not in before_keys]


def write_records(records: list[dict], out_path: Path | None) -> None:
    payload = "\n".join(json.dumps(r, sort_keys=True) for r in records)
    if records:
        payload += "\n"
    if out_path is None:
        sys.stdout.write(payload)
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Path to write the JSONL snapshot. Default: stdout. The "
            "parent directory is created if needed."
        ),
    )
    parser.add_argument(
        "--diff",
        type=Path,
        default=None,
        help=(
            "Path to a previous snapshot. When supplied, only the "
            "(type, name) tuples that appear NOW but not in the "
            "baseline are emitted -- the side effects spawned "
            "between the two snapshots."
        ),
    )
    args = parser.parse_args()

    if args.diff is not None:
        records = diff_against(args.diff)
    else:
        records = snapshot()
    write_records(records, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
