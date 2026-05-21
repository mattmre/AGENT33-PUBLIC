# Contributing Guide

## Development Setup

### Prerequisites

- Python 3.11+
- Docker and Docker Compose
- Git

### Local installation

```bash
cd engine
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

### Start infrastructure

```bash
docker compose up -d postgres redis nats ollama
```

## Code Style

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting.

```bash
# Check for issues
ruff check src/ tests/

# Auto-fix
ruff check --fix src/ tests/

# Format
ruff format src/ tests/
```

Configuration is in `pyproject.toml` under `[tool.ruff]`:

- Target: Python 3.11
- Line length: 99
- Selected rules: E, F, W, I, N, UP, B, A, SIM, TCH

### Type checking

```bash
mypy src/
```

Strict mode is enabled. All public APIs should have complete type annotations.

## Testing

### Run the full suite

```bash
pytest
```

### Run with coverage

```bash
pytest --cov=agent33 --cov-report=term-missing
```

### Test categories

- **Unit tests** (`tests/`): No external services required.
- **Integration tests** (`tests/integration/`): Require running services. Marked with `@pytest.mark.integration`.
- **Benchmarks** (`tests/benchmarks/`): Performance tests.

### Writing tests

- Use `pytest-asyncio` for async tests (auto mode is enabled).
- Use `MockLLMProvider` from `agent33.testing.mock_llm` for deterministic LLM responses.
- Use `WorkflowTestHarness` and `AgentTestHarness` for definition testing.

## Pull Request Process

1. Create a feature branch from `main`.
2. Write code following the existing patterns.
3. Add or update tests for your changes.
4. Ensure `ruff check`, `mypy`, and `pytest` all pass.
5. Open a PR with a clear description of the changes.
6. Address review feedback.

## Commit Messages

Use conventional commits:

- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation
- `refactor:` code restructuring
- `test:` adding or updating tests
- `chore:` maintenance tasks

## Architecture Decision Process

When proposing a change that affects the system architecture (new modules, new infrastructure dependencies, protocol changes, or significant behavioral changes), follow this process:

1. **Open a discussion issue** describing the problem, proposed solution, and alternatives considered.
2. **Write an Architecture Decision Record (ADR)** if the change is accepted. ADRs should include:
   - **Context**: What situation or problem prompted the decision.
   - **Decision**: What was decided and why.
   - **Consequences**: Trade-offs, risks, and follow-up work.
3. **Get approval** from at least one maintainer before implementation.
4. **Update documentation** (architecture.md, README, API reference) as part of the same PR.

Examples of changes that require an ADR:

- Adding a new infrastructure service (e.g., a new database, message broker).
- Changing the authentication or authorization model.
- Introducing a new protocol or replacing an existing one.
- Altering the workflow execution model.

## Module-Specific Guidelines

When adding new features, place your code in the appropriate module. The following table describes where different kinds of changes belong.

| Feature Type | Module | Key Files | Notes |
|---|---|---|---|
| New API endpoint | `api/routes/` | Create a new route module, register in `main.py` | Follow existing router patterns; use Pydantic models for request/response |
| New LLM provider | `llm/` | Implement `LLMProvider` protocol from `base.py` | Register in `ModelRouter`; add integration test |
| New agent definition | `agent-definitions/` | JSON file matching `AgentDefinition` schema | Auto-discovered by `AgentRegistry` on startup |
| New workflow definition | `workflow-definitions/` | JSON or YAML file matching `WorkflowDefinition` schema | Validated on load; step IDs must be unique |
| New workflow action | `workflows/actions/` | Create module with `async def execute(...)` | Register in `WorkflowExecutor._dispatch_action()`; add `StepAction` enum value |
| New tool | `tools/builtin/` | Implement `Tool` protocol from `tools/base.py` | Register in `tools/registry.py`; add governance rules if accessing external resources |
| New sensor | `automation/sensors/` | Follow patterns in `file_change.py`, `freshness.py` | Register with `SensorRegistry` |
| New messaging integration | `messaging/` | Follow patterns in `telegram.py`, `discord.py` | Add optional dependencies to `pyproject.toml` |
| Memory/RAG changes | `memory/` | Extend existing classes or add new submodules | Changes to embeddings or long-term storage require migration |
| Security changes | `security/` | See `auth.py`, `middleware.py`, `allowlists.py` | Requires security review (see checklist below) |
| Observability | `observability/` | `logging.py`, `tracing.py`, `metrics.py`, `alerts.py` | Use structlog for all logging; never use `print()` |

### Import rules

- Never introduce circular imports. The module dependency graph must remain a DAG.
- Lower-level modules (`config`, `llm`, `security`) must never import higher-level modules (`api`, `workflows`).
- Use Protocol classes for cross-module interfaces to maintain loose coupling.

## Documentation Requirements for New Features

Every PR that introduces a new feature or changes existing behavior must include documentation updates:

1. **Code comments**: Add docstrings to all public classes, methods, and functions. Use Google-style or NumPy-style docstrings consistently with the module.
2. **Architecture documentation**: If the change adds a new module, protocol, or extension point, update `docs/architecture.md`.
3. **API reference**: If the change adds or modifies API endpoints, update `docs/api-reference.md` with request/response formats and examples.
4. **Getting started**: If the change affects installation, configuration, or first-use experience, update `docs/getting-started.md`.
5. **README**: If the change adds a new top-level concept (new service, new CLI command, new config variable), update `engine/README.md`.
6. **Inline examples**: Include at least one working example in the docstring or documentation for any new public API.

PRs without documentation updates for user-facing changes will be sent back for revision.

## Performance Testing Expectations

### When to write performance tests

- Any change to the workflow executor, DAG builder, or step dispatch logic.
- Any change to the LLM router or provider implementations.
- Any change to the memory/RAG pipeline (embedding, search, ingestion).
- Any new tool implementation that performs I/O.

### How to write benchmarks

Place benchmark tests in `tests/benchmarks/`. Use `pytest-benchmark` or simple timing assertions:

```python
import time
import pytest

@pytest.mark.benchmark
async def test_workflow_execution_time():
    """Workflow with 10 sequential steps should complete under 5 seconds (dry run)."""
    definition = WorkflowDefinition.load_from_file("workflow-definitions/bench-10-steps.json")
    executor = WorkflowExecutor(definition)

    start = time.monotonic()
    result = await executor.execute({"dry_run": True})
    elapsed = time.monotonic() - start

    assert result.status == WorkflowStatus.SUCCESS
    assert elapsed < 5.0, f"Took {elapsed:.2f}s, expected < 5s"
```

### Performance baselines

- **Health check**: Less than 100ms (all service probes).
- **Single agent invocation (dry run)**: Less than 50ms.
- **10-step sequential workflow (dry run)**: Less than 500ms.
- **DAG build for 100 steps**: Less than 100ms.
- **Expression evaluation**: Less than 1ms per expression.

Include the benchmark results in your PR description if the change is performance-sensitive.

## Security Review Checklist for PRs

All PRs must be checked against the following security criteria. PRs that touch the `security/`, `tools/`, or `api/` modules require explicit sign-off from a maintainer on each applicable item.

### Authentication and authorization

- [ ] New endpoints require authentication (added to a router that goes through `AuthMiddleware`).
- [ ] New endpoints check appropriate scopes via `TokenPayload.scopes`.
- [ ] No endpoints accidentally added to the `_PUBLIC_PATHS` set in `security/middleware.py`.

### Input validation

- [ ] All user inputs are validated through Pydantic models (no raw `dict` from request body).
- [ ] String inputs have appropriate `max_length` constraints.
- [ ] Numeric inputs have `ge` / `le` bounds.
- [ ] File paths are validated against the path allowlist before use.

### Secrets and credentials

- [ ] No secrets, API keys, or passwords are hardcoded in source files.
- [ ] New configuration secrets use the `Settings` class in `config.py`.
- [ ] Secrets are not logged (check structlog calls for accidental exposure).
- [ ] Default values for secrets are clearly marked as development-only (e.g., `"change-me-in-production"`).

### Tool and command execution

- [ ] New tools enforce the command, path, and domain allowlists from `ToolContext`.
- [ ] Shell commands are not constructed from unsanitized user input.
- [ ] File operations respect the working directory and path allowlist.
- [ ] Network requests respect the domain allowlist.

### Data handling

- [ ] Sensitive data stored in PostgreSQL or Redis is encrypted if `ENCRYPTION_KEY` is set.
- [ ] User data is not leaked in error messages returned to clients.
- [ ] NATS messages do not contain raw secrets or credentials.

### Prompt security

- [ ] User inputs that flow into LLM prompts pass through `security/injection.py`.
- [ ] Agent definitions do not allow unconstrained prompt templates that could enable injection.

### Dependencies

- [ ] New Python dependencies are pinned with version ranges in `pyproject.toml`.
- [ ] New dependencies have been checked for known vulnerabilities (`pip audit` or equivalent).
- [ ] Optional dependencies (messaging, browser) are in the correct optional group, not in core dependencies.
