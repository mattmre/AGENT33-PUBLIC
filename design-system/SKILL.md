---
name: agent33-design
description: Use this skill to generate well-branded interfaces and assets for AGENT-33, either for production or throwaway prototypes/mocks/etc. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read the README.md file within this skill, and explore the other available files.

If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy assets out and create static HTML files for the user to view. If working on production code, you can copy assets and read the rules here to become an expert in designing with this brand.

If the user invokes this skill without any other guidance, ask them what they want to build or design, ask some questions, and act as an expert designer who outputs HTML artifacts _or_ production code, depending on the need.

## Quick reference

- Tokens & primitives → `colors_and_type.css`
- Brand mark → `assets/logo-orb.html`, `assets/wordmark.svg`
- Visual / content / iconography rules → `README.md`
- Reference component code → `ui_kits/control-plane/`
- Original frontend source (read-only) → `frontend/src/`

## Non-negotiables

- Dark canvas: `#0c1015`, deep wells `#050a0e`. Never lighter cards — depth comes from chamfered corners and hairline gradient strokes.
- One accent: teal `#30d5c8`. One warm: `#f6bd60`. Don't invent new ones.
- Two fonts: **Space Grotesk** + **IBM Plex Mono** (Google Fonts). Mono is for paths, JSON, timestamps, code, badge labels.
- Sentence case everything. UPPERCASE only for short eyebrows / labels (with letter-spacing).
- Emoji only as the four health status dots. Never decorative.
- Sharp geometry: 10px chamfer on panels, 4px on buttons. No `border-radius` above 0 except chamfer cuts. No drop shadows on cards — depth via `::before` gradient strokes.
- Buttons: rest = hairline border, hover = teal border + soft teal-tinted fill, primary = solid teal on dark. Active nav tab = solid teal background.
- No icon library is canonical. Use Lucide (1.5px stroke, currentColor) and flag the substitution.
- Workspace vocabulary: AGENT-33 calls workspaces **Drydock** (not BridgeSpace). Roles: Coordinator / Scout / Builder / Reviewer.
