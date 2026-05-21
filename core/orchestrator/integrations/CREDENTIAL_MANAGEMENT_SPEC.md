# Credential Management Specification

**Status:** Draft
**Version:** 0.1.0
**Last Updated:** 2026-01-30
**Author:** AGENT-33 Implementer

## Purpose

Define mandatory credential handling practices for all AGENT-33 integrations. This specification replaces plaintext storage patterns (as found in similar frameworks) with vault-backed, encrypted credential management. Compliance with this specification is not optional; any integration that stores or transmits credentials outside these requirements MUST be rejected during review.

---

## 1. Storage Requirements (MANDATORY)

### 1.1 Prohibited Practices

The following storage methods are **NEVER** permitted:

- **NEVER** store credentials in plaintext JSON, YAML, TOML, or INI files.
- **NEVER** store credentials in environment variables for production deployments.
- **NEVER** embed credentials in source code, including comments.
- **NEVER** store credentials in browser local storage or cookies.
- **NEVER** log credentials at any log level, including debug/trace.

### 1.2 Required Storage Backend

Production deployments MUST use one of the following, in order of preference:

| Priority | Backend | Use Case |
|----------|---------|----------|
| 1 (REQUIRED) | OS Keyring | Single-machine deployments |
| 2 (REQUIRED for distributed) | HashiCorp Vault | Multi-node, enterprise |
| 3 (ALTERNATIVE) | AWS Secrets Manager | AWS-native deployments |
| 4 (ALTERNATIVE) | Azure Key Vault | Azure-native deployments |
| 5 (ALTERNATIVE) | GCP Secret Manager | GCP-native deployments |

**OS Keyring Details:**

| Platform | Backend | Library |
|----------|---------|---------|
| Windows | Windows Credential Manager | `keyring` (Python) / `keytar` (Node) |
| macOS | macOS Keychain | `keyring` / `keytar` |
| Linux | Secret Service (GNOME Keyring / KWallet) | `keyring` / `keytar` |

### 1.3 Development-Only Fallback

For local development environments where a keyring or vault is unavailable:

- Encrypted local file using AES-256-GCM
- Key derivation: argon2id with parameters: `m=65536, t=3, p=4`
- Master password prompted at startup (never stored)
- File permissions: owner-only read/write (`0600` on Unix, ACL-restricted on Windows)
- File location: `{data_dir}/credentials.enc`
- This method is **NOT** permitted in production

---

## 2. Credential Categories

| Category | Examples | Storage | Rotation Period | Access Scope |
|----------|----------|---------|-----------------|-------------|
| API Keys | Anthropic, OpenAI, Google AI | Vault/Keyring | 90 days | Per-agent |
| OAuth Tokens | GitHub, Slack, Google OAuth | Vault + auto-refresh | Per-expiry | Per-integration |
| Channel Tokens | Telegram bot token, Discord bot token | Vault/Keyring | 180 days | Per-channel agent |
| Webhook Secrets | HMAC signing keys, webhook verification | Vault/Keyring | 90 days | Per-endpoint |
| TLS Certificates | Gateway TLS, mutual TLS client certs | Vault/PKI backend | Per-expiry | Per-service |
| AWS Credentials | Access key ID + secret access key | IAM roles preferred | 90 days (if keys used) | Per-service |
| Database Credentials | PostgreSQL, Redis passwords | Vault dynamic secrets | Per-session preferred | Per-service |
| Encryption Keys | Media encryption, cache encryption | Vault transit backend | 365 days | Per-subsystem |

---

## 3. Access Control

### 3.1 Principle of Least Privilege

Each agent or integration receives access to only the credentials it requires. Credential scoping is enforced at the vault/keyring level, not at the application level.

```
Agent: voice-assistant
  Allowed credentials:
    - stt/openai_api_key        (read-only)
    - tts/piper_license         (read-only)
  Denied credentials:
    - github/oauth_token        (not in scope)
    - telegram/bot_token        (not in scope)
```

### 3.2 Per-Agent Credential Scoping

- Each agent has a credential scope defined in its manifest.
- Credential requests outside the defined scope are denied and logged as security events.
- No agent may enumerate available credentials beyond its scope.

### 3.3 Audit Logging

Every credential access event MUST be logged:

```json
{
  "timestamp": "2026-01-30T12:00:00Z",
  "event": "credential_access",
  "agent": "voice-assistant",
  "credential": "stt/openai_api_key",
  "operation": "read",
  "result": "granted",
  "source_ip": "127.0.0.1",
  "request_id": "req-abc123"
}
```

Audit logs are append-only and stored separately from application logs. Credential values NEVER appear in audit logs.

### 3.4 No Credential Inheritance

- Child processes spawned by agents do NOT inherit parent credentials.
- Environment variables containing credentials are cleared before process spawn.
- Credentials are passed to child processes only through secure IPC (Unix domain sockets, named pipes) when required.

---

## 4. Rotation Policy

### 4.1 Automated Rotation

Where the credential backend supports it, rotation is automated:

1. New credential generated or requested from provider.
2. New credential written to vault/keyring.
3. Grace period begins: both old and new credentials are valid.
4. Application transitions to new credential.
5. Old credential revoked after grace period.

### 4.2 Grace Period (Dual-Key Operation)

During rotation, both the old and new credential are active to prevent downtime:

| Credential Type | Grace Period |
|----------------|-------------|
| API Keys | 24 hours |
| OAuth Tokens | Until old token expires |
| Channel Tokens | 48 hours |
| Webhook Secrets | 1 hour (verify both signatures) |
| TLS Certificates | 7 days |

### 4.3 Rotation Failure Notification

On rotation failure:
1. Alert sent to configured notification channel (Slack, email, webhook).
2. Retry with exponential backoff (1 min, 5 min, 15 min, 1 hour).
3. After 3 failures, escalate to human operator.
4. Old credential remains active until manual intervention.

### 4.4 Emergency Revocation Procedure

For suspected credential compromise:

1. **Immediate:** Revoke credential at provider (API dashboard, vault command).
2. **Within 5 minutes:** Generate replacement credential.
3. **Within 15 minutes:** Deploy replacement to all consuming agents.
4. **Within 1 hour:** Audit all access logs for the compromised credential.
5. **Within 24 hours:** Post-incident review documenting scope and impact.

Command for emergency revocation:
```bash
agent33 credentials revoke --credential <name> --reason "compromise" --force
agent33 credentials rotate --credential <name> --emergency
```

---

## 5. Anti-Patterns (from External Analysis)

The following anti-patterns were identified through analysis of external frameworks and similar projects. Each is documented here as a cautionary reference.

### 5.1 Plaintext API Keys in JSON Files

**Anti-pattern:** Storing API keys in `auth-profiles.json` or similar configuration files in plaintext.

```json
// NEVER DO THIS
{
  "profiles": {
    "default": {
      "anthropic_api_key": "sk-ant-api03-XXXX",
      "openai_api_key": "sk-XXXX"
    }
  }
}
```

**Risk:** Any process with filesystem read access can steal credentials. Backup software, cloud sync, or misconfigured permissions expose keys.

**Fix:** Store in OS keyring or vault. Reference by name, not value.

### 5.2 Credentials in Environment Variables

**Anti-pattern:** Relying on environment variables for credential storage in production.

**Risk:** Environment variables are readable via `/proc/[pid]/environ` on Linux, `Get-Process` on Windows, and are inherited by all child processes. They appear in process listings, crash dumps, and container inspection output.

**Fix:** Read credentials from vault/keyring at runtime. Clear environment after reading if environment variables must be used for bootstrap.

### 5.3 Shell History Containing Secrets

**Anti-pattern:** Passing credentials as command-line arguments.

```bash
# NEVER DO THIS
curl -H "Authorization: Bearer sk-XXXX" https://api.example.com
export ANTHROPIC_API_KEY=sk-ant-api03-XXXX
```

**Risk:** Commands are recorded in `~/.bash_history`, `~/.zsh_history`, and similar files. These persist across sessions and may be backed up.

**Fix:** Use credential files with restricted permissions, or pipe credentials from a vault command. Configure `HISTIGNORE` as a defense-in-depth measure, but do not rely on it.

### 5.4 Editor Backup Files

**Anti-pattern:** Editors creating backup copies of credential files (e.g., `.auth-profiles.json~`, `.auth-profiles.json.swp`, `auth-profiles.json.bak`).

**Risk:** Backup files may not have the same permissions as the original, and are often missed by `.gitignore` rules.

**Fix:** Do not store credentials in files that editors open. Use vault/keyring. If files are necessary, configure editors to disable backups for credential paths, and add comprehensive gitignore rules.

### 5.5 Git Accidents

**Anti-pattern:** Credentials committed to version control, even if later removed.

**Risk:** Git history retains all committed content. Even after removal, credentials are recoverable from history, reflog, and any cloned copies.

**Fix:** Use pre-commit hooks (e.g., `detect-secrets`, `gitleaks`) to prevent credential commits. If a credential is committed, rotate it immediately; do not rely on history rewriting.

### 5.6 Shared Bearer Tokens

**Anti-pattern:** Using a single bearer token or API key across all clients, agents, and environments.

**Risk:** Compromise of any single client exposes the token for all clients. Audit logs cannot distinguish between clients. Revocation affects all clients simultaneously.

**Fix:** Issue per-agent, per-environment credentials. Use OAuth client credentials flow where supported.

### 5.7 Non-Expiring Pairing/Approval Codes

**Anti-pattern:** Generating pairing codes, approval tokens, or setup codes that never expire.

**Risk:** Codes intercepted or leaked remain valid indefinitely. No forced rotation means compromised codes provide permanent access.

**Fix:** All codes and tokens must have a maximum TTL. Pairing codes: 10 minutes. Approval tokens: 1 hour. Setup codes: 24 hours. Enforce expiry server-side.

---

## 6. Implementation Checklist

All AGENT-33 integrations MUST satisfy every item before deployment:

- [ ] All credentials stored in vault or OS keyring
- [ ] No plaintext secrets in any configuration file
- [ ] No credentials in source code (verified by pre-commit hook)
- [ ] Credential access audited with structured logging
- [ ] Rotation schedule defined for each credential
- [ ] Emergency revocation tested in staging environment
- [ ] No credentials in application logs (redaction enabled and tested)
- [ ] No credentials in error messages or stack traces
- [ ] Process environment cleaned after credential use
- [ ] Child processes do not inherit credentials
- [ ] Backup files excluded from credential directories
- [ ] Pre-commit hooks installed (`detect-secrets`, `gitleaks`)
- [ ] Per-agent credential scoping enforced
- [ ] Grace period dual-key operation validated
- [ ] Rotation failure alerting configured and tested

---

## 7. Credential Access API

AGENT-33 provides a unified credential access interface. All integrations MUST use this API rather than reading credentials directly.

```python
from agent33.credentials import CredentialStore

store = CredentialStore(agent_name="voice-assistant")

# Read a credential (audited, scope-checked)
api_key = store.get("stt/openai_api_key")

# Use credential in a managed context (auto-cleanup)
with store.credential("stt/openai_api_key") as key:
    client = SomeClient(api_key=key)
    result = client.transcribe(audio)
# key reference is invalidated after context exit

# Check rotation status
status = store.rotation_status("stt/openai_api_key")
if status.days_until_rotation < 7:
    log.warning("Credential rotation approaching")
```

The `CredentialStore` enforces all policies defined in this specification: scoping, auditing, redaction, and cleanup.

---

## 8. Compliance Verification

Automated compliance checks run as part of the CI/CD pipeline:

1. **Static analysis:** Scan all source files for credential patterns (high-entropy strings, known key prefixes).
2. **Configuration audit:** Verify no plaintext credentials in any config file.
3. **Integration test:** Confirm credential access API is used by all integrations.
4. **Rotation test:** Verify rotation procedures work in staging.

Failure of any compliance check blocks deployment.
