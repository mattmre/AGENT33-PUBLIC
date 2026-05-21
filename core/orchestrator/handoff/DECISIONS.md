# DECISIONS (Architecture Decision Log)

## Related Handoff Docs
- Spec-first checklist: `handoff/SPEC_FIRST_CHECKLIST.md`
- Autonomy budget: `handoff/AUTONOMY_BUDGET.md`

## 2026-01-20: Competitive Analysis Integration Approach
**Decision:** Create separate PRs for each integration phase rather than one large PR.
**Why:** Easier review, clearer scope per PR, ability to merge incrementally.
**Consequences:** More PRs to review; may have merge conflicts if done out of order.

## 2026-01-20: Adopt Hooks, Commands, Skills, Rules Pattern
**Decision:** Integrate hooks system, slash commands, skills framework, and modular rules from competitive analysis.
**Why:** Improves developer UX, adds automation capabilities, maintains model-agnostic principle.
**Consequences:** Larger documentation surface; requires registry maintenance; adds ~5,200 lines across 4 PRs.

## 2026-01-20: Defer Plugin/Marketplace Guidance
**Decision:** Do not implement R-06 (Plugin/Marketplace Guidance) from competitive analysis.
**Why:** Low priority; Claude-specific feature; not aligned with model-agnostic principle.
**Consequences:** None significant; can revisit if needed.

## 2026-01-10: Separate repo + separate Ollama stack
**Decision:** Keep a dedicated qwen_ollama container + volume and expose on port 11435.
**Why:** Isolation from other projects; reproducible setup; easy to push to GitHub.
**Consequences:** Two Ollama instances can compete for one GPU if both active; manage via usage discipline.

## 2026-01-10: Worker model pinned hot
**Decision:** Pin Qwen model in memory during active sessions to avoid cold-start latency.
**Why:** 30B model cold load can take ~60s; pinned hot keeps responses fast.
**Consequences:** VRAM remains allocated; may interfere with other local LLM workloads.

## Example (Template)
**Decision:** <short decision title>
**Why:** <rationale>
**Consequences:** <tradeoffs>

## Decision Types
- Architecture
- Process/Policy
- Tooling/Runtime
- Security/Compliance
