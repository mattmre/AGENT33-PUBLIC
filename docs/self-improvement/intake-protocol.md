# Intake Protocol

How AGENT-33 processes new information sources and converts them into actionable knowledge.

## Repo Intake

When a new repository is provided for analysis:

1. **Clone** — Fetch the repository to a local working directory
2. **Dossier** — Generate a structured dossier using `docs/research/templates/REPO_DOSSIER_TEMPLATE.md`
3. **Feature Matrix** — Extract capabilities into `docs/research/templates/FEATURE_MATRIX_SCHEMA.md` format
4. **Gap Analysis** — Compare extracted features against AGENT-33's current capabilities
5. **Improvement Proposals** — Generate specific, testable proposals for any identified gaps
6. **Output** — Store dossier in `docs/research/repo_dossiers/`, update feature matrix

Usage: `agent33 intake <repo-url>`

## User Guidance Intake

When receiving user instructions or corrections:

1. **Parse Intent** — Identify what the user wants changed (behavior, output format, policy)
2. **Map to Files** — Locate the specific prompts, templates, or configs that govern the behavior
3. **Generate Edits** — Produce minimal, targeted changes
4. **Regression Test** — Run affected workflows against test cases to verify no regressions
5. **Apply** — Commit changes with full provenance (user request → file change → test result)

## Format/Situation Adaptation

When encountering a new data format or operational context:

1. **Analyze Structure** — Parse samples to identify schema, patterns, and edge cases
2. **Check Tool Registry** — Determine if existing tools can handle the format
3. **Generate Extension** — If no tool exists, generate a handler following the plugin system
4. **Test** — Validate against sample data
5. **Register** — Add to tool registry with capability declaration
