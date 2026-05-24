#!/usr/bin/env bash
# scripts/smoke.sh — project release gate.1 Rule 5 smoke gate.
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
# Two-tier framing per v3.7.1 Rule 5 (§1 + §10):
#   - Floor: import + surface-check through production code paths (what the
#     reference smoke_pipeline.py.template emits). Acceptable for the BHS floor minimum.
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
# check-the-API CI jobs) run a partial smoke. v3.7.1 §4 PR template requires that
# any "complete" PR's SMOKE: line includes the FULL output (not the partial one)
# OR explicitly calls out that this PR is docs-only and Stage 2 was intentionally
# skipped — and even then, the script EXITS NON-ZERO so the skip is visible.

set -u  # treat unset vars as errors; do NOT set -e (we handle errors explicitly)

# Pick the first available Python binary. python and python.exe are tried before
# python3 so that Git Bash on Windows (where python or python.exe is the working
# binary and python3 may be missing or stub) selects a working interpreter.
if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
elif command -v python.exe >/dev/null 2>&1; then
    PYTHON_BIN="python.exe"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
else
    echo "smoke.sh: neither python, python.exe, nor python3 is available on PATH" >&2
    echo "smoke.sh: install Python 3.10+ and re-run (or run scripts/smoke.ps1 on Windows; see docs/operators/brutal-honesty-kit/v3.5/INSTALL.md)" >&2
    exit 127
fi

SCRIPT_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

API_ONLY=0
DETECT_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --api-only|--skip-stage2)
            API_ONLY=1
            ;;
        --detect-language)
            DETECT_ONLY=1
            ;;
        --help|-h)
            sed -n '2,40p' "$SCRIPT_FILE"
            exit 0
            ;;
        *)
            echo "smoke.sh: unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

# -----------------------------------------------------------------------------
# Language detection / runner dispatch (issue #5)
# -----------------------------------------------------------------------------
#
# Determines which scripts/smoke_pipeline.<ext> runner Stage 2 will invoke.
# Reads smoke.config.json's "language" field if present; otherwise detects
# by presence of language-marker files. Fails loudly on ambiguity.
detect_language() {
    if [ -f "$REPO_ROOT/smoke.config.json" ]; then
        # Extract "language" via the same awk technique used in smoke_pipeline.sh.template.
        awk '/"language"[[:space:]]*:[[:space:]]*"[^"]*"/ {
            s=$0; sub(/.*"language"[[:space:]]*:[[:space:]]*"/, "", s);
            sub(/".*/, "", s); print s; exit }' "$REPO_ROOT/smoke.config.json"
        return
    fi
    local candidates=""
    [ -f "$REPO_ROOT/package.json" ]    && candidates="$candidates node"
    [ -f "$REPO_ROOT/pyproject.toml" ]  && candidates="$candidates python"
    [ -f "$REPO_ROOT/setup.py" ]        && candidates="$candidates python"
    [ -f "$REPO_ROOT/go.mod" ]          && candidates="$candidates shell"
    [ -f "$REPO_ROOT/Cargo.toml" ]      && candidates="$candidates shell"
    # Deduplicate and emit space-separated tokens.
    echo "$candidates" | tr ' ' '\n' | sort -u | grep -v '^$' | tr '\n' ' '
}

LANGUAGE_CANDIDATES="$(detect_language)"
# Trim trailing space and count tokens (POSIX-portable via positional params).
# shellcheck disable=SC2086
set -- $LANGUAGE_CANDIDATES
LANG_COUNT=$#
if [ "$LANG_COUNT" -eq 0 ]; then
    SMOKE_LANGUAGE=""
elif [ "$LANG_COUNT" -eq 1 ]; then
    SMOKE_LANGUAGE="$1"
else
    echo "smoke.sh: ambiguous language detection: candidates=($LANGUAGE_CANDIDATES)" >&2
    echo "smoke.sh: create smoke.config.json at the repo root with an explicit \"language\" field." >&2
    echo "smoke.sh: see scripts/smoke.config.json.example for the format." >&2
    exit 3
fi

if [ "$DETECT_ONLY" -eq 1 ]; then
    if [ -n "$SMOKE_LANGUAGE" ]; then
        echo "$SMOKE_LANGUAGE"
    fi
    exit 0
fi

# Status accumulator
SMOKE_STATUS=0
STAGE1_RESULT="NOT RUN"
STAGE2_RESULT="NOT RUN"
STAGE2_REASON=""

echo "========================================================================="
echo "project release gate.1 Rule 5 smoke"
echo "Repo root: $REPO_ROOT"
echo "Started:   $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "========================================================================="

# -----------------------------------------------------------------------------
# Stage 1 — application/surface boot smoke (always runs)
# -----------------------------------------------------------------------------
echo
echo "--- Stage 1: application/surface boot smoke ---"
if [ -f "tests/test_e2e_smoke.py" ]; then
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
    echo "NOTE: Rule 5 (v3.7.1) requires end-to-end production-path verification."
    echo "      --api-only is acceptable for docs-only PRs but smoke EXITS NON-ZERO"
    echo "      so the caller must explicitly disclose the skip in PR body SMOKE: line."
elif [ "$STAGE1_RESULT" != "PASS" ]; then
    STAGE2_RESULT="SKIPPED"
    STAGE2_REASON="Stage 1 failed — Stage 2 cannot run on a broken stack"
    echo
    echo "--- Stage 2: SKIPPED (Stage 1 failed) ---"
else
    RUN_CMD=()
    case "$SMOKE_LANGUAGE" in
        python)
            RUNNER="scripts/smoke_pipeline.py"
            RUN_CMD=("$PYTHON_BIN" "$RUNNER")
            ;;
        node)
            RUNNER="scripts/smoke_pipeline.mjs"
            if command -v node >/dev/null 2>&1; then
                RUN_CMD=(node "$RUNNER")
            else
                STAGE2_RESULT="SKIPPED"
                STAGE2_REASON="node binary not on PATH (language=node)"
                SMOKE_STATUS=1
            fi
            ;;
        shell)
            RUNNER="scripts/smoke_pipeline.sh"
            RUN_CMD=(bash "$RUNNER")
            ;;
        "")
            STAGE2_RESULT="SKIPPED"
            STAGE2_REASON="no language detected; create smoke.config.json with a \"language\" field"
            SMOKE_STATUS=1
            ;;
        *)
            STAGE2_RESULT="SKIPPED"
            STAGE2_REASON="unknown language: $SMOKE_LANGUAGE"
            SMOKE_STATUS=1
            ;;
    esac

    if [ "${#RUN_CMD[@]}" -gt 0 ]; then
        if [ ! -f "$REPO_ROOT/$RUNNER" ]; then
            STAGE2_RESULT="SKIPPED"
            STAGE2_REASON="$RUNNER not present (copy ${RUNNER}.template and fill placeholders)"
            SMOKE_STATUS=1
            echo
            echo "--- Stage 2: SKIPPED (no $RUNNER) ---" >&2
            echo "Copy $RUNNER.template to $RUNNER and fill in the placeholders for your repo." >&2
        else
            echo
            echo "--- Stage 2: production-pipeline smoke (language=$SMOKE_LANGUAGE) ---"
            if "${RUN_CMD[@]}"; then
                STAGE2_RESULT="PASS"
                echo "Stage 2 PASS"
            else
                STAGE2_RESULT="FAIL"
                STAGE2_REASON="see $RUNNER output above"
                SMOKE_STATUS=1
                echo "Stage 2 FAIL" >&2
            fi
        fi
    else
        echo
        echo "--- Stage 2: SKIPPED ($STAGE2_REASON) ---" >&2
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
