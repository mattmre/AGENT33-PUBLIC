# Improvement Cycle Workflow Templates

This directory contains the canonical, executable improvement-cycle workflow templates for Agent33.

## Source of Truth

- `*.workflow.yaml` files in this directory are the source of truth for improvement-cycle templates.
- Frontend preset metadata is a temporary projection of these YAML definitions until a backend template catalog is added.

## Templates

- `retrospective.workflow.yaml`
  - Workflow name: `improvement-cycle-retrospective`
  - Purpose: produce a deterministic retrospective scaffold with evidence prompts, action prompts, and a markdown summary.
- `metrics-review.workflow.yaml`
  - Workflow name: `improvement-cycle-metrics-review`
  - Purpose: produce a deterministic metrics review scaffold with focus areas, recommendation prompts, and a markdown summary.

## Usage

Load either template through the workflow definition loader:

```python
from pathlib import Path

from agent33.workflows.definition import WorkflowDefinition

definition = WorkflowDefinition.load_from_file(
    Path("core/workflows/improvement-cycle/retrospective.workflow.yaml")
)
```

These templates intentionally avoid fragile network-heavy or LLM-heavy actions. They use deterministic `validate` and `transform` steps so they can execute safely in the current engine.
