# Testing Protocol

Continuous testing ensures self-improvements do not degrade system quality.

## Always-Running Tests

These execute on every improvement cycle:

- **Prompt Quality Regression** — Compare outputs of modified prompts against baseline examples; flag quality drops
- **Workflow Validity** — Parse all workflow definitions; verify DAG integrity, action availability, and schema compliance
- **Policy Consistency** — Check that governance rules, RBAC policies, and tool allowlists remain internally consistent
- **Template Completeness** — Verify all templates have required fields, no unresolved placeholders

## On-Change Tests

Triggered when specific files are modified:

- **APO Comparison** — Before/after evaluation of prompt modifications using the training eval model
- **Dry-Run Workflows** — Execute modified workflows with mock inputs; compare outputs to expected baselines
- **Compliance Checks** — Verify changes respect security policies and governance constraints

## Self-Generated Test Cases

The system generates and maintains its own test corpus:

- **Storage**: `engine/data/test-cases/`
- **Format**: JSON files with input, expected output, and metadata
- **Lifecycle**: Generated during intake, updated when behavior changes, pruned when obsolete
- **Coverage**: Each improvement proposal must include at least one test case that would fail without the improvement

## Quality Gates

All improvements must pass the regression gates defined in `core/arch/REGRESSION_GATES.md` before being applied. No improvement is applied if any gate fails.
