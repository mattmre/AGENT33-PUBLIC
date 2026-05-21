# Canonical Data Flows

This document is the sequence-diagram view of AGENT-33. It traces six canonical flows through the engine, showing which subsystems handle which steps and where state lands. The diagrams are simplified for clarity — error paths and retries are shown where they matter, omitted where they don't.

The flows are:

1. Agent invocation (synchronous HTTP)
2. Streaming agent invocation (SSE)
3. Workflow execution (DAG)
4. Pack installation
5. Tool call with approval gate
6. Memory ingestion and retrieval

For the architectural background read [ARCHITECTURE.md](../../ARCHITECTURE.md). For the per-subsystem reference read [components.md](components.md). For the API surface read [api-surface.md](api-surface.md).

## 1. Agent invocation

The shortest interesting path through the engine. An operator (or the frontend, or an SDK client) posts a message to an agent and gets a response.

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant MW as AuthMiddleware
    participant Route as POST /v1/agents/{name}/invoke
    participant Reg as AgentRegistry
    participant Rt as AgentRuntime
    participant Inj as SkillInjector
    participant Rec as ProgressiveRecall
    participant Mem as LongTermMemory
    participant LLM as ModelRouter
    participant Tools as ToolRegistry
    participant Gov as ToolGovernance
    participant Trace as TraceCollector
    participant Out as OutcomesService

    Client->>MW: Authorization: Bearer <jwt>
    MW->>MW: verify_token, attach request.state.user
    MW->>Route: forward
    Route->>Trace: start_run(agent=name, tenant_id)
    Route->>Reg: get(name)
    Reg-->>Route: AgentDefinition
    Route->>Rt: invoke(definition, message, context)

    Rt->>Inj: build_system_prompt(definition, skills)
    Inj-->>Rt: system prompt (L0/L1, L2 on-demand refs)

    Rt->>Rec: progressive_recall(tenant_id, query)
    Rec->>Mem: hybrid search
    Mem-->>Rec: SearchResult list
    Rec-->>Rt: relevant context

    Rt->>LLM: complete(prompt, allowed_tools)

    loop tool-use iterations (until done or max_iterations)
        LLM-->>Rt: response (text or tool calls)
        alt model returned a tool call
            Rt->>Tools: get(tool_name)
            Rt->>Gov: authorize(tool, params, autonomy)
            alt allowed
                Gov-->>Rt: allowed
                Rt->>Tools: validated_execute(tool, params, ctx)
                Tools-->>Rt: ToolResult
                Rt->>LLM: continue with tool result
            else needs approval
                Gov-->>Rt: needs-approval
                Rt-->>Route: pending approval (HITL)
            else denied
                Gov-->>Rt: denied (reason)
                Rt->>LLM: continue with denial message
            end
        else final answer
            Rt-->>Route: AgentRunResult
        end
    end

    Route->>Out: record_outcome(tenant_id, status, latency)
    Route->>Trace: complete_run(status)
    Route-->>Client: HTTP 200 with result body
```

Notes:

- The auth middleware runs once. If the token is missing or invalid, the chain short-circuits with `401`.
- The trace is opened *before* registry lookup so that lookup failures are recorded.
- `ProgressiveRecall` and the `LongTermMemory` calls are skipped if RAG is disabled in settings or if the agent definition opts out.
- The tool-use loop has a hard iteration cap; if it hits it, the loop returns the last assistant message and records a `max_iterations` warning to the trace.
- Outcomes capture is best-effort. If the SQLite store is unavailable it swallows the error and logs.

## 2. Streaming agent invocation (SSE)

The streaming variant of the same call. The route returns an SSE stream, and the runtime emits events as the model produces tokens and the tool loop progresses.

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant Route as POST /v1/agents/{name}/invoke<br/>(Accept: text/event-stream)
    participant Rt as AgentRuntime
    participant LLM as ModelRouter
    participant Tools as ToolRegistry
    participant Trace as TraceCollector

    Client->>Route: open stream
    Route-->>Client: 200 OK<br/>Content-Type: text/event-stream

    Route->>Rt: invoke_stream(definition, message)
    Rt->>Trace: start_run

    par
        loop tokens
            Rt->>LLM: stream_complete
            LLM-->>Rt: token chunk
            Rt-->>Client: event: token<br/>data: {...}
        end
    and
        loop tool events
            Rt->>Tools: validated_execute
            Tools-->>Rt: ToolResult
            Rt-->>Client: event: tool_result<br/>data: {...}
        end
    end

    Rt->>Trace: complete_run
    Rt-->>Client: event: completed<br/>data: {...}
    Client->>Route: close
```

The SSE stream emits structured events:

- `event: token` — incremental text from the LLM
- `event: tool_call` — the agent decided to call a tool
- `event: tool_result` — the tool returned
- `event: thinking` — reasoning chunk if the provider exposes them
- `event: completed` — the final answer, with the full content
- `event: error` — the run failed; the data carries the failure category

If the stream hits `max_iterations` it still emits a final `completed` event carrying the last assistant message. The corresponding regression case is `tests/test_streaming_tool_loop.py::test_stream_max_iterations`.

## 3. Workflow execution

The DAG executor. The route accepts a workflow name and parameter map, the executor walks the topological order, and each step either calls an agent, runs a command, transforms data, branches, parallelises, or runs a sub-workflow.

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant Route as POST /v1/workflows/{name}/execute
    participant Reg as WorkflowDefinitionRegistry
    participant Exec as WorkflowExecutor
    participant DAG as DAGBuilder
    participant Step as Step action handler
    participant Bridge as Agent-to-Workflow Bridge
    participant Rt as AgentRuntime
    participant Chk as CheckpointManager
    participant WS as WebSocket / SSE
    participant Trace as TraceCollector

    Client->>Route: parameter map
    Route->>Reg: get(name)
    Reg-->>Route: WorkflowDefinition
    Route->>Exec: execute(definition, params, tenant_id)
    Exec->>Trace: start workflow run
    Exec->>DAG: build(steps)
    DAG-->>Exec: topological order + parallel groups
    Exec->>Chk: create checkpoint

    loop for each parallel group
        par for each step in group
            Exec->>Step: dispatch(step, state)
            alt invoke-agent
                Step->>Bridge: invoke(agent_name, inputs)
                Bridge->>Rt: invoke
                Rt-->>Bridge: result
                Bridge-->>Step: result
            else run-command
                Step->>Step: subprocess
            else execute-code
                Step->>Step: CodeExecutor
            else conditional / transform / wait
                Step->>Step: evaluate locally
            else sub-workflow
                Step->>Exec: execute(sub_def, sub_params)
            end
            Step-->>Exec: step result
            Exec->>WS: publish step event
            Exec->>Chk: update checkpoint
        end
    end

    Exec->>Trace: complete workflow run
    Exec-->>Route: WorkflowRunResult
    Route-->>Client: HTTP 200 with run id and outputs
```

Notes:

- `DAGBuilder` runs Kahn's algorithm at build time. Cycles raise `CycleDetectedError` before any step executes.
- Each parallel group is dispatched concurrently. Steps within a group cannot depend on each other.
- Step retries are configured per step (`max_attempts`, `delay_seconds`).
- Checkpoints land in PostgreSQL (`workflow_checkpoints` table). On restart, `WorkflowExecutor.resume_from_checkpoint(workflow_id)` resumes the run from the last persisted step.
- WebSocket and SSE subscribers receive structured step events: `step_started`, `step_completed`, `step_failed`, `workflow_completed`.

## 4. Pack installation

Installing a pack from disk or from the pack hub. The flow verifies the SHA-256 digest, checks the revocation list, validates path-traversal safety, loads the manifest, loads each declared skill, applies the trust policy, and registers the pack and its skills.

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant Route as POST /v1/packs/install
    participant Hub as PackHub
    participant Loader as packs/loader.py
    participant Trust as TrustPolicyManager
    participant Sig as Sigstore signing
    participant Reg as PackRegistry
    participant SkillL as skills/loader.py
    participant SkillR as SkillRegistry

    Client->>Route: pack_ref + source
    alt source = hub
        Route->>Hub: get(pack_ref)
        Hub-->>Route: PackHubEntry
        Route->>Hub: get_revocation_status(name, version)
        Hub-->>Route: RevocationStatus
        alt revoked
            Hub-->>Route: revoked=true
            Route-->>Client: 409 Conflict (revoked)
        else not revoked
            Route->>Hub: download(entry, dest_dir)
            Hub-->>Route: pack file path
        end
    else source = local
        Route->>Route: use provided path
    end

    Route->>Loader: load_pack_manifest(pack_dir)
    Loader->>Loader: parse PACK.yaml
    Loader-->>Route: PackManifest

    Route->>Loader: verify_checksums(pack_dir)
    Loader->>Loader: hmac.compare_digest per file
    Loader-->>Route: (all_valid, mismatches)

    alt checksum mismatch
        Route-->>Client: 422 Unprocessable Entity
    end

    Route->>Trust: evaluate(manifest)
    Trust->>Sig: verify cosign signature (if required)
    Sig-->>Trust: verified | unverified
    Trust-->>Route: trust decision

    Route->>Loader: load_pack_skills(pack_dir, manifest)
    loop for each declared skill
        Loader->>SkillL: load_from_directory / load_from_skillmd / load_from_yaml
        SkillL-->>Loader: SkillDefinition
    end
    Loader-->>Route: (loaded_skills, errors)

    alt required-skill load failed
        Route-->>Client: 422 with errors
    end

    Route->>Reg: register pack
    Reg->>SkillR: register qualified and bare aliases
    Reg-->>Route: InstalledPack

    Route-->>Client: 201 Created with InstalledPack
```

Key safety properties:

- **Path traversal** is blocked in the loader: every skill path is resolved against the pack directory and rejected if it escapes (`skill_path.relative_to(pack_dir.resolve())` raises `ValueError`).
- **Revocation** is checked *before* any extraction or registration. A revoked pack is never installed.
- **SHA-256** verification uses `hmac.compare_digest` to avoid timing side channels.
- **Trust policy** is evaluated against the manifest. Strict mode requires a verified Sigstore signature; permissive mode warns but allows.
- **Optional skills** that fail to load produce a warning; required skills that fail produce an installation failure.

## 5. Tool call with approval gate

Some tool calls require human approval before they execute — destructive file writes, shell commands, browser navigation to high-risk domains. The approval flow is stateless from the engine's perspective: the gate produces a token, the operator approves it, the agent re-runs with the token, the token is consumed.

```mermaid
sequenceDiagram
    autonumber
    participant Rt as AgentRuntime
    participant Gov as ToolGovernance
    participant Appr as ToolApprovalService
    participant Tok as ApprovalTokenManager
    participant Op as Operator
    participant Tool as Tool

    Rt->>Gov: authorize(tool, params, autonomy)
    Gov->>Gov: check rate limit
    Gov->>Gov: check autonomy budget
    Gov->>Gov: check approved_tools.json
    Gov->>Gov: classify as destructive
    Gov-->>Rt: needs_approval(reason, request_id)

    Rt->>Appr: create approval request
    Appr-->>Rt: pending request
    Rt-->>Op: notify (UI / webhook)

    Op->>Appr: POST /v1/tool-approvals/{id}/approve
    Appr->>Tok: issue(approval, arguments)
    Tok->>Tok: sign JWT with typ=a33_approval,<br/>jti, arg_hash, exp
    Tok-->>Appr: signed token
    Appr-->>Op: approval token

    Op->>Rt: resume run with token

    Rt->>Gov: authorize(tool, params, token=...)
    Gov->>Tok: verify(token, tool, arg_hash)
    Tok->>Tok: check signature, jti not consumed, not revoked, not expired
    Tok-->>Gov: valid
    Gov->>Tok: consume(jti) (if one_time)
    Gov-->>Rt: allowed

    Rt->>Tool: execute(params, ctx)
    Tool-->>Rt: ToolResult
```

Approval tokens are signed with `JWT_SECRET` (or a dedicated approval-token secret). The `typ: a33_approval` claim prevents reuse as a regular auth token. The `jti` is recorded in a consumed-set after a one-time call. Tokens have a default 300-second TTL.

The destructive-tool set (`_WRITE_TOOLS = {"shell", "browser"}`) and per-tool destructive parameters (`_DESTRUCTIVE_PARAMS = {"file_ops": {"write"}, "apply_patch": {"apply"}}`) are defined in `tools/governance.py`. Adding a new destructive surface means extending those sets.

## 6. Memory ingestion and retrieval

The memory pipeline. Operator content (or agent observations) is chunked, embedded, indexed in BM25 and pgvector, and later retrieved via hybrid search.

```mermaid
sequenceDiagram
    autonumber
    participant Source as Source<br/>(ingestion, agent observation,<br/>API upload)
    participant RAG as RAGPipeline
    participant Emb as EmbeddingProvider
    participant Cache as EmbeddingCache
    participant LTM as LongTermMemory
    participant BM25 as BM25Index
    participant Hyb as HybridSearcher
    participant Rt as AgentRuntime

    rect rgb(240, 248, 255)
        note right of Source: Ingestion
        Source->>RAG: ingest(content, metadata)
        RAG->>RAG: chunk (1200 tokens, sliding)
        loop for each chunk
            RAG->>Cache: get(chunk hash)
            alt cache hit
                Cache-->>RAG: embedding
            else cache miss
                RAG->>Emb: embed(chunk)
                Emb-->>RAG: vector
                RAG->>Cache: put(chunk hash, vector)
            end
            RAG->>LTM: store(chunk, vector, metadata)
            LTM-->>RAG: record id
            RAG->>BM25: index(record_id, chunk)
        end
    end

    rect rgb(255, 245, 238)
        note right of Rt: Retrieval
        Rt->>Hyb: search(query, top_k)
        par
            Hyb->>Emb: embed(query)
            Emb-->>Hyb: query vector
            Hyb->>LTM: search(query_vector, top_k * 2)
            LTM-->>Hyb: vector results
        and
            Hyb->>BM25: search(query, top_k * 2)
            BM25-->>Hyb: BM25 results
        end
        Hyb->>Hyb: Reciprocal Rank Fusion
        Hyb-->>Rt: top_k merged SearchResult
    end
```

Ingestion notes:

- Chunking is **token-aware**, not character-aware. The chunker uses the model's tokenizer (cached at startup) and produces 1200-token chunks with configurable overlap.
- The **embedding cache** is an LRU keyed by chunk hash. With an Ollama-backed provider on commodity hardware it cuts ingestion cost dramatically for repeated content.
- Secret redaction runs *before* embedding. If a chunk looks like it contains an API key or password, the secret is masked before the vector is computed.

Retrieval notes:

- **Hybrid retrieval** runs the vector and BM25 queries concurrently and fuses them with Reciprocal Rank Fusion. The fusion weight is configurable (`rag_rrf_k`).
- The over-fetch factor (`top_k * 2`) gives the fusion room to drop irrelevant tails.
- `ProgressiveRecall` is layered on top of the hybrid searcher for long-session memory tiering; agents typically call `ProgressiveRecall.recall` rather than `HybridSearcher.search` directly.

## Cross-cutting: traces and lineage

Every flow above writes to the trace collector. The trace hierarchy is Session → Run → Task → Step → Action. A single agent invocation is one Run, with one Task containing N Steps (one per tool-use iteration), each Step containing M Actions (one per tool call within the iteration). A workflow run is a Run with one Task per workflow step, structured the same way.

```mermaid
flowchart LR
    SES["Session"]
    RUN1["Run"]
    RUN2["Run"]
    TASK1["Task"]
    TASK2["Task"]
    STEP1["Step"]
    STEP2["Step"]
    ACT1["Action"]
    ACT2["Action"]
    ACT3["Action"]

    SES --> RUN1
    SES --> RUN2
    RUN1 --> TASK1
    RUN1 --> TASK2
    TASK1 --> STEP1
    TASK1 --> STEP2
    STEP1 --> ACT1
    STEP1 --> ACT2
    STEP2 --> ACT3
```

The `ExecutionLineage` subsystem additionally records parent-child relationships across runs (sub-agent spawn, sub-workflow execution) so that you can trace any artifact back to the originating user request. See [observability.md](observability.md) for the full model.

## Where to go next

- For the per-subsystem code map: [components.md](components.md).
- For the workflow DAG details: [workflows.md](workflows.md).
- For the agent runtime details: [agents.md](agents.md).
- For storage layout: [storage.md](storage.md).
- For pack lifecycle: [packs-and-skills.md](packs-and-skills.md).
- For the security model: [security-model.md](security-model.md).
- For the observability surface: [observability.md](observability.md).
