# Agent OS Runtime

AGENT-33 ships a contained Linux operator workspace for local-first agent work. It gives agents and operators a stable tool-rich environment without forcing users to install Python, Node, Go, Rust, Docker CLI, database clients, or shell utilities on the host.

## Start it

PowerShell:

```powershell
scripts\agent-os.ps1 start
scripts\agent-os.ps1 shell
```

Bash:

```bash
scripts/agent-os.sh start
scripts/agent-os.sh shell
```

The starter script creates `engine/.env` from `engine/.env.example` if needed, then starts the API dependencies and the Agent OS container with the `agent-os` Compose profile.

## Work in named sessions

Use named sessions when an operator, agent, or experiment needs its own persistent workspace. Each session stores files under `.agent-os/sessions/<name>/workspace` on the host and mounts that directory at `/agent-workspace` in the container.

PowerShell:

```powershell
scripts\agent-os.ps1 start research-loop
scripts\agent-os.ps1 shell
scripts\agent-os.ps1 list
scripts\agent-os.ps1 clean old-experiment
```

Bash:

```bash
scripts/agent-os.sh start research-loop
scripts/agent-os.sh shell
scripts/agent-os.sh list
scripts/agent-os.sh clean old-experiment
```

Session names may use letters, numbers, `.`, `_`, and `-`, and must start with a letter or number. Starting a different named session recreates only the Agent OS container while keeping the API, Postgres, Redis, NATS, and SearXNG services running.

## What is included

- Ubuntu 24.04 userland with a non-root `agentos` user
- Python 3, `uv`, Poetry, Node.js 22, npm, pnpm, Yarn, Go, Rust, build tools, `git`, GitHub CLI, `jq`, `rg`, `fd`, `tmux`, and common database/service clients
- Docker CLI and Compose plugin for controlled sibling-container workflows when the Docker socket is available
- Persistent home and shared-data volumes, plus per-session `/agent-workspace` directories
- Network access to AGENT-33 API, Postgres, Redis, NATS, SearXNG, and host Ollama

## Useful commands inside the container

```bash
agent33-health
agent33-tools
agent33-token
```

`agent33-health` verifies the AGENT-33 API and service dependencies from inside the Agent OS network. `agent33-tools` prints installed tool versions. `agent33-token` mints a short-lived local admin JWT from the local development `JWT_SECRET`.

## Safety posture

The Agent OS profile is designed to be safer than the older `devbox` profile:

- it runs as a non-root Linux user by default;
- host files are mounted into `/workspace`, while agent-generated state should go in the active session's `/agent-workspace`;
- the Docker socket is mounted only for this explicit operator runtime profile, not for the API service;
- default secrets remain development-only and must be rotated before shared or public deployments.

Do not expose this profile directly to the internet. Treat it as an operator workstation attached to a local or trusted AGENT-33 stack.
