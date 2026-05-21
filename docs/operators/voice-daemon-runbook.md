# Voice Daemon Runbook

## Purpose

Operate the Phase 48 voice stack safely across the compatibility runtime and the standalone sidecar.

## Current Runtime Modes

- `stub`: session lifecycle works end to end for UI, policy, auth, and shutdown handling
- `sidecar`: session lifecycle is delegated to the standalone `agent33.voice` FastAPI sidecar
- `livekit`: intentionally rejected in the current runtime and reserved for the Phase 48 sidecar

## Required Engine Settings

- `VOICE_DAEMON_ENABLED=true|false`
- `VOICE_DAEMON_TRANSPORT=stub|sidecar|livekit`
- `VOICE_DAEMON_URL`
- `VOICE_DAEMON_API_KEY`
- `VOICE_DAEMON_API_SECRET`
- `VOICE_DAEMON_ROOM_PREFIX`
- `VOICE_DAEMON_MAX_SESSIONS`
- `VOICE_SIDECAR_URL`
- `VOICE_SIDECAR_PROBE_TIMEOUT_SECONDS`
- `VOICE_SIDECAR_VOICES_PATH`
- `VOICE_SIDECAR_ARTIFACTS_DIR`
- `VOICE_SIDECAR_PLAYBACK_BACKEND`

For local validation, use:

```env
VOICE_DAEMON_ENABLED=true
VOICE_DAEMON_TRANSPORT=stub
VOICE_DAEMON_ROOM_PREFIX=agent33-voice
VOICE_DAEMON_MAX_SESSIONS=25
```

For standalone sidecar validation, use:

```env
VOICE_DAEMON_ENABLED=true
VOICE_DAEMON_TRANSPORT=sidecar
VOICE_SIDECAR_URL=http://127.0.0.1:8790
VOICE_SIDECAR_VOICES_PATH=config/voice/voices.json
VOICE_SIDECAR_ARTIFACTS_DIR=var/voice-sidecar
VOICE_SIDECAR_PLAYBACK_BACKEND=noop
```

Start the sidecar locally with:

```bash
python -m agent33.voice main --host 127.0.0.1 --port 8790
```

or, when the engine package entrypoint is installed:

```bash
agent33-voice-sidecar main --host 127.0.0.1 --port 8790
```

## Tenant Policy Controls

Use the multimodal tenant policy endpoint to tune voice access:

- `voice_enabled`
- `max_voice_concurrent_sessions`
- `max_voice_session_seconds`

`max_voice_session_seconds` is currently recorded on each session for operator budgeting,
but the stub runtime does not auto-expire sessions yet. Stop or reconnect sessions
manually when they exceed the expected duration.

Example:

```json
{
  "voice_enabled": true,
  "max_voice_concurrent_sessions": 1,
  "max_voice_session_seconds": 1800
}
```

## Operator Actions

### List sessions

`GET /v1/multimodal/voice/sessions`

Use this to:

- find currently active tenant-scoped sessions
- locate a `session_id` before deeper inspection or stop requests

### Get session details

`GET /v1/multimodal/voice/sessions/{session_id}`

Use this to inspect:

- session state
- room name
- transport mode
- last recorded startup error, if any

### Start a session

`POST /v1/multimodal/voice/sessions`

Expected result:

- HTTP `201`
- session state `active`
- transport `stub` or configured transport

### Inspect session health

`GET /v1/multimodal/voice/sessions/{session_id}/health`

Use this to confirm:

- session state
- daemon health boolean
- transport mode
- basic daemon counters or sidecar snapshot details

### Check sidecar and status-line health

Use:

- `GET /health`
- `GET /v1/operator/status`

Expected additional health services:

- `voice_sidecar`
- `status_line`

Expected additional operator inventory:

- `voice_sessions`

### Stop a session

`POST /v1/multimodal/voice/sessions/{session_id}/stop`

Expected result:

- HTTP `200`
- session state `stopped`

## Failure Modes

### `503 voice runtime is disabled`

Cause:

- `VOICE_DAEMON_ENABLED=false`

Resolution:

- enable the runtime or leave the voice tab disabled for the environment

### `503 livekit transport is deferred to the Phase 48 voice sidecar; use the stub transport in the current runtime`

Cause:

- `VOICE_DAEMON_TRANSPORT=livekit` was selected in the current in-process control plane

Resolution:

- switch back to `stub` for the current runtime
- keep LiveKit credentials only for the future sidecar deployment path

### `503 voice runtime could not start session` with `VOICE_DAEMON_TRANSPORT=sidecar`

Cause:

- the main API runtime could not create the remote sidecar session
- `VOICE_SIDECAR_URL` is unset, unreachable, or the sidecar returned an error

Resolution:

- confirm the sidecar is running and `GET {VOICE_SIDECAR_URL}/health` returns `200`
- confirm `VOICE_DAEMON_TRANSPORT=sidecar`
- inspect `var/voice-sidecar/<session_id>/` artifacts on the sidecar host for session evidence

### `503 voice runtime could not start session`

Cause:

- the configured transport failed during daemon startup

Resolution:

- inspect engine logs for the specific startup failure
- switch back to `stub` until the failing transport or daemon factory is fixed

### `400 voice session limit exceeded`

Cause:

- tenant hit `max_voice_concurrent_sessions`

Resolution:

- stop the active session or raise the policy limit explicitly

## Shutdown Behavior

Active voice daemon sessions are stopped during FastAPI lifespan shutdown. When `VOICE_DAEMON_TRANSPORT=sidecar`, the compatibility daemon asks the standalone sidecar to stop the remote session first and the sidecar persists per-session artifacts under `VOICE_SIDECAR_ARTIFACTS_DIR`.
