# Testing

This document describes how the test suite is organized, what each layer
is responsible for, and how to run tests locally.

## Layout

```
engine/
├── tests/                  # All Python tests
│   ├── unit/               # Pure unit tests (no external services)
│   ├── integration/        # Tests that boot subsystems together
│   ├── benchmarks/         # SkillsBench tier-runner tests
│   └── conftest.py         # Shared fixtures
└── pyproject.toml          # pytest config

frontend/
└── src/
    └── **/__tests__/       # Component and hook tests, colocated
```

Tests live next to a module named after what they cover. A test for
`engine/src/agent33/agents/registry.py` lives at
`engine/tests/unit/agents/test_registry.py` (or a similar path that
mirrors the source tree).

## Running tests

### Python

From the `engine/` directory:

```bash
# Full suite
python -m pytest tests/ -q

# Single file
python -m pytest tests/unit/agents/test_registry.py -q

# Single test by name
python -m pytest tests/ -k "test_registry_loads_definitions" -q

# Stop on first failure
python -m pytest tests/ -x -q

# With coverage
python -m pytest tests/ --cov=agent33 --cov-report=term-missing -q
```

### TypeScript

From the `frontend/` directory:

```bash
# Full suite
npm run test

# Single file in watch mode
npm run test -- src/components/SessionView.test.tsx

# Lint and type-check
npm run lint
```

### Integration tests in Docker

Some integration tests need Postgres, Redis, and NATS running. The
simplest way to provide them is the Docker Compose stack:

```bash
# From repo root
docker compose up -d postgres redis nats

# Then run the integration suite from engine/
cd engine
python -m pytest tests/integration/ -q
```

The integration tests connect to the services on their default ports.
Override with environment variables if you have something else running
there:

```bash
POSTGRES_HOST=localhost POSTGRES_PORT=15432 python -m pytest tests/integration/ -q
```

## Test categories

### Unit tests

Unit tests exercise a single module in isolation. External services are
mocked. They should:

- Run fast (under 100 ms per test).
- Not need network access.
- Not need a running database or Redis or NATS.
- Assert on behavior, not on internal implementation details.

Use `pytest` fixtures for setup. Use `unittest.mock` for replacing
collaborators.

### Integration tests

Integration tests boot real subsystems and exercise them together. They
should:

- Use a real Postgres (via `docker compose up -d postgres`).
- Use a real Redis if Redis is part of the path under test.
- Reset state at the start of each test, not at the end (so a failed
  test does not leak state into the next one).
- Tear down resources in a `finally` block.

The `httpx.ASGITransport` pattern is common — it mounts the FastAPI app
in-process and lets you call routes without a real HTTP server.

### Benchmark tests

`tests/benchmarks/` contains the SkillsBench tier runners. They are
gated by markers so they do not run on every pull request:

```bash
# Smoke tier (runs on every pull request)
python -m pytest tests/benchmarks/test_skills_smoke.py -q

# Full tier (runs weekly)
python -m pytest tests/benchmarks/test_skills_full.py -q
```

See [`docs/benchmarks/README.md`](benchmarks/README.md) for what the
tiers measure.

## Writing useful tests

A useful test would catch a regression in the code it covers. A test
that asserts only "the route returns 200" is not useful by itself —
pair it with assertions on response shape, validation errors, persisted
state, or rendered output.

Concrete things to check in a request-handling test:

- Status code is the specific code you expect, not "either 200 or 401."
- Response body matches the documented shape (field names, types,
  required vs. optional).
- Database rows are written with the expected `tenant_id`.
- Negative cases return the documented error code and message.
- Cross-tenant access is denied (a token for tenant A cannot read tenant
  B's data).

Concrete things to check in a workflow test:

- The DAG executes in the expected order.
- Step outputs flow into the next step's inputs.
- A failing step triggers the retry policy.
- A timed-out step produces the right trace event.
- The checkpoint persists what the resume path needs.

## Fixtures

Common fixtures live in `engine/tests/conftest.py` and module-specific
`conftest.py` files closer to where they are used.

### Database

```python
@pytest.fixture
async def db_session(postgres_container):
    async with AsyncSession(engine) as session:
        yield session
        await session.rollback()
```

### Tenant

```python
@pytest.fixture
def tenant_id() -> str:
    return "test-tenant"

@pytest.fixture
def auth_headers(tenant_id):
    token = make_test_jwt(tenant_id=tenant_id)
    return {"Authorization": f"Bearer {token}"}
```

### App with overrides

```python
@pytest.fixture
async def app(monkeypatch):
    monkeypatch.setenv("AGENT33_TESTING", "1")
    async with lifespan_test_context() as app_:
        yield app_
```

## Mocking the LLM

Real LLM calls in tests are slow, non-deterministic, and expensive. The
test suite uses a fake provider that returns scripted responses:

```python
from agent33.llm.fakes import ScriptedProvider

provider = ScriptedProvider(
    responses=[
        {"content": "I will use the search tool.", "tool_calls": [...]},
        {"content": "The answer is 42."},
    ]
)
```

Register it through the model router for the duration of the test:

```python
@pytest.fixture
def scripted_router(provider):
    return ModelRouter(providers={"scripted": provider}, default="scripted")
```

## Async tests

Async tests work automatically because `pyproject.toml` sets
`asyncio_mode = "auto"`. You can declare a test as `async def` without
the `@pytest.mark.asyncio` decorator.

If you convert a synchronous service method to `async`, remember to
update direct callers in tests. A missed `await` will show up as a
`RuntimeWarning: coroutine was never awaited` and an `AttributeError` on
the returned coroutine.

## Frontend tests

Frontend tests use Vitest and React Testing Library. Each test should:

- Render the component with the same props the production code uses.
- Assert on what the user sees, not on internal component state.
- Mock API calls at the `fetch`/`axios` boundary, not deeper.

A useful frontend test exercises an interaction the user can perform
and checks that the UI ends up in the expected state.

## CI

The CI pipeline runs on every pull request:

1. **Lint** — `ruff check`, `ruff format --check`, `mypy --strict`.
2. **Unit tests** — `pytest tests/unit/` and `npm run test`.
3. **Integration tests** — `pytest tests/integration/` against a
   service container.
4. **Build** — `npm run build` and a Docker image build for the engine.
5. **Smoke benchmark** — `pytest tests/benchmarks/test_skills_smoke.py`.

A pull request is mergeable when all five pass. CI failure on the smoke
benchmark is treated as a regression unless the diff is in
`tests/benchmarks/` itself.

## Test quality checklist

Before requesting review on a pull request that adds tests:

- [ ] Each test would catch a real regression in the code under test.
- [ ] Each assertion checks a specific expected outcome, not "either X
      or Y."
- [ ] Mocks reach the layer under test (not so deep that the test only
      exercises the mock).
- [ ] Negative cases are covered, not just happy paths.
- [ ] Cross-tenant negative cases are covered where applicable.
- [ ] No test depends on the order of other tests.
- [ ] No test leaves state behind on failure.

## See also

- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — contribution workflow
- [`docs/CONVENTIONS.md`](CONVENTIONS.md) — code and review standards
- [`docs/benchmarks/README.md`](benchmarks/README.md) — SkillsBench
  tiers
