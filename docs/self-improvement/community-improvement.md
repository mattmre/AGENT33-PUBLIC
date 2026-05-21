# Community Improvement

How multiple AGENT-33 agent instances share knowledge and improve collectively.

## Cross-Session Observations

Agents record observations during workflow execution:

- Performance metrics (latency, token usage, success rates)
- Failure patterns (common errors, edge cases, timeouts)
- User corrections (explicit feedback mapped to specific behaviors)

Observations are stored in engine memory with session provenance, accessible to all subsequent sessions.

## Structured Improvement Proposals

Proposals follow a standard format to enable automated evaluation:

```yaml
proposal:
  id: <uuid>
  type: prompt | workflow | template | routing | policy
  target_file: <path>
  description: <what changes and why>
  evidence:
    - observation_ids: [<uuid>, ...]
    - metrics: {before: ..., after: ...}
  test_cases:
    - input: ...
      expected_output: ...
  risk: low | medium | high
  requires_approval: true | false
```

Free-form suggestions are converted to this format before evaluation.

## Consensus Mechanism

Before applying a proposal:

1. **Multiple Evaluations** — At least 2 independent agent evaluations score the proposal on correctness, impact, and risk
2. **Regression Testing** — Proposal is tested against the full test suite
3. **Approval Gate** — High-risk proposals require human approval (`self_improve_require_approval` config)
4. **Application** — Approved proposals are applied atomically with rollback capability

## Knowledge Consolidation

Periodically, the system consolidates cross-session patterns:

- Summarizes recurring observations into durable knowledge entries
- Prunes obsolete or contradicted observations
- Updates routing weights based on accumulated performance data
- Generates trend reports stored in engine memory
