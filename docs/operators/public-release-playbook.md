# AGENT-33 Public Release Playbook

**Maintainer reference for releasing AGENT-33 (and projects like it) from a
private internal monorepo into a polished public mirror.**

This playbook captures the procedure used to publish AGENT-33 v2.1.0 to
[mattmre/AGENT33-PUBLIC](https://github.com/mattmre/AGENT33-PUBLIC). It is
distilled from the EDCOCR-PUBLIC v4.1.0 release playbook (2026-05-21) plus
the AGENT-33-specific lessons learned during this release wave.

Treat it as a phase-by-phase checklist. Every phase has concrete commands,
a "what to verify" list, and the gotchas that cost real time on this
release. If you hit a new gotcha, add it to Phase 7 so the next release
benefits.

---

## How to read this doc

- **[FILE]** = a file to create or copy.
- **[CLI]** = a shell command — copy-paste, substitute `OWNER/REPO`.
- **[MANUAL]** = a GitHub web-UI step with no public API. Don't try to
  script it; you'll waste time.
- **[INTERNAL]** = a step that runs against the private monorepo's release
  tooling (`release/` directory in the maintainer's checkout). Public
  contributors do not run these.

Commands assume `gh` (GitHub CLI) is installed and authenticated against
the publishing account, and that you are at the working-tree root of the
public repo unless otherwise noted.

---

## Phase 0 — Sanitization (private → public mirror)

The hard rule for this phase: **do not git-init the public folder in
place inside the internal monorepo**. Stage a clean sibling folder. The
goal is a public repo whose `git log --all` carries no internal session
references, no `Co-Authored-By:` LLM footers, no internal program codes,
and no AI/agent platform references that don't belong in public.

### 0.1 Use the maintainer's `sync_public` engine [INTERNAL]

AGENT-33 ships a deterministic sync engine in the maintainer's internal
checkout at `release/scripts/sync_public.py`. It runs a three-phase
pipeline:

1. **Excludes** — skip files matched by `release/excludes.txt` and (since
   v2.1) `.gitignore`-scoped patterns. Internal-only paths (sessions,
   BHS, internal session logs, ops-only configuration, internal program
   research artifacts) drop here.
2. **Overrides** — substitute public-safe versions from
   `release/overrides/` for files that need a public counterpart distinct
   from the internal version (README, CHANGELOG, etc.).
3. **Regex rewrites** — apply token-level substitutions from
   `release/sanitize.yaml`. This is the catch-all for individual phrases
   that survive the previous two phases.

Run as:

```bash
# From the internal monorepo working tree
python release/scripts/sync_public.py --clean --target ../AGENT33-PUBLIC
```

`--clean` empties the target tree first. Be aware of the documented
`--clean` rename gap: files renamed on the internal side will not be
followed unless you re-add them to `release/manifest.yaml`. (Documented
in `release/README.md` of the internal checkout.)

### 0.2 Validate the staged tree [INTERNAL]

After every sync, the staged tree must pass:

```bash
python release/scripts/validate_public.py --target ../AGENT33-PUBLIC --static
python release/scripts/validate_public.py --target ../AGENT33-PUBLIC --deep
```

- `--static` checks: zero forbidden-token hits, no `mattmre@gmail.com` (PII),
  no `Co-Authored-By: Claude/Codex/Gemini` footers, no internal session
  IDs (`AEP-*`, `BHS-*`, `POST-*`), correct file layout, working
  `pyproject.toml` license declarations.
- `--deep` exercises `docker compose build` against the staged tree.
  Expects an operator-supplied `engine/.env` (the public ships
  `engine/.env.example` as a template). A missing `.env` is **not** a
  release blocker — public clones of the repo are expected to set up
  their own; it just means the deep validator can't smoke compose
  locally.

### 0.3 Owner sign-off

The owner reviews the staged tree manually before any `git init` or
`git push`. Specifically, owner should:

- Spot-check 5–10 random files for residue.
- Run `grep -rn "internal-program-code-pattern" .` (substitute the
  specific codes used internally).
- Confirm the `LICENSE`, `README.md`, `CHANGELOG.md`, `RELEASE_NOTES.md`,
  and `pyproject.toml` all agree on the release version and license.
- Confirm `git log --all` is clean (1 commit, no AI footers, no internal
  codes).

Sign-off is by explicit say-so. No "ship it if it looks right." On this
release, the sign-off uncovered a real PII leak in `CODE_OF_CONDUCT.md`
that the regex sweep had missed.

---

## Phase 1 — File layout (commit before publishing)

AGENT-33 v2.1.0 ships the following surface. Treat this as the
minimum-viable list for a flagship public release.

### 1.1 Root files

| File | Purpose | Status in v2.1.0 |
|---|---|---|
| `LICENSE` | Apache-2.0 | ✅ shipped |
| `README.md` | Landing page with hero, badges, quickstart, Mermaid diagram | ✅ shipped, polish gaps tracked |
| `CHANGELOG.md` | "Keep a Changelog" format, `[Unreleased]` + `[2.1.0]` entries | ✅ shipped |
| `RELEASE_NOTES.md` | Long-form release notes for the current version | ✅ shipped |
| `CONTRIBUTING.md` | How to file issues, submit PRs, run tests | ✅ shipped |
| `CODE_OF_CONDUCT.md` | **Link-only** to Contributor Covenant 2.1 | ✅ shipped (link-only pattern) |
| `SECURITY.md` | Vulnerability disclosure via GitHub Security Advisories | ✅ shipped |
| `SUPPORT.md` | Where to get help (Discussions vs. Issues) | ❌ MISSING |
| `CITATION.cff` | Surfaces "Cite this repository" button | ❌ MISSING |
| `INSTALL.md` | Install paths beyond what fits in the README | ✅ shipped |
| `DEVELOPMENT.md` | Local-dev workflow (lint, test, debug) | ❌ MISSING |
| `ARCHITECTURE.md` | High-level system architecture with Mermaid diagrams | ✅ shipped |
| `Makefile` | Common targets (`make install`, `make test`, `make lint`) | ✅ shipped |
| `QUICKSTART.md` | 5-minute path to a working stack | ✅ shipped |

### 1.2 `.github/` files

| File | Purpose | Status in v2.1.0 |
|---|---|---|
| `.github/CODEOWNERS` | Path-scoped review routing | ✅ shipped |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR checklist (include an explicit "no AI Co-Authored-By footers" line) | ✅ shipped |
| `.github/dependabot.yml` | Auto-bump dependencies | ✅ shipped |
| `.github/FUNDING.yml` | Renders "Sponsor" button — `github: [mattmre]` | ❌ MISSING |
| `.github/ISSUE_TEMPLATE/bug_report.yml` | Structured bug report form | ❌ MISSING |
| `.github/ISSUE_TEMPLATE/feature_request.yml` | Structured feature request form | ❌ MISSING |
| `.github/ISSUE_TEMPLATE/question.yml` | Routes questions to Discussions | ❌ MISSING |
| `.github/ISSUE_TEMPLATE/config.yml` | Disables blank issues; routes "Question" to Discussions | ❌ MISSING |
| `.github/social-preview.png` | 1280×640 hero banner / og:image source | ❌ MISSING |

### 1.3 `.github/workflows/`

| Workflow | Purpose | Status in v2.1.0 |
|---|---|---|
| `ci.yml` | Lint + test on PR and push | ✅ shipped |
| `benchmarks-weekly.yml` | Weekly SkillsBench full-tier benchmark | ✅ shipped |
| `docker-smoke.yml` | Docker compose build smoke | ✅ shipped |
| `post-merge-smoke.yml` | Post-merge full smoke on main | ✅ shipped |
| `runtime-compatibility.yml` | Runtime ABI/compat tests | ✅ shipped |
| `security-scan.yml` | Trivy + CVE scan | ✅ shipped |
| `release.yml` | Auto-create GitHub Release on `v*` tag | ❌ MISSING |
| `docker-publish.yml` | Build + push container image to `ghcr.io` on tag | ❌ MISSING |
| `dependabot-auto-merge.yml` | Auto-merge Dependabot PRs that pass CI | ❌ MISSING |

### 1.4 `docs/` tree

AGENT-33 already ships a structured `docs/` tree. Public release docs
live in `docs/operators/` (this file, the operator manual, deployment
runbooks, incident playbooks), `docs/architecture/` (deep-dive component
docs with mermaid diagrams), and topical reference docs at the top
level. The structure is good as-is for v2.1.0; future polish is the
numbered-prefix ordering (`00-...`, `01-...`) for natural sort.

### 1.5 `presentation/` HTML suite

A static HTML deck served via GitHub Pages. **MISSING in v2.1.0.** The
canonical layout is:

| Page | Audience |
|---|---|
| `presentation/index.html` | Landing / marketing hook |
| `presentation/executive-summary.html` | Non-technical decision-makers |
| `presentation/technical-brief.html` | Engineers evaluating the project |
| `presentation/use-cases.html` | "Could I use this for X?" |
| `presentation/architecture.html` | System diagram + component walkthrough |
| `presentation/white-paper.html` | Long-form technical write-up |
| `presentation/slides.html` | Conference-style slide deck |
| `presentation/assets/` | Shared CSS / JS / images |

Cross-link via a consistent nav bar. Verify GitHub Pages serves at
`https://mattmre.github.io/AGENT33-PUBLIC/presentation/`.

### 1.6 README structure

The polished README has these ingredients **in order**:

1. **Hero banner** — `<img src=".github/social-preview.png" alt="..." width="820">` above the H1.
2. **H1 title** + one-line tagline.
3. **Status badge row** — CI, container scan, license, version, Discussions, "PRs welcome".
4. **30-second quickstart** — `git clone → docker compose up → one command that does something`.
5. **System overview** — a Mermaid diagram (mirrored from `ARCHITECTURE.md`).
6. **Feature highlights** — bullet list, 8–15 items.
7. **Links to deeper docs** — `docs/` and `presentation/`.
8. **Contributing call-to-action** — explicit "open a Discussion" invite.
9. **Contributors widget** — `<img src="https://contrib.rocks/image?repo=mattmre/AGENT33-PUBLIC" />`.
10. **Star history** — `star-history.com` `<picture>` block.
11. **Footer nav** — Issues · Discussions · Security · License.

AGENT-33 v2.1.0 README has #2, #3, #4, #6, #7, #11. Hero banner,
Mermaid, contrib.rocks, star history are gaps — track for v2.2.0.

---

## Phase 2 — Initial publish

```bash
# In the staged public-mirror working tree
cd ../AGENT33-PUBLIC
git init
git add .
git commit -m "Initial public release: AGENT-33 v2.1.0"  # No AI co-author footers
git branch -M main
git remote add origin https://github.com/mattmre/AGENT33-PUBLIC.git
git push -u origin main

# Annotated tag for v2.1.0
git tag -a v2.1.0 -m "AGENT-33 v2.1.0 — Initial Public Release (2026-05-21)"
git push origin v2.1.0
```

If the repo doesn't exist on GitHub yet:
`gh repo create mattmre/AGENT33-PUBLIC --public --source . --remote origin --push`

**Auto-generated initial commit pattern.** If GitHub's "Create
repository" UI was used (with `Initialize this repository with a README`
checked), the remote will already have an initial commit you do not
own. Force-push your own initial commit over it:

```bash
git push --force-with-lease origin main
```

That cleanly rewrites the remote to your single commit. Acceptable on a
brand-new repo before public consumption begins.

---

## Phase 3 — GitHub web/API configuration

Order matters; some steps require the repo to be populated first.

### 3.1 Description + homepage [CLI]

```bash
gh repo edit mattmre/AGENT33-PUBLIC \
  --description "Local-first multi-agent orchestration platform with governance, evidence capture, and a usable control plane. FastAPI engine + React operator console + CLI + K8s manifests." \
  --homepage "https://github.com/mattmre/AGENT33-PUBLIC"
```

(Or `--homepage "https://mattmre.github.io/AGENT33-PUBLIC/"` once Pages
is enabled with a microsite.)

### 3.2 Topics (cap 20) [CLI]

Pick keyword-dense, search-discoverable tags. Mix **categorical** (`python`,
`docker`, `kubernetes`), **architectural** (`fastapi`, `react`, `multi-tenant`,
`postgresql`, `pgvector`, `nats`), **domain** (`ai-agents`, `multi-agent`,
`orchestration`, `llm-orchestration`, `workflow-engine`), **feature**
(`rag`, `bm25`, `mcp`, `skills`, `packs`), and **adjacent ecosystem**
(`ollama`, `local-first-ai`).

```bash
gh api -X PUT repos/mattmre/AGENT33-PUBLIC/topics \
  -H "Accept: application/vnd.github.mercy-preview+json" \
  -f names='["ai-agents","multi-agent","agent-orchestration","llm-orchestration","workflow-engine","local-first","fastapi","python","react","typescript","docker","kubernetes","postgresql","pgvector","nats","ollama","mcp","rag","governance","apache-2"]'
```

> **Gotcha (Git Bash on Windows)**: omit the leading slash. Use
> `repos/...`, not `/repos/...`.

### 3.3 Enable Discussions [CLI]

```bash
gh api -X PATCH repos/mattmre/AGENT33-PUBLIC -f has_discussions=true
```

### 3.4 Enable GitHub Pages [CLI]

```bash
gh api -X POST repos/mattmre/AGENT33-PUBLIC/pages \
  -f "source[branch]=main" \
  -f "source[path]=/"
```

Verify after 2–3 minutes at `https://mattmre.github.io/AGENT33-PUBLIC/`.

### 3.5 Disable Wiki [CLI]

The playbook recommends Wiki off because docs live in `docs/`, not the
Wiki:

```bash
gh api -X PATCH repos/mattmre/AGENT33-PUBLIC -f has_wiki=false
```

### 3.6 Create the GitHub Release [CLI]

```bash
gh release create v2.1.0 \
  --title "AGENT-33 v2.1.0 — Initial Public Release" \
  --notes-file RELEASE_NOTES.md \
  --latest
```

### 3.7 Repo Settings → Features [MANUAL]

At `https://github.com/mattmre/AGENT33-PUBLIC/settings`, verify:

- [x] Issues
- [x] Discussions (just enabled)
- [x] Sponsorships — pulls from `.github/FUNDING.yml` automatically
- [ ] Wiki — OFF
- [x] Preserve this repository — optional (Software Heritage archive)

### 3.8 Upload og:image / share card [MANUAL — NO API]

At `https://github.com/mattmre/AGENT33-PUBLIC/settings#social-preview`,
upload `.github/social-preview.png` (1280×640 minimum).

> **Critical**: there is NO public API for the og:image. Having the PNG
> at `.github/social-preview.png` renders it *inside* the README but
> does NOT set the share card on Slack / X / LinkedIn. Manual upload is
> the only way. Verify with the [LinkedIn Post
> Inspector](https://www.linkedin.com/post-inspector/).

### 3.9 Post an inaugural Discussion [CLI, GraphQL]

```bash
REPO_ID=$(gh api graphql -f query='
  query {
    repository(owner: "mattmre", name: "AGENT33-PUBLIC") {
      id
      discussionCategories(first: 10) { nodes { id name } }
    }
  }' --jq '.data.repository.id')

# Get the Announcements category ID from the query above, then:
gh api graphql -f query='
  mutation {
    createDiscussion(input: {
      repositoryId: "'$REPO_ID'",
      categoryId: "ANNOUNCEMENT_CATEGORY_ID",
      title: "Welcome to AGENT-33 — and how to join as a contributor",
      body: "..."
    }) { discussion { url } }
  }'
```

> **Gotcha**: `pinDiscussion` does **not** exist in GitHub's GraphQL
> schema. Posts in **Announcements** get prominent visual treatment
> without explicit pinning.

### 3.10 Verify the About sidebar

The right sidebar at `https://github.com/mattmre/AGENT33-PUBLIC` should show:

- ✅ Description
- ✅ Website link
- ✅ All ~20 topics
- ✅ Activity / Stars / Forks / Watchers
- ✅ Releases — v2.1.0 marked "Latest"
- ✅ Packages — once docker-publish workflow succeeds
- ✅ Contributors — auto-populated
- ✅ Languages — auto-detected
- ✅ Sponsor button — from `.github/FUNDING.yml`
- ✅ Cite this repository — from `CITATION.cff`

---

## Phase 4 — CI/CD workflows

AGENT-33 v2.1.0 ships 6 workflows. Three remain to add for a fully
polished public release.

### 4.1 Already-shipped

| Workflow | Purpose |
|---|---|
| `ci.yml` | Lint + test |
| `benchmarks-weekly.yml` | Weekly SkillsBench full-tier |
| `docker-smoke.yml` | Compose build smoke |
| `post-merge-smoke.yml` | Post-merge smoke on main |
| `runtime-compatibility.yml` | ABI / runtime compat |
| `security-scan.yml` | Trivy + CVE scan |

### 4.2 To-add for full polish

| Workflow | Purpose | Critical gotchas |
|---|---|---|
| `release.yml` | Auto-creates a GitHub Release when a `v*` tag is pushed | Build release notes from `CHANGELOG.md` `[Unreleased]` section |
| `docker-publish.yml` | Build + push to `ghcr.io/mattmre/agent33:tag` on `v*` tag | **Build context**: AGENT-33's frontend `Dockerfile` `COPY`s from `core/` at repo root, so set `context: .`, `file: ./frontend/Dockerfile` — not `context: ./frontend` |
| `dependabot-auto-merge.yml` | Auto-merge Dependabot patch/minor PRs | Scope to `dependency-name:*` patch+minor only; force humans on majors |

### 4.3 Workflow hygiene

- [ ] All workflows pinned to specific action versions
  (`actions/checkout@v6`, not `@main`)
- [ ] Use `permissions:` blocks at job level (no `write-all` default)
- [ ] Use `concurrency:` to cancel superseded runs on the same PR
- [ ] Verify each workflow goes green before announcing the repo publicly

**Billing note**: this repo's owner runs with GitHub Actions billing
intentionally unavailable, so workflows may report 3-second failures on
every PR. Local validation is authoritative; release decisions do not
gate on Actions.

---

## Phase 5 — Discoverability & community polish

### 5.1 README hero polish

- Banner image at top (`.github/social-preview.png`)
- 5–7 shields.io badges
- A `<details>` block for the long Mermaid diagram so it collapses
- Always-current "Latest release" badge

### 5.2 `contrib.rocks` contributors panel

```markdown
## Contributors
<a href="https://github.com/mattmre/AGENT33-PUBLIC/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=mattmre/AGENT33-PUBLIC" />
</a>
```

### 5.3 Star history widget

```markdown
## Star history
<a href="https://star-history.com/#mattmre/AGENT33-PUBLIC&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)"
            srcset="https://api.star-history.com/svg?repos=mattmre/AGENT33-PUBLIC&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)"
            srcset="https://api.star-history.com/svg?repos=mattmre/AGENT33-PUBLIC&type=Date" />
    <img alt="Star history" src="https://api.star-history.com/svg?repos=mattmre/AGENT33-PUBLIC&type=Date" />
  </picture>
</a>
```

### 5.4 GitHub Pages microsite

If `presentation/` is shipped (Phase 1.5), Pages serves it at
`https://mattmre.github.io/AGENT33-PUBLIC/presentation/`. Verify
cross-links and that each HTML page has its own
`<meta property="og:image">` tag.

---

## Phase 6 — Verification checklist

Do not announce the repo publicly until every item passes.

### Repo landing page
- [ ] Banner image renders at the top of README
- [ ] CI badge is green (or honestly absent)
- [ ] Description is present and keyword-dense
- [ ] Homepage URL works
- [ ] Topics visible on About sidebar
- [ ] Sponsor button visible
- [ ] "Cite this repository" button visible
- [ ] Latest release (v2.1.0) shown
- [ ] Discussions tab visible

### Functional surfaces
- [ ] `git clone` + 30-second quickstart actually works on a fresh
  machine
- [ ] Issue templates render (3 options — Bug / Feature / Question)
- [ ] PR template renders on a test PR
- [ ] Discussions tab loads; inaugural welcome post visible in
  Announcements
- [ ] GitHub Pages site loads
- [ ] Docker image visible in the Packages sidebar (once
  `docker-publish.yml` succeeds)

### Sharing surfaces
- [ ] Paste the repo URL into Slack — share card uses the
  social-preview PNG
- [ ] Same test for X / LinkedIn
- [ ] `https://raw.githubusercontent.com/mattmre/AGENT33-PUBLIC/main/.github/social-preview.png` returns HTTP 200

### Hygiene
- [ ] Grep for `mattmre@gmail.com` — zero matches
- [ ] Grep for `Co-Authored-By: Claude/Codex/Gemini` — zero matches
- [ ] Grep for internal program codes (`AEP-*`, `BHS-*`, `POST-*`,
  session IDs) — zero matches
- [ ] `git log --all` clean (1 commit, no AI footers)
- [ ] License consistency: `LICENSE` file + `README.md` badge +
  `engine/pyproject.toml` `license` field + tool-definition YAMLs all
  agree

---

## Phase 7 — Gotchas (read before you start)

These cost real time on AGENT-33 v2.1.0 and EDCOCR-PUBLIC v4.1.0.

### From EDCOCR-PUBLIC v4.1.0

1. **Content-filter trip on the Contributor Covenant full text.** Use
   the link-only pattern in `CODE_OF_CONDUCT.md`. The full v2.1
   document enumerates harassment behaviors and trips some content
   filters when an AI tries to write it.

2. **Git Bash on Windows mangles `gh api` paths starting with `/`.** Use
   `repos/OWNER/REPO/...`, not `/repos/OWNER/REPO/...`.

3. **No `pinDiscussion` GraphQL mutation.** Use the **Announcements**
   category instead.

4. **No public API for the og:image / social preview share card.**
   `<img>` in README does not set the share card. Manual upload at
   Settings → Social preview is the only way.

5. **Repo node IDs are not predictable.** Query the GraphQL `id` field;
   never guess.

6. **Docker Publish workflow build context.** If your repo has
   subdirectories with their own Dockerfiles that `COPY` files from the
   repo root, the workflow must set `context: .` and
   `file: ./subdir/Dockerfile`. AGENT-33's frontend Dockerfile imports
   workflow YAML from `core/` and will fail with "file not found" if
   built with `context: ./frontend`.

7. **`CODEOWNERS` solo-maintainer trap.** Bare `* @your-handle` requires
   *you* to approve every PR. For community contributions, scope
   ownership to specific high-risk paths (CI workflows, governance
   files) and leave the rest unowned.

8. **Topics cap at 20.** Pick carefully.

9. **Failing CI is worse than missing CI.** Env-gate workflows that
   cannot possibly succeed yet.

10. **`.gitignore` `*.txt` rule traps `requirements*.txt`.** Add a
    `!requirements*.txt` exception.

11. **`git add -A` on Windows can fail on `nul` files.** Use specific
    file paths.

### NEW gotchas from AGENT-33 v2.1.0

12. **License consistency drift.** The README badge said "License: MIT",
    `engine/pyproject.toml` declared `license = { text = "MIT" }`, AND
    the 7 first-party tool-definition YAMLs (`shell.yml`, `browser.yml`,
    etc.) had `license: MIT` — but the actual `LICENSE` file shipped
    Apache-2.0. Always grep for `MIT|GPL|BSD|Apache` after touching any
    license-adjacent file. Tool-definition YAMLs frequently inherit a
    stale license declaration from a generic template.

13. **Version drift across release artifacts.** A single version bump
    must update `engine/pyproject.toml`, `frontend/package.json`,
    `frontend/package-lock.json` (TWO lines: the root and the inner `""`
    package entry), `engine/uv.lock` (line for the `agent33` package
    entry), `README.md` badges, `CHANGELOG.md` heading + footer links,
    and `RELEASE_NOTES.md` title + container image references. Missing
    any of these creates a confusing release.

14. **Re-tagging after a published release is destructive.** If you
    publish v0.1.0 and discover you wanted v2.1.0 instead, the safe
    sequence is: (a) `gh release delete v0.1.0 --yes`, (b) `git push
    origin :refs/tags/v0.1.0` (delete remote tag), (c) `git tag -d
    v0.1.0` (delete local tag), (d) amend the initial commit, (e)
    `git push --force-with-lease origin main`, (f) create the new tag,
    (g) `gh release create` for the new version. Deleting a GitHub
    Release does NOT delete the underlying tag — both must be deleted
    separately.

15. **Container image referenced in RELEASE_NOTES may not exist yet.**
    `RELEASE_NOTES.md` includes a line like
    `Container image: ghcr.io/mattmre/agent33:2.1.0`. If
    `docker-publish.yml` doesn't exist or hasn't run, this link will
    404. Either build/push the image before publishing or remove the
    reference until the pipeline exists.

16. **Owner sign-off catches what regex sweeps miss.** On this release,
    the regex-based sanitizer passed clean, but a 2-pass operator-driven
    review found PII (`mattmre@gmail.com` in `CODE_OF_CONDUCT.md`) and 5
    broken internal-repo URLs (`mattmre/AGENT33` instead of
    `mattmre/AGENT33-PUBLIC`). Build the sign-off step into the release
    process; don't trust the automation alone.

17. **GitHub Actions billing exhaustion is normal here.** This account
    runs with Actions billing intentionally unavailable. PR checks
    fail in ~3s across the board. Local validation
    (`validate_public.py --static --deep`) is authoritative. Admin-merge
    via the REST API `gh api -X PUT repos/OWNER/REPO/pulls/N/merge -f
    merge_method=squash` is the documented path when CI cannot run.

18. **`gh repo merge` can collide with local worktree branch usage.**
    `gh pr merge --delete-branch` can fail with
    `fatal: 'main' is already used by worktree ...`. Use the REST API
    merge instead.

---

## Phase 8 — Tiered checklists

### Minimum-viable release (≈ half a day)

The repo doesn't look abandoned. Suitable for narrow-audience tools.

- LICENSE, README, CHANGELOG, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT
  (link-only)
- `.github/ISSUE_TEMPLATE/{bug_report,feature_request}.yml`
- `.github/PULL_REQUEST_TEMPLATE.md`
- One CI workflow (lint + test)
- Topics set (5–10 is fine)
- `v*` tag + GitHub Release with notes
- Repo description + homepage URL
- Sponsor button (FUNDING.yml)

### Full polish (≈ 2–3 days)

What AGENT-33 v2.1.0 targets long-term. Suitable for flagship public
repos.

- Everything in Minimum-viable, plus:
- ARCHITECTURE.md with Mermaid diagrams
- Full `docs/` tree with numbered prefixes
- `presentation/` HTML suite served via GitHub Pages
- `.github/social-preview.png` + manual og:image upload
- Maxed-out 20 topics
- Discussions enabled + inaugural welcome post in Announcements
- Container publish workflow → `ghcr.io`
- Container security-scan workflow
- Dependabot + auto-merge for patch/minor
- README hero banner + badge row + Mermaid + contrib.rocks + star-history
- Verified share card via LinkedIn Post Inspector

### AGENT-33 v2.1.0 status against the full-polish checklist

- ✅ Apache-2.0 LICENSE
- ✅ README + CHANGELOG + CONTRIBUTING + SECURITY + CODE_OF_CONDUCT
- ✅ `.github/PULL_REQUEST_TEMPLATE.md`
- ✅ `.github/CODEOWNERS`
- ✅ `.github/dependabot.yml`
- ✅ 6 of 9 target CI workflows
- ✅ ARCHITECTURE.md
- ✅ Full `docs/` tree
- ✅ `v2.1.0` tag + GitHub Release with notes
- ❌ Topics (0 of 20 set)
- ❌ Homepage URL not set
- ❌ Discussions disabled
- ❌ Wiki still on
- ❌ No og:image / social-preview.png
- ❌ No CITATION.cff, SUPPORT.md, DEVELOPMENT.md
- ❌ No FUNDING.yml (no Sponsor button)
- ❌ No issue templates
- ❌ No `presentation/` microsite
- ❌ README lacks hero banner, Mermaid, contrib.rocks, star-history
- ❌ `release.yml`, `docker-publish.yml`, `dependabot-auto-merge.yml`
  not yet shipped

These are the v2.2.0 polish roadmap items, prioritized by reader-facing
impact (topics + Discussions + og:image first; presentation/ microsite
last).

---

## Appendix A — One-shot bootstrap (for the next release)

```bash
OWNER=mattmre
REPO=AGENT33-PUBLIC
VERSION=v2.1.0

# (Phase 0–2 already done at this point)

# Topics + Discussions + Pages
gh api -X PUT repos/$OWNER/$REPO/topics \
  -H "Accept: application/vnd.github.mercy-preview+json" \
  -f names='["ai-agents","multi-agent","agent-orchestration","llm-orchestration","workflow-engine","local-first","fastapi","python","react","typescript","docker","kubernetes","postgresql","pgvector","nats","ollama","mcp","rag","governance","apache-2"]'

gh api -X PATCH repos/$OWNER/$REPO -f has_discussions=true
gh api -X PATCH repos/$OWNER/$REPO -f has_wiki=false

gh api -X POST repos/$OWNER/$REPO/pages \
  -f "source[branch]=main" -f "source[path]=/" 2>/dev/null || true

# Description + homepage
gh repo edit $OWNER/$REPO \
  --description "Local-first multi-agent orchestration platform with governance, evidence capture, and a usable control plane. FastAPI engine + React operator console + CLI + K8s manifests." \
  --homepage "https://github.com/$OWNER/$REPO"

# Verify
gh repo view $OWNER/$REPO --json description,homepageUrl,hasDiscussionsEnabled,hasWikiEnabled,repositoryTopics

# THEN MANUALLY:
#   1. Settings → Social preview → upload .github/social-preview.png
#   2. Post inaugural Discussion in Announcements
#   3. Verify share card via LinkedIn Post Inspector
```

---

## Appendix B — Source references

| Source | URL |
|---|---|
| EDCOCR-PUBLIC v4.1.0 reference implementation | https://github.com/mattmre/EDCOCR-PUBLIC |
| Original playbook (distilled from this release) | (maintainer's local notes) |
| Keep a Changelog spec | https://keepachangelog.com/en/1.1.0/ |
| Contributor Covenant 2.1 | https://www.contributor-covenant.org/version/2/1/code_of_conduct/ |
| Citation File Format | https://citation-file-format.github.io/ |
| Shields.io badges | https://shields.io |
| contrib.rocks contributor widget | https://contrib.rocks |
| star-history.com | https://star-history.com |
| LinkedIn Post Inspector | https://www.linkedin.com/post-inspector/ |

---

**Maintainer note**: every public release surfaces one or two new
gotchas. Append them to Phase 7 and bump this playbook so the next
release benefits. If a step here becomes scriptable, lift it into
`release/scripts/` (internal) and reference the script here rather than
inlining the command sequence.
