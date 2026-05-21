# Security Audit Checklist

## Purpose

Track periodic security maintenance tasks for the AGENT-33 deployment.
This document consolidates all dependency, container, and CI security
audit procedures into a single operator reference.

## Dependency Audit

### Python Dependencies

- Run `scripts/dependency-audit.sh` to check installed packages for known CVEs
  via [pip-audit](https://pypi.org/project/pip-audit/).  The script installs
  pip-audit on-demand so it does not need to be a project dependency.
- Review `engine/pyproject.toml` for pinned version ranges that may need
  bumping (current pins use lower-bounded ranges, e.g. `fastapi>=0.115.6,<1`).
- Check `engine/uv.lock` for transitive dependency vulnerabilities.  A full
  `uv lock --check` validates that the lockfile is consistent with the declared
  dependency ranges.

### Docker Base Image

- Current base image: `python:3.11.13-slim-trixie` (pinned by digest in
  `engine/Dockerfile`).
- The production Dockerfile already runs `apt-get update && apt-get upgrade`
  at build time so that OS packages reflect the current Debian security
  repository state rather than a stale upstream snapshot.
- Run `docker pull` and `trivy image` against the pinned image to verify no
  new CRITICAL/HIGH CVEs have appeared since the last build.
- The `scripts/verify_trivy_image.py` script validates that specific blocked
  CVE IDs (e.g. `CVE-2026-0861`) are absent from a Trivy JSON report.  It is
  invoked automatically in the `trivy-image` CI job.

### GitHub Actions

- Dependabot (`.github/dependabot.yml`) tracks weekly version bumps for the
  `github-actions` ecosystem.
- Node.js 24 migration deadline: June 2, 2026.  Actions still on Node 20 are
  annotated with `TODO(node24)` comments in
  `.github/workflows/security-scan.yml`:
  - `actions/cache@v4` -- awaiting v5 for Node 24
  - `aquasecurity/trivy-action` -- pinned at v0.35.0 by commit SHA
  - `github/codeql-action@v3` -- awaiting v4 for Node 24
  - `anthropics/claude-code-action@beta` -- tracks latest; verify Node 24
    compatibility at deadline
- Review `actions/checkout` (currently v5, Node 24 ready) and
  `actions/setup-python` for new major versions.

## CI Security Scans

All scans are defined in `.github/workflows/security-scan.yml` and run on
every push to `main` and every pull request targeting `main`.

| Job | What it checks | Exit-code policy |
|-----|---------------|-----------------|
| `trivy-fs` | Python dependency CVEs (`./engine` filesystem) | Fails on CRITICAL/HIGH |
| `trivy-image` | Built Docker container image CVEs | Fails on CRITICAL/HIGH (unfixed ignored) |
| `trivy-config` | IaC misconfiguration (`./engine`) | Advisory (exit 0) |
| `trivy-secrets` | Secret leak detection (full repo) | Fails on CRITICAL/HIGH/MEDIUM |
| `trivy-sarif` | SARIF upload to GitHub Security tab | Advisory (exit 0) |
| `claude-code-security` | AI-assisted security review on PRs | Advisory (`continue-on-error: true`) |

### Targeted CVE Verification

The `trivy-image` job exports a JSON report and passes it to
`scripts/verify_trivy_image.py` to assert that specific blocked CVEs are no
longer present.  To add a new blocked CVE:

1. Add the CVE ID to the `Verify runtime image` step arguments in
   `.github/workflows/security-scan.yml`.
2. If the CVE is an OS-level package issue, ensure the Dockerfile
   `apt-get upgrade` resolves it; if not, pin a fixed package version
   explicitly.

### GitGuardian

GitGuardian scans PR history (not just current file contents).  If an alert
fires on an earlier commit in a PR, the branch history must be rewritten to
a clean commit before re-pushing.

## Audit Schedule

| Check | Frequency | Owner | Automation |
|-------|-----------|-------|------------|
| pip-audit | Monthly | Platform | `scripts/dependency-audit.sh` |
| Docker base image Trivy | On each PR | CI | `.github/workflows/security-scan.yml` |
| Python dependency versions | Monthly | Platform | Manual review of `pyproject.toml` |
| GitHub Actions versions | Weekly | Dependabot | `.github/dependabot.yml` |
| Alembic migration chain | On each PR | CI | `test_alembic_migration_chain.py` |
| Trivy IaC / secrets | On each PR | CI | `.github/workflows/security-scan.yml` |
| Node.js 24 action audit | Before June 2, 2026 | Platform | `TODO(node24)` markers |

## Referenced Files

- `engine/Dockerfile` -- production container build
- `engine/pyproject.toml` -- Python dependency declarations
- `engine/uv.lock` -- resolved dependency lockfile
- `.github/workflows/security-scan.yml` -- Trivy and security CI
- `.github/dependabot.yml` -- Dependabot configuration
- `scripts/dependency-audit.sh` -- on-demand pip-audit runner
- `scripts/verify_trivy_image.py` -- targeted CVE verification script
- `docs/operators/production-deployment-runbook.md` -- deployment procedure
- `docs/operators/incident-response-playbooks.md` -- incident response

## Last Audit

- **Date**: 2026-03-24 (P3.12)
- **Python deps**: Trivy filesystem scan passing in CI (CRITICAL/HIGH gate)
- **Docker image**: Trivy image scan passing; `CVE-2026-0861` verified absent
- **Actions**: `checkout@v5` (Node 24 ready); remaining actions tracked via
  `TODO(node24)` for June 2026 deadline
- **Dependabot**: Active for `github-actions` ecosystem (weekly schedule)
