# Jupyter Kernel Containers Runbook

## Purpose

Operate the Docker-backed Jupyter kernel adapter introduced for Phase 38 Stage 3 / Phase 42 follow-on work.

## Enablement

Set:

- `JUPYTER_KERNEL_ENABLED=true`
- `JUPYTER_KERNEL_MODE=docker`

Optional settings:

- `JUPYTER_KERNEL_DOCKER_IMAGE`
- `JUPYTER_KERNEL_ALLOWED_IMAGES`
- `JUPYTER_KERNEL_NETWORK_ENABLED`
- `JUPYTER_KERNEL_MOUNT_WORKDIR`
- `JUPYTER_KERNEL_CONTAINER_WORKDIR`

## Operational Notes

- Docker mode publishes kernel ports to the host and mounts a per-session runtime directory containing the Jupyter connection file.
- When `JUPYTER_KERNEL_NETWORK_ENABLED=false`, the adapter starts containers with `--network none`.
- Working-directory mounting is opt-in and should only point at paths already approved by workflow / execution policy.
- The adapter enforces an image allowlist when one is configured.

## Failure Modes

- `jupyter_client not installed`: install with `pip install agent33[jupyter]`
- `docker executable not found`: install Docker and ensure `docker` is on `PATH`
- `Docker image ... is not permitted`: align the requested image with `JUPYTER_KERNEL_ALLOWED_IMAGES`
- kernel startup timeout: inspect Docker logs for the session container and verify the image includes `ipykernel`

## Cleanup

- One-shot sessions are removed after execution.
- Stateful sessions are removed explicitly or via adapter shutdown.
- Forced cleanup uses `docker rm -f <container>` and deletes the runtime connection directory.

## Quick Smoke Workflow

Register a minimal workflow that exercises the Docker-backed `code-interpreter` tool:

```bash
curl -X POST http://localhost:8000/v1/workflows/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "docker-kernel-smoke",
    "version": "1.0.0",
    "description": "Validate Docker-backed Jupyter execution",
    "triggers": {"manual": true},
    "inputs": {},
    "outputs": {
      "result": {"type": "object"}
    },
    "steps": [
      {
        "id": "run-notebook-code",
        "action": "execute-code",
        "inputs": {
          "tool_id": "code-interpreter",
          "language": "python",
          "code": "print(6 * 7)"
        }
      }
    ],
    "execution": {"mode": "sequential"}
  }'
```

Then execute it:

```bash
curl -X POST http://localhost:8000/v1/workflows/docker-kernel-smoke/execute \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"inputs": {}}'
```
