# CLI Reference

Complete reference for the `agent33` command-line interface.

---

## Overview

The `agent33` CLI provides commands to scaffold agent and workflow definitions, execute workflows against a running AGENT-33 server, run tests, and check system health. It is built with Typer and communicates with the engine API over HTTP.

---

## Installation

```bash
pip install agent33
```

Or from the repository:

```bash
cd engine
pip install -e .
```

After installation the `agent33` command is available on your PATH.

---

## Commands

### agent33 init

Scaffold a new agent or workflow definition file.

```
agent33 init NAME [OPTIONS]
```

#### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `NAME` | Yes | Name of the agent or workflow to scaffold |

#### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--kind` | `-k` | `agent` | Type of definition: `agent` or `workflow` |
| `--output` | `-o` | `.` | Directory to write the scaffolded file into |

#### Generated Files

When `--kind agent`, creates `NAME.agent.json` with the following structure:

```json
{
  "name": "my-agent",
  "version": "0.1.0",
  "role": "worker",
  "description": "my-agent agent",
  "capabilities": [],
  "inputs": {
    "query": {
      "type": "string",
      "description": "Input query",
      "required": true
    }
  },
  "outputs": {
    "result": {
      "type": "string",
      "description": "Output result"
    }
  },
  "dependencies": [],
  "prompts": {
    "system": "",
    "user": "",
    "examples": []
  },
  "constraints": {
    "max_tokens": 4096,
    "timeout_seconds": 120,
    "max_retries": 2,
    "parallel_allowed": true
  },
  "metadata": {
    "author": "",
    "tags": []
  }
}
```

When `--kind workflow`, creates `NAME.workflow.json` with:

```json
{
  "name": "my-workflow",
  "version": "0.1.0",
  "description": "my-workflow workflow",
  "triggers": {
    "manual": true
  },
  "inputs": {},
  "outputs": {},
  "steps": [
    {
      "id": "step-1",
      "name": "First step",
      "action": "invoke-agent",
      "agent": "my-agent",
      "inputs": {},
      "outputs": {}
    }
  ],
  "execution": {
    "mode": "sequential"
  },
  "metadata": {
    "author": "",
    "tags": []
  }
}
```

#### Examples

```bash
# Scaffold a new agent definition
agent33 init research-assistant

# Scaffold a workflow into a specific directory
agent33 init data-pipeline --kind workflow --output ./definitions

# Scaffold an agent with short flags
agent33 init summarizer -k agent -o ./agents
```

---

### agent33 run

Execute a workflow by name via the AGENT-33 API.

```
agent33 run WORKFLOW [OPTIONS]
```

#### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `WORKFLOW` | Yes | Name of the workflow to execute |

#### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--base-url` | `-b` | `http://localhost:8000` | API base URL |
| `--inputs` | `-i` | None | JSON string of workflow inputs |

The command sends a POST request to `/api/v1/workflows/run` and prints the JSON response to stdout.

#### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Workflow executed successfully |
| 1 | Invalid JSON inputs, HTTP error, or connection failure |

#### Examples

```bash
# Run a workflow with defaults
agent33 run data-pipeline

# Run with inputs
agent33 run summarize -i '{"text": "Long article content...", "max_length": 200}'

# Run against a remote server
agent33 run deploy-check -b https://agent33.example.com

# Capture output to a file
agent33 run analysis -i '{"query": "revenue trends"}' > result.json
```

---

### agent33 test

Run the test suite using pytest.

```
agent33 test [PATH] [OPTIONS]
```

#### Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `PATH` | No | `tests` | Path to the test directory or file |

#### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--verbose` | `-v` | False | Enable verbose pytest output |

The exit code matches the pytest exit code (0 for all tests passed, 1+ for failures).

#### Examples

```bash
# Run all tests
agent33 test

# Run a specific test file with verbose output
agent33 test tests/test_workflows.py -v

# Run a test directory
agent33 test tests/integration
```

---

### agent33 status

Show system health by calling the `/health` endpoint.

```
agent33 status [OPTIONS]
```

#### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--base-url` | `-b` | `http://localhost:8000` | API base URL |

#### Example Output

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "uptime_seconds": 3421,
  "agents_loaded": 5,
  "workflows_loaded": 3
}
```

#### Examples

```bash
# Check local server health
agent33 status

# Check remote server
agent33 status -b https://agent33.example.com
```

---

## Environment Variables

The CLI respects the following environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT33_BASE_URL` | `http://localhost:8000` | Default API base URL (overridden by `--base-url`) |
| `AGENT33_API_KEY` | None | API key for authenticated requests |
| `AGENT33_CONFIG` | None | Path to a configuration file |
| `AGENT33_LOG_LEVEL` | `INFO` | Logging verbosity: DEBUG, INFO, WARNING, ERROR |
| `NO_COLOR` | None | When set, disables colored output |

---

## Integration with Other Tools

### Piping Output

All commands that produce JSON write to stdout, making them composable with `jq` and other tools.

```bash
# Extract workflow status from run output
agent33 run my-workflow | jq '.status'

# Pretty-print health check
agent33 status | jq .

# Feed workflow output into another command
agent33 run extract-data -i '{"source": "db"}' | jq '.data[]' | wc -l
```

### Scripting

```bash
#!/usr/bin/env bash
set -euo pipefail

# Scaffold, run, and verify
agent33 init my-pipeline -k workflow -o ./defs

# Start workflow and check result
RESULT=$(agent33 run my-pipeline -i '{"input": "value"}')
STATUS=$(echo "$RESULT" | jq -r '.status')

if [ "$STATUS" != "success" ]; then
  echo "Workflow failed: $RESULT" >&2
  exit 1
fi

echo "Workflow completed successfully."
```

### CI/CD Usage

```yaml
# GitHub Actions example
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install agent33
      - run: agent33 test tests/ -v

  health-check:
    runs-on: ubuntu-latest
    needs: deploy
    steps:
      - run: pip install agent33
      - run: agent33 status -b ${{ vars.AGENT33_URL }}
```

```yaml
# GitLab CI example
test:
  script:
    - pip install agent33
    - agent33 test -v

smoke-test:
  stage: deploy
  script:
    - agent33 run smoke-check -b "$AGENT33_BASE_URL"
    - agent33 status -b "$AGENT33_BASE_URL"
```

---

## Common Workflows

### 1. Create and Run a New Agent Pipeline

```bash
# Step 1: Scaffold the agent
agent33 init data-fetcher -k agent -o ./agents

# Step 2: Scaffold the workflow that uses it
agent33 init fetch-pipeline -k workflow -o ./workflows

# Step 3: Edit the generated files to configure inputs/outputs
# (Edit agents/data-fetcher.agent.json and workflows/fetch-pipeline.workflow.json)

# Step 4: Start the server (separate terminal)
# python -m agent33.main

# Step 5: Run the workflow
agent33 run fetch-pipeline -i '{"url": "https://example.com/data"}'
```

### 2. Health Monitoring Script

```bash
#!/usr/bin/env bash
# Poll health every 30 seconds
while true; do
  if ! agent33 status -b "$AGENT33_BASE_URL" > /dev/null 2>&1; then
    echo "[$(date)] AGENT-33 is DOWN" >&2
  fi
  sleep 30
done
```

### 3. Batch Workflow Execution

```bash
#!/usr/bin/env bash
# Run a workflow for each input file
for FILE in data/*.json; do
  INPUTS=$(cat "$FILE")
  echo "Processing $FILE..."
  agent33 run process-data -i "$INPUTS" > "results/$(basename "$FILE")"
done
```

### 4. Test Before Deploy

```bash
#!/usr/bin/env bash
set -euo pipefail

# Run unit tests
agent33 test tests/unit -v

# Run integration tests
agent33 test tests/integration -v

# If all pass, deploy and verify
# ... deploy steps ...
agent33 status -b "$PRODUCTION_URL"
```
