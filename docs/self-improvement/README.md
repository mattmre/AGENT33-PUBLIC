# Self-Improvement Protocols

AGENT-33 is designed to improve itself continuously. Rather than storing static analyses, the system generates knowledge on demand and refines its own capabilities over time.

## Continuous Improvement Loop

1. **Observe** — Collect metrics, user feedback, and execution traces
2. **Analyze** — Identify patterns, bottlenecks, and capability gaps
3. **Propose** — Generate structured improvement proposals with expected impact
4. **Test** — Validate proposals against regression gates (`core/arch/REGRESSION_GATES.md`)
5. **Apply** — Merge approved changes into prompts, workflows, templates, or routing config
6. **Record** — Log the change, rationale, and measured outcome in engine memory

## Scope of Self-Improvement

| Can self-improve | Requires human approval |
|------------------|------------------------|
| Prompt templates | Schema changes |
| Workflow definitions | Security policies |
| Routing weights | Engine source code |
| Analysis templates | Spec deletion |
| Tool configurations | Access control rules |

## Offline Mode

When running without internet connectivity, the system continues optimizing using local models (Ollama). Proposals that require cloud resources or external data are queued for review when connectivity returns. See [offline-mode.md](offline-mode.md).

## Protocol Documents

- [intake-protocol.md](intake-protocol.md) — How to process new information (repos, guidance, formats)
- [testing-protocol.md](testing-protocol.md) — Continuous testing and regression prevention
- [offline-mode.md](offline-mode.md) — Silo operation and graceful degradation
- [community-improvement.md](community-improvement.md) — Multi-agent communal learning
