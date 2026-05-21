#!/usr/bin/env bash
# Multi-replica smoke test for AGENT-33 (P4.9).
#
# This script starts the multi-instance Docker Compose setup, waits for
# both API instances to become healthy, runs basic cross-instance checks,
# and tears everything down.
#
# Usage:
#   cd <repo-root>
#   bash scripts/multi-replica-smoke.sh
#
# Prerequisites:
#   - Docker and Docker Compose installed
#   - engine/docker-compose.yml and engine/docker-compose.multi.yml present
#   - engine/.env file (or defaults are acceptable)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENGINE_DIR="$REPO_ROOT/engine"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

COMPOSE_FILES="-f docker-compose.yml -f docker-compose.multi.yml"

cleanup() {
    info "Tearing down multi-replica stack..."
    cd "$ENGINE_DIR"
    docker compose $COMPOSE_FILES down --volumes --remove-orphans 2>/dev/null || true
}

# Always clean up on exit
trap cleanup EXIT

# -------------------------------------------------------------------
# 1. Start the multi-instance stack
# -------------------------------------------------------------------
info "Starting multi-replica stack from $ENGINE_DIR..."
cd "$ENGINE_DIR"

docker compose $COMPOSE_FILES up -d --build

# -------------------------------------------------------------------
# 2. Wait for both instances to become healthy
# -------------------------------------------------------------------
MAX_WAIT=120
INTERVAL=5

wait_for_health() {
    local url="$1"
    local name="$2"
    local elapsed=0

    info "Waiting for $name to become healthy at $url..."
    while [ $elapsed -lt $MAX_WAIT ]; do
        if curl -sf "$url" > /dev/null 2>&1; then
            info "$name is healthy (${elapsed}s)"
            return 0
        fi
        sleep $INTERVAL
        elapsed=$((elapsed + INTERVAL))
    done

    error "$name did not become healthy within ${MAX_WAIT}s"
    return 1
}

wait_for_health "http://localhost:8001/healthz" "api-1"
wait_for_health "http://localhost:8002/healthz" "api-2"
wait_for_health "http://localhost:8000/lb-health" "load-balancer"

# -------------------------------------------------------------------
# 3. Run basic cross-instance checks
# -------------------------------------------------------------------
PASS=0
FAIL=0

check() {
    local name="$1"
    shift
    if "$@"; then
        info "PASS: $name"
        PASS=$((PASS + 1))
    else
        error "FAIL: $name"
        FAIL=$((FAIL + 1))
    fi
}

# Check 1: Both instances return healthy
check "api-1 healthz" curl -sf http://localhost:8001/healthz -o /dev/null
check "api-2 healthz" curl -sf http://localhost:8002/healthz -o /dev/null

# Check 2: Load balancer distributes requests
check "lb forwards to backend" curl -sf http://localhost:8000/healthz -o /dev/null

# Check 3: Multiple requests through LB all succeed
check_lb_distribution() {
    local success=0
    for i in $(seq 1 10); do
        if curl -sf http://localhost:8000/healthz -o /dev/null; then
            success=$((success + 1))
        fi
    done
    [ $success -eq 10 ]
}
check "lb distributes 10 requests" check_lb_distribution

# Check 4: Full health endpoint on both instances
check "api-1 full health" curl -sf http://localhost:8001/health -o /dev/null
check "api-2 full health" curl -sf http://localhost:8002/health -o /dev/null

# -------------------------------------------------------------------
# 4. Summary
# -------------------------------------------------------------------
echo ""
info "============================================"
info "  Multi-Replica Smoke Test Results"
info "============================================"
info "  Passed: $PASS"
if [ $FAIL -gt 0 ]; then
    error "  Failed: $FAIL"
    echo ""
    error "Some checks failed. Review the output above."
    exit 1
else
    info "  Failed: $FAIL"
    echo ""
    info "All checks passed."
    exit 0
fi
