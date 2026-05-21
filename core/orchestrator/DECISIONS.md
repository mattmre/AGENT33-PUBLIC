# Design Decisions

This document records important design decisions made for the local agent orchestration system.

## Decision 1: Documentation-Based Coordination

**Status:** Accepted
**Date:** 2024-01-01

We decided to use documentation files (PLAN.md, TASKS.md, STATUS.md) as the single source of truth instead of a database or centralized system. This approach:

- Is simple and doesn't require additional infrastructure
- Works well for local development
- Enables clear audit trails of decisions
- Allows offline access to system state

## Decision 2: Agent Specialization

**Status:** Accepted
**Date:** 2024-01-01

We decided to specialize the agents:
- **Orchestrator (Claude)**: High-level planning, task delegation, reviews
- **Workers (Qwen)**: Implementation, testing, code generation

This separation allows for clear division of responsibilities and avoids ambiguity in task execution.

## Decision 3: PowerShell Scripts for Windows

**Status:** Accepted
**Date:** 2024-01-01

We use PowerShell scripts for the Windows environment because:

- PowerShell is native to Windows
- Can easily manage Docker containers and environment variables
- Provides good integration with the Ollama setup
- Matches the tooling preferences for Windows-based developers

## Decision 4: Docker for Local LLM Setup

**Status:** Accepted
**Date:** 2024-01-01

We decided to use Docker for LLM containerization because:

- Provides consistent environment across different machines
- Enables GPU access with proper configuration
- Allows for easy model management and updates
- Facilitates reproducible setups

## Decision 5: Queue-Based Worker System

**Status:** Accepted
**Date:** 2024-01-01

We implemented a queue-based worker system to handle GPU resource constraints:

- Limited OLLAMA_NUM_PARALLEL=1 for 30B model
- Queued requests with OLLAMA_MAX_QUEUE=256
- Optimized VRAM usage with OLLAMA_KV_CACHE_TYPE=q8_0
- Enabled flash attention for performance (OLLAMA_FLASH_ATTENTION=1)

This prevents memory overflow when multiple agents are running concurrently.