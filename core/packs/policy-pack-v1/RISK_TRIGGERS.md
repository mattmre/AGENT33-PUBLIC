# RISK_TRIGGERS.md (Policy Pack v1)

Purpose: Identify changes that require review before completion.

Related docs:
- `core/orchestrator/SECURITY_HARDENING.md` (prompt injection defense, sandbox approvals, secrets handling)
- `core/orchestrator/TOOL_GOVERNANCE.md` (allowlist policy)
- `core/orchestrator/CODE_EXECUTION_CONTRACT.md` (sandbox limits)

## Core Risk Triggers
- Security/Auth/Crypto changes.
- Schema or data model changes.
- Public API or interface changes.
- CI/CD or deployment changes.
- Large refactors or wide file touch.

## Agentic-Specific Triggers
- Prompt injection exposure (untrusted external content).
- Sandbox escape / expanded permissions.
- Secrets/tokens handling or config changes.
- Supply chain changes (new deps, lockfiles, build scripts).

## Prompt Injection Triggers
- Processing untrusted user input without sanitization.
- Fetching external content that may contain instructions.
- Passing user content to tool invocations.
- Modifying system prompts or agent behavior dynamically.

## Sandbox Approval Triggers
- First use of a new tool in session (AG-01).
- Request exceeds defined autonomy budget (AG-02).
- External network access request (AG-03).
- File write outside designated workspace (AG-04).
- Request for elevated permissions (AG-05).

## Secrets Handling Triggers
- Access to S3+ classified secrets.
- Potential secret exposure in logs or outputs.
- Changes to secrets storage or vault configuration.
- Token or credential rotation procedures.
