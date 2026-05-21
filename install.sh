#!/usr/bin/env bash
# AGENT-33 one-shot installer (Linux/macOS).
# Defaults to Docker Compose. Pass --mode=source for a Python venv install.
set -euo pipefail

MODE="docker"
COMPOSE_FILE="engine/docker-compose.yml"
API_URL="http://localhost:8000"
HEALTH_PATH="/healthz"
MAX_WAIT="${MAX_WAIT:-120}"
REPO_URL="https://github.com/mattmre/AGENT33-PUBLIC.git"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--mode=docker|source] [--help]

Options:
  --mode=docker   (default) Bring up the full stack via Docker Compose.
  --mode=source   Set up engine/.venv with the dev extras for local hacking.
  --help          Show this help text and exit.

Environment overrides:
  MAX_WAIT        Seconds to wait for the API healthcheck (default 120).
USAGE
}

for arg in "$@"; do
  case "$arg" in
    --mode=docker) MODE="docker" ;;
    --mode=source) MODE="source" ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown argument: $arg" >&2
      usage
      exit 2
      ;;
  esac
done

log() { printf "==> %s\n" "$*"; }
err() { printf "ERROR: %s\n" "$*" >&2; }

require_tool() {
  local tool="$1"
  local hint="$2"
  if ! command -v "$tool" >/dev/null 2>&1; then
    err "'$tool' is not installed or not on PATH."
    err "$hint"
    exit 1
  fi
}

require_repo_root() {
  if [[ ! -f "engine/pyproject.toml" || ! -f "$COMPOSE_FILE" ]]; then
    err "Run this script from the AGENT33-PUBLIC repo root."
    err "Expected files: engine/pyproject.toml and $COMPOSE_FILE"
    err "If you have not cloned yet:"
    err "  git clone $REPO_URL && cd AGENT33-PUBLIC && ./install.sh"
    exit 1
  fi
}

wait_for_health() {
  local url="$1"
  local deadline=$(( SECONDS + MAX_WAIT ))
  log "Waiting up to ${MAX_WAIT}s for $url ..."
  while (( SECONDS < deadline )); do
    if curl --fail --silent --max-time 3 "$url" >/dev/null 2>&1; then
      log "API is healthy at $url"
      return 0
    fi
    sleep 2
  done
  err "API never became healthy at $url within ${MAX_WAIT}s."
  err "Check 'docker compose -f $COMPOSE_FILE logs api' for details."
  return 1
}

install_docker() {
  require_tool git "Install git from https://git-scm.com/downloads"
  require_tool docker "Install Docker Desktop from https://www.docker.com/products/docker-desktop/"
  if ! docker compose version >/dev/null 2>&1; then
    err "'docker compose' v2 plugin is not available."
    err "Update Docker Desktop or install the docker-compose-plugin package."
    exit 1
  fi

  require_repo_root

  if [[ ! -f "engine/.env" ]]; then
    log "Creating engine/.env from engine/.env.example"
    cp engine/.env.example engine/.env
  else
    log "engine/.env already exists, leaving it alone"
  fi

  log "Building and starting the stack: docker compose -f $COMPOSE_FILE up -d"
  docker compose -f "$COMPOSE_FILE" up -d --build

  if ! wait_for_health "${API_URL}${HEALTH_PATH}"; then
    exit 1
  fi

  cat <<DONE

AGENT-33 is running.

  API:       $API_URL
  Frontend:  http://localhost:3000
  Health:    ${API_URL}${HEALTH_PATH}

Next steps:
  - Try a request:  see QUICKSTART.md
  - Tail logs:      docker compose -f $COMPOSE_FILE logs -f api
  - Stop the stack: docker compose -f $COMPOSE_FILE down
DONE
}

install_source() {
  require_tool git "Install git from https://git-scm.com/downloads"
  require_tool python3 "Install Python 3.11+ from https://www.python.org/downloads/"

  local pyver
  pyver="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  if [[ "$(printf '%s\n3.11\n' "$pyver" | sort -V | head -n1)" != "3.11" ]]; then
    err "Python 3.11+ is required (found $pyver)."
    exit 1
  fi

  if ! command -v node >/dev/null 2>&1; then
    log "Node.js was not found; the engine will install but the frontend will not."
    log "Install Node 20+ from https://nodejs.org/ to run the UI."
  fi

  require_repo_root

  log "Creating engine/.venv"
  (
    cd engine
    python3 -m venv .venv
    # shellcheck disable=SC1091
    source .venv/bin/activate
    python -m pip install --upgrade pip
    pip install -e ".[dev]"
  )

  if [[ ! -f "engine/.env" ]]; then
    log "Creating engine/.env from engine/.env.example"
    cp engine/.env.example engine/.env
  fi

  cat <<DONE

Source install complete.

To run the engine:
  source engine/.venv/bin/activate
  cd engine
  uvicorn agent33.main:app --reload --host 0.0.0.0 --port 8000

To run the frontend (in a second terminal):
  cd frontend
  npm install
  npm run dev

Infra services (Postgres, Redis, NATS, SearXNG) still come from Docker:
  docker compose -f $COMPOSE_FILE up -d postgres redis nats searxng
DONE
}

case "$MODE" in
  docker) install_docker ;;
  source) install_source ;;
  *)
    err "Unknown mode: $MODE"
    usage
    exit 2
    ;;
esac
