# Control Plane UI Kit

Recreation of the AGENT-33 cockpit. The single product surface in the repo. Open `index.html` to see it interactive — pick a workspace, switch tabs, run an `invoke orchestrator` call and watch the activity panel update.

## Aesthetic

The kit was rebuilt to match AGENT-33's industrial / instrument-panel register:

- **Sharp geometry** — chamfered corners (`clip-path` 10px on panels, 4px on buttons), no rounded glass.
- **Hairline gradient strokes** — 1px borders applied via `::before` masked-gradient (`linear-gradient(135deg, line-strong, transparent, line-strong)`).
- **No drop shadows** on cards. Depth comes from chamfers + hairlines.
- **2px coloured left rule** for status tinting (lanes, tasks, gates, observation events).
- Shared in `_kit.css` — every page in this folder loads it.

## Interactive cockpit (React)

`index.html` composes 5 React components into a working cockpit:

- **Topbar.jsx** — sticky brand bar with the pulsing logo orb, gradient AGENT-33 wordmark, workspace label, permission-mode pill, runtime endpoint.
- **Sidebar.jsx** — workspace session card (selector + 3-stat grid: running / review / blocked) plus the grouped nav: Cockpit / Build / Inspect / Govern.
- **Dashboard.jsx** — cockpit hero with eyebrow + project goal + status, three KPI cards (current run, recommended next, safety gate), and the runtime health row.
- **OperationCard.jsx** — API operation card with a method pill (`GET`/`POST`/`DELETE` colour-coded), title + description + mono path, request/headers fields, run button, response well.
- **ActivityPanel.jsx** — right rail with the observation stream and recent-calls list.
- **App.jsx** — composes them and wires up the demo: clicking *Run* on `POST /v1/agents/orchestrator/invoke` generates a mock 200 response and prepends to the activity feed.

## Standalone reference pages (HTML)

Each one is a single self-contained HTML file showing one component or surface in isolation. They share `_kit.css`.

| File | Source | What it shows |
|---|---|---|
| `AuthPanel.html` | `AuthPanel.tsx` | Local-first sign-in: login + token + API-key tabs, mode chip, runtime banner. |
| `HealthPanel.html` | `HealthPanel.tsx` | Compact health row with emoji status dots (cockpit footer). |
| `HealthPanelFull.html` | `HealthPanel.tsx` (full) | Settings-page health surface with grouped service rows + actions. |
| `PermissionModeControl.html` | `PermissionModeControl.tsx` | 4-mode segmented control (Observe / Suggest / Operate / Auto) + scope detail. |
| `SafetyGateIndicator.html` | `SafetyGateIndicator.tsx` | Gate detail panel: tone-tinted, scope rows, override actions. |
| `GlobalSearch.html` | `GlobalSearch.tsx` | Cockpit ⌘K search bar + results + empty + disabled states. |
| `DomainPanel.html` | `DomainPanel.tsx` | Domain list of operations (filter + feature panel + 4 ops). |
| `WorkflowGraph.html` | `WorkflowGraph.tsx` + `WorkflowStatusNode.tsx` | DAG of workflow status nodes + state legend. |
| `WorkspaceTaskBoard.html` | `WorkspaceTaskBoard.tsx` | Roster strip + starters + 5-lane kanban. |
| `ShipyardLaneScaffold.html` | `ShipyardLaneScaffold.tsx` | Coordinator / Scout / Builder / Reviewer role lanes. |
| `ArtifactReviewDrawer.html` | `ArtifactReviewDrawer.tsx` | 5-tab review drawer with validation evidence + safety records. |
| `ExplanationView.html` | `ExplanationView.tsx` | Fact-checked explanation: text + claims + iframe-HTML mode. |
| `ObservationStream.html` | `ObservationStream.tsx` | Live SSE feed: 4 event tints + empty state. |

## Vocabulary

Workspaces are **Drydock** (not BridgeSpace). Roles in a Drydock workspace:

- **Coordinator** — sequences work, owns the plan, manages handoffs.
- **Scout** — read-only research, risk surfacing, comparison findings.
- **Builder** — implementation slices, validation commands, change-set artifacts.
- **Reviewer** — quality gate, redaction audit, merge recommendation.

Permission modes (gate strength): **Observe → Suggest → Operate → Auto**. Gates are tagged hard / soft / allowed.

## Coverage notes

This kit replicates the cockpit shell, plus the 13 highest-value product surfaces from `frontend/src/components/`. It does **not** recreate every domain panel (packs marketplace, agent builder, MCP catalog, training, releases, etc.) — those reuse the same primitives and would be straightforward to layer on. The purpose here is component coverage of the canonical interactions, not screen-by-screen replication.
