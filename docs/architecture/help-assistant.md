# Help Assistant — Architecture

The Help Assistant drawer is the in-product help surface. It is populated from
`frontend/src/features/help-assistant/helpCorpus.ts`, a static corpus of
help topics organized by user intent (connect, demo mode, role-based start
paths, helper runtime modes, etc.).

## Runtime

- **Drawer** — `frontend/src/features/help-assistant/HelpAssistantDrawer.tsx`
  renders a sliding panel with search and topic cards.
- **Corpus** — `helpCorpus.ts` defines each topic: title, audience, summary,
  body bullets, step list, keywords, source file references, and contextual
  actions.
- **Modes** — `helperModes.ts` exposes three readiness modes (deterministic
  cited search, optional browser semantic search, optional Ollama sidecar).
  Only the deterministic mode is enabled by default; the other two are
  opt-in to keep first-run installs lightweight.
- **Retrieval** — `search.ts` does the in-corpus lookup. `ragApi.ts` is the
  thin client for the optional engine-backed RAG retrieval (off by default).

## Operator notes

- Edit topics in `helpCorpus.ts`. Each topic's `sources` list shows operators
  which code files the topic is grounded in; keep these accurate so a curious
  user can audit the recommendation.
- The drawer does not call models or store secrets. It is safe to surface
  before any credentials are configured.
- New topics should follow the existing schema: an `id`, an `audience` line
  describing who the topic helps, a short `summary`, `body` bullets for
  context, a `steps` list for the action, `keywords` for search, `sources`
  for traceability, and contextual `actions` for navigation.

## Source map

The drawer is wired in `frontend/src/App.tsx` (or the equivalent shell file)
behind a help icon in the global header. The default open state is closed;
state is local to the session.
