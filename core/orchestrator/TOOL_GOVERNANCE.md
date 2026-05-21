# Tool Governance (Allowlist + Provenance)

Purpose: define how tools and MCP servers are discovered, approved, and operated.

Related docs:
- `core/orchestrator/TOOL_REGISTRY_CHANGE_CONTROL.md` (change control checklists and registry)
- `core/orchestrator/TOOLS_AS_CODE.md` (tools-as-code guidance)
- `core/orchestrator/CODE_EXECUTION_CONTRACT.md` (sandbox limits, adapters)
- `core/orchestrator/SECURITY_HARDENING.md` (prompt injection defense, secrets handling)
- `core/packs/policy-pack-v1/RISK_TRIGGERS.md` (security risk triggers)

## Scope
- Tool: any deterministic capability invoked by an agent (CLI, API, SDK, MCP server).
- Discovery: identifying a tool or MCP server for possible use.
- Allowlist: explicit approvals for commands, endpoints, and domains.

## Allowlist Policy
1) Default deny: tools and network are off unless explicitly allowlisted.
2) Allowlist entries are explicit and scoped:
   - Name and owner
   - Command, endpoint, or domain (exact or prefix)
   - Allowed arguments or routes
   - Data classification and access scope (read/write)
   - Required approvals (role + date)
3) Every new tool requires:
   - Provenance checklist completion
   - Risk trigger review (if applicable)
   - TASKS and DECISIONS update

## Governance Checkpoints
- Discovery: document candidate tools and why they are needed.
- Approval: complete provenance checklist and add allowlist entry.
- Integration: define usage limits, timeouts, and sandbox boundaries.
- Verification: add deterministic checks or fixtures if possible.
- Monitoring: record usage and failures in session logs.

## Provenance Checklist (Tools + MCP Servers)
- Ownership: maintainer/organization identified.
- Source integrity: repo URL, version tag/commit, checksum or signature.
- License: recorded and compatible with usage.
- Build/packaging: reproducible build steps or verified binaries.
- Dependencies: critical dependencies reviewed for risk.
- Security: vulnerability scan or security notes recorded.
- Data handling: what data is accessed, stored, or transmitted.
- Permissions: filesystem/network scopes explicitly bounded.
- Runtime isolation: sandbox/container requirements documented.
- Update policy: version pinning and change review cadence.
- Revocation plan: how to disable or remove the tool safely.
- MCP specifics: server host, auth method, transport, and logging.

## Evidence
- Record allowlist updates and provenance checks in TASKS and DECISIONS.
- Log verification commands in `core/arch/verification-log.md`.
