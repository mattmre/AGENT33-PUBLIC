# AGENT-33 Load Test Harness

Repeatable load-test harness for the AGENT-33 single-instance deployment
baseline. Built on [Locust](https://locust.io/) for Python-native scenario
authoring and real-time metrics visualization.

## Prerequisites

- Python 3.11+
- A running AGENT-33 instance (local or remote)
- An authentication token with scopes: `agents:invoke`, `sessions:read`,
  `sessions:write`

Install dependencies:

```bash
cd engine
pip install -e ".[dev]"
```

This installs `locust` as part of the dev dependency group.

## Quick Start

Start a local AGENT-33 instance:

```bash
cd engine
docker compose up -d
uvicorn agent33.main:app --host 0.0.0.0 --port 8000
```

Obtain an auth token (see the production deployment runbook for bootstrap
instructions):

```bash
export AUTH_TOKEN="your-jwt-token-here"
```

Run the light scenario:

```bash
cd load-tests
locust -f locustfile.py --config scenarios/light.yaml --auth-token "$AUTH_TOKEN"
```

## Scenarios

All scenario files live in `scenarios/` as Locust-compatible YAML configs.

| Scenario | Users | Spawn Rate | Duration | Purpose |
| --- | --- | --- | --- | --- |
| `light.yaml` | 10 | 2/s | 60s | Post-deploy smoke validation |
| `standard.yaml` | 50 | 5/s | 120s | Normal production workload simulation |
| `stress.yaml` | 200 | 10/s | 180s | Capacity ceiling and failure mode discovery |

Run any scenario:

```bash
locust -f locustfile.py --config scenarios/<scenario>.yaml --auth-token "$AUTH_TOKEN"
```

## User Types (Scenarios)

The locustfile defines four user types that are spawned according to their
relative weights:

### HealthCheckUser (weight: 3)

High-frequency health endpoint polling. Exercises:
- `GET /healthz` -- liveness probe (highest frequency)
- `GET /readyz` -- readiness probe with dependency checks
- `GET /health` -- full aggregated health check

### AgentInvokeUser (weight: 2)

Agent invocation workload. Posts to `POST /v1/agents/{name}/invoke` with
randomly selected agent names and lightweight prompts. Latency depends on
the backing LLM (Ollama by default).

### MetricsScrapeUser (weight: 1)

Simulates Prometheus scraping `GET /metrics` at 10-30s intervals. Validates
the Prometheus exposition endpoint stays responsive under load.

### SessionLifecycleUser (weight: 1)

Full operator session lifecycle:
1. `POST /v1/sessions/` -- create a new session
2. `GET /v1/sessions/{id}` -- query the created session
3. `GET /v1/sessions/?limit=10` -- list recent sessions
4. `POST /v1/sessions/{id}/end` -- end the session

## Authentication

All authenticated endpoints require a Bearer token. Provide it via:

1. Environment variable: `export AUTH_TOKEN="..."`
2. CLI argument: `--auth-token "..."`

If no token is provided, authenticated endpoints will return 401 and Locust
will correctly report these as failures. This is intentional -- an
unconfigured load test should fail visibly rather than silently skip auth
coverage.

## Web UI Mode

For interactive exploration, run without `--headless`:

```bash
locust -f locustfile.py --host http://localhost:8000 --auth-token "$AUTH_TOKEN"
```

Then open http://localhost:8089 and configure users/spawn-rate interactively.

## Interpreting Results

### Locust Output Columns

- **# Requests**: Total requests completed
- **# Fails**: Requests that returned non-2xx or failed validation
- **Median/Avg/p95/p99**: Response time in milliseconds
- **RPS**: Requests per second at measurement time

### Acceptance Criteria

See the [single-instance baseline profile](profiles/single-instance-baseline.md)
for target latencies and failure rate thresholds per endpoint.

### Key Signals

1. **Health endpoint degradation** under load indicates resource exhaustion
   (CPU, memory, or event loop saturation)
2. **Agent invoke p95 > 5s** is expected under stress due to LLM inference
   time; focus on whether health endpoints remain responsive
3. **Session lifecycle failures** under stress may indicate contention in the
   file-backed session storage (documented in the horizontal-scaling
   architecture)
4. **Metrics endpoint latency spikes** suggest the Prometheus collector is
   blocking the event loop

### Exporting Results

Locust supports CSV export:

```bash
locust -f locustfile.py --config scenarios/standard.yaml \
  --auth-token "$AUTH_TOKEN" \
  --csv=results/standard-run
```

This produces `results/standard-run_stats.csv`,
`results/standard-run_failures.csv`, and related files.

## Related Documentation

- [Single-Instance Baseline Profile](profiles/single-instance-baseline.md)
- [Horizontal Scaling Architecture](../docs/operators/horizontal-scaling-architecture.md)
- [Production Deployment Runbook](../docs/operators/production-deployment-runbook.md)
- [Service Level Objectives](../docs/operators/service-level-objectives.md)
- [P1.5 Research Scope](../docs/research/session103-p15-load-harness-scope.md)
