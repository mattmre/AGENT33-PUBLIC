#!/usr/bin/env python3
"""scripts/smoke_pipeline.py — Stage 2 of the v3.3 Rule 5 smoke gate.

AGENT33 FLOOR + CEILING TIER SMOKE — verifies the production module surface
(floor) AND drives real production code paths against real on-disk fixtures
(ceiling). See `run_ceiling_smoke()` for the ceiling-tier exercise.

Two-tier framing per project release gate:

  Floor (this template, default):
    Imports the production module, verifies its documented surface (constants,
    entry points, scanner functions). Catches L1 scaffold-as-feature, L9
    dependency-phantom, L10 broken imports. Acceptable as the v3.2 minimum but
    NOT a substitute for ceiling-tier verification.

  Ceiling (your target):
    Runs the real production entry point against tests/fixtures/<input> and
    asserts the produced output (file content, persisted record, response body)
    matches expectations. Examples:
      - OCR pipeline:  extract → OCR → assemble → verify output PDF contains
                       expected text from the fixture
      - Web service:   start app → POST /api/x → assert persisted record
                       matches the request payload
      - CLI tool:      run CLI with fixture args → assert output file exists
                       with expected content
    Until you reach ceiling-tier, the SMOKE: line in your PR body MUST name
    which tier was run AND any ceiling gap MUST appear as a Carried Debt entry
    in your next-session.md per §6.3.

AGENT33 FLOOR-TIER SURFACE:
  production module: agent33.main
  expected constants: []
  entry point names: ["app"]
  scanner names: []
  also required imports: ["agent33.config", "agent33.workflows.executor"]
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Optional: point at a real fixture if you build a ceiling-tier exercise below.
# These paths are only checked if you uncomment the fixture-presence guard.
FIXTURE_PRIMARY = REPO_ROOT / "tests" / "fixtures" / "sample.pdf"
FIXTURE_SECONDARY = REPO_ROOT / "tests" / "fixtures" / "sample.png"


def _print(msg: str) -> None:
    print(msg, flush=True)


def _fail(reason: str) -> int:
    _print(f"SMOKE_PIPELINE FAIL: {reason}")
    return 1


def _ok(msg: str) -> None:
    _print(f"  OK: {msg}")


def run_floor_smoke() -> int:
    """Floor-tier smoke: import + surface verification through production code.

    Returns 0 on PASS, 1 on FAIL. Does NOT require GPU, models, or external
    services. Acceptable as the v3.2 minimum but not a substitute for ceiling.
    """
    _print(f"smoke_pipeline.py (floor tier) — REPO_ROOT={REPO_ROOT}")

    # --- Make the repo importable -------------------------------------------
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "engine" / "src"))

    # --- 1. Import the primary production module ----------------------------
    production_module_name = "agent33.main"  # FastAPI production application surface.
    try:
        import importlib
        production_module = importlib.import_module(production_module_name)
        _ok(f"imported {production_module_name}")
    except ImportError as exc:
        return _fail(
            f"cannot import production module {production_module_name!r}: {exc}\n"
            f"  Production deps are not installed in the current Python env.\n"
            f"  Stage 2 cannot honestly verify the production path without them.\n"
            f"  Fix: install production deps OR run smoke.sh inside the production "
            f"container."
        )
    except Exception as exc:  # noqa: BLE001 — surface ALL failures
        return _fail(
            f"{production_module_name} import raised non-ImportError: {exc!r}\n"
            f"{traceback.format_exc()}"
        )

    # --- 2. Import additional required production modules -------------------
    also_required: list[str] = ["agent33.config", "agent33.workflows.executor"]
    for mod_name in also_required:
        try:
            importlib.import_module(mod_name)
            _ok(f"imported {mod_name}")
        except ImportError as exc:
            return _fail(f"cannot import required production module {mod_name!r}: {exc}")
        except Exception as exc:  # noqa: BLE001
            return _fail(
                f"{mod_name} import raised non-ImportError: {exc!r}\n"
                f"{traceback.format_exc()}"
            )

    # --- 3. Verify the documented surface — public constants ---------------
    expected_constants: list[str] = []
    if expected_constants:
        missing = [c for c in expected_constants if not hasattr(production_module, c)]
        if missing:
            return _fail(
                f"{production_module_name} is missing documented constants: {missing}\n"
                f"  These are load-bearing per your CLAUDE.md / docs.\n"
                f"  Missing them is L4 partial-with-claim-of-complete: the module "
                f"imports but its documented surface is incomplete."
            )
        _ok(f"production constants present: {expected_constants}")

    # --- 4. Verify a CLI / programmatic entry point exists -----------------
    entry_point_names: list[str] = ["app"]
    if entry_point_names:
        has_entry = next(
            (n for n in entry_point_names if hasattr(production_module, n)),
            None,
        )
        if has_entry is None:
            return _fail(
                f"{production_module_name} exposes no entry point "
                f"(looked for {entry_point_names}). The production module has no "
                f"callable entry — this is L1 scaffold-as-feature."
            )
        _ok(f"production entry point exposed: {has_entry}")

    # --- 5. Verify an input-iteration / scanner function exists ------------
    scanner_names: list[str] = []
    if scanner_names:
        has_scanner = [n for n in scanner_names if hasattr(production_module, n)]
        if not has_scanner:
            return _fail(
                f"{production_module_name} exposes no input-iteration function "
                f"(looked for {scanner_names}). The production entry point has no "
                f"way to find work to do — this is L1 scaffold-as-feature."
            )
        _ok(f"production input-iteration functions exposed: {has_scanner}")

    return 0


AGENT_DEFINITIONS_DIR = REPO_ROOT / "engine" / "agent-definitions"
WORKFLOW_FIXTURE = (
    REPO_ROOT / "core" / "workflows" / "capability-packs" / "docs-overhaul.workflow.yaml"
)


def run_ceiling_smoke() -> int:
    """Ceiling-tier smoke: drive real production code paths against real fixtures.

    Exercises three load-bearing production surfaces with on-disk fixtures that
    ship with the repo. Each step parses real bytes through real Pydantic models
    and asserts on a non-trivial parsed field — not just that an import succeeded.

    Coverage:
      1. AgentRegistry.discover() against engine/agent-definitions/ — exercises
         AgentDefinition Pydantic validation, file iteration, and registry storage.
         Asserts: at least 6 definitions load and the canonical "orchestrator"
         definition (AGT-001) is present with the documented role.
      2. WorkflowDefinition.load_from_file() against the docs-overhaul workflow
         YAML — exercises YAML parsing, the WorkflowStep / WorkflowDefinition
         Pydantic stack, and the depends_on cross-step validator. Asserts: the
         parsed workflow has the documented step id, action, and target agent.
      3. agent33.main.app surface — asserts the FastAPI app exposes the Gate 2.1
         workflow-resume route (PR #628). This is the runtime evidence that the
         most-recent merged feature is wired into the production app, not just
         present as code.

    No external services (Postgres / Redis / NATS / Ollama) are required. The
    exercise runs in <5s on a cold interpreter.
    """
    _print("smoke_pipeline.py (ceiling tier) — real fixtures + production code paths")

    # --- 1. Agent definitions: real JSON files through real Pydantic ---------
    if not AGENT_DEFINITIONS_DIR.is_dir():
        return _fail(
            f"missing fixture directory: {AGENT_DEFINITIONS_DIR}\n"
            f"  Agent definitions are required for ceiling-tier smoke."
        )

    try:
        from agent33.agents.registry import AgentRegistry
    except ImportError as exc:
        return _fail(f"cannot import AgentRegistry: {exc}")

    registry = AgentRegistry()
    loaded = registry.discover(AGENT_DEFINITIONS_DIR)
    if loaded < 6:
        return _fail(
            f"agent registry discovered only {loaded} definitions in "
            f"{AGENT_DEFINITIONS_DIR}; expected at least 6 (orchestrator, director, "
            f"code-worker/worker, qa, researcher, browser-agent). L4 partial-as-complete: "
            f"production registry boot would ship a degraded agent roster."
        )
    _ok(f"AgentRegistry.discover loaded {loaded} definitions from real JSON")

    orchestrator = registry.get("orchestrator")
    if orchestrator is None:
        return _fail("registry is missing 'orchestrator' after discovery")
    if orchestrator.agent_id != "AGT-001":
        return _fail(
            f"orchestrator definition has agent_id={orchestrator.agent_id!r}, "
            f"expected 'AGT-001'. Either the fixture drifted or the Pydantic model is "
            f"dropping the field."
        )
    if orchestrator.role != "orchestrator":
        return _fail(
            f"orchestrator definition has role={orchestrator.role!r}, expected 'orchestrator'."
        )
    _ok(
        f"orchestrator definition parsed: agent_id={orchestrator.agent_id} "
        f"role={orchestrator.role}"
    )

    # --- 2. Workflow YAML: real fixture through real Pydantic ---------------
    if not WORKFLOW_FIXTURE.is_file():
        return _fail(
            f"missing workflow fixture: {WORKFLOW_FIXTURE}\n"
            f"  Ceiling-tier smoke needs a real workflow file to parse."
        )

    try:
        from agent33.workflows.definition import WorkflowDefinition
    except ImportError as exc:
        return _fail(f"cannot import WorkflowDefinition: {exc}")

    try:
        workflow = WorkflowDefinition.load_from_file(WORKFLOW_FIXTURE)
    except Exception:  # noqa: BLE001 — surface ALL failures
        return _fail(
            f"WorkflowDefinition.load_from_file({WORKFLOW_FIXTURE.name}) failed:\n"
            f"{traceback.format_exc()}"
        )

    if workflow.name != "docs-overhaul":
        return _fail(f"workflow name={workflow.name!r}, expected 'docs-overhaul'")
    if len(workflow.steps) != 1:
        return _fail(
            f"workflow has {len(workflow.steps)} steps, expected 1 — fixture drift."
        )
    step = workflow.steps[0]
    if step.id != "document":
        return _fail(f"step.id={step.id!r}, expected 'document'")
    if step.action != "invoke-agent":
        return _fail(f"step.action={step.action!r}, expected 'invoke-agent'")
    if step.agent != "researcher":
        return _fail(
            f"step.agent={step.agent!r}, expected 'researcher' — "
            f"WorkflowStep model is dropping the agent field."
        )
    _ok(
        f"WorkflowDefinition.load_from_file parsed {workflow.name!r}: "
        f"step={step.id} action={step.action} agent={step.agent}"
    )

    # --- 3. FastAPI app surface: Gate 2.1 resume route present --------------
    try:
        from agent33.main import app
    except Exception:  # noqa: BLE001
        return _fail(f"importing agent33.main:app failed:\n{traceback.format_exc()}")

    route_paths = {getattr(route, "path", "") for route in app.routes}
    required_routes = {"/health", "/healthz"}
    missing_required = required_routes - route_paths
    if missing_required:
        return _fail(f"app is missing required routes: {sorted(missing_required)}")

    resume_routes = sorted(p for p in route_paths if "resume" in p and "workflow" in p)
    if not resume_routes:
        return _fail(
            "app exposes no workflow resume route. PR #628 (Gate 2.1) claims to have "
            "wired POST /v1/workflows/{run_id}/resume — but the production app surface "
            "does not expose it. L4 partial-as-complete on a merged claim."
        )
    _ok(f"app exposes resume route(s): {resume_routes}")
    _ok(f"app exposes {len(route_paths)} routes total including /health and /healthz")

    _ok("ceiling-tier exercise PASS")
    return 0


def main() -> int:
    floor_status = run_floor_smoke()
    if floor_status != 0:
        return floor_status

    _print("")
    ceiling_status = run_ceiling_smoke()
    if ceiling_status != 0:
        return ceiling_status

    _print("")
    _print("SMOKE_PIPELINE PASS (floor + ceiling tiers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
