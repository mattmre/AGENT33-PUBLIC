# Collected — Dynamic Intake Directory

This directory is populated automatically by `agent33 intake <repo-url>`.

When the intake protocol processes a repository, it stores raw cloned assets here temporarily. Structured outputs (dossiers, feature matrices) are written to `docs/research/repo_dossiers/` and the feature matrix.

## Usage

```bash
# Analyze a repository
agent33 intake https://github.com/org/repo

# Analyze a local directory
agent33 intake /path/to/local/repo
```

## Contents

This directory should generally be empty in version control. Cloned repos are added to `.gitignore` and processed into structured outputs elsewhere.

See `docs/self-improvement/intake-protocol.md` for the full intake workflow.
