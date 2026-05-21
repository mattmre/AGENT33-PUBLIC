# Workflow Promotion Criteria

Use these criteria to decide whether a workflow or template should move from `core/workflows/sources/` into canonical `core/workflows/`.

## Promote if
- It is broadly reusable across repos (not product-specific).
- It documents a standard quality gate (tests, lint, security checks).
- It does not hardcode repo-specific paths or secrets.
- It matches the model-agnostic orchestration intent.
- It includes acceptance checks and verification evidence.
- It includes a brief security posture note (risk triggers, approvals).

## Keep in sources if
- It deploys a specific product or service.
- It assumes a particular repo layout, SDK, or runtime.
- It encodes organization-specific ownership or paths (e.g., CODEOWNERS).

## How to promote
1) Compare with existing canonical files.
2) Normalize names and paths for generic use.
3) Capture rationale, acceptance checks, and evidence references.
4) Update `core/workflows/README.md` and `core/CHANGELOG.md`.

## Promotion Decision Log (Template)
- Date:
- Candidate file:
- Decision: Promote / Keep in sources
- Rationale:
- Acceptance checks:
- Evidence:
- Security notes:
