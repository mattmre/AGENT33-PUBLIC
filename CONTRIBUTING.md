# Contributing to AGENT-33

Thanks for taking the time to consider a contribution. AGENT-33 is an open
multi-agent orchestration framework, and the project is at its best when it is
shaped by the people who actually deploy and depend on it. This guide explains
how to file an issue, propose a feature, and submit a change — whether that
change is a one-line documentation fix or a new subsystem.

If anything below is unclear, open a discussion or a draft pull request and ask.
We would rather help you land your first contribution than have you guess at our
preferences and bounce off.

---

## Project at a glance

AGENT-33 is a Python 3.11+ runtime engine (`engine/`) plus a Markdown-native
specification layer (`core/`) and a React/TypeScript control plane
(`frontend/`). The engine is FastAPI-based and depends on PostgreSQL with
pgvector, Redis, NATS, and an optional local LLM via Ollama. The project is
released under the Apache License 2.0.

The official repository is
[`github.com/mattmre/AGENT33-PUBLIC`](https://github.com/mattmre/AGENT33-PUBLIC).
Container images are published to
[`ghcr.io/mattmre/agent33`](https://github.com/mattmre/AGENT33-PUBLIC/pkgs/container/agent33).

You can contribute in several ways:

- **Bug reports and reproductions.** Even a careful description of an
  unreproducible issue is helpful — it often surfaces a missing log line or an
  unclear error path.
- **Documentation.** Typos, broken links, clearer explanations, new tutorials,
  and worked examples are all in scope and very welcome.
- **Agent definitions, workflow templates, skills, and packs.** These are
  declarative artifacts under `core/` and `engine/agent-definitions/` — you do
  not need to touch the runtime to ship a useful one.
- **Engine features and fixes.** Bug fixes, new tools, new providers, new
  observability hooks, and improvements to the workflow engine.
- **Frontend features and fixes.** The control plane is a Vite + React app
  under `frontend/`.

---

## Filing an issue

Use [GitHub Issues](https://github.com/mattmre/AGENT33-PUBLIC/issues) for bug
reports and feature requests. Before opening a new one, please search both open
and closed issues — a quick check often finds the answer or an active thread.

A useful bug report contains:

1. **A short title** that names the surface and the symptom
   (e.g. "`agent33 bench run` exits 0 even when no tasks discovered").
2. **What you ran**, including the command, environment, and Python version.
   If the bug is in the engine, the output of `agent33 status` is often enough
   to reproduce.
3. **What you expected to happen.**
4. **What actually happened**, with the relevant log lines or stack trace.
   Wrap multi-line output in fenced code blocks so it stays readable.
5. **A minimal reproduction**, if you have one. A single failing command or a
   five-line snippet beats a long narrative.

A useful feature request contains:

1. **The problem** you are trying to solve. Even a one-sentence "I want to do
   X but cannot because Y" is enough.
2. **Why the existing surface does not solve it.** This helps us avoid
   suggesting a workaround you have already tried.
3. **A sketch of the API or UX you would like.** This does not need to be
   precise — it is a conversation starter, not a spec.

Please do **not** file public issues for security-sensitive reports. See
[`SECURITY.md`](./SECURITY.md) for the disclosure process.

---

## Proposing a change

For small fixes (typos, obvious bugs, one-line clarifications), you can skip
straight to a pull request. For larger changes — anything that adds a new API
surface, changes existing behavior, or touches multiple subsystems — please
open an issue first to discuss the direction. A short design conversation up
front saves everyone time.

If your change is substantial, opening the PR early as a **draft** is a great
way to get feedback while you are still iterating. Mark it ready for review
when you are happy with it.

---

## Setting up locally

You will need:

- **Python 3.11 or newer**. The engine targets `>=3.11` and uses syntax from
  newer versions.
- **Node 20 or newer** if you plan to touch the frontend.
- **Git**, of course.
- **Docker** is optional but useful for the full development stack
  (Postgres, Redis, NATS, Ollama).

Clone the repository and create a worktree-local virtual environment for the
engine:

```bash
git clone https://github.com/mattmre/AGENT33-PUBLIC.git
cd AGENT33-PUBLIC/engine

python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1

python -m pip install -e ".[dev]"
```

We strongly recommend the worktree-local virtualenv. Sibling Git worktrees
sharing one global editable install will silently run code from the wrong
checkout, which is the kind of bug that costs an afternoon.

For frontend work:

```bash
cd ../frontend
npm install
```

A fresh worktree never inherits `node_modules` from its parent — always run
`npm install` once per worktree before any `npm run` command.

To spin up the full local stack (engine + database + Redis + NATS):

```bash
make up        # docker compose up -d --build
make logs      # follow the API logs
make down      # stop the stack
```

See [`docs/testing.md`](./docs/testing.md) for the test layout and
[`docs/CONVENTIONS.md`](./docs/CONVENTIONS.md) for the contribution standard
reviewers apply.

---

## Branch and pull-request workflow

We use a lightweight, PR-based workflow:

1. **Branch off `main`.** Use a short, descriptive branch name. Prefix it with
   `fix/`, `feat/`, `docs/`, or similar if you like — we do not enforce a
   convention, but readable branch names help.
2. **Keep PRs focused.** One coherent change per PR. If you find yourself
   adding "and also" to the description, that probably wants to be a second
   PR.
3. **Write a useful PR description.** Explain *why*, not just *what* — the
   problem you are solving, what you considered, and any tradeoffs. Code
   answers "what"; the PR body should answer "why".
4. **Push and open the PR.** A `.github/PULL_REQUEST_TEMPLATE.md` is provided.
   You do not need to fill out every field of the contributor-internal
   template — focus on the summary, test plan, and any caveats.
5. **Respond to review.** A reviewer may ask for changes, ask questions, or
   suggest a different approach. None of this is personal; it is how the
   project stays consistent.
6. **Squash-merge is the default.** Once approved and CI is green, your PR
   will be squash-merged into `main`. Delete your branch after the merge —
   long-lived branches drift.

We **do not** require contributors to sign a CLA. By submitting a contribution
you agree it can be distributed under the Apache 2.0 license — that is the
extent of the legal mechanics.

---

## Commit message conventions

Commit messages are encouraged to follow a simple
[Conventional Commits](https://www.conventionalcommits.org/)-style prefix when
practical:

```
feat(workflows): add resume endpoint for paused executions
fix(memory): correct off-by-one in token chunker
docs(plugins): clarify lifecycle ordering for on_enable
refactor(api): consolidate auth scope helpers
test(execution): cover Windows subprocess quoting
chore(deps): bump pydantic to 2.10
```

We do not enforce this with a hook. The point is to make `git log` skimmable,
not to gate merges on commit message format. For PRs with multiple small
commits, the squash-merge title is what ends up on `main`, so make that title
informative.

---

## Code quality standards

Every PR must pass these checks locally before being marked ready for review.
CI runs the same set; you should not be guessing whether a check will fail.

From `engine/`:

```bash
python -m ruff check src/ tests/        # zero errors
python -m ruff format --check src/ tests/   # zero diffs
python -m mypy src --config-file pyproject.toml   # strict, zero errors
python -m pytest tests/ -q                # full suite green
```

From `frontend/`:

```bash
npm run lint          # TypeScript no-emit type check
npm run test          # Vitest
npm run build         # full production build
```

`ruff check` and `ruff format --check` are independent — the linter can pass
while the formatter still wants to reflow whitespace. Always run both.

Type checking is configured in strict mode. New code should be fully annotated.

### Tests should test behavior

The single most common reason a PR is sent back is shallow tests. A test that
asserts only on a route's existence, or that the module can be imported, or
that an endpoint returns 401 without auth, has near-zero regression value —
it would not catch any real bug in the handler.

When you add code, the test should exercise the same code path that production
traffic exercises and assert on response shapes, validation errors, business
rules, or state changes. If the boundary you need to mock does not exist,
build the mock — do not write a placeholder test instead and call it done.

This is explained in more depth in
[`docs/CONVENTIONS.md`](./docs/CONVENTIONS.md), which is the contribution
standard reviewers apply. Reading it before your first substantial PR is worth
fifteen minutes.

---

## Documentation contributions

Documentation lives in:

- The root files: `README.md`, `QUICKSTART.md`, `INSTALL.md`,
  [`CHANGELOG.md`](./CHANGELOG.md), [`RELEASE_NOTES.md`](./RELEASE_NOTES.md).
- The [`docs/`](./docs/) tree: concepts, glossary, conventions, testing,
  releasing, examples, plus the `operators/` and `runbooks/` subdirectories.
- Inline docstrings and code comments.

Documentation PRs follow the same workflow as code PRs — branch, PR, review,
merge. Two things to keep in mind:

1. **Examples should be runnable.** If you include a command, a YAML snippet,
   or a curl call, copy it out of your terminal — do not type it from memory.
   Broken examples are worse than no examples.
2. **Keep cross-links accurate.** If you rename a file, search the repo for
   inbound links and update them. Broken doc links are a project-wide tax.

If you are adding a new agent definition, workflow template, plugin, or pack,
the documentation for it lives next to the artifact. New plugins should include
a top-level `README.md`; new workflows should include an inline `description`
and a useful `metadata.tags` field.

---

## Anti-patterns we ask you to avoid

These are the most common ways well-intentioned PRs get bounced. None of them
will get you flamed — they will get the PR sent back with a request to fix
them, and avoiding them up front is faster.

1. **Half-wired client/server features.** If a change specifies that the
   client calls a server endpoint, both sides must exist and actually be
   connected. Calling the database directly from the client to "ship faster"
   defeats the layering and tends to break later in subtle ways.
2. **Placeholder values shipped unresolved.** If a UI field needs to be
   resolved from data (a title, a name, a URL), the code that resolves it
   must exist in the same PR. Raw IDs as display text with a comment
   promising "later" is a bug, not a feature.
3. **Silent scope reduction.** If a blocker prevents you from delivering what
   was discussed, say so explicitly in the PR description with a concrete
   proposal to close the gap. Quietly substituting an easier deliverable is
   the worst-case outcome for everyone.
4. **Tests that cannot fail.** An assertion like `assert status == 401 or
   status == 503` tests nothing — it means the test author did not know what
   the code would do. Each assertion should check one specific outcome.
5. **Test count as a quality metric.** Twenty tests that all check "the
   module imports" are worth less than three tests that catch real
   regressions. Write fewer, sharper tests.

If your PR drifts toward one of these because of a real blocker, the right
move is to call it out in the PR body and propose a follow-up. The wrong move
is to hope the reviewer does not notice.

---

## Platform-specific gotchas

A few things have bitten enough contributors to be worth flagging up front:

- **Fresh frontend worktrees need `npm install`.** A new Git worktree never
  inherits `frontend/node_modules` from the parent.
- **Windows console encoding can mask the real error.** On a Windows shell
  with a non-UTF-8 code page, stack traces from `structlog` can cascade into
  a `UnicodeEncodeError` that hides the underlying failure. Set
  `PYTHONIOENCODING=utf-8` before running tests if you see encoding errors.
- **Editable installs across worktrees.** If `pytest` seems to be running
  code from a different checkout than the one you are editing, you almost
  certainly have a stale `pip install -e` pointing at a sibling worktree.
  Fix it with a worktree-local venv as described above.

---

## Releases

The project follows [Semantic Versioning](https://semver.org/) and uses a
release lifecycle described in [`docs/releasing.md`](./docs/releasing.md). You
do not need to think about releases as a contributor — they are cut from `main`
on a rolling cadence — but a couple of things help:

- **Update [`CHANGELOG.md`](./CHANGELOG.md)** for any change that a user might
  notice. Add an entry under `## [Unreleased]` in the appropriate
  Added / Changed / Deprecated / Removed / Fixed / Security section.
- **For breaking changes**, call them out in the PR title (`feat!:` or
  `BREAKING CHANGE:` in the body) and in the changelog entry.

---

## License

AGENT-33 is licensed under the
[Apache License, Version 2.0](./LICENSE). By submitting a contribution to this
repository, you agree that your contribution may be distributed under the same
license. There is no separate contributor agreement to sign.

---

## Code of Conduct

This project is governed by the
[Contributor Covenant Code of Conduct](./CODE_OF_CONDUCT.md). By participating,
you agree to uphold it. Reports of unacceptable behavior may be sent to the
maintainer contact listed in that document.

---

## A note on tone

Reviews on this project aim to be direct, specific, and focused on the work.
"This needs to handle the empty-list case" is fine. "This is bad" is not.
We try to extend the same standard to contributor responses. If a review comment
lands wrong, please tell us so we can recalibrate — we would much rather adjust
than lose a contributor over a phrasing mistake.

Thanks again for considering a contribution. Clear, well-tested, end-to-end
changes from the community are what keep the project useful in the long run.

See also:

- [`docs/CONVENTIONS.md`](./docs/CONVENTIONS.md) — contribution standard
- [`docs/concepts.md`](./docs/concepts.md) — the mental model
- [`docs/testing.md`](./docs/testing.md) — how to write tests that matter
- [`docs/examples.md`](./docs/examples.md) — end-to-end worked examples
- [`SECURITY.md`](./SECURITY.md) — security disclosure process
