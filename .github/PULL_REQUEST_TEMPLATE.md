<!--
  Thanks for contributing to AGENT-33! Please fill in each section. The
  more concrete you are, the faster a maintainer can review and merge.
-->

## Summary

<1-3 sentences. What does this PR do? Link the issue, discussion, or
roadmap item it addresses.>

## Motivation

<Why is this change worth making? If it changes user-facing behavior, what
does the user gain? If it's internal, what does it unblock?>

## Changes

- <Bullet the substantive changes — modules, endpoints, behaviors. Keep
  it scannable. Code-style or formatting tweaks can be one line.>

## Test plan

- [ ] <How did you verify this works? `pytest tests/...`, `npm run test`,
      manual UI step, container build, etc.>
- [ ] <Edge case or regression you intentionally covered.>
- [ ] <If applicable: smoke command and expected exit code.>

## Risk & rollout

<Anything reviewers should look at especially carefully? Migrations,
schema changes, breaking API behavior, perf? Is this safe to roll back
by reverting? If feature-flagged, name the flag.>

## Checklist

- [ ] Lint / format / type-check pass locally (`ruff check`, `ruff format`,
      `mypy`, `npm run lint` as applicable).
- [ ] New code has tests; behavior changes have updated tests.
- [ ] Docs updated if user-facing surface changed (`README.md`, `docs/`,
      OpenAPI, CLI `--help`).
- [ ] No secrets, tokens, or private fixtures committed.
- [ ] Commits are reviewable on their own (squash if needed at merge).
