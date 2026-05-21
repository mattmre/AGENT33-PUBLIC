#!/usr/bin/env bash
set -euo pipefail

# Dependency security audit script
# Checks Python dependencies for known vulnerabilities using pip-audit.
#
# Usage:
#   ./scripts/dependency-audit.sh            # audit installed packages
#   ./scripts/dependency-audit.sh --fix      # attempt auto-remediation
#
# The script installs pip-audit on-demand so it does not need to be a
# project dependency.  It runs from the engine/ directory and exits
# non-zero when vulnerabilities are found.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENGINE_DIR="${SCRIPT_DIR}/../engine"

if [ ! -d "${ENGINE_DIR}" ]; then
    echo "ERROR: engine/ directory not found at ${ENGINE_DIR}" >&2
    exit 2
fi

cd "${ENGINE_DIR}"

# ------------------------------------------------------------------
# 1. Ensure pip-audit is available
# ------------------------------------------------------------------
echo "==> Ensuring pip-audit is installed..."
python -m pip install pip-audit --quiet 2>/dev/null || {
    echo "ERROR: Failed to install pip-audit. Check your Python environment." >&2
    exit 2
}

# ------------------------------------------------------------------
# 2. Build pip-audit flags
# ------------------------------------------------------------------
AUDIT_FLAGS=(--strict --desc)

if [[ "${1:-}" == "--fix" ]]; then
    AUDIT_FLAGS+=(--fix)
    echo "==> Running pip-audit in fix mode..."
else
    echo "==> Running pip-audit (read-only scan)..."
fi

# ------------------------------------------------------------------
# 3. Run pip-audit
# ------------------------------------------------------------------
python -m pip_audit "${AUDIT_FLAGS[@]}" 2>&1 || {
    echo ""
    echo "WARNING: pip-audit found vulnerabilities. Review output above." >&2
    echo "  Re-run with --fix to attempt automatic remediation:" >&2
    echo "    ./scripts/dependency-audit.sh --fix" >&2
    exit 1
}

echo "==> All Python dependencies are clean."
