#!/usr/bin/env bash
# scripts/smoke.sh — project release gate Rule 5 smoke gate.
#
# Single deterministic smoke command. Exercises the production code path end-to-end.
# Returns 0 only if every check it ran passed.
#
# Honest disclosure (built into the script's output):
#   - Stage 1 (API / surface boot): always runs. Validates the application stack
#     can construct (whatever "the application" is in your repo — FastAPI app,
#     Django settings, CLI argument parser, etc.). The default invocation runs
#     `pytest tests/test_e2e_smoke.py -x` — replace with your own surface check
#     if you do not have that file.
#   - Stage 2 (production-pipeline import + minimal exercise): runs ONLY if your
#     production deps are importable. If they are not, Stage 2 is reported as
#     SKIPPED with a clear reason — and the script EXITS NON-ZERO because Rule 5
#     demands an actual end-to-end production-path verification.
#
# Two-tier framing per v3.2 Rule 5 (§1 + §10):
#   - Floor: import + surface-check through production code paths (what the
#     reference smoke_pipeline.py.template emits). Acceptable for a v3.2 minimum.
#   - Ceiling: true end-to-end against a real fixture (your real OCR/web/CLI
#     entry point producing a real output that downstream consumers depend on).
#     This is the target. Until you reach ceiling, your PR body's SMOKE: line
#     MUST name the tier you ran AND any ceiling gap MUST appear as a Carried
#     Debt entry in your next-session.md.
#
# Use:
#   bash scripts/smoke.sh                 # full local smoke
#   bash scripts/smoke.sh --api-only      # only Stage 1 (CI use, docs-only PRs)
#   bash scripts/smoke.sh --skip-stage2   # alias for --api-only
#
# The --api-only / --skip-stage2 flags exist to let docs-only PRs (and pre-deploy
# check-the-API CI jobs) run a partial smoke. v3.2 §4 PR template requires that
# any "complete" PR's SMOKE: line includes the FULL output (not the partial one)
# OR explicitly calls out that this PR is docs-only and Stage 2 was intentionally
# skipped — and even then, the script EXITS NON-ZERO so the skip is visible.

set -u  # treat unset vars as errors; do NOT set -e (we handle errors explicitly)

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
elif command -v python.exe >/dev/null 2>&1; then
    PYTHON_BIN="python.exe"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
else
    echo "smoke.sh: neither python, python.exe, nor python3 is available on PATH" >&2
    exit 127
fi

API_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --api-only|--skip-stage2)
            API_ONLY=1
            ;;
        --help|-h)
            sed -n '2,40p' "$0"
            exit 0
            ;;
        *)
            echo "smoke.sh: unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

# Status accumulator
SMOKE_STATUS=0
STAGE1_RESULT="NOT RUN"
STAGE2_RESULT="NOT RUN"
STAGE2_REASON=""

echo "========================================================================="
echo "project release gate Rule 5 smoke"
echo "Repo root: $REPO_ROOT"
echo "Started:   $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "========================================================================="

# -----------------------------------------------------------------------------
# Stage 1 — application/surface boot smoke (always runs)
# -----------------------------------------------------------------------------
echo
echo "--- Stage 1: application/surface boot smoke ---"
if [ -f "$REPO_ROOT/tests/test_e2e_smoke.py" ]; then
    if "$PYTHON_BIN" -m pytest tests/test_e2e_smoke.py -v --tb=short -x 2>&1; then
        STAGE1_RESULT="PASS"
        echo "Stage 1 PASS"
    else
        STAGE1_RESULT="FAIL"
        SMOKE_STATUS=1
        echo "Stage 1 FAIL — application surface does not boot. Halting before Stage 2." >&2
    fi
else
    STAGE1_RESULT="SKIPPED"
    STAGE2_REASON="tests/test_e2e_smoke.py not present"
    SMOKE_STATUS=1
    echo "Stage 1 SKIPPED — no tests/test_e2e_smoke.py found." >&2
    echo "Add a surface-boot test (FastAPI client, Django setup, CLI parser, etc.)" >&2
    echo "and re-run. Rule 5 requires a deterministic Stage 1 surface check." >&2
fi

# -----------------------------------------------------------------------------
# Stage 2 — production-pipeline smoke (the load-bearing tier)
# -----------------------------------------------------------------------------
if [ "$API_ONLY" -eq 1 ]; then
    STAGE2_RESULT="SKIPPED"
    STAGE2_REASON="--api-only flag set by caller"
    SMOKE_STATUS=1
    echo
    echo "--- Stage 2: SKIPPED (--api-only) ---"
    echo "NOTE: Rule 5 (v3.2) requires end-to-end production-path verification."
    echo "      --api-only is acceptable for docs-only PRs but smoke EXITS NON-ZERO"
    echo "      so the caller must explicitly disclose the skip in PR body SMOKE: line."
elif [ "$STAGE1_RESULT" != "PASS" ]; then
    STAGE2_RESULT="SKIPPED"
    STAGE2_REASON="Stage 1 failed — Stage 2 cannot run on a broken stack"
    echo
    echo "--- Stage 2: SKIPPED (Stage 1 failed) ---"
elif [ ! -f "$REPO_ROOT/scripts/smoke_pipeline.py" ]; then
    STAGE2_RESULT="SKIPPED"
    STAGE2_REASON="scripts/smoke_pipeline.py not present (copy the .template and fill it in)"
    SMOKE_STATUS=1
    echo
    echo "--- Stage 2: SKIPPED (no smoke_pipeline.py) ---" >&2
    echo "Copy the kit's scripts/smoke_pipeline.py.template to scripts/smoke_pipeline.py" >&2
    echo "and fill in the production-module placeholders for your repo." >&2
else
    echo
    echo "--- Stage 2: production-pipeline smoke ---"
    if "$PYTHON_BIN" scripts/smoke_pipeline.py; then
        STAGE2_RESULT="PASS"
        echo "Stage 2 PASS"
    else
        STAGE2_RESULT="FAIL"
        STAGE2_REASON="see scripts/smoke_pipeline.py output above"
        SMOKE_STATUS=1
        echo "Stage 2 FAIL" >&2
    fi
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo
echo "========================================================================="
echo "SMOKE SUMMARY"
echo "  Stage 1 (surface boot):       $STAGE1_RESULT"
echo "  Stage 2 (production pipeline): $STAGE2_RESULT${STAGE2_REASON:+ ($STAGE2_REASON)}"
echo "  Overall exit code:            $SMOKE_STATUS"
echo "  Finished:                     $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "========================================================================="

exit $SMOKE_STATUS
