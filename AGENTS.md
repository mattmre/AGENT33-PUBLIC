# AGENTS.md

Repository-level rules for coding agents working in this repository.

## CI policy

GitHub Actions is **not used** in this repository, by Matt's decision (2026-10-17). This repo is public, so
hosted minutes are free, but the hosted runs still failed and sent failure email. One example is the
scheduled "Benchmarks Weekly" job, which fails at a `git` step with exit code 128. Matt does not use or
maintain GitHub Actions.

Rules for every agent and contributor:

1. Do **not** add, restore, or re-enable GitHub Actions workflows, triggers (`push`, `pull_request`,
   `schedule`, `workflow_run`, `release`, tags), Dependabot-driven workflows, or self-hosted GitHub runners.
   Files kept under `.github/workflows/` are retained only as reference and as a source for a future local
   runner. Their `on:` block is `workflow_dispatch` only, so nothing runs automatically.
2. Do not wait for, rerun, fund, or cite GitHub Actions results. A hosted run that failed or never started
   is neither a pass nor a product failure.
3. Before you open or update a PR, run the checks below locally from a clean checkout of the exact revision.
   Record the commands and results in the PR body.
4. Merges need Matt's explicit sign-off. Agents never merge.

### Local checks (taken from `.github/workflows/ci.yml` and friends; run from `engine/`)

```bash
cd engine
pip install -e ".[dev]"
python scripts/check_import_boundaries.py
python scripts/check_runtime_compatibility.py
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/
pytest --cov=agent33 --cov-report=term-missing -x -q
docker compose build
pip install hatchling && python -m hatchling build --target wheel && pip install dist/*.whl && agent33 --help
python scripts/check_runtime_compatibility.py --check-upstream     # runtime-compatibility.yml (weekly)
scripts/docker-smoke-test.sh engine/docker-compose.yml             # docker-smoke.yml (from repo root)
```

Security scans (`security-scan.yml`) used Trivy (fs/config/secrets/image). Run Trivy locally when a change
touches dependencies or images.

### Local CI on the Spark boxes (planned)

Local CI will run on the NVIDIA GB10 Spark boxes (gx10-eba1, gx10-6724). It is planned but not
installed yet. The plan is a self-hosted Forgejo/Gitea forge that mirrors this repo, plus a CPU-capped
`forgejo-runner`/`act_runner`. That runner can run the GitHub-Actions-format YAML above without GitHub. Until
it exists, the commands above are the CI. Do not point workflows at GitHub-hosted or GitHub self-hosted
runners as a workaround.
