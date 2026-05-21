# Public Launch and Release Checklist

Use this checklist before treating AGENT-33 as a public-facing or shared deployment.

## Identity and secrets

- [ ] Disable bootstrap auth: `AUTH_BOOTSTRAP_ENABLED=false`
- [ ] Replace `API_SECRET_KEY`
- [ ] Replace `JWT_SECRET`
- [ ] Replace `ENCRYPTION_KEY`
- [ ] Confirm your token-issuing path is not using local defaults
- [ ] Review [SECURITY.md](../SECURITY.md)

## Runtime verification

- [ ] `docker compose up -d` succeeds cleanly
- [ ] `GET /health` returns healthy status
- [ ] UI loads at `http://localhost:3000`
- [ ] Authenticated `GET /v1/agents/` succeeds
- [ ] Authenticated `POST /v1/agents/orchestrator/invoke` succeeds
- [ ] Minimal workflow registration and execution succeeds

## Operator readiness

- [ ] Operators know where the canonical docs live
- [ ] Operators have reviewed [Getting Started](getting-started.md)
- [ ] Operators have reviewed [Operator Onboarding](ONBOARDING.md)
- [ ] Operators have reviewed [API Surface](api-surface.md)
- [ ] Operators have reviewed [Production Deployment Runbook](operators/production-deployment-runbook.md)
- [ ] Operators have reviewed [Operator Verification Runbook](operators/operator-verification-runbook.md)

## Environment posture

- [ ] Ollama connectivity is explicit and tested
- [ ] Database, Redis, and NATS connectivity are verified
- [ ] Environment-specific secrets are stored outside `.env.example`
- [ ] Public-facing URLs and reverse-proxy settings are documented for the deployment

## Observability and operations

- [ ] Health endpoints are monitored
- [ ] Metrics collection path is understood
- [ ] Incident runbooks are available to operators
- [ ] Rollback owner and rollback path are documented
- [ ] Log access and alert-routing expectations are defined

Reference docs:

- [Incident Response Playbooks](operators/incident-response-playbooks.md)
- [Service Level Objectives](operators/service-level-objectives.md)
- [Horizontal Scaling Architecture](operators/horizontal-scaling-architecture.md)

## Product-surface readiness

- [ ] Root `README.md` reflects the current product story
- [ ] Quick-start commands are copy-pasteable
- [ ] Frontend URL and login expectations are documented
- [ ] Security warnings are visible before first public use
- [ ] Release notes link is present

## Known constraints to communicate

- [ ] Several services remain in-memory and reset on restart
- [ ] Webhook routes require explicit adapter registration
- [ ] Some training/runtime wiring is partial by default
- [ ] Baseline repo security scans may still require separate remediation work

## Final go / no-go questions

- [ ] Can a new operator get from clone to first successful agent invocation in one pass?
- [ ] Are there any production-critical defaults still enabled?
- [ ] Are the public docs aligned with the actual shipped runtime surfaces?
- [ ] Is rollback documented before broader exposure?
