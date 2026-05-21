# AGENT-33 Design System

A design system, brand guide, and UI kit for **AGENT-33** — a local-first AI agent orchestration platform. Use this folder as the source of truth when designing new screens, prototypes, decks, or marketing material that should look and feel like AGENT-33.

> **The brand in one breath:** dark, technical, calm. A teal beacon (`#30d5c8`) on near-black panels, sharp chamfered corners and hairline accents (no soft cards, no rounded glass), mono labels for system speak, and Space Grotesk for everything else. It's a control plane for serious operators — not a consumer toy.

---

## Sources

The system was reverse-engineered from a single source repository:

- **GitHub:** [`mattmre/AGENT33-PUBLIC`](https://github.com/mattmre/AGENT33-PUBLIC) — main branch
- **Frontend code:** `frontend/src/styles.css` (~7,800 lines, exhaustive — the canonical token + component sheet) plus `frontend/src/components/*` (~25 React components covering the full control plane).
- **Top-level README** describes the platform's purpose, surfaces, and audience.

The repo describes itself as: *"a local-first AI agent orchestration platform for teams that want real workflows, explicit governance, and a usable control plane instead of a pile of disconnected scripts."*

There is **no Figma file**, no formal style guide doc, and no logo SVG in the repo. The only "logo" today is a CSS-rendered `.logo-orb` — a teal-to-deep-cyan conic-gradient circle with a pulse animation. Treat it as the official mark until told otherwise.

---

## What's in here

| File / folder | Purpose |
|---|---|
| `README.md` | This file. Brand overview, content guide, visual foundations, iconography, index. |
| `SKILL.md` | Agent Skill manifest so this folder can be consumed by Claude Code. |
| `colors_and_type.css` | All design tokens as CSS vars: colors, shadows, radii, spacing, type scale, plus a few semantic primitives (`.ds-button`, `.ds-input`, `.ds-method-badge`, `.logo-orb`, etc.). Drop this into any page to get the AGENT-33 look. |
| `assets/` | Logo + brand assets (the orb, wordmark mock). |
| `fonts/` | (None bundled — Space Grotesk and IBM Plex Mono load from Google Fonts. See "Fonts" below.) |
| `preview/` | Cards rendered on the Design System tab — type, colors, spacing, components. |
| `ui_kits/control-plane/` | The cockpit UI: topbar, nav, dashboard, operation cards, observation stream, auth panel, etc. Recreated from the source. |

---

## Brand context

**Product:** AGENT-33 (sometimes "AGENT33" or "AGENT-33 Control Plane" in chrome).

**One-liner:** "Local-first AI agent orchestration for teams that want real workflows, explicit governance, and a usable control plane."

**Audience:** Operators, platform engineers, researchers running self-hosted / on-prem AI. Not consumers. Comfortable with JWTs, Docker Compose, FastAPI.

**Surfaces:**
1. **Control plane web UI** (the cockpit) — at `localhost:3000`. Hosts: cockpit dashboard, agents, workflows, memory, reviews, traces, evaluations, autonomy, releases, dashboard, training, webhooks, MCP health, packs, tool catalog, agent builder, demo mode. Single product surface. *This is the only product surface — there is no separate marketing site, mobile app, or docs portal in the repo.*
2. **API** (FastAPI, served at `:8000`) — out of scope for visual design.

---

## Content fundamentals

How AGENT-33 talks. Match this voice in every label, button, and toast.

### Tone

- **Operator-grade.** Direct, precise, sometimes blunt. Assumes the reader has root.
- **No marketing fluff.** No "Welcome aboard! ✨", no "Let's get started together". Closer to a Cisco admin console than a Notion onboarding.
- **Calm & literal.** State what is happening, what's locked, what to do next. No hype, no exclamation points.

### Voice mechanics

| Aspect | Rule | Example from source |
|---|---|---|
| Person | **You**, occasionally implicit imperative. Never "we". | "Use login for seeded local credentials, or paste a token/API key." |
| Casing | **Sentence case** for everything — buttons, headings, nav. | "Choose workflow", "Review task board", "Sign In" (only exception). |
| Eyebrows | UPPERCASE, letter-spaced, very short. | "Project cockpit", "Current run", "Recommended next action". |
| Punctuation | Periods on full sentences. No periods on labels/buttons. No exclamation points anywhere. | — |
| Numbers | Spell out below 10 in copy ("one task"), digits in stats. Pluralize correctly: "1 task needs attention" / "3 tasks need attention". | — |
| Emoji | **Yes, sparingly — only as status dots in health/status indicators.** 🟢 ok / healthy. 🟡 configured / pending. 🔴 error / degraded. ⚪ unconfigured. Never decorative, never in headings. | `HealthPanel.tsx` uses these literal emoji as state icons. |

### Vocabulary (used in source)

Use these words; they're the product's native vocabulary:

> agent, workflow, run, session, scope, autonomy, autonomy budget, approval, gate, safety gate, release, review, artifact, pack, P-PACK, P-PACK v3, evaluation, trace, observation, telemetry, rollout, improvement loop, cockpit, control plane, operator, runtime, JWT, API key, model routing, Ollama, hard gate, soft gate, MCP, runbook, walkthrough.

Avoid the generic SaaS register: "magic", "delight", "supercharge", "AI-powered", "seamless", "effortless", "journey", "empower".

### Writing samples

```
Eyebrow:   PROJECT COCKPIT
Heading:   Welcome back, operator
Paragraph: Pick up the active project, or open the cockpit to plan the next run.
Button:    Review task board
Helper:    Approval required • Soft gate
Error:     Health check failed (503)
Toast OK:  Token persisted to local storage
```

---

## Visual foundations

### Color

The palette is **dark, near-monochromatic, with one true accent**.

- **Surface** is a single charcoal: `#1a1d21`. There is no `bg-card` vs `bg-elevated` differentiation by hue — the variables exist but resolve to the same value. **Depth is created by shadow, never by lighter cards.** Deeper wells (`#0b1f29`, `#06131b`) appear only inside response/code/observation areas.
- **Text** runs cool: `#e2e8f0` (main), `#94a3b8` (soft), `#6fa8b8` (muted/eyebrow). Mono accents lean cyan: `#8dc8dd`, `#9fd5e4`.
- **Accent** is a single teal: `#30d5c8`. It appears as: the logo orb, eyebrow text, focus rings, the active-tab pill, primary buttons, glows, and gradient stops paired with `#184e68`.
- **Warm accent** `#f6bd60` is reserved for warnings, helper steps, and "operation has caveats" callouts.
- **Semantic:** `#8be9a8` ok / `#ff6b6b` danger / `#7dd3fc` info.
- **HTTP method swatches** are a small named subsystem for API badges: GET `#14394b`, POST `#27481e`, DELETE `#542728`, PATCH `#423520`, PUT `#2d2d55`.

Imagery, when present, is **cool and dim** — no warm photography, no people-stock. Most of the product has zero imagery; it's all panels and data.

### Type

- **Display & UI:** `Space Grotesk` 400/500/700 — geometric, friendly-but-flat, medium x-height. Loaded from Google Fonts.
- **Mono:** `IBM Plex Mono` 400/500 — code, paths, timestamps, JSON, method badges. Loaded from Google Fonts.
- **Hierarchy:**
  - Eyebrow `0.74rem`, letter-spacing `0.12em`, color = accent teal.
  - Group label `0.68rem`, letter-spacing `0.08em`, uppercase, muted blue.
  - H1 fluid `clamp(1.3rem, 3vw, 1.9rem)`, weight 600.
  - H2 ~`1.4rem`, H3 `1.02rem`.
  - Body `0.84–0.9rem`. Helper/meta `0.78rem`.
  - Buttons: weight 600, letter-spacing `0.05em`.
- **The wordmark** uses a `linear-gradient(135deg, #fff, #9dc3cf)` text-fill — a subtle white→ice-blue.

### Spacing & rhythm

Grid uses `rem` units, mostly multiples of `0.2rem` and `0.65–0.85rem`. Common values: `0.2 / 0.35 / 0.5 / 0.65 / 0.85 / 1 / 1.2`. Cards and panels live on a `gap: 0.55–1rem` rhythm. Layout is **CSS Grid** almost everywhere — `display: grid` + `gap`, never inline-flow.

### Backgrounds & textures

- **No images, no patterns, no grain.** The entire product is solid panels and translucent overlays.
- A few decorative **radial-gradient highlights** appear on the help-assistant and action-bar surfaces — top-right teal bloom, ~16% opacity, fading to transparent at ~32%. These are subtle, not splashy.
- Translucent layers use `rgba(11, 30, 39, 0.64)` over the charcoal base.

### Elevation

This system **does not lean on neumorphic shadows.** Depth comes from chamfered corners, hairline gradient borders (`linear-gradient(135deg, line-strong, transparent, line-strong)` masked to 1px), and stripe/grid decorations behind hero surfaces.

- **Panels** get a chamfered clip-path (`--cut: 10px` corners) and a 1px gradient stroke applied via `::before` mask.
- **Buttons** are flat with a smaller 4px chamfer.
- **Wells** (deep response areas, code blocks) drop to `--bg-deep` (`#050a0e`) with a hairline left rule for status tinting.
- **Pure-glow** `0 0 15px rgba(48,213,200,0.5)` is still reserved for the logo orb pulse and a couple of beacon moments.

Legacy neumorphic shadow tokens (`--shadow-outer`, `--shadow-inner`, etc.) remain in `colors_and_type.css` for source-faithful recreation, but **new designs should use the sharp / hairline system** — see any page in `ui_kits/control-plane/` for examples.

### Borders

Most borders are *transparent* placeholders that become accent-tinted on focus or active. Real visible borders are `#315365` (operation cards), `#2c4f5f`, `#2c5261`, or `rgba(125,211,252,0.16)` for soft separators. **Never** use a 1px solid black/white border.

### Corner radii

- Inputs / buttons: `0` (sharp) with a 4px chamfer cut on two corners.
- Inner items (task cards, lane rows): `0` with a 2px coloured left rule.
- Panels / hero cards: `0` with a 10px chamfer cut on two corners.
- Pills / method badges: `0` with a 3px chamfer (no longer fully-rounded).

> Source had `border-radius: 18px` everywhere. We replaced this with a sharp chamfer system so the UI reads industrial / instrument-panel rather than soft-SaaS. The chamfer helpers live in `ui_kits/control-plane/_kit.css`.

### Animation

- Default transition: `all 0.25s ease`.
- **One ambient animation:** the logo orb's `pulse-orb` (4s scale 1→1.1, opacity 0.8→1, infinite). It's the only "alive" element.
- A `wf-pulse-border` 1.8s ease-in-out infinite for running workflow nodes.
- No bounce, no spring, no fancy easings. Calm and instrument-panel-like.

### Hover & press states

- **Hover:** swap `--shadow-outer-sm` for `--shadow-outer` (lift), and recolor text to accent teal. No background flash.
- **Active/press:** swap to `--shadow-inner` (depress).
- **Active nav tab:** solid teal background `#30d5c8` + dark text `#03080c` + teal-glow shadow.
- **Disabled:** opacity 0.5, no shadow, cursor not-allowed.
- **Focus:** input gains `box-shadow: var(--shadow-active)` + accent-tinted border.

### Transparency & blur

Used **sparingly** for layered overlays (help-assistant drawer over the cockpit). Not used as a decoration. No frosted-glass nav bars. No backdrop-filter on cards.

### Cards

The canonical card: charcoal background (`linear-gradient(180deg, rgba(8,24,32,.92), rgba(8,24,32,.78))`), `padding: 14px 16px` for `.panel-body`, sharp clip-path with a 10px chamfer top-left and bottom-right, a 1px gradient stroke applied via `::before` + mask. Variants: `.panel.warn` / `.panel.danger` / `.panel.ok` swap the stroke gradient for the matching semantic colour. Operation cards drop the panel chrome entirely and use a 2px coloured left rule per HTTP method.

### Layout rules

- Top-level shell is a 3-column grid: `sidebar | workspace | activity panel`, with breakpoints collapsing to 2 then 1 column (980px / 1380px).
- The cockpit topbar is sticky, ~4rem tall (`--cockpit-topbar-height: 4rem`), with the brand on the left and meta on the right.
- Sidebar is `position: sticky`, scrollable, ~280px wide.
- Skip-links and visually-hidden helpers exist — accessibility is taken seriously.

---

## Iconography

### What's actually in the source

- **No icon font.** No Lucide, Heroicons, FontAwesome, Material Symbols. No SVG icon sprite. No PNG icons.
- **The only "icons" used are emoji as status dots** — 🟢🟡🔴⚪ — inside `<span class="rh-icon …">` wrappers in `HealthPanel.tsx`.
- **The brand mark** is a CSS conic-gradient circle (`.logo-orb`) — see `assets/logo-orb.html` for a standalone version and `assets/wordmark.svg` for a wordmark mock.
- A couple of inline arrows (`->`) appear in copy (e.g., `cockpit-safety-signal small`) rather than as glyphs.

### Recommended substitution

Because there is no first-party icon set, use **[Lucide](https://lucide.dev)** when icons are needed in new designs:

- Reason: stroke-based, calm, geometric, matches Space Grotesk's flatness.
- Stroke width: `1.5` (default).
- Color: `currentColor` so they pick up text color (text-soft for inactive, accent for active).
- Size: 16–20px in nav, 14px inline with body copy.

> ⚠️ **This is a substitution.** AGENT-33 has no canonical icon system — confirm with the team if production designs should commit to Lucide, or commission a proprietary set.

### Emoji policy

- **Yes** for the four status dots above. They are part of the UI vocabulary.
- **No** anywhere else — not in headings, not in buttons, not as decoration in marketing or slides.

### Unicode chars

`->` is used as a literal arrow ligature in source-rendered text. Em-dashes (`—`) are used in copy. No special use of bullets — lists use `<ul>` defaults.

---

## Fonts

Both fonts are served by **Google Fonts** in the source `index.html`:

```html
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet" />
```

No `.ttf` / `.woff2` files are bundled with the project. **For offline / production use, host the woff2 files locally** — but until then, the Google Fonts link is canonical.

> ⚠️ **Substitution flag:** if you need offline-safe versions, both fonts are open-source and downloadable from Google Fonts directly. They are flagged here so the user can decide whether to bundle them later.

---

## Index — manifest

```
README.md                 ← you are here
SKILL.md                  ← Claude-Code skill manifest
colors_and_type.css       ← design tokens + primitives
assets/
  logo-orb.html             ← canonical logo orb, standalone
  wordmark.svg              ← AGENT-33 wordmark mock (Space Grotesk)
  README.md                 ← assets index
preview/
  type-display.html
  type-mono.html
  colors-surface.html
  colors-accent.html
  colors-semantic.html
  colors-method.html
  shadows-elevation.html
  radii.html
  spacing.html
  buttons.html
  inputs.html
  badges.html
  health-states.html
  cards.html
  logo-orb-card.html
ui_kits/
  control-plane/
    README.md
    _kit.css                ← shared cockpit aesthetic (chamfer + hairline)
    index.html              ← interactive cockpit recreation (React + Babel)
    Topbar.jsx              ← sticky brand bar
    Sidebar.jsx             ← workspace nav
    Dashboard.jsx           ← cockpit hero + KPI cards
    OperationCard.jsx       ← API operation card (chamfered)
    ActivityPanel.jsx       ← right rail observation feed
    App.jsx                 ← composes the cockpit
    AuthPanel.html          ← local-first sign-in
    HealthPanel.html        ← runtime health row (compact)
    HealthPanelFull.html    ← full settings health page
    PermissionModeControl.html  ← 4-mode segmented control
    SafetyGateIndicator.html    ← gate context detail
    GlobalSearch.html       ← cockpit search + results
    DomainPanel.html        ← domain list of operations
    WorkflowGraph.html      ← graph + WorkflowStatusNode states
    WorkspaceTaskBoard.html ← roster + starters + 5-lane kanban
    ShipyardLaneScaffold.html   ← coordinator/scout/builder/reviewer lanes
    ArtifactReviewDrawer.html   ← 5-tab review drawer (validation evidence)
    ExplanationView.html    ← fact-checked explanation panel
    ObservationStream.html  ← live SSE event stream
frontend/                 ← imported source from the repo (read-only reference)
  src/styles.css            ← canonical CSS source (~7800 lines)
  src/App.tsx               ← App shell
  src/components/*.tsx      ← reference components
```

---

## Caveats & open questions

- **No formal logo.** The orb is the only mark. A real logotype hasn't been commissioned.
- **No icon system.** Lucide is suggested but unconfirmed.
- **Fonts not bundled.** Google-hosted. Local hosting recommended for production.
- **No marketing surface, deck template, or social card system.** Everything in this design system is built around the single in-product cockpit. Extend before reuse.
