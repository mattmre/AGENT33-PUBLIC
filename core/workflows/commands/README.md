# Commands Specification

Commands are standardized workflow entry points for the AGENT-33 orchestration framework. They provide a consistent interface for invoking common workflows across any execution environment.

## Purpose

Commands serve as:
- **Workflow triggers**: Standardized entry points for recurring operations
- **Context loaders**: Automatic ingestion of relevant handoff documents
- **Output producers**: Structured updates to handoff artifacts

## Naming Conventions

| Convention | Example | Description |
|------------|---------|-------------|
| Lowercase | `/status` | All command names use lowercase |
| Single word | `/verify` | Prefer single-word names when possible |
| Hyphenated | `/review` | Multi-word commands use hyphens |
| No prefix | `status` | Registry IDs omit the `/` prefix |

## Integration with AGENT-33 Orchestration

Commands integrate with the orchestration layer via:

1. **Handoff Documents**: Commands read from and write to standardized handoff files:
   - `STATUS.md`: Runtime state and blockers
   - `TASKS.md`: Task queue and priorities
   - `PLAN.md`: Implementation plans and phases
   - `DECISIONS.md`: Architecture decisions
   - `SESSION_WRAP.md`: Session handoff summaries
   - `REVIEW_CAPTURE.md`: Review outcomes

2. **Evidence Capture**: Commands that produce verification evidence follow the capture protocol defined in `core/packs/policy-pack-v1/EVIDENCE.md`.

3. **Role Routing**: Commands may route to specific agent roles as defined in `core/orchestrator/AGENT_ROUTING_MAP.md`.

## Command Lifecycle

```
Invocation → Context Load → Workflow Execution → Output → Handoff Update
```

1. **Invocation**: Command triggered by operator or orchestrator
2. **Context Load**: Relevant handoff docs ingested automatically
3. **Workflow Execution**: Command-specific logic runs
4. **Output**: Results returned to invoker
5. **Handoff Update**: Artifacts updated per command spec

## Model-Agnostic Design

Commands are designed to work with any execution environment:
- No assumptions about specific LLM providers
- No hardcoded tool or API dependencies
- Workflow logic expressed as portable specifications

## Related Documents

- `COMMAND_REGISTRY.md`: Full registry of available commands
- `core/ORCHESTRATION_INDEX.md`: Orchestration system overview
- `core/orchestrator/handoff/`: Handoff document templates
- `core/packs/policy-pack-v1/EVIDENCE.md`: Evidence capture protocol
