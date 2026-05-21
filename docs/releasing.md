# Releasing

This document explains how AGENT-33 releases are cut: the versioning
scheme, the lifecycle a release goes through, what the pre-release
checklist looks like, and how rollback works.

## Versioning

AGENT-33 follows [Semantic Versioning 2.0.0](https://semver.org/).

A version number is `MAJOR.MINOR.PATCH`:

- **MAJOR** changes when there is a breaking change to a public API,
  the persistence schema, or the configuration surface.
- **MINOR** changes when new functionality is added in a
  backwards-compatible way.
- **PATCH** changes for backwards-compatible bug fixes.

Pre-release tags use the `-rc.N` suffix: `0.2.0-rc.1`, `0.2.0-rc.2`,
and so on. A release candidate becomes a release by retagging without
the `-rc.N` suffix after validation completes.

## What counts as a breaking change

- Removing or renaming a public HTTP route under `/v1/`.
- Removing or renaming a CLI command or a CLI flag.
- Removing a field from a documented response shape, or changing its
  type.
- Removing an environment variable that has been documented in
  `docs/configuration.md`.
- A persistence migration that drops a column the engine reads.
- Changing the default behavior of an autonomy budget enforcement rule
  in a way that lets more behavior through.

Breaking changes are not forbidden — they are scheduled. They land in
the next MAJOR release with deprecation notices in the preceding MINOR
release.

## Release lifecycle

A release moves through a state machine:

```
planned → frozen → rc → validating → released
                                   → rolled_back
```

### planned

The maintainers have decided that a release will be cut. The version
number has been chosen. Pull requests targeting the release are tagged
with the release milestone in GitHub.

### frozen

The feature freeze date has been reached. From this point forward, only
bug fixes and documentation changes go into the release branch. New
features wait for the next release.

The release branch is named `release/MAJOR.MINOR` — for example,
`release/0.2`. PATCH releases for `0.2.0`, `0.2.1`, etc. are cut from
this branch.

### rc

A release candidate has been tagged. The CI pipeline runs the full
benchmark suite (not just the smoke tier) against the RC, and the
maintainers run the pre-release checklist below.

If the checklist surfaces a regression, a fix lands on the release
branch and the next RC (`-rc.2`, `-rc.3`, ...) is tagged.

### validating

The candidate has passed CI and the checklist. It is now being
validated in a representative deployment: a staging environment, a
maintainer's local environment, or a friendly user's environment. This
state lasts long enough to see whether anything breaks under real load
that the test suite did not catch.

### released

The release is tagged without the `-rc.N` suffix. The container image
is pushed to `ghcr.io/mattmre/agent33:MAJOR.MINOR.PATCH`. The release
notes are published. `CHANGELOG.md` is updated. The `main` branch is
fast-forwarded to include the release commit.

### rolled_back

If a post-release defect makes the release unusable, the release is
moved to `rolled_back` and the prior release is republished as the
recommended version. The defective release stays in the registry but
carries a warning in its release notes.

## Pre-release checklist

Run this checklist on every release candidate before promoting it to
`released`.

### Functional

- [ ] Full Python test suite passes (`python -m pytest tests/ -q`).
- [ ] Frontend test suite passes (`npm run test`).
- [ ] `ruff check` and `ruff format --check` pass.
- [ ] `mypy --strict` passes.
- [ ] Full SkillsBench tier passes (not just smoke).
- [ ] Docker image builds and the engine boots inside it.
- [ ] Docker Compose stack comes up cleanly from a fresh clone.
- [ ] All Alembic migrations apply forward from the previous release.
- [ ] All Alembic migrations apply backward (downgrade) from this
      release to the previous one.

### Documentation

- [ ] `CHANGELOG.md` is updated with the new version section.
- [ ] `RELEASE_NOTES.md` is updated (or a versioned release-notes file
      is added under `docs/release-notes/`).
- [ ] Any new environment variables are documented in
      `docs/configuration.md`.
- [ ] Any new CLI commands are documented in `docs/cli-reference.md`.
- [ ] Any new HTTP routes are documented in `docs/api-reference.md`.
- [ ] Any breaking changes have an entry in `docs/upgrade-guide.md`.

### Security

- [ ] Dependency scan has no high-severity findings against the new
      lockfile.
- [ ] No new secrets are committed (`git diff --stat` against the
      previous release tag is clean).
- [ ] The container image's published SBOM is up to date.

### Operations

- [ ] `deploy/k8s/` manifests render cleanly with `kubectl apply
      --dry-run=client`.
- [ ] The production overlay's HPA spec still references real metrics.
- [ ] Operator runbooks under `docs/operators/` and `docs/runbooks/`
      reference the new version where they reference a version at all.

If any line is unchecked, the candidate stays in `validating`. The
checklist itself lives in this document so it is versioned alongside
the code; copy it into the release pull request body and check items
off there.

## How to cut a release

These steps are written for a maintainer with push access to `main`
and tag-push access to the registry.

### 1. Open the release pull request

From the release branch (or `main` for a first MAJOR.MINOR):

```bash
git checkout -b release/0.2
git push -u origin release/0.2
gh pr create --base main --head release/0.2 \
  --title "Release 0.2.0" \
  --body-file .github/PULL_REQUEST_TEMPLATE/release.md
```

The body includes the checklist above.

### 2. Tag the release candidate

```bash
git tag v0.2.0-rc.1 -m "Release candidate 0.2.0-rc.1"
git push origin v0.2.0-rc.1
```

The CI workflow builds and pushes the RC container image as
`ghcr.io/mattmre/agent33:0.2.0-rc.1`.

### 3. Validate

Run the full pre-release checklist. If anything fails, fix it on the
release branch and tag the next RC.

### 4. Promote to released

When the checklist is clean:

```bash
git tag v0.2.0 -m "Release 0.2.0"
git push origin v0.2.0
```

The CI workflow:

- Builds and pushes the release container image.
- Creates a GitHub Release pointing at the tag with the release notes.
- Updates the `latest` container tag to point to the new release.

### 5. Merge the release pull request

Merge the release pull request into `main`. Delete the release branch
if it was a single-MINOR release branch; keep it if you intend to cut
patches.

### 6. Announce

Post the release announcement in the project's discussions area. Link
to the release notes and the migration guide if there is one.

## Patch releases

PATCH releases are cut from the existing `release/MAJOR.MINOR` branch.
The flow is the same as a MINOR release except the pre-release
checklist can skip the full benchmark suite (the smoke tier is enough
for a bug-fix release).

## Hotfix releases

A hotfix is a PATCH cut to address a defect in `released` state. Hotfix
flow:

1. Create a `hotfix/MAJOR.MINOR.PATCH` branch from the release tag.
2. Land the fix.
3. Run the pre-release checklist (smoke benchmark only is fine).
4. Tag and release.
5. Forward-port the fix into `main` if it does not already exist there.

## Rollback

If a post-release defect requires rollback:

1. Republish the previous release's container image as
   `ghcr.io/mattmre/agent33:latest`.
2. Add a `rolled_back` entry to the rolled-back release's section in
   `CHANGELOG.md` with the reason.
3. Open a hotfix branch from the previous release and start
   remediation.

The rollback action itself is reversible — once a hotfix release is
out, the rolled-back release stays in the registry with its warning,
and the hotfix becomes the recommended version.

## Release cadence

The intended cadence is:

- **MAJOR** releases: when breaking changes accumulate and are
  scheduled. Not on a fixed cadence.
- **MINOR** releases: roughly every 6-8 weeks once the project is
  stable.
- **PATCH** releases: as needed for bug fixes.

This is a target, not a contract. Releases ship when they are ready,
not when the calendar says they should.

## See also

- [`CHANGELOG.md`](../CHANGELOG.md) — version history
- [`RELEASE_NOTES.md`](../RELEASE_NOTES.md) — current release notes
- [`docs/upgrade-guide.md`](upgrade-guide.md) — migration notes
- [`docs/CONVENTIONS.md`](CONVENTIONS.md) — code and review standards
