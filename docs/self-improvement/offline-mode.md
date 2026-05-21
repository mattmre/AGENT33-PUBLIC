# Offline Mode

AGENT-33 is designed to operate fully within air-gapped or connectivity-limited environments.

## What Works Offline

| Capability | Offline Behavior |
|-----------|-----------------|
| LLM Inference | Ollama with locally-pulled models — full functionality |
| Prompt Optimization | APO loop runs entirely locally |
| Workflow Execution | All DAG execution is local |
| Memory / RAG | PostgreSQL + pgvector — full functionality |
| Embeddings | Falls back from Jina to Ollama embeddings automatically |
| Tool Execution | Shell, file, and local tools — full functionality |

## What Degrades Gracefully

| Capability | Degraded Behavior |
|-----------|------------------|
| Web Search | SearXNG returns no results → system uses local knowledge base |
| Web Reading | Jina reader unavailable → URLs queued for later processing |
| Cloud LLM | OpenAI unavailable → all routing goes to Ollama |
| Repo Intake | Cannot clone remote repos → accepts local paths only |

## Queuing Improvements

When offline, the system continues generating improvement proposals but queues those that require:

- External validation (web search for current data)
- Cloud model evaluation (when local models lack capability)
- Remote repo access

Queued items are stored in engine memory with status `pending_connectivity`. When connectivity returns, run `agent33 sync` to process the queue.

## Data Sovereignty

All observations, analyses, and improvements are stored locally:

- Engine database (PostgreSQL)
- Local filesystem (`docs/`, `engine/data/`)
- No telemetry or external data transmission

The `offline_mode: true` config setting enforces this by disabling all outbound network calls from the engine.
