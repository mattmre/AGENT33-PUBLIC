# Review Checklist (Model-Agnostic)

Use this when risk triggers apply.

Related docs:
- `core/orchestrator/TWO_LAYER_REVIEW.md` (two-layer review workflow, signoff flow)
- `core/orchestrator/handoff/REVIEW_CAPTURE.md` (review capture template)
- `core/packs/policy-pack-v1/RISK_TRIGGERS.md` (risk triggers)

## Quick Reference

For full two-layer review workflow, see `TWO_LAYER_REVIEW.md`. This checklist provides a quick reference for common reviews.

## Required (All Reviews)
- [ ] Correctness and edge cases reviewed.
- [ ] Test plan is appropriate and executed (or rationale recorded).
- [ ] No unintended files or scope creep.
- [ ] Security or data-handling implications reviewed.

## Risk Trigger Checklist
- [ ] Security/Auth/Crypto
- [ ] Schema/Data Model
- [ ] Public API or Interface
- [ ] CI/CD or Deployment
- [ ] Large Refactor
- [ ] Prompt injection exposure
- [ ] Sandbox escape / expanded permissions
- [ ] Secrets/tokens handling
- [ ] Supply chain changes (dependencies, lockfiles, build scripts)

**If any triggers checked**: Two-layer review required. See `TWO_LAYER_REVIEW.md` for L1/L2 checklists.

Reference: `core/packs/policy-pack-v1/RISK_TRIGGERS.md`

## Optional (when applicable)
- [ ] Performance implications considered.
- [ ] Documentation updates confirmed.

## Signoff
- L1 Reviewer: _________________ Date: _________
- L2 Reviewer (if required): _________________ Date: _________
