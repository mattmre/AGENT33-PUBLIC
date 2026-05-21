# Tool Registry Change Control

Purpose: Define the change control process for tool registry updates, including provenance verification and allowlist management.

Related docs:
- `core/orchestrator/TOOL_GOVERNANCE.md` (allowlist policy and provenance checklist)
- `core/orchestrator/TOOLS_AS_CODE.md` (tools-as-code guidance)
- `core/packs/policy-pack-v1/RISK_TRIGGERS.md` (security risk triggers)

---

## Tool Registry Schema

Each tool entry follows this schema:

```yaml
tool_id: <unique-identifier>
name: <tool-name>
version: <semver>
owner: <maintainer-or-org>
provenance:
  repo_url: <source-repository>
  commit_or_tag: <version-reference>
  checksum: <sha256-or-signature>
  license: <license-type>
scope:
  commands: [<allowed-commands>]
  endpoints: [<allowed-endpoints>]
  data_access: <read|write|none>
  network: <on|off>
  filesystem: [<allowed-paths>]
approval:
  approver: <role-or-name>
  date: <YYYY-MM-DD>
  evidence: <link-to-approval-record>
status: <active|deprecated|blocked>
last_review: <YYYY-MM-DD>
next_review: <YYYY-MM-DD>
```

---

## Change Control Checklist

### CCC-01: New Tool Addition

| Step | Check | Required | Notes |
|------|-------|----------|-------|
| 1 | **Need Assessment** | Yes | Document why the tool is needed (TASKS or DECISIONS) |
| 2 | **Provenance Checklist** | Yes | Complete all items in Provenance Verification section |
| 3 | **Risk Trigger Review** | If applicable | Check RISK_TRIGGERS.md for security/supply chain concerns |
| 4 | **Scope Definition** | Yes | Define allowed commands, endpoints, data access |
| 5 | **Sandbox Boundaries** | Yes | Document filesystem, network, and execution limits |
| 6 | **Security Review** | If risk triggers | Capture review in REVIEW_CAPTURE.md |
| 7 | **Approval Record** | Yes | Record approver, date, and evidence link |
| 8 | **Allowlist Update** | Yes | Add entry to allowlist with scope constraints |
| 9 | **Registry Entry** | Yes | Create tool entry following schema |
| 10 | **Verification Test** | Recommended | Add deterministic check or fixture |

### CCC-02: Tool Version Update

| Step | Check | Required | Notes |
|------|-------|----------|-------|
| 1 | **Change Log Review** | Yes | Review upstream changelog for breaking changes |
| 2 | **Dependency Check** | Yes | Verify dependency updates are compatible |
| 3 | **Security Scan** | Recommended | Check for new CVEs or security advisories |
| 4 | **Provenance Update** | Yes | Update commit/tag, checksum, version |
| 5 | **Scope Review** | If behavior changed | Verify scope constraints still apply |
| 6 | **Risk Trigger Check** | If security-relevant | Re-run risk trigger review |
| 7 | **Approval Record** | Yes | Record approver, date, rationale |
| 8 | **Registry Update** | Yes | Update version, last_review, next_review |
| 9 | **Rollback Plan** | Yes | Document rollback steps (see Rollback Guidance) |
| 10 | **Verification Test** | Recommended | Re-run existing checks with new version |

### CCC-03: Tool Scope Change

| Step | Check | Required | Notes |
|------|-------|----------|-------|
| 1 | **Scope Change Request** | Yes | Document what scope is expanding or contracting |
| 2 | **Risk Assessment** | Yes | Evaluate impact of scope change |
| 3 | **Provenance Re-check** | If scope expands | Verify tool can safely handle expanded scope |
| 4 | **Security Review** | If expands | Capture review if expanding network/filesystem access |
| 5 | **Allowlist Update** | Yes | Update scope constraints in allowlist |
| 6 | **Registry Update** | Yes | Update scope section and last_review |
| 7 | **Approval Record** | Yes | Record approver with scope change rationale |

### CCC-04: Tool Removal/Deprecation

| Step | Check | Required | Notes |
|------|-------|----------|-------|
| 1 | **Deprecation Notice** | Yes | Document reason and timeline |
| 2 | **Dependent Check** | Yes | Identify tasks or agents depending on tool |
| 3 | **Migration Plan** | If dependencies exist | Document migration to replacement |
| 4 | **Status Update** | Yes | Set status to `deprecated` or `blocked` |
| 5 | **Allowlist Removal** | When complete | Remove from active allowlist |
| 6 | **Archive Entry** | Yes | Move to archived tools section (retain history) |
| 7 | **Evidence Capture** | Yes | Record removal rationale in DECISIONS |

---

## Provenance Verification

### Required Checks

| Check | Description | Evidence Required |
|-------|-------------|-------------------|
| **PRV-01: Ownership** | Maintainer or organization identified | Link to maintainer profile or org page |
| **PRV-02: Source Integrity** | Repo URL with version tag or commit hash | `<repo>@<tag>` or `<repo>#<commit>` |
| **PRV-03: Checksum** | SHA256 hash or cryptographic signature | Hash value or signature file |
| **PRV-04: License** | License type recorded and compatible | License identifier (MIT, Apache-2.0, etc.) |
| **PRV-05: Build Reproducibility** | Build steps documented or verified binaries | Build docs link or attestation |
| **PRV-06: Dependencies** | Critical dependencies reviewed | Dependency list with risk notes |
| **PRV-07: Security Scan** | Vulnerability scan or security notes | Scan report link or "none found" note |
| **PRV-08: Data Handling** | What data is accessed, stored, transmitted | Data flow description |
| **PRV-09: Permissions** | Filesystem and network scopes bounded | Explicit path and domain lists |
| **PRV-10: Isolation** | Sandbox or container requirements | Isolation method documented |
| **PRV-11: Update Policy** | Version pinning and review cadence | Pin strategy and next review date |
| **PRV-12: Revocation Plan** | How to disable or remove safely | Rollback steps documented |

### MCP Server Additional Checks

| Check | Description | Evidence Required |
|-------|-------------|-------------------|
| **MCP-01: Server Host** | Where the MCP server runs | Host identifier or URL |
| **MCP-02: Auth Method** | Authentication mechanism | OAuth, API key, mTLS, etc. |
| **MCP-03: Transport** | Communication protocol | HTTP, gRPC, stdio, etc. |
| **MCP-04: Logging** | Audit logging requirements | Log destination and retention |
| **MCP-05: Rate Limits** | Request throttling policy | Limits documented |

---

## Allowlist Update Workflow

### Adding to Allowlist

1. **Complete provenance verification** (all PRV checks pass)
2. **Create allowlist entry**:
   ```yaml
   - tool_id: TL-NNN
     name: <tool-name>
     commands:
       - <command-1>
       - <command-2>
     endpoints:
       - <endpoint-pattern>
     data_access: read|write|none
     network: on|off
     filesystem:
       - <path-pattern>
     approved_by: <role>
     approved_date: <YYYY-MM-DD>
   ```
3. **Record in TASKS.md** under "Tool Registry Changes"
4. **Update DECISIONS.md** with approval rationale
5. **Log in verification-log.md**

### Modifying Allowlist Entry

1. **Document change request** in TASKS or DECISIONS
2. **Re-run relevant provenance checks** (PRV-xx)
3. **Update entry** with new scope or constraints
4. **Record approval** with change rationale
5. **Increment review date**

### Removing from Allowlist

1. **Follow CCC-04** (Tool Removal/Deprecation)
2. **Set status to blocked** before removal (grace period)
3. **Remove entry** after migration complete
4. **Archive** the entry for audit trail

---

## Tool Registry (Active)

### TL-001: Git

```yaml
tool_id: TL-001
name: git
version: "2.40+"
owner: Git Project
provenance:
  repo_url: https://github.com/git/git
  commit_or_tag: v2.40.0+
  checksum: verified via package manager
  license: GPL-2.0
scope:
  commands: [status, diff, log, add, commit, push, pull, checkout, branch]
  endpoints: []
  data_access: read/write
  network: on (for push/pull only)
  filesystem: [<repo-root>]
approval:
  approver: Orchestrator
  date: 2026-01-16
  evidence: baseline tool
status: active
last_review: 2026-01-16
next_review: 2026-04-16
```

### TL-002: Markdown Lint

```yaml
tool_id: TL-002
name: markdownlint
version: "0.35+"
owner: DavidAnson
provenance:
  repo_url: https://github.com/DavidAnson/markdownlint
  commit_or_tag: v0.35.0+
  checksum: npm package integrity
  license: MIT
scope:
  commands: [lint]
  endpoints: []
  data_access: read
  network: off
  filesystem: [*.md]
approval:
  approver: QA Agent
  date: 2026-01-16
  evidence: baseline tool
status: active
last_review: 2026-01-16
next_review: 2026-04-16
```

### TL-003: Ripgrep (rg)

```yaml
tool_id: TL-003
name: ripgrep
version: "14+"
owner: BurntSushi
provenance:
  repo_url: https://github.com/BurntSushi/ripgrep
  commit_or_tag: 14.0.0+
  checksum: verified via package manager
  license: MIT/Unlicense
scope:
  commands: [search]
  endpoints: []
  data_access: read
  network: off
  filesystem: [<repo-root>]
approval:
  approver: Researcher Agent
  date: 2026-01-16
  evidence: baseline tool
status: active
last_review: 2026-01-16
next_review: 2026-04-16
```

---

## Tool Registry (Archived)

_No archived tools yet._

---

## Review Schedule

| Review Type | Frequency | Responsible |
|-------------|-----------|-------------|
| Quarterly security scan | Every 3 months | Security Agent |
| Version currency check | Every 3 months | Orchestrator |
| Scope audit | Every 6 months | Architect Agent |
| Full registry review | Annually | Director |

---

## Evidence Requirements

### For New Tools
- Provenance checklist completion record
- Risk trigger review (if applicable)
- Approval in DECISIONS.md
- Verification test result (if available)

### For Updates
- Change log review notes
- Updated provenance fields
- Approval with rationale
- Rollback plan reference

### For Removals
- Deprecation notice with timeline
- Migration evidence (if applicable)
- Final status update record

---

## References

- Tool governance policy: `core/orchestrator/TOOL_GOVERNANCE.md`
- Risk triggers: `core/packs/policy-pack-v1/RISK_TRIGGERS.md`
- Review checklist: `core/orchestrator/handoff/REVIEW_CHECKLIST.md`
- Evidence capture: `core/orchestrator/handoff/EVIDENCE_CAPTURE.md`
