# Upgrade guide

Upgrading AGENT-33 means moving from one engine release to the next while
preserving Postgres schema, run history, packs, and tenant credentials. This
guide gives you a repeatable process: backup, upgrade, migrate, smoke, and
rollback.

This page is version-agnostic. For per-release call-outs (deprecations,
breaking changes), check the release notes and the
[upgrade-guide notes for the target version on GitHub Releases](https://github.com/mattmre/AGENT33-PUBLIC/releases).

## Before you begin

1. **Read the release notes** for every version between your current one and
   the target. Skipping minor versions is supported within a major, but read
   the notes for all of them.
2. **Check Python compatibility.** AGENT-33 requires Python 3.11+. Major
   releases may raise this requirement.
3. **Check Postgres compatibility.** `pgvector` must be installed; versions
   below Postgres 14 are not supported.
4. **Pin the source.** Note the current git SHA (`/health` reports it).
   Rollback returns to this SHA, not "latest".
5. **Schedule a window.** Postgres migrations are usually fast (seconds to
   tens of seconds), but plan for downtime during the API restart.

## The upgrade flow

```
backup -> stop -> pull new code -> migrate DB -> start -> smoke -> proceed or rollback
```

Each step is described below. The order matters: never migrate the schema
without a backup, and never start the new code without migrating.

## 1. Take a backup

### Postgres

```bash
# Docker
docker compose exec -T postgres pg_dump -U postgres agent33 > backup-$(date +%F).sql

# Managed Postgres
pg_dump -h $DB_HOST -U $DB_USER -d $DB_NAME > backup-$(date +%F).sql
```

For large databases, prefer `pg_dump -Fc` (custom-format) to a directory,
which allows parallel restore.

### `var/` directory

```bash
tar -czf var-backup-$(date +%F).tgz engine/var/
```

This captures: replay archive, SQLite stores (ingestion, outcomes,
approvals), pack marketplace cache, and rollback snapshots.

### Encryption key

If `ENCRYPTION_KEY` is set, copy it to a secure store. Without it you cannot
decrypt persisted encrypted fields.

## 2. Stop the engine

### Docker Compose

```bash
docker compose stop api frontend
```

Leave the data services (Postgres, Redis, NATS) running.

### Bare metal / systemd

```bash
sudo systemctl stop agent33
sudo systemctl stop agent33-frontend  # if you run one
```

### Kubernetes

```bash
kubectl scale -n agent33 deploy/api --replicas=0
kubectl scale -n agent33 deploy/frontend --replicas=0
```

## 3. Pull the new code

### Docker Compose

If you pin a tag in `docker-compose.yml`:

```yaml
services:
  api:
    image: ghcr.io/mattmre/agent33:v<new-version>
```

then:

```bash
docker compose pull api frontend
```

If you build from source:

```bash
git fetch --tags
git checkout v<new-version>
docker compose build api frontend
```

### Bare metal

```bash
cd /opt/agent33
git fetch --tags
git checkout v<new-version>
cd engine
.venv/bin/pip install --upgrade -e ".[dev]"
```

### Kubernetes

Update the image tag in your manifest and apply:

```bash
kubectl set image deploy/api -n agent33 api=ghcr.io/mattmre/agent33:v<new-version>
kubectl set image deploy/frontend -n agent33 frontend=ghcr.io/mattmre/agent33-frontend:v<new-version>
```

Hold the scale-up until step 5.

## 4. Migrate the database

Run Alembic migrations against the running Postgres.

### Docker Compose

```bash
docker compose run --rm api alembic upgrade head
```

### Bare metal

```bash
cd /opt/agent33/engine
.venv/bin/alembic upgrade head
```

### Kubernetes

A migration job (or one-shot pod) is the cleanest pattern:

```bash
kubectl run agent33-migrate \
  --rm -it --restart=Never \
  --image=ghcr.io/mattmre/agent33:v<new-version> \
  --env=DATABASE_URL=... \
  --command -- alembic upgrade head
```

If migrations fail, do **not** start the new code. Restore the backup
(section 7) and file a bug.

## 5. Start the engine

### Docker Compose

```bash
docker compose up -d api frontend
```

### Bare metal

```bash
sudo systemctl start agent33
sudo systemctl start agent33-frontend
```

### Kubernetes

```bash
kubectl scale -n agent33 deploy/api --replicas=<desired>
kubectl scale -n agent33 deploy/frontend --replicas=<desired>
```

Tail the logs and watch for the lifespan banner. The engine should report
ready within 30-60 seconds.

## 6. Smoke test

A short, scripted smoke covers the major surfaces:

```bash
# 1. Liveness
curl -f http://localhost:8000/healthz

# 2. Full health
curl -s http://localhost:8000/health | jq '.status'

# 3. Auth
TOKEN=$(curl -sX POST http://localhost:8000/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"'"$AUTH_BOOTSTRAP_ADMIN_PASSWORD"'"}' \
  | jq -r .access_token)

# 4. Agent registry survived
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/agents/search | jq 'length'

# 5. Workflows registry survived
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/workflows | jq '.[].name'

# 6. Packs survived
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/packs | jq '.packs | length'

# 7. Trace endpoint reachable
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/traces?limit=1 | jq '.[0].id'

# 8. Run one end-to-end workflow
curl -sX POST http://localhost:8000/v1/workflows/research-assistant/execute \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"inputs":{"topic":"upgrade smoke","depth":"brief"}}' | jq '.run_id'
```

If any step fails, treat the upgrade as failed and roll back.

You can also run:

```bash
agent33 diagnose --json
```

and diff against your pre-upgrade baseline (section 7 of
[ONBOARDING.md](ONBOARDING.md)).

## 7. Rollback

If the smoke test fails or you discover a regression in the first hour:

### Stop the new code

Same commands as section 2.

### Restore the database

```bash
# Docker
cat backup-YYYY-MM-DD.sql | docker compose exec -T postgres \
  psql -U postgres agent33

# Managed Postgres
psql -h $DB_HOST -U $DB_USER -d $DB_NAME < backup-YYYY-MM-DD.sql
```

Some migrations are not reversible (column drops, type changes). If the
forward migration succeeded but the new code is broken, restoring the DB
backup and re-deploying the previous engine image is the safest path.

### Restore `var/`

```bash
tar -xzf var-backup-YYYY-MM-DD.tgz -C engine/
```

### Re-deploy the previous version

Set the image tag (or `git checkout` the prior tag), start, smoke.

## Per-version notes

For specific breaking changes, deprecations, and forced settings changes,
consult the release notes on GitHub. Common themes across releases include:

- **New required environment variables.** A release may introduce a setting
  with no safe default; the engine will refuse to start until you set it.
- **Deprecation removals.** Settings deprecated two minor versions ago are
  removed in the next major. Check your `.env` against
  [configuration.md](configuration.md).
- **Schema migrations that touch hot tables.** For installations with
  hundreds of millions of trace or replay rows, plan extra downtime.
- **Pack manifest schema bumps.** New fields are additive; old packs keep
  working. Removed fields trigger validation warnings before failing.

## Long-lived deployments

For multi-region or zero-downtime deployments:

1. Run migrations in **expand/contract** style: each new release adds
   columns/tables additively; deprecated ones are dropped one release later.
2. Roll API pods one at a time. Old and new pods coexist briefly.
3. Drain workflow workers (if you have any external runners) before
   restarting.
4. Front the API with a load balancer that respects `/readyz`.

Read [operators/horizontal-scaling-architecture.md](operators/horizontal-scaling-architecture.md)
for the full multi-replica picture.

## See also

- [configuration.md](configuration.md) — env var reference with deprecation notes.
- [operators/production-deployment-runbook.md](operators/production-deployment-runbook.md) — green-field production install.
- [runbooks/secret-rotation.md](runbooks/secret-rotation.md) — rotate secrets across an upgrade.
- [troubleshooting.md](troubleshooting.md) — when the smoke fails.
