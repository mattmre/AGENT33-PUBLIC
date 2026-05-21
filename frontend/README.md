# AGENT-33 Frontend

First-party control plane UI for AGENT-33.

## Features

- Login/token/API-key access panel
- Runtime health panel
- Domain workspace covering AGENT-33 API surfaces:
  - auth, chat, agents, workflows, memory, reviews, traces, evaluations
  - autonomy, releases, improvements, dashboard, training, webhooks
- Request/response visibility and recent-call activity feed

## Local Dev

```bash
cd frontend
npm install
npm run dev
```

Default API target is read from `public/runtime-config.js` (`http://localhost:8000`).

## Build + Test

```bash
cd frontend
npm run lint
npm run test
npm run build
```

## Docker

```bash
cd engine
docker compose up -d frontend
```

Frontend runs at `http://localhost:3000`.

Runtime API URL is configured via `API_BASE_URL` env var on the frontend container.

For the normal local stack, start the full runtime from `engine/`:

```bash
docker compose up -d
```

Then:

- open `http://localhost:3000`
- sign in with the bootstrap credentials from `engine/.env` (or the copied
  defaults from `engine/.env.example`: `admin` / `admin`)
- use the domain workspace to access agents, workflows, memory, reviews, evaluations, releases, and dashboard surfaces

See:

- `../docs/getting-started.md`
- `../docs/ONBOARDING.md`
