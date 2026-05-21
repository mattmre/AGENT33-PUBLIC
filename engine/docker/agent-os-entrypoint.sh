#!/usr/bin/env bash
set -euo pipefail

cat <<'BANNER'
AGENT-33 Agent OS is ready.

Useful commands:
  agent33-health       Check API, Postgres, Redis, NATS, and toolchain reachability
  agent33-token        Mint a local admin JWT from the API container secret
  agent33-tools        Show installed language/tool versions

Workspace:
  /workspace           Project files
  /agent-workspace     Persistent operator session workspace
  /data/shared         Shared data volume with the AGENT-33 stack

Session:
  ${AGENT33_SESSION:-default}
BANNER

mkdir -p "${AGENT33_HOME:-$HOME/.agent33}" /agent-workspace

cat > "${HOME}/.bashrc.d-agent33" <<'EOF'
export AGENT33_API_URL="${AGENT33_API_URL:-http://api:8000}"
export AGENT33_HOME="${AGENT33_HOME:-$HOME/.agent33}"
export AGENT33_SESSION="${AGENT33_SESSION:-default}"
export AGENT33_WORKSPACE="${AGENT33_WORKSPACE:-/agent-workspace}"
EOF

if ! grep -q ".bashrc.d-agent33" "${HOME}/.bashrc" 2>/dev/null; then
  {
    echo ''
    echo 'if [ -f "$HOME/.bashrc.d-agent33" ]; then'
    echo '  . "$HOME/.bashrc.d-agent33"'
    echo 'fi'
  } >> "${HOME}/.bashrc"
fi

tail -f /dev/null
