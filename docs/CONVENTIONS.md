# Conventions

This document explains how AGENT-33 is organized, how changes flow through
the repository, and the standards a contribution is expected to meet. If
you have read `CONTRIBUTING.md`, this is the next level down: the day-to-day
rules of the road.

## Repository layout

```
AGENT33-PUBLIC/
├── engine/               # Python/FastAPI runtime engine
│   ├── src/agent33/      # Importable package
│   ├── tests/            # Pytest suite
│   ├── alembic/          # Database migrations
│   └── agent-definitions/  # JSON agent definitions auto-loaded at startup
├── frontend/             # React/TypeScript operator console
├── core/                 # Runtime templates, schemas, workflows, packs
├── deploy/               # Docker Compose and Kubernetes manifests
├── docs/                 # Public documentation
├── scripts/              # Helper scripts for local development
└── examples/             # Worked examples and walkthroughs
```

Each subtree owns a focused part of the system. Cross-cutting changes
should be split into per-subtree commits where possible so reviewers can
read one concern at a time.

## Branching and merge policy

- `main` is the integration branch and is always intended to be releasable.
- Feature work happens on short-lived branches named after the change:
  `feat/<short-slug>`, `fix/<short-slug>`, `docs/<short-slug>`, etc.
- A pull request is the only way changes land on `main`. Direct pushes to
  `main` are disabled.
- One pull request equals one focused change. If a branch grows beyond one
  concern, split it before requesting review.
- Squash merge is the default. Merge commits and rebase merges are also
  acceptable; the maintainer choosing the merge button picks the strategy
  that produces the clearest history.

## Commit messages

Use imperative present tense and keep the subject line under 72
characters.

```
Add tenant scope guard to /v1/sessions

Sessions previously returned across tenants when the caller used a
service-account token. This adds the scope guard at the route layer
and the corresponding service-layer assertion.
```

The body is optional for small changes, expected for anything touching
public APIs, persistence, or security boundaries. Reference the relevant
issue with `Refs #NNN` or `Closes #NNN`.

## Code style

### Python

- Python 3.11 or newer. We use 3.12 in CI.
- Formatter and linter: `ruff`. Config is in `pyproject.toml`.
- Line length: 99.
- Type checker: `mypy --strict` with the pydantic plugin. Type annotations
  are required for new public functions and methods.
- Imports are sorted by ruff (`I` rule set).

Run before pushing:

```bash
cd engine
python -m ruff check src/ tests/
python -m ruff format --check src/ tests/
python -m mypy src --config-file pyproject.toml
python -m pytest tests/ -q
```

All four must pass locally.

### TypeScript

- TypeScript strict mode. No `any` without a justifying comment.
- ESLint and Prettier configs live in `frontend/`.
- Components are functional. Hooks live next to the component they serve
  unless they are shared.

Run before pushing:

```bash
cd frontend
npm run lint
npm run test
npm run build
```

### Markdown

- Wrap lines at roughly 80 characters where it does not break readability.
- Use ATX headings (`#`, `##`, `###`).
- Use fenced code blocks with a language tag (` ```python `, ` ```bash `,
  etc.) so syntax highlighting renders correctly.
- Mermaid diagrams use ` ```mermaid ` and live alongside the prose they
  illustrate.

## Tests

Every change that touches engine code is expected to ship with tests that
exercise the behavior it changes.

- Unit tests live in `engine/tests/` next to a file named after the module
  under test.
- Integration tests that boot subsystems live in
  `engine/tests/integration/`.
- Frontend unit tests live next to the component they cover, named
  `<Component>.test.tsx`.

A test is useful when it would catch a regression in the code it covers.
Tests that only assert the route exists or that a function returns
without raising are not enough on their own — pair them with assertions
on response shape, validation errors, persisted state, or rendered
output.

If something is hard to test because the mock infrastructure does not
exist yet, build the mock infrastructure as part of the same change
rather than skipping the test.

See `docs/testing.md` for the full testing guide.

## Documentation

- Public-facing behavior change requires a docs update in the same pull
  request. This includes new routes, new CLI commands, new environment
  variables, new config knobs, and any change to defaults.
- Architecture docs live in `docs/architecture/`. Operator runbooks live
  in `docs/operators/` and `docs/runbooks/`.
- Examples live in `examples/`. If you add a new example, add a pointer
  to it from `docs/examples.md`.

## Configuration

- All configuration is read through `engine/src/agent33/config.py`.
- New settings get an entry in `docs/configuration.md` with the variable
  name, type, default, and a one-line description.
- Sensitive settings use `pydantic.SecretStr`. Callers must use
  `.get_secret_value()` at the point of use.
- Defaults are chosen so that the system runs safely out of the box.
  Production-only defaults (longer timeouts, stricter rate limits) live
  behind explicit environment variables, not in code.

## Database migrations

- Schema changes go through Alembic. The migration lives in
  `engine/alembic/versions/` and is generated with
  `alembic revision --autogenerate -m "<short message>"`.
- Read the generated migration before committing it. Autogeneration is a
  starting point, not a final draft.
- Backwards-incompatible migrations need an upgrade note in
  `docs/upgrade-guide.md`.

## Security-relevant changes

If a change touches authentication, authorization, the tool framework,
the sandbox, autonomy enforcement, secrets, or the audit trail, mark the
pull request with the `security` label and request a second reviewer.

See `SECURITY.md` for the disclosure process for security issues you
discover in already-merged code.

## Multi-tenancy

`tenant_id` is propagated through every persistence and service layer.
When adding new tables, queries, or service methods:

- Tables get a `tenant_id` column unless the data is genuinely global
  (e.g., the pack registry).
- Queries are scoped by `tenant_id` from the resolved auth context.
- Tests cover the cross-tenant negative case (token from tenant A must
  not see data for tenant B).

See `docs/architecture/multi-tenancy.md` for the full model.

## Performance budgets

- New synchronous endpoints should respond in under 200 ms at p95 on the
  reference Docker Compose stack with a representative tenant fixture.
- New async pipelines should not block the event loop. Use
  `run_in_executor` for CPU-bound work and async clients for I/O.
- Database queries inside request handlers must use an index. If the
  query is new, the migration that supports it ships in the same pull
  request.

## Dependency policy

- Engine dependencies live in `engine/pyproject.toml`. Pin to a
  compatible range (e.g., `>=1.4,<2.0`), not a single version, unless a
  pin is required for a security fix.
- Frontend dependencies live in `frontend/package.json`. Lockfiles
  (`package-lock.json`) are checked in.
- New dependencies need a short justification in the pull request body:
  what problem they solve, what the alternative was, and whether the
  license is compatible (Apache 2.0, MIT, BSD-style are fine; copyleft
  needs a maintainer review).

## API stability

- Routes under `/v1/` are stable. Breaking changes require a `/v2/` route
  and a deprecation window for `/v1/`.
- Response shapes are stable. Adding a new optional field is allowed;
  removing or renaming a field is a breaking change.
- The CLI's command names and flag names follow the same rules as the
  HTTP API.

## License headers

Source files do not require per-file license headers. The Apache 2.0
license at the repository root covers the project. New files should still
carry a one-line module docstring explaining what the module does.

## Maintainer notes

Reviewers approve pull requests that meet these conventions and the
acceptance criteria in `CONTRIBUTING.md`. A pull request that does not
meet them gets review comments, not an approval. The contributor and the
reviewer share responsibility for making the diff land in a state the
project can stand behind.

## See also

- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — how to make a contribution
- [`docs/testing.md`](testing.md) — how the test suite is organized
- [`docs/releasing.md`](releasing.md) — how releases are cut
- [`docs/architecture/`](architecture/) — system internals
