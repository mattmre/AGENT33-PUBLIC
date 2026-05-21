# CLI reference

The `agent33` command is the operator's shell. It wraps the most common API
calls, runs local diagnostics, scaffolds new agents and workflows, and ships
the first-run wizard. This page enumerates every command, its arguments, and a
real example.

`agent33` is installed when you `pip install -e ".[dev]"` from `engine/`. After
install, `agent33 --help` shows the top-level command list.

## Conventions

- Commands that hit the API accept `--base-url` (default
  `http://localhost:8000`) and `--token` (default reads the `TOKEN`
  environment variable, then falls back to no auth).
- Several sub-apps (`packs`, `tools`, `skills`, `env`) also accept
  `--api-url` and read `AGENT33_API_URL` and `TOKEN` from the environment.
- Output is human-friendly by default. Most commands accept `--json` (and some
  also `--plain`) for machine-parseable output.
- Exit code 0 indicates success. Non-zero codes are returned on validation
  failure, API errors, or unsatisfied checks (see individual commands).

## Top-level commands

### `agent33 status`

Show the engine's health by calling `GET /health`.

```bash
agent33 status
agent33 status --base-url http://api.example.com
```

Exit code is 0 if the response succeeds. The output is the raw JSON from the
health endpoint (status, dependencies, build info). Use this in scripts or as
a Compose `healthcheck`.

### `agent33 diagnose`

Run a battery of diagnostic checks across the engine's subsystems: Python
version, environment config, disk space, port availability, Ollama
reachability, LLM provider sanity, database/Redis connectivity, and (with a
token) live pack health checks.

```bash
agent33 diagnose
agent33 diagnose --fix                       # auto-remediate safe issues
agent33 diagnose --json > diagnose.json      # machine-readable output
agent33 diagnose --plain                     # compact, grep-friendly
```

Options:

| Option | Purpose |
|--------|---------|
| `--fix` | Apply safe auto-remediations (create missing dirs, write a `.env.local`, etc.) |
| `--json` | Emit one JSON document per run |
| `--plain` | Emit key=value lines |
| `--api-url` | Defaults to `http://localhost:8000`, also reads `AGENT33_API_URL` |
| `--token` | Bearer token; falls back to `TOKEN` |

Exit code reflects the worst severity found (`0` = ok, `1` = warning, `2` =
failure). Run this weekly and diff the output as a drift signal.

### `agent33 bootstrap`

Generate a `.env.local` with secure random values for `JWT_SECRET`,
`API_SECRET_KEY`, and a dev API key.

```bash
agent33 bootstrap                        # writes .env.local
agent33 bootstrap --output engine/.env.local
agent33 bootstrap --force                # overwrite existing
```

The output file is intended for local development. It is not suitable for
production; production secrets should be supplied via a secrets manager or
orchestrator environment.

### `agent33 start`

Start the engine. Thin wrapper around `uvicorn agent33.main:app` that also
accepts a profile shortcut.

```bash
agent33 start                                  # default profile + 0.0.0.0:8000
agent33 start --profile developer --reload
agent33 start --profile production --port 9000
```

Options:

| Option | Purpose |
|--------|---------|
| `--profile / -P` | One of `minimal`, `developer`, `production`, `enterprise`, `airgapped`. Sets `AGENT33_PROFILE` before settings load |
| `--host` | Default `0.0.0.0` |
| `--port` | Default `8000` |
| `--reload` | Auto-reload on source changes (dev only) |

### `agent33 wizard`

Interactive first-run wizard. Detects your environment, helps you pick an LLM
provider, runs a test invocation, and writes a `.env.local`.

```bash
agent33 wizard
agent33 wizard --env /etc/agent33/.env.local
```

Designed for the first 5 minutes after install. It is safe to re-run later;
it will not clobber existing settings without confirmation.

### `agent33 init`

Scaffold a new agent or workflow definition file.

```bash
agent33 init my-agent                        # writes my-agent.agent.json
agent33 init my-workflow --kind workflow     # writes my-workflow.workflow.json
agent33 init my-agent --output agent-definitions/
```

Options:

| Option | Purpose |
|--------|---------|
| `--kind / -k` | `agent` (default) or `workflow` |
| `--output / -o` | Output directory (default `.`) |

The scaffold is a valid skeleton: name, version, role, inputs, outputs,
constraints, and metadata. Customize it before registering.

### `agent33 run`

Execute a registered workflow.

```bash
agent33 run research-assistant \
  --inputs '{"topic":"hybrid retrieval","depth":"brief"}' \
  --token "$TOKEN"

agent33 run research-assistant -i '{"topic":"X"}' -b https://api.example.com
```

Options:

| Option | Purpose |
|--------|---------|
| `--inputs / -i` | JSON string passed as workflow inputs |
| `--base-url / -b` | API base URL (default `http://localhost:8000`) |
| `--token / -t` | Bearer token (falls back to `TOKEN`) |

The response is the JSON returned by `POST /v1/workflows/<name>/execute`.

### `agent33 chat`

Send a single chat message to `/v1/chat` with optional slash-command skill
routing.

```bash
agent33 chat "Hello"
agent33 chat "/research-agent analyze this codebase"
agent33 chat "hello" --preload research-agent --preload deploy
```

Options:

| Option | Purpose |
|--------|---------|
| `--preload / -p` | Preload a skill for the session (repeatable) |
| `--base-url / -b` | API base URL |
| `--token / -t` | Bearer token |

If the message begins with `/skill-name`, the engine routes the request to
that skill. `--preload` keeps a skill warm for the duration of the session.

### `agent33 test`

Run the engine's pytest suite. Equivalent to invoking pytest directly; useful
in CI where you want a stable entry point.

```bash
agent33 test
agent33 test tests/test_agents.py
agent33 test -v
```

Options:

| Option | Purpose |
|--------|---------|
| `--verbose / -v` | Pass `-v` to pytest |

## Sub-app: `agent33 env`

Environment detection and self-adaptation.

### `agent33 env show`

Print the detected hardware profile (OS, CPU, RAM, GPU, disk), available
tools (Docker, Git, Ollama, Node, curl), and a recommended local LLM model.

```bash
agent33 env show
agent33 env show --refresh             # ignore cache, re-detect
agent33 env show --json-output         # JSON
```

Cache lives at `~/.agent33/env.json` and is refreshed on `--refresh`.

## Sub-app: `agent33 tools`

Local tool approval workflow. Tool approvals live in
`~/.agent33/approved-tools.json` and are loaded by the engine on startup.

### `agent33 tools search`

Search for tools by capability description (calls
`GET /v1/discovery/tools`).

```bash
agent33 tools search "send an email"
agent33 tools search "browser" --limit 10
```

Approved tools are marked `[v]` in the listing.

### `agent33 tools approve`

Permanently approve a tool for use by agents.

```bash
agent33 tools approve send_email
agent33 tools approve write_file --reason "team approved for filesystem writes"
```

### `agent33 tools revoke`

Remove a tool from the approval list.

```bash
agent33 tools revoke send_email
```

### `agent33 tools list`

Show all currently approved tools.

```bash
agent33 tools list
```

## Sub-app: `agent33 skills`

Skill discovery against the running engine.

### `agent33 skills search`

Search for skills by capability description (calls
`GET /v1/discovery/skills`).

```bash
agent33 skills search "browser automation"
agent33 skills search "summarize" -n 10
```

### `agent33 skills list`

List skills visible to the current tenant.

```bash
agent33 skills list
agent33 skills list --limit 50
```

## Sub-app: `agent33 packs`

Pack management — local validation, server-side install/enable, registry
search, and updates.

### `agent33 packs validate`

Validate a pack manifest without installing it. Checks the YAML schema and
runs prompt-injection scanning on any `prompt_addenda` sections.

```bash
agent33 packs validate ./my-pack
agent33 packs validate ./my-pack/PACK.yaml --json
```

Exit code is 1 on validation failure.

### `agent33 packs list`

List installed packs via the API.

```bash
agent33 packs list
agent33 packs list --json
```

### `agent33 packs apply`

Apply an installed pack. Supports tenant-wide enablement and session-scoped
overlays.

```bash
agent33 packs apply security-baseline                       # tenant-wide
agent33 packs apply security-baseline --session abcd1234    # session-scoped
agent33 packs apply security-baseline --dry-run             # preview only
```

### `agent33 packs search`

Search the community pack registry.

```bash
agent33 packs search "compliance"
agent33 packs search "research" --tags rag,academic --limit 20
```

### `agent33 packs install`

Download and install a pack from the registry. The server handles the actual
download and SHA-256 verification.

```bash
agent33 packs install research-pro
```

### `agent33 packs update`

Compare installed packs against the registry and report (or apply) updates.

```bash
agent33 packs update                  # check + apply all
agent33 packs update research-pro     # one pack only
agent33 packs update --check          # only check, don't apply
```

### `agent33 packs publish`

Validate a pack and print the publish instructions for your registry. Does
not push anything by itself — produces a registry-entry template you can
include in a PR to your registry.

```bash
agent33 packs publish ./my-pack
```

### `agent33 packs revocation-status`

Check whether a pack has been revoked in the community registry. Designed for
CI pre-install gates; exits with code 1 if the pack is revoked.

```bash
agent33 packs revocation-status my-pack
agent33 packs revocation-status my-pack --version 1.2.0
```

## Sub-app: `agent33 bench`

SkillsBench benchmark evaluation. Requires a checkout of
[SkillsBench](https://github.com/benchflow-ai/skillsbench) for the full suite;
the smoke suite is bundled.

### `agent33 bench smoke`

Fast, deterministic smoke benchmark. Does not call a live LLM. Suitable for
every PR.

```bash
agent33 bench smoke
agent33 bench smoke --baseline baselines/smoke.json --output smoke.json
```

Exit code is 1 if the smoke fails or if a regression is detected against the
baseline.

### `agent33 bench run`

Run the full SkillsBench suite against a live LLM and write a CTRF report.

```bash
agent33 bench run \
  --skillsbench-root ./skillsbench \
  --model llama3.2:3b \
  --agent code-worker \
  --trials 5 \
  --output ctrf-bench.json
```

Options:

| Option | Purpose |
|--------|---------|
| `--skillsbench-root` | Path to a SkillsBench repo checkout |
| `--model / -m` | LLM model identifier (default `llama3.2`) |
| `--agent` | Agent name (default `code-worker`) |
| `--baseline` | CTRF baseline to compare against |
| `--trials / -t` | Trials per task (default 5) |
| `--output / -o` | Output CTRF report path |

### `agent33 bench report`

Display a summary of a CTRF benchmark report.

```bash
agent33 bench report ctrf-bench.json
agent33 bench report ctrf-bench.json --baseline baselines/full.json
agent33 bench report ctrf-bench.json --github-step-summary
```

`--github-step-summary` appends the report markdown to the file pointed to by
`GITHUB_STEP_SUMMARY` (so the summary shows up in GitHub Actions).

## Exit codes

Almost every command follows this convention:

| Code | Meaning |
|------|---------|
| 0    | Success |
| 1    | Validation, API, or precondition failure |
| 2    | Diagnostic command found a hard failure |

Scripts should branch on `agent33 status` and `agent33 diagnose` exit codes
rather than parsing output.

## Environment variables that affect the CLI

| Variable | Used by | Purpose |
|----------|---------|---------|
| `TOKEN` | most subcommands | Bearer token fallback |
| `AGENT33_API_URL` | `packs`, `tools`, `skills`, `env`, `diagnose` | API base URL fallback |
| `AGENT33_PROFILE` | `start` | Profile preset (also read by the engine) |
| `GITHUB_STEP_SUMMARY` | `bench report --github-step-summary` | Path to append summary markdown |

## See also

- [api-reference.md](api-reference.md) — every route the CLI calls.
- [configuration.md](configuration.md) — env var reference.
- [troubleshooting.md](troubleshooting.md) — fixes for common CLI failures.
