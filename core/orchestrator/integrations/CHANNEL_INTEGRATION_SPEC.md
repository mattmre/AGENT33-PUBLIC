# Channel Integration Specification

Purpose: Define the canonical architecture for multi-platform messaging channel integrations within AGENT-33 orchestrated workflows.

Related docs:
- `core/orchestrator/SECURITY_HARDENING.md` (prompt injection defense, secrets handling)
- `core/orchestrator/TOOL_GOVERNANCE.md` (allowlist policy, provenance checklists)
- `core/orchestrator/AGENT_REGISTRY.md` (agent identity and capability declarations)

---

## Architecture Overview

Plugin-based channel system where each messaging platform is an isolated module with:
- Standardized message interface (inbound/outbound)
- Per-channel credential isolation
- Configurable access control (DM policies, group policies, allowlists)
- Sandboxed execution context

### Design Principles

1. **Default deny**: No channel is active until explicitly registered and approved.
2. **Credential isolation**: Each channel holds its own vault-backed credentials; no sharing across channels.
3. **Plugin sandboxing**: Channel plugins run in isolated contexts with no cross-channel memory access.
4. **Auditability**: Every inbound and outbound message is logged with tamper-evident metadata.
5. **Provenance required**: Every SDK or client library must pass the provenance checklist defined in `TOOL_GOVERNANCE.md`.

---

## Channel Categories

### Tier 1: Enterprise-Grade (recommended)

| Platform | Client | Notes |
|----------|--------|-------|
| **Slack** | `@slack/bolt` (official SDK) | OAuth2, granular scopes, event subscriptions |
| **Microsoft Teams** | Graph API (official SDK) | Azure AD integration, tenant isolation |
| **Google Chat** | Official Google API | Service account auth, Workspace integration |
| **Matrix** | Open protocol | Self-hosted option, end-to-end encryption native |

Tier 1 platforms have official SDKs with well-documented security models, active maintenance, and enterprise support contracts available.

### Tier 2: Consumer Platforms (use with caution)

| Platform | Client | Notes |
|----------|--------|-------|
| **Discord** | `discord.js` (official SDK) | Bot token auth, gateway intents required |
| **Telegram** | `grammy` (community) | Requires provenance check; Bot API only |

Tier 2 platforms have functional SDKs but weaker enterprise guarantees. Provenance checklist completion is mandatory. Rate limit enforcement is critical due to platform-imposed limits.

### Tier 3: Restricted (security concerns)

| Platform | Client | Risk |
|----------|--------|------|
| **WhatsApp** | `baileys` | REVERSE ENGINEERED, violates WhatsApp ToS. **NOT RECOMMENDED.** |
| **iMessage** | Platform-locked | Requires macOS device pairing, no official API |
| **Signal** | `libsignal` | Requires careful cryptographic handling, protocol compliance |

Tier 3 platforms carry legal, compliance, or security risks. Integration requires explicit written approval from the project owner and a completed risk assessment.

### Tier 4: Experimental

| Platform | Notes |
|----------|-------|
| **Nostr** | Decentralized protocol, relay-based |
| **Matrix federation** | Cross-server identity verification required |
| **Twitch** | Chat-only, IRC-based |
| **Custom webhooks** | Generic inbound/outbound HTTP hooks |

Tier 4 integrations are not production-ready. Use only in development or research contexts.

---

## Security Requirements Per Channel

For each channel integration, the following controls are REQUIRED before activation:

| # | Requirement | Enforcement |
|---|-------------|-------------|
| SEC-CH-01 | Official SDK or provenance-checked open-source client | Provenance checklist in `TOOL_GOVERNANCE.md` |
| SEC-CH-02 | Credential storage via vault/keyring (NEVER plaintext JSON) | Vault adapter validation at registration |
| SEC-CH-03 | Per-channel sandbox isolation | Process-level or container-level boundary |
| SEC-CH-04 | Message content encryption in transit and at rest | TLS 1.2+ in transit; AES-256 at rest |
| SEC-CH-05 | Access control: default deny, explicit allowlist | Policy file per channel |
| SEC-CH-06 | Rate limiting per channel | Configurable tokens-per-minute with backpressure |
| SEC-CH-07 | Audit logging of all inbound/outbound messages | Append-only log, tamper-evident |
| SEC-CH-08 | No hardcoded external endpoints | All endpoints resolved from configuration |

Failure to meet any requirement blocks channel activation.

---

## Message Interface Schema

All channel plugins MUST normalize messages to this canonical schema before routing to agents.

```yaml
message:
  id: string            # Unique message identifier (UUID v4)
  channel: string       # Channel identifier (e.g., "slack", "teams", "discord")
  direction: inbound | outbound
  sender:
    id: string          # Platform-specific user identifier
    display_name: string
    verified: boolean   # Whether sender identity has been verified
  content:
    type: text | media | reaction | system
    text: string        # Optional; present for text and system types
    media:              # Optional; present for media type
      type: image | audio | video | file
      url: string       # Local path only, NEVER external URL
      mime_type: string
      size_bytes: number
  metadata:
    timestamp: string   # ISO-8601 with timezone (e.g., 2026-01-30T12:00:00Z)
    thread_id: string   # Optional; for threaded conversations
    reply_to: string    # Optional; message ID being replied to
    channel_specific: object  # Opaque platform-specific metadata
  security:
    encrypted: boolean        # Was content encrypted end-to-end
    sanitized: boolean        # Has content passed sanitization (PI-SAN-01)
    injection_checked: boolean # Has content been checked for prompt injection
```

### Schema Validation

- All inbound messages MUST pass schema validation before agent routing.
- Messages failing validation are quarantined and logged.
- The `security.sanitized` and `security.injection_checked` fields MUST be `true` before any message reaches an agent. See `SECURITY_HARDENING.md` for sanitization rules.

---

## Access Control Model

### DM Policy (per channel)

| Policy | Behavior | Default |
|--------|----------|---------|
| `disabled` | No direct messages accepted | |
| `allowlist` | Only pre-approved user IDs accepted | **DEFAULT** |
| `pairing` | Out-of-band approval with expiring codes (max 15 minutes) | |
| `open` | Accept all direct messages | NOT RECOMMENDED; requires explicit project-owner approval |

Configuration example:

```yaml
dm_policy:
  mode: allowlist
  allowed_users:
    - "U12345678"    # Slack user ID
    - "U87654321"
  pairing:
    code_expiry_minutes: 15
    max_active_codes: 5
```

### Group Policy

| Control | Default | Notes |
|---------|---------|-------|
| Trigger mode | `@mention` required | Agent only responds when explicitly mentioned |
| Group allowlist | Empty (deny all) | Groups must be explicitly added |
| Admin changes | Admin-only | Only group admins can modify agent configuration |
| Broadcast mode | Disabled | When enabled, agent sends read-only output; no inbound processing |

Configuration example:

```yaml
group_policy:
  trigger: mention          # mention | keyword | all
  allowed_groups:
    - "C00001234"           # Slack channel ID
  admin_only_config: true
  broadcast_mode: false
```

---

## Credential Management

### Mandatory Requirements

| # | Requirement |
|---|-------------|
| CRED-01 | All channel credentials stored in OS keyring or encrypted vault |
| CRED-02 | Credential rotation schedule defined per channel (max 90 days for tokens) |
| CRED-03 | No credentials in environment variables (use vault references) |
| CRED-04 | No credentials in configuration files (use vault references) |
| CRED-05 | Credential access audited with timestamp and accessor identity |

### Vault Reference Format

Configuration files reference credentials by vault path, never by value:

```yaml
credentials:
  slack:
    bot_token: vault://agent33/channels/slack/bot_token
    signing_secret: vault://agent33/channels/slack/signing_secret
  teams:
    client_id: vault://agent33/channels/teams/client_id
    client_secret: vault://agent33/channels/teams/client_secret
```

### Rotation Policy

| Credential Type | Max Lifetime | Rotation Trigger |
|----------------|--------------|------------------|
| Bot tokens | 90 days | Automatic rotation with overlap window |
| OAuth tokens | Per provider (usually 1 hour) | Automatic refresh via SDK |
| Signing secrets | 90 days | Manual rotation with dual-secret overlap |
| Webhook secrets | 90 days | Manual rotation with signature re-enrollment |

---

## Channel Lifecycle

### 1. Registration

- Complete provenance checklist for the SDK/client library.
- Document the channel in the integration registry.
- Assign a channel identifier and tier classification.

### 2. Configuration

- Store all credentials in vault (CRED-01 through CRED-05).
- Define access policies (DM policy, group policy).
- Set rate limits and retention policies.
- Configure webhook endpoints if applicable.

### 3. Activation

- Run health check: verify connectivity to platform API.
- Validate credential access from vault.
- Confirm sandbox isolation is enforced.
- Log activation event to audit trail.

### 4. Operation

- Route inbound messages through schema validation and sanitization.
- Enforce rate limits with backpressure signaling.
- Log all messages to audit trail.
- Monitor for anomalies (unusual volume, unknown senders, injection attempts).

### 5. Deactivation

- Graceful disconnect: close WebSocket connections, unsubscribe from events.
- Revoke short-lived credentials (OAuth tokens).
- Log deactivation event to audit trail.
- Retain audit logs per retention policy.

### 6. Removal

- Destroy all credentials associated with the channel.
- Archive audit trail (do not delete).
- Remove channel from integration registry.
- Log removal event.

---

## Webhook Security

All webhook endpoints exposed by channel integrations MUST implement the following controls:

| # | Control | Details |
|---|---------|---------|
| WH-01 | HMAC signature validation | Every inbound webhook request must carry a valid HMAC signature; reject unsigned requests |
| WH-02 | Secrets in vault | Webhook signing secrets stored via vault reference, never in config files |
| WH-03 | IP allowlisting | Where the platform publishes IP ranges (e.g., Slack, GitHub), enforce allowlist |
| WH-04 | Payload size limit | Maximum 1 MB per request; reject oversized payloads before parsing |
| WH-05 | Request timeout | 5-second processing timeout; return 202 Accepted for async work |
| WH-06 | Replay protection | Reject requests with timestamps older than 5 minutes |
| WH-07 | TLS required | HTTPS only; no plaintext HTTP endpoints |

---

## Privacy Controls

| # | Control | Details |
|---|---------|---------|
| PRIV-01 | Message retention | Configurable per channel; default 30 days; purge on schedule |
| PRIV-02 | Right-to-delete | Support deletion of all messages from a specific sender on request |
| PRIV-03 | Data minimization | Store only fields required for operation; discard platform-specific metadata unless needed |
| PRIV-04 | No third-party forwarding | Messages are never forwarded to external services without explicit, logged consent |
| PRIV-05 | Geographic residency | Configuration option for data storage region; default to deployment region |
| PRIV-06 | PII handling | Personally identifiable information in messages flagged and handled per data classification policy |

### Retention Configuration Example

```yaml
privacy:
  retention:
    default_days: 30
    per_channel:
      slack: 90
      discord: 7
  right_to_delete: true
  data_minimization: true
  forwarding_consent_required: true
  data_residency: "us-east-1"
```

---

## Integration Registry Entry Template

Each registered channel MUST have an entry in the integration registry:

```yaml
channel:
  id: slack-prod-01
  platform: slack
  tier: 1
  status: active
  sdk:
    name: "@slack/bolt"
    version: "3.x"
    provenance_checklist: completed
    provenance_date: 2026-01-30
  credentials:
    bot_token: vault://agent33/channels/slack-prod-01/bot_token
    signing_secret: vault://agent33/channels/slack-prod-01/signing_secret
  policies:
    dm_policy: allowlist
    group_policy: mention
    rate_limit: 60/min
  privacy:
    retention_days: 90
    data_residency: us-east-1
  lifecycle:
    registered: 2026-01-30
    activated: 2026-01-30
    last_health_check: 2026-01-30T12:00:00Z
```

---

## Compliance Matrix

| Requirement | SECURITY_HARDENING | TOOL_GOVERNANCE | This Spec |
|-------------|-------------------|-----------------|-----------|
| Input sanitization | PI-SAN-01 | - | Schema validation + `security.sanitized` |
| Credential handling | SEC-SECRETS | - | CRED-01 through CRED-05 |
| Provenance checks | - | Provenance checklist | SDK tier classification |
| Default deny | L4 privilege separation | Allowlist policy | DM/group allowlists |
| Audit logging | - | Monitoring checkpoint | SEC-CH-07, all lifecycle events |
| Sandbox isolation | - | Integration checkpoint | SEC-CH-03, per-channel sandbox |
