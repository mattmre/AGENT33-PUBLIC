#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/engine/docker-compose.yml"
ENV_FILE="${REPO_ROOT}/engine/.env"
SESSION_ROOT="${REPO_ROOT}/.agent-os/sessions"
ACTIVE_SESSION_FILE="${REPO_ROOT}/.agent-os/active-session"
COMMAND="${1:-start}"
SESSION="${2:-default}"

ensure_env() {
  if [ ! -f "${ENV_FILE}" ]; then
    cp "${REPO_ROOT}/engine/.env.example" "${ENV_FILE}"
    echo "Created engine/.env from .env.example. Rotate secrets before shared use."
  fi
}

validate_session_name() {
  local name="$1"
  if [[ ! "${name}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
    echo "Invalid session name '${name}'. Use letters, numbers, '.', '_', or '-', starting with a letter or number." >&2
    exit 2
  fi
}

session_dir() {
  echo "${SESSION_ROOT}/$1"
}

session_workspace() {
  echo "$(session_dir "$1")/workspace"
}

active_session() {
  if [ -f "${ACTIVE_SESSION_FILE}" ]; then
    cat "${ACTIVE_SESSION_FILE}"
  else
    echo "default"
  fi
}

resolve_running_session() {
  local requested="${1:-}"
  local active
  active="$(active_session)"

  if [ -n "${requested}" ] && [ "${requested}" != "${active}" ]; then
    validate_session_name "${requested}"
    echo "Session '${requested}' is not active. Start it first with: scripts/agent-os.sh start ${requested}" >&2
    exit 2
  fi

  echo "${active}"
}

activate_session() {
  local name="$1"
  validate_session_name "${name}"
  mkdir -p "$(session_workspace "${name}")"
  mkdir -p "$(dirname "${ACTIVE_SESSION_FILE}")"
  printf '%s\n' "${name}" > "${ACTIVE_SESSION_FILE}"
  export AGENT_OS_SESSION_NAME="${name}"
  export AGENT_OS_SESSION_WORKSPACE="$(session_workspace "${name}")"
}

use_session() {
  local name="${1:-$(active_session)}"
  validate_session_name "${name}"
  export AGENT_OS_SESSION_NAME="${name}"
  export AGENT_OS_SESSION_WORKSPACE="$(session_workspace "${name}")"
}

print_session_status() {
  local name
  name="$(active_session)"
  echo "Active Agent OS session: ${name}"
  echo "Session workspace: $(session_workspace "${name}")"
}

case "${COMMAND}" in
  start)
    ensure_env
    activate_session "${SESSION}"
    docker compose -f "${COMPOSE_FILE}" --profile agent-os up -d postgres redis nats searxng api
    docker compose -f "${COMPOSE_FILE}" --profile agent-os up -d --force-recreate agent-os
    echo "Agent OS session '${SESSION}' is starting."
    echo "Open it with: scripts/agent-os.sh shell"
    ;;
  shell)
    ensure_env
    use_session "$(resolve_running_session "${2:-}")"
    docker compose -f "${COMPOSE_FILE}" --profile agent-os exec agent-os \
      bash -lc 'cd "${AGENT33_WORKSPACE:-/agent-workspace}" && exec bash -l'
    ;;
  status)
    ensure_env
    use_session "$(active_session)"
    print_session_status
    docker compose -f "${COMPOSE_FILE}" --profile agent-os ps
    ;;
  logs)
    ensure_env
    use_session "$(active_session)"
    docker compose -f "${COMPOSE_FILE}" --profile agent-os logs --tail=120 agent-os
    ;;
  stop)
    ensure_env
    use_session "$(active_session)"
    docker compose -f "${COMPOSE_FILE}" --profile agent-os down
    ;;
  list)
    mkdir -p "${SESSION_ROOT}"
    print_session_status
    echo
    echo "Known sessions:"
    for session_path in "${SESSION_ROOT}"/*; do
      [ -d "${session_path}" ] || continue
      printf '  %s\n' "$(basename "${session_path}")"
    done | sort
    ;;
  clean)
    validate_session_name "${SESSION}"
    if [ "${SESSION}" = "$(active_session)" ]; then
      echo "Refusing to clean active session '${SESSION}'. Stop Agent OS or start a different session first." >&2
      exit 2
    fi
    if [ ! -d "$(session_dir "${SESSION}")" ]; then
      echo "No Agent OS session named '${SESSION}' exists." >&2
      exit 2
    fi
    rm -rf "$(session_dir "${SESSION}")"
    echo "Removed Agent OS session '${SESSION}'."
    ;;
  *)
    echo "Usage: scripts/agent-os.sh [start|shell|status|logs|stop|list|clean] [session-name]" >&2
    exit 2
    ;;
esac
