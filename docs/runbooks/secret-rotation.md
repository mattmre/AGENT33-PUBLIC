# Kubernetes Secret Rotation Runbook

## Overview

This runbook covers rotation procedures for all secrets consumed by the
AGENT-33 engine in a Kubernetes deployment. It applies to the two Secret
objects defined in `deploy/k8s/base/`:

- `agent33-api-secrets` -- API keys, JWT signing, encryption key
- `agent33-postgres-secrets` -- PostgreSQL credentials

Secrets are classified into four tiers based on rotation complexity and blast
radius. Each tier has its own procedure below.

### When to Rotate

- **Scheduled**: per the rotation cadence table at the end of this document.
- **Reactive**: immediately upon suspected compromise, employee departure with
  access, or security audit finding.
- **Proactive**: before any secret reaches its maximum age policy.

## Prerequisites

1. `kubectl` authenticated with cluster credentials and access to the
   `agent33` namespace.
2. Ability to generate cryptographically secure random values (e.g.,
   `openssl rand`).
3. A recent database backup (for ENCRYPTION_KEY and POSTGRES_PASSWORD
   rotations).
4. Awareness of the current replica count. Check before starting:

```bash
kubectl get deploy agent33-api -n agent33 -o jsonpath='{.spec.replicas}'
kubectl get statefulset postgres -n agent33 -o jsonpath='{.spec.replicas}'
```

5. Access to external provider dashboards (OpenAI, ElevenLabs, etc.) if
   rotating third-party API keys.

### Notation

Throughout this document:

- `NS=agent33` is assumed. Adjust if you deploy to a different namespace.
- All `kubectl` commands include `-n agent33` explicitly.
- `openssl rand -base64 32` produces a 256-bit random value suitable for most
  secrets. Use `-hex 32` when a hex-encoded value is required.

## 1. Critical Secrets

These secrets cause immediate service disruption or data loss if rotated
without coordination.

---

### 1.1 JWT_SECRET

**Secret object**: `agent33-api-secrets`, key `JWT_SECRET`
**Impact**: All active JWT tokens become invalid immediately. Every
authenticated session is terminated.

**Zero-downtime rotation is not supported** for this secret because the engine
does not implement dual-key JWT verification. Plan a brief maintenance window
or accept that all users must re-authenticate.

#### Procedure

1. Generate a new secret value:

```bash
NEW_JWT_SECRET=$(openssl rand -base64 32)
echo "New JWT_SECRET: $NEW_JWT_SECRET"
```

2. Notify users of an upcoming authentication reset (if applicable).

3. Patch the Kubernetes secret:

```bash
kubectl patch secret agent33-api-secrets -n agent33 \
  -p "{\"stringData\":{\"JWT_SECRET\":\"$NEW_JWT_SECRET\"}}"
```

4. Perform a rolling restart of the API deployment:

```bash
kubectl rollout restart deployment/agent33-api -n agent33
kubectl rollout status deployment/agent33-api -n agent33 --timeout=300s
```

5. Verify the new pods are healthy:

```bash
kubectl get pods -n agent33 -l app.kubernetes.io/name=agent33-api
```

6. Confirm authentication works with a fresh token. See the Verification
   section below.

#### Rollback

If the new value is lost or misrecorded, there is no way to recover the
previous JWT_SECRET from the cluster after it has been overwritten. Keep a
record of the old value in your secrets manager before patching.

```bash
# Save old value BEFORE patching
kubectl get secret agent33-api-secrets -n agent33 \
  -o jsonpath='{.data.JWT_SECRET}' | base64 -d
```

---

### 1.2 ENCRYPTION_KEY

**Secret object**: `agent33-api-secrets`, key `ENCRYPTION_KEY`
**Impact**: The CredentialVault uses AES-256-GCM encryption. Rotating this key
without re-encrypting stored credentials makes all vault entries unreadable.

The CredentialVault is currently in-memory (`security/vault.py`), meaning vault
entries do not persist across restarts. If your deployment does not persist
vault entries externally, rotation is simpler -- a restart with the new key
starts with an empty vault.

If you have added persistent vault storage, you must re-encrypt all entries
before rotating.

#### Procedure (in-memory vault)

1. Generate a new 256-bit key:

```bash
NEW_ENCRYPTION_KEY=$(python3 -c "
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import base64
print(base64.urlsafe_b64encode(AESGCM.generate_key(256)).decode())
")
echo "New ENCRYPTION_KEY: $NEW_ENCRYPTION_KEY"
```

2. Patch the Kubernetes secret:

```bash
kubectl patch secret agent33-api-secrets -n agent33 \
  -p "{\"stringData\":{\"ENCRYPTION_KEY\":\"$NEW_ENCRYPTION_KEY\"}}"
```

3. Rolling restart:

```bash
kubectl rollout restart deployment/agent33-api -n agent33
kubectl rollout status deployment/agent33-api -n agent33 --timeout=300s
```

4. Re-inject any vault credentials that were previously stored via the API.

#### Procedure (persistent vault -- future)

If vault persistence is added in a future phase:

1. Before rotating, export all vault entries using the old key.
2. Generate the new key (as above).
3. Re-encrypt all entries with the new key.
4. Patch the secret and restart.
5. Verify vault retrieval works for all stored credentials.

This procedure will be updated when persistent vault storage is implemented.

---

### 1.3 POSTGRES_PASSWORD

**Secret object**: `agent33-postgres-secrets`, key `POSTGRES_PASSWORD`
**Impact**: The API deployment constructs `DATABASE_URL` from this value. The
PostgreSQL StatefulSet also reads it. Changing one without the other breaks
database connectivity.

**Zero-downtime rotation is possible** but requires careful ordering.

#### Procedure

1. Generate a new password:

```bash
NEW_PG_PASS=$(openssl rand -base64 24)
echo "New POSTGRES_PASSWORD: $NEW_PG_PASS"
```

2. Save the current password (for rollback):

```bash
OLD_PG_PASS=$(kubectl get secret agent33-postgres-secrets -n agent33 \
  -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)
echo "Old POSTGRES_PASSWORD: $OLD_PG_PASS"
```

3. Add the new password to PostgreSQL using the old credentials. Exec into the
   running pod:

```bash
kubectl exec -n agent33 statefulset/postgres -- psql \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "ALTER USER agent33_app PASSWORD '$NEW_PG_PASS';"
```

   If env vars are not available in the exec shell, retrieve them first:

```bash
PG_USER=$(kubectl get secret agent33-postgres-secrets -n agent33 \
  -o jsonpath='{.data.POSTGRES_USER}' | base64 -d)
PG_DB=$(kubectl get secret agent33-postgres-secrets -n agent33 \
  -o jsonpath='{.data.POSTGRES_DB}' | base64 -d)

kubectl exec -n agent33 statefulset/postgres -- psql \
  -U "$PG_USER" -d "$PG_DB" \
  -c "ALTER USER $PG_USER PASSWORD '$NEW_PG_PASS';"
```

4. Update the Kubernetes secret:

```bash
kubectl patch secret agent33-postgres-secrets -n agent33 \
  -p "{\"stringData\":{\"POSTGRES_PASSWORD\":\"$NEW_PG_PASS\"}}"
```

5. Rolling restart the API deployment so it picks up the new DATABASE_URL:

```bash
kubectl rollout restart deployment/agent33-api -n agent33
kubectl rollout status deployment/agent33-api -n agent33 --timeout=300s
```

6. The PostgreSQL StatefulSet reads `POSTGRES_PASSWORD` via `envFrom`, but
   PostgreSQL itself only uses this env var at initial database creation (via
   the Docker entrypoint). A running PostgreSQL instance does not re-read the
   env var, so the StatefulSet does not need a restart after step 3. However,
   if the StatefulSet is ever recreated, it will use the new secret value.

7. Verify connectivity:

```bash
kubectl exec -n agent33 deploy/agent33-api -- python3 -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
import os
engine = create_async_engine(os.environ['DATABASE_URL'])
async def check():
    async with engine.connect() as conn:
        result = await conn.execute(__import__('sqlalchemy').text('SELECT 1'))
        print('DB OK:', result.scalar())
asyncio.run(check())
"
```

#### Rollback

If the API cannot connect after rotation:

```bash
# Revert PostgreSQL password
kubectl exec -n agent33 statefulset/postgres -- psql \
  -U "$PG_USER" -d "$PG_DB" \
  -c "ALTER USER $PG_USER PASSWORD '$OLD_PG_PASS';"

# Revert Kubernetes secret
kubectl patch secret agent33-postgres-secrets -n agent33 \
  -p "{\"stringData\":{\"POSTGRES_PASSWORD\":\"$OLD_PG_PASS\"}}"

# Restart API
kubectl rollout restart deployment/agent33-api -n agent33
```

## 2. Standard Secrets

These secrets can be rotated with a simple patch-and-restart cycle. No
additional coordination is needed beyond updating the K8s secret and
restarting the API pods.

**Applies to**:

| Key | Secret Object | Purpose |
|-----|---------------|---------|
| `API_SECRET_KEY` | `agent33-api-secrets` | FastAPI app signing |
| `AUTH_BOOTSTRAP_ADMIN_PASSWORD` | `agent33-api-secrets` | Initial admin bootstrap |
| `OPENAI_API_KEY` | `agent33-api-secrets` | OpenAI LLM provider |
| `ELEVENLABS_API_KEY` | `agent33-api-secrets` | ElevenLabs TTS |
| `JINA_API_KEY` | `agent33-api-secrets` | Jina embeddings/reader |
| `BROWSER_CLOUD_API_KEY` | env / secret | BrowserBase (Phase 55) |
| `VOICE_DAEMON_API_KEY` | env / secret | Voice daemon |
| `VOICE_DAEMON_API_SECRET` | env / secret | Voice daemon |
| `VOICE_ELEVENLABS_API_KEY` | env / secret | Voice ElevenLabs |
| `VOICE_LIVEKIT_API_KEY` | env / secret | LiveKit |
| `VOICE_LIVEKIT_API_SECRET` | env / secret | LiveKit |

LLM provider keys loaded from environment (auto-registered in
`llm/providers.py`):

| Env Var | Provider |
|---------|----------|
| `ANTHROPIC_API_KEY` | Anthropic |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI |
| `GROQ_API_KEY` | Groq |
| `TOGETHER_API_KEY` | Together AI |
| `MISTRAL_API_KEY` | Mistral |
| `FIREWORKS_API_KEY` | Fireworks AI |
| `DEEPSEEK_API_KEY` | DeepSeek |
| `PERPLEXITY_API_KEY` | Perplexity |
| `ANYSCALE_API_KEY` | Anyscale |
| `COHERE_API_KEY` | Cohere |
| `GOOGLE_API_KEY` | Google AI |
| `XAI_API_KEY` | xAI |
| `OPENROUTER_API_KEY` | OpenRouter |
| `REPLICATE_API_KEY` | Replicate |
| `HUGGINGFACE_API_KEY` | Hugging Face |
| `CEREBRAS_API_KEY` | Cerebras |

### Procedure

1. Generate or obtain the new key from the provider's dashboard.

2. If the key is in `agent33-api-secrets`:

```bash
kubectl patch secret agent33-api-secrets -n agent33 \
  -p "{\"stringData\":{\"KEY_NAME\":\"new-value-here\"}}"
```

   If the key is in a separate secret or injected via another mechanism,
   patch that object instead.

3. Rolling restart:

```bash
kubectl rollout restart deployment/agent33-api -n agent33
kubectl rollout status deployment/agent33-api -n agent33 --timeout=300s
```

4. Verify the health endpoint reports no provider errors:

```bash
kubectl exec -n agent33 deploy/agent33-api -- \
  curl -s http://localhost:8000/readyz | python3 -m json.tool
```

5. Revoke the old key in the provider's dashboard after confirming the new
   key works.

### Notes on API_SECRET_KEY

Rotating `API_SECRET_KEY` may invalidate any tokens or signatures that depend
on it. The `config.py` validator warns if the default value is in use. Treat
this with the same session-invalidation awareness as JWT_SECRET, though its
blast radius is smaller.

### Notes on AUTH_BOOTSTRAP_ADMIN_PASSWORD

This password is only used during initial admin user creation when
`AUTH_BOOTSTRAP_ENABLED=true`. In steady-state operation with bootstrap
disabled, rotating this value has no runtime effect. Rotate it anyway to
prevent re-use if bootstrap is ever re-enabled.

## 3. Coordinated Secrets

These require alignment with external parties or secondary systems.

---

### 3.1 Webhook HMAC Secrets

**Location**: Stored per-webhook in the webhook registry (not in K8s secrets).
Each `WebhookTrigger` has its own `secret` field used for HMAC-SHA256
signature validation (`automation/webhooks.py`).

**Constraint**: The sender (external system) and AGENT-33 (receiver) must
agree on the same secret. Rotating one side without the other causes signature
validation failures and dropped webhooks.

#### Procedure

1. Generate a new HMAC secret:

```bash
NEW_HMAC=$(openssl rand -hex 32)
```

2. Update the webhook secret in the external system (GitHub, GitLab, etc.)
   first. Most platforms let you set the new secret without immediately
   invalidating the old one.

3. Update the webhook registration in AGENT-33 via the API:

```bash
curl -X PATCH http://localhost:8000/v1/webhooks/<webhook-id> \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"secret\": \"$NEW_HMAC\"}"
```

4. Send a test payload from the external system to verify signature
   validation passes.

5. If validation fails, revert the external system's secret to the old value
   and investigate.

---

### 3.2 Messaging Platform Tokens

**Applies to**: Telegram bot tokens, Discord bot tokens, Slack app tokens,
WhatsApp API tokens.

These tokens are issued by the respective platforms. AGENT-33 consumes them
via environment variables and the NATS-based messaging adapters
(`messaging/`).

#### Procedure

1. Rotate the token in the platform's developer dashboard:
   - **Telegram**: Talk to @BotFather, `/revoke`, then `/newbot` or
     `/token` to regenerate.
   - **Discord**: Developer Portal > Bot > Reset Token.
   - **Slack**: App Management > OAuth & Permissions > Rotate Tokens.
   - **WhatsApp**: Meta Business Suite > API Setup > Generate new token.

2. Update the corresponding K8s secret or env var:

```bash
kubectl patch secret agent33-api-secrets -n agent33 \
  -p "{\"stringData\":{\"TELEGRAM_BOT_TOKEN\":\"new-token\"}}"
```

3. Rolling restart and verify the messaging adapter health:

```bash
kubectl rollout restart deployment/agent33-api -n agent33
# Check adapter health via the /health endpoint
kubectl exec -n agent33 deploy/agent33-api -- \
  curl -s http://localhost:8000/health | python3 -m json.tool
```

4. Send a test message through the platform to confirm end-to-end
   connectivity.

---

### 3.3 PACK_SIGNING_KEY

**Config field**: `pack_signing_key` (plain string, not SecretStr)
**Impact**: All previously signed skill packs become unverifiable with a new
key. If `pack_checksums_required=true`, those packs will fail integrity checks
at load time.

#### Procedure

1. Generate a new signing key:

```bash
NEW_SIGNING_KEY=$(openssl rand -hex 32)
```

2. Re-sign all existing packs with the new key before deploying:

```bash
# Re-sign each pack in the packs directory
# (exact command depends on pack tooling -- adapt as needed)
for pack in packs/*/; do
  agent33 pack sign "$pack" --key "$NEW_SIGNING_KEY"
done
```

3. Update the K8s secret or configmap with the new key.

4. Rolling restart. The new pods will verify packs against the new key.

5. Verify all packs load correctly:

```bash
kubectl logs -n agent33 deploy/agent33-api --tail=50 | grep -i pack
```

## 4. Infrastructure Gaps

The following infrastructure components currently have no authentication
configured in the K8s manifests. This is a known gap.

### Redis

`deploy/k8s/base/redis-deployment.yaml` does not set `requirepass`. Any pod
in the namespace can connect to Redis without credentials.

**Recommendation**: Add Redis AUTH by:
1. Setting `requirepass` in a Redis ConfigMap or Secret.
2. Adding `REDIS_PASSWORD` to the API deployment env.
3. Updating the Redis connection URL in the application config.

### NATS

`deploy/k8s/base/nats-deployment.yaml` does not configure authentication.

**Recommendation**: Enable NATS token or NKey authentication and inject
credentials into both the NATS server config and the API deployment env.

These gaps should be addressed before any production deployment. Until then,
rely on Kubernetes NetworkPolicy to restrict access to these services.

## 5. Verification

After any rotation, run through these checks.

### Health Endpoints

```bash
# Lightweight process check
kubectl exec -n agent33 deploy/agent33-api -- curl -sf http://localhost:8000/healthz

# Dependency-aware readiness (postgres, redis, nats, ollama)
kubectl exec -n agent33 deploy/agent33-api -- curl -sf http://localhost:8000/readyz

# Full diagnostic
kubectl exec -n agent33 deploy/agent33-api -- curl -s http://localhost:8000/health
```

### Authentication

```bash
# Obtain a fresh JWT token
TOKEN=$(curl -s -X POST http://<INGRESS>/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<password>"}' | python3 -c "
import sys, json; print(json.load(sys.stdin)['access_token'])")

# Use the token to call a protected endpoint
curl -s -H "Authorization: Bearer $TOKEN" http://<INGRESS>/v1/agents/ | head -c 200
```

### Database Connectivity

```bash
kubectl exec -n agent33 deploy/agent33-api -- python3 -c "
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
async def check():
    e = create_async_engine(os.environ['DATABASE_URL'])
    async with e.connect() as c:
        r = await c.execute(text('SELECT version()'))
        print('OK:', r.scalar()[:60])
asyncio.run(check())
"
```

### LLM Provider Keys

```bash
# Quick smoke test for OpenAI
kubectl exec -n agent33 deploy/agent33-api -- python3 -c "
import os, urllib.request, json
req = urllib.request.Request(
    os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com') + '/v1/models',
    headers={'Authorization': f'Bearer {os.environ[\"OPENAI_API_KEY\"]}'}
)
resp = urllib.request.urlopen(req, timeout=10)
data = json.loads(resp.read())
print(f'OK: {len(data.get(\"data\", []))} models available')
"
```

### Pod Status

```bash
# All pods should be Running with no restarts
kubectl get pods -n agent33 -o wide

# Check for crash loops or secret-related errors
kubectl describe pods -n agent33 -l app.kubernetes.io/name=agent33-api | grep -A5 "Events:"
```

## 6. Emergency Procedures

### Symptoms of a Failed Rotation

- Pods in `CrashLoopBackOff` with `FATAL: jwt_secret` or `SystemExit` in logs
- `/readyz` returning 503 with database connection errors
- All API calls returning 401 Unauthorized
- CredentialVault raising decryption errors in logs

### Immediate Triage

```bash
# Check pod logs for the most recent error
kubectl logs -n agent33 deploy/agent33-api --tail=100 --since=5m

# Check events
kubectl get events -n agent33 --sort-by='.lastTimestamp' | tail -20
```

### Rollback Procedure

If you saved the old secret value before patching (as recommended in each
procedure above):

```bash
# Revert the specific key
kubectl patch secret agent33-api-secrets -n agent33 \
  -p "{\"stringData\":{\"KEY_NAME\":\"old-value-here\"}}"

# Restart
kubectl rollout restart deployment/agent33-api -n agent33
kubectl rollout status deployment/agent33-api -n agent33 --timeout=300s
```

If the old value was not saved, the only recovery path is to generate a new
value and accept the consequences (session invalidation for JWT_SECRET, vault
data loss for ENCRYPTION_KEY, etc.).

### Full Secret Object Restore from Backup

If you maintain etcd backups or use an external secrets manager with
versioning:

```bash
# Example: restore from a YAML backup
kubectl apply -f /path/to/backup/agent33-api-secrets.yaml
kubectl rollout restart deployment/agent33-api -n agent33
```

### Scaling Down During Emergency

If the broken rotation is causing cascading failures:

```bash
# Scale to zero to stop the bleeding
kubectl scale deployment/agent33-api -n agent33 --replicas=0

# Fix the secret
kubectl patch secret agent33-api-secrets -n agent33 \
  -p "{\"stringData\":{\"KEY_NAME\":\"corrected-value\"}}"

# Scale back up
kubectl scale deployment/agent33-api -n agent33 --replicas=2
kubectl rollout status deployment/agent33-api -n agent33 --timeout=300s
```

## 7. Rotation Schedule

| Secret | Cadence | Notes |
|--------|---------|-------|
| JWT_SECRET | 90 days | Requires user re-authentication |
| ENCRYPTION_KEY | 180 days | Re-encrypt vault if persistent storage is added |
| POSTGRES_PASSWORD | 90 days | Follow the coordinated procedure above |
| API_SECRET_KEY | 90 days | May invalidate signed artifacts |
| LLM provider keys | Per provider policy or 180 days | Rotate sooner if key exposure is suspected |
| Messaging tokens | 180 days | Platform-specific regeneration |
| Webhook HMAC secrets | 180 days | Coordinate with external senders |
| PACK_SIGNING_KEY | On compromise only | Requires re-signing all packs |
| VOICE_* keys | 180 days | Standard rotation |
| AUTH_BOOTSTRAP_ADMIN_PASSWORD | On each bootstrap use | Rotate immediately after bootstrap |

### Pre-Rotation Checklist

- [ ] Database backup completed
- [ ] Old secret value saved to secrets manager
- [ ] Maintenance window communicated (for JWT_SECRET)
- [ ] External parties notified (for coordinated secrets)
- [ ] Rollback procedure reviewed
- [ ] Verification commands ready

### Post-Rotation Checklist

- [ ] All pods Running, no CrashLoopBackOff
- [ ] `/readyz` returns 200
- [ ] Authentication works with fresh tokens
- [ ] Database queries succeed
- [ ] No decryption errors in logs
- [ ] Old keys revoked in provider dashboards
- [ ] Rotation recorded in change management system
