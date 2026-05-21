# Privacy-First Architecture Specification

Purpose: Define the canonical privacy architecture for AGENT-33 platform integrations, addressing data flow, consent, encryption, and data minimization requirements.

## Related Documents

- `core/orchestrator/SECURITY_HARDENING.md`
- `core/orchestrator/integrations/CREDENTIAL_MANAGEMENT_SPEC.md`
- `core/orchestrator/integrations/CHANNEL_INTEGRATION_SPEC.md`

---

## Data Flow Classification

| Data Type | Classification | Storage | Encryption | Retention |
|-----------|---------------|---------|------------|-----------|
| User messages | PII/Sensitive | Local only | AES-256-GCM at rest | Configurable (default 90 days) |
| Session transcripts | PII/Sensitive | Local only | AES-256-GCM at rest | Configurable (default 90 days) |
| API credentials | Secret | Vault/Keyring | Vault-managed | Until rotated |
| Model responses | Internal | Local only | AES-256-GCM at rest | With session |
| Telemetry/metrics | Internal | Local or configured endpoint | TLS in transit | 30 days |
| Media files | PII/Sensitive | Local only | AES-256-GCM at rest | Configurable |
| Audit logs | Compliance | Local + optional SIEM | AES-256-GCM at rest | 1 year minimum |

---

## External Data Transmission Policy

**MANDATORY**: Before any data is sent to an external service:

1. User consent must be explicitly granted (not assumed)
2. Data must be minimized (only send what is needed)
3. Transmission must use TLS 1.3+
4. Provider must be on the approved provider list
5. Data handling agreement must be in place
6. Transmission must be logged in audit trail

---

## Approved External Providers

Only these categories of providers are approved for data transmission:

- **Tier 1 (Major Cloud)**: AWS, Azure, Google Cloud - with BAA/DPA
- **Tier 2 (AI Model Providers)**: Anthropic, OpenAI - with data processing agreements
- **Tier 3 (Specialized)**: Must complete full provenance checklist + legal review

### BLOCKED Providers

The following providers are blocked due to security and privacy concerns identified in the external platform analysis:

- **MiniMax** (api.minimax.io) - Chinese company, data jurisdiction concerns
- **Chutes AI** (api.chutes.ai) - hardcoded endpoint, no configurability
- **node-edge-tts endpoints** - reverse-engineered, no data handling agreement
- **WhatsApp/Baileys** - reverse-engineered, no official API agreement

---

## Session Data Lifecycle

1. **Creation**: Encrypted at creation time
2. **Active**: Decrypted in memory only during active session
3. **Idle**: Re-encrypted after configurable idle timeout
4. **Archived**: Compressed + encrypted after retention period
5. **Deleted**: Secure deletion (overwrite + unlink)

---

## Encryption Requirements

- **At rest**: AES-256-GCM with per-session keys
- **In transit**: TLS 1.3 minimum
- **Key derivation**: Argon2id for user-derived keys
- **Key storage**: OS keyring or hardware security module
- **Key rotation**: Automated, configurable schedule

---

## Data Minimization

- Do not store full message history if not needed
- Strip metadata from media before processing
- Use embeddings/summaries instead of raw text where possible
- Implement right-to-delete (purge user data on request)
- No unnecessary logging of message content

---

## Telemetry and Observability

- Telemetry **DISABLED by default** (opt-in only)
- When enabled: no PII in telemetry data
- Metrics only: token counts, latency, error rates (no content)
- Local-first: prefer local log files over external endpoints
- If external OTEL endpoint used: must be on approved provider list
