# Operator Guide: Improvement Cycles and Docker Kernels

This guide covers the merged operator surfaces for:

- the Phase 26 improvement-cycle review wizard
- the Phase 27 canonical workflow presets
- the Phase 38 Docker-backed Jupyter kernel workflow

Use it when you want the shortest current path from UI entry point to a real workflow run.

## 1. Improvement-Cycle Wizard

The wizard is mounted inside the frontend control plane under the `Workflows` domain.

### Entry path

1. Open the frontend at `http://localhost:3000`
2. Authenticate with a bearer token or API key
3. Open `Advanced Settings`
4. Select the `Workflows` domain
5. Use the `Improvement Cycle Wizard` panel at the top of the page

### What the wizard does

The wizard stitches together the backend surfaces that previously had to be called manually:

- plan review / diff review generation
- review creation and risk assessment
- L1 and L2 review submission
- tool approval request review and decision capture

Reference implementation:

- frontend: `frontend/src/features/improvement-cycle/ImprovementCycleWizard.tsx`
- tests: `frontend/src/features/improvement-cycle/ImprovementCycleWizard.test.tsx`

For the detailed review flow, keep using:

- [`phase25-26-live-review-walkthrough.md`](phase25-26-live-review-walkthrough.md)

## 2. Canonical Workflow Presets

The `Workflows` domain now exposes preset-assisted create and execute flows backed by the canonical YAML templates in `core/workflows/improvement-cycle/`.

### Available presets

- `Retrospective improvement cycle`
- `Metrics review improvement cycle`

### Source of truth

- `core/workflows/improvement-cycle/retrospective.workflow.yaml`
- `core/workflows/improvement-cycle/metrics-review.workflow.yaml`
- `core/workflows/improvement-cycle/README.md`

### Frontend wiring

Preset metadata is projected from those YAML files into:

- `frontend/src/features/improvement-cycle/presets.ts`
- `frontend/src/data/domains/workflows.ts`
- `frontend/src/components/OperationCard.tsx`

### Operator flow

1. Open `Advanced Settings`
2. Select `Workflows`
3. Choose either:
   - `Create Workflow`
   - `Execute Workflow`
4. Apply an improvement-cycle preset before submitting
5. Review the populated workflow name, path params, and sample inputs
6. Submit the request

The preset flow prevents drift between the UI payloads and the canonical workflow definitions.

## 3. Docker-Backed Jupyter Kernels

The Jupyter adapter can now run in Docker mode and is wired into the `execute-code` workflow action.

### Required settings

Set these in the engine environment:

```env
JUPYTER_KERNEL_ENABLED=true
JUPYTER_KERNEL_MODE=docker
```

Common optional controls:

```env
JUPYTER_KERNEL_DOCKER_IMAGE=quay.io/jupyter/minimal-notebook:python-3.11
JUPYTER_KERNEL_ALLOWED_IMAGES=
JUPYTER_KERNEL_NETWORK_ENABLED=false
JUPYTER_KERNEL_MOUNT_WORKDIR=true
JUPYTER_KERNEL_CONTAINER_WORKDIR=/workspace
```

The detailed runtime controls and failure modes are documented in:

- [`runbooks/jupyter-kernel-containers.md`](runbooks/jupyter-kernel-containers.md)

### Quick smoke workflow

Register a workflow that uses `execute-code` with the `code-interpreter` tool:

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

Execute it:

```bash
curl -X POST http://localhost:8000/v1/workflows/docker-kernel-smoke/execute \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"inputs": {}}'
```

Expected result:

- workflow completes successfully
- the `execute-code` step uses the Jupyter adapter
- Docker container lifecycle is cleaned up automatically for one-shot execution

## 4. Recommended Operator Sequence

When validating the merged UX stack locally:

1. Confirm the workflow presets load in the `Workflows` domain
2. Run one improvement-cycle preset from the UI
3. Walk through the improvement-cycle wizard once
4. Enable Docker kernels and run the `docker-kernel-smoke` workflow
5. Review the live workflow graph / status surfaces if needed via the Phase 25/26 walkthrough
