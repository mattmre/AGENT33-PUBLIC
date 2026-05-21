# Python instructions

```yaml
applyTo:
  - "**/*.py"
  - "src/**"
```
- Use `black`, `ruff`, `isort`; import order: stdlib, third‑party, local.
- Prefer `requests` (or `httpx` if present); centralize HTTP in a single module.
- Add `tenacity`-style retries only if repo already uses it; otherwise implement simple backoff.
- Use `argparse` with subcommands for CLI.
- `pytest` with fixtures; mark network tests and make them opt‑in.
