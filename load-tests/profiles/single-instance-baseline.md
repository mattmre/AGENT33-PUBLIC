# Single-Instance Baseline Profile

## Purpose

Define the traffic profile assumptions and acceptance criteria for load
testing the AGENT-33 single-instance Kubernetes deployment. This profile
is the foundation for all three load-test scenarios (light, standard, stress)
and provides the first quantitative performance contract for the production
baseline.

This profile must be read alongside:

- [`../docs/operators/horizontal-scaling-architecture.md`](../../docs/operators/horizontal-scaling-architecture.md)
  -- the guardrail that limits production to `replicas: 1`
- [`../docs/operators/service-level-objectives.md`](../../docs/operators/service-level-objectives.md)
  -- the current SLO baseline (effort-routing telemetry only)

## Deployment Assumptions

| Parameter | Value | Source |
| --- | --- | --- |
| Replica count | 1 | `deploy/k8s/overlays/production/` |
| API framework | FastAPI + Uvicorn (single worker) | `engine/src/agent33/main.py` |
| Python version | 3.11+ | `engine/pyproject.toml` |
| Backing services | PostgreSQL, Redis, NATS, Ollama, SearXNG | `deploy/k8s/base/` |
| State model | Single-process; file-backed orchestration state | horizontal-scaling-architecture.md |
| LLM backend | Ollama (local, model: `llama3.2`) | `config.py` |

## Traffic Profile Rationale

The traffic mix reflects a realistic single-operator or small-team deployment
where monitoring probes dominate request volume, agent invocations are the
primary workload, and session operations are infrequent.

### Request Mix by User Weight

| User Type | Weight | Approx. Traffic Share | Rationale |
| --- | --- | --- | --- |
| HealthCheckUser | 3 | ~43% | Kubernetes liveness/readiness probes + monitoring |
| AgentInvokeUser | 2 | ~29% | Primary API workload |
| MetricsScrapeUser | 1 | ~14% | Prometheus scrape simulation |
| SessionLifecycleUser | 1 | ~14% | Operator session management |

### Scenario Parameters

| Scenario | Concurrent Users | Spawn Rate | Duration | Intent |
| --- | --- | --- | --- | --- |
| Light | 10 | 2/s | 60s | Post-deploy smoke check |
| Standard | 50 | 5/s | 120s | Sustained normal load |
| Stress | 200 | 10/s | 180s | Capacity discovery |

## Acceptance Criteria

### Light Scenario (10 users)

| Endpoint | Metric | Target |
| --- | --- | --- |
| `GET /healthz` | p95 latency | < 50ms |
| `GET /health` | p95 latency | < 100ms |
| `GET /readyz` | p95 latency | < 200ms |
| `GET /metrics` | p95 latency | < 100ms |
| `POST /v1/agents/[name]/invoke` | p95 latency | < 5s |
| `POST /v1/sessions/` | p95 latency | < 1s |
| All endpoints | Failure rate | 0% |
| All endpoints | HTTP 5xx | 0 |

### Standard Scenario (50 users)

| Endpoint | Metric | Target |
| --- | --- | --- |
| `GET /healthz` | p95 latency | < 50ms |
| `GET /health` | p95 latency | < 100ms |
| `GET /readyz` | p95 latency | < 200ms |
| `GET /metrics` | p95 latency | < 200ms |
| `POST /v1/agents/[name]/invoke` | p95 latency | < 5s |
| Session lifecycle | p95 latency | < 2s |
| All endpoints | Failure rate | < 1% |
| Health + metrics | HTTP 5xx | 0 |

### Stress Scenario (200 users)

The stress scenario is designed to find limits, not pass strict SLOs.

| Endpoint | Metric | Expected |
| --- | --- | --- |
| `GET /healthz` | p95 latency | < 200ms |
| `GET /health` | p95 latency | May exceed 100ms |
| `POST /v1/agents/[name]/invoke` | p95 latency | > 5s expected |
| All endpoints | Failure rate | < 5% |

Key signals under stress:
- RPS ceiling before error rate exceeds 5%
- Health endpoint responsiveness during LLM saturation
- Connection pool exhaustion symptoms (Redis, PostgreSQL, NATS timeouts)
- Memory/CPU utilization at peak load (capture externally via `kubectl top`)

## Known Limitations

### LLM Inference Bottleneck

Agent invocation latency is dominated by Ollama inference time, not the
AGENT-33 API itself. Under stress, the Ollama queue depth is the primary
bottleneck. The load test measures end-to-end latency including LLM
inference; isolating API-layer latency requires a stub/mock LLM backend.

### File-Backed State Contention

The session lifecycle scenario creates and ends sessions rapidly. Under
stress, the file-backed session storage may show contention or I/O latency
spikes. This is a known single-instance limitation documented in the
horizontal-scaling architecture.

### Dependency Health Probes

`GET /readyz` and `GET /health` probe external dependencies (Ollama, Redis,
PostgreSQL, NATS) synchronously. Under load, these probes can be slow if
the backing services are also saturated. Readyz latency under stress should
not be compared to the light scenario without accounting for dependency
saturation.

### Auth Token Requirement

All authenticated endpoints (agent invoke, sessions) require a valid JWT
token. If the token expires during a long stress run, failures will spike.
Use a long-lived token or rotate mid-test.

## Future Work

| Item | Slice | Notes |
| --- | --- | --- |
| CI load-gate automation | P1.7 | Run standard scenario as PR gate |
| Multi-replica load profile | P1.2+ | New profile after scaling blockers resolved |
| Stub LLM backend profile | Future | Isolate API-layer latency from inference |
| Connection pool tuning | Future | Derive from stress scenario results |
