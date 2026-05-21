# AGENT-33 Use Cases

Practical examples showing how to combine AGENT-33 components to build real systems.

---

## Table of Contents

1. [Automated Code Review Pipeline](#1-automated-code-review-pipeline)
2. [Research Assistant](#2-research-assistant)
3. [Multi-Channel Customer Support](#3-multi-channel-customer-support)
4. [Content Generation Factory](#4-content-generation-factory)
5. [Automated DevOps](#5-automated-devops)
6. [Data Processing Pipeline](#6-data-processing-pipeline)
7. [Security Audit Automation](#7-security-audit-automation)
8. [Knowledge Base Builder](#8-knowledge-base-builder)

---

## 1. Automated Code Review Pipeline

### Description

An automated pipeline that reviews pull requests by analyzing code changes, running linting, checking for security issues, and posting consolidated feedback. When a PR webhook fires, the workflow fetches the diff, routes it through specialized agents, and posts the review.

### Components Used

- **Agents**: `diff-analyzer` (worker), `lint-runner` (worker), `security-checker` (worker), `review-summarizer` (reviewer)
- **Workflows**: Sequential pipeline with parallel lint + security checks
- **Automation**: Webhook trigger from GitHub/GitLab
- **Tools**: `run-command` for linting, `invoke-agent` for AI analysis

### Agent Definitions

**diff-analyzer.json**

```json
{
  "name": "diff-analyzer",
  "version": "1.0.0",
  "role": "worker",
  "description": "Analyze a code diff and identify potential bugs, logic errors, and style issues",
  "capabilities": ["file-read"],
  "inputs": {
    "diff": { "type": "string", "description": "Unified diff content", "required": true },
    "language": { "type": "string", "description": "Primary language", "default": "python" }
  },
  "outputs": {
    "issues": { "type": "array", "description": "List of issues found with line numbers" },
    "summary": { "type": "string", "description": "Overall assessment" }
  },
  "constraints": { "max_tokens": 4096, "timeout_seconds": 90, "max_retries": 1 }
}
```

**review-summarizer.json**

```json
{
  "name": "review-summarizer",
  "version": "1.0.0",
  "role": "reviewer",
  "description": "Combine analysis results into a single PR review comment with actionable feedback",
  "capabilities": ["validation", "refinement"],
  "inputs": {
    "diff_analysis": { "type": "object", "description": "Output from diff-analyzer", "required": true },
    "lint_results": { "type": "object", "description": "Linting output", "required": true },
    "security_results": { "type": "object", "description": "Security scan output", "required": true }
  },
  "outputs": {
    "review_comment": { "type": "string", "description": "Formatted review for posting" },
    "approval": { "type": "string", "description": "approve, request-changes, or comment", "enum": ["approve", "request-changes", "comment"] }
  },
  "constraints": { "max_tokens": 2048, "timeout_seconds": 60 }
}
```

### Workflow Definition

```json
{
  "name": "code-review-pipeline",
  "version": "1.0.0",
  "description": "Automated PR review pipeline",
  "triggers": {
    "manual": true,
    "on_event": []
  },
  "inputs": {
    "diff": { "type": "string", "required": true },
    "language": { "type": "string", "default": "python" },
    "pr_url": { "type": "string", "required": true }
  },
  "steps": [
    {
      "id": "analyze-diff",
      "action": "invoke-agent",
      "agent": "diff-analyzer",
      "inputs": { "diff": "${inputs.diff}", "language": "${inputs.language}" }
    },
    {
      "id": "parallel-checks",
      "action": "parallel-group",
      "depends_on": ["analyze-diff"],
      "steps": [
        {
          "id": "lint",
          "action": "run-command",
          "command": "ruff check --diff --output-format json",
          "inputs": { "stdin": "${inputs.diff}" }
        },
        {
          "id": "security-scan",
          "action": "run-command",
          "command": "bandit -r --format json -",
          "inputs": { "stdin": "${inputs.diff}" }
        }
      ]
    },
    {
      "id": "summarize",
      "action": "invoke-agent",
      "agent": "review-summarizer",
      "inputs": {
        "diff_analysis": "${analyze-diff}",
        "lint_results": "${parallel-checks.results.lint}",
        "security_results": "${parallel-checks.results.security-scan}"
      },
      "depends_on": ["parallel-checks"]
    }
  ],
  "execution": {
    "mode": "dependency-aware",
    "fail_fast": false,
    "continue_on_error": true,
    "timeout_seconds": 300
  }
}
```

### Configuration

```env
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_DEFAULT_MODEL=llama3.2
# Or use OpenAI for higher quality reviews:
OPENAI_API_KEY=sk-...
```

Set up a webhook endpoint to receive PR events and trigger the workflow with the diff content and PR URL as inputs.

### Expected Outcome

Each PR receives an automated review comment containing:
- AI-identified bugs and logic issues with line references
- Linting violations from static analysis
- Security findings from bandit
- A consolidated recommendation (approve, request changes, or comment)

---

## 2. Research Assistant

### Description

A RAG-powered agent that ingests documents into vector memory, then answers user questions with citations drawn from the ingested material. Uses the `DocumentIngester` for chunking, `EmbeddingProvider` for vectorization, `LongTermMemory` for storage, and `RAGPipeline` for retrieval-augmented generation.

### Components Used

- **Agents**: `research-answerer` (researcher)
- **Memory**: `DocumentIngester`, `EmbeddingProvider`, `LongTermMemory`, `RAGPipeline`
- **LLM**: Any model via `ModelRouter`

### Agent Definition

```json
{
  "name": "research-answerer",
  "version": "1.0.0",
  "role": "researcher",
  "description": "Answer questions using retrieved context from ingested documents. Always cite sources by number.",
  "capabilities": ["research"],
  "inputs": {
    "question": { "type": "string", "description": "User question", "required": true }
  },
  "outputs": {
    "answer": { "type": "string", "description": "Detailed answer with [Source N] citations" },
    "confidence": { "type": "number", "description": "Confidence score 0-1" },
    "sources_used": { "type": "array", "description": "Source numbers referenced" }
  },
  "constraints": { "max_tokens": 4096, "timeout_seconds": 120, "max_retries": 2 }
}
```

### Setup Code

```python
from agent33.memory.ingestion import DocumentIngester
from agent33.memory.embeddings import EmbeddingProvider
from agent33.memory.long_term import LongTermMemory
from agent33.memory.rag import RAGPipeline
from agent33.agents.definition import AgentDefinition
from agent33.agents.runtime import AgentRuntime
from agent33.llm.router import ModelRouter
from agent33.llm.ollama import OllamaProvider

# 1. Ingest documents
ingester = DocumentIngester()
chunks = ingester.ingest_markdown(document_text, chunk_size=500, overlap=50)

# 2. Embed and store
embedder = EmbeddingProvider(model="nomic-embed-text")
memory = LongTermMemory(...)  # backed by PostgreSQL + pgvector
for chunk in chunks:
    embedding = await embedder.embed(chunk.text)
    await memory.store(text=chunk.text, embedding=embedding, metadata=chunk.metadata)

# 3. Build RAG pipeline
rag = RAGPipeline(
    embedding_provider=embedder,
    long_term_memory=memory,
    top_k=5,
    similarity_threshold=0.3,
)

# 4. Query with augmented context
rag_result = await rag.query("What are the main features?")

# 5. Pass augmented prompt to agent
router = ModelRouter()
router.register("ollama", OllamaProvider())
agent_def = AgentDefinition.load_from_file("research-answerer.json")
runtime = AgentRuntime(definition=agent_def, router=router, model="llama3.2")
result = await runtime.invoke({"question": rag_result.augmented_prompt})
```

### Configuration

```env
OLLAMA_BASE_URL=http://ollama:11434
DATABASE_URL=postgresql+asyncpg://agent33:agent33@postgres:5432/agent33
```

The embedding model `nomic-embed-text` must be pulled into Ollama: `ollama pull nomic-embed-text`.

### Expected Outcome

Users ask natural language questions and receive answers grounded in the ingested documents. Each answer includes `[Source N]` citations that reference specific chunks from the original material. The confidence score indicates how well the retrieved context matched the question.

---

## 3. Multi-Channel Customer Support

### Description

A support system that receives messages from Telegram, Discord, and Slack simultaneously, routes them through a triage agent that classifies the request, then delegates to specialized agents (billing, technical, general). Responses are sent back on the same platform.

### Components Used

- **Agents**: `support-triage` (director), `billing-support` (worker), `tech-support` (worker), `general-support` (worker)
- **Messaging**: `TelegramAdapter`, `DiscordAdapter`, `SlackAdapter` (all implement `MessagingAdapter`)
- **Workflows**: Conditional routing based on triage classification
- **Memory**: Session memory for conversation context

### Agent Definitions

**support-triage.json**

```json
{
  "name": "support-triage",
  "version": "1.0.0",
  "role": "director",
  "description": "Classify incoming support messages into categories and extract key details",
  "capabilities": ["orchestration"],
  "inputs": {
    "message": { "type": "string", "description": "Customer message", "required": true },
    "platform": { "type": "string", "description": "Source platform" },
    "history": { "type": "array", "description": "Previous messages in session" }
  },
  "outputs": {
    "category": { "type": "string", "description": "Support category", "enum": ["billing", "technical", "general"] },
    "priority": { "type": "string", "description": "Priority level", "enum": ["low", "medium", "high"] },
    "summary": { "type": "string", "description": "Brief summary of the request" }
  },
  "constraints": { "max_tokens": 512, "timeout_seconds": 30, "max_retries": 1 }
}
```

**tech-support.json**

```json
{
  "name": "tech-support",
  "version": "1.0.0",
  "role": "worker",
  "description": "Provide technical support responses with troubleshooting steps",
  "capabilities": ["research"],
  "inputs": {
    "summary": { "type": "string", "description": "Triage summary", "required": true },
    "message": { "type": "string", "description": "Original message", "required": true },
    "history": { "type": "array", "description": "Conversation history" }
  },
  "outputs": {
    "response": { "type": "string", "description": "Support response to send to customer" },
    "escalate": { "type": "boolean", "description": "Whether to escalate to human" }
  },
  "constraints": { "max_tokens": 2048, "timeout_seconds": 60, "max_retries": 2 }
}
```

### Workflow Definition

```json
{
  "name": "customer-support-flow",
  "version": "1.0.0",
  "description": "Route and handle customer support messages",
  "inputs": {
    "message": { "type": "string", "required": true },
    "platform": { "type": "string", "required": true },
    "channel_id": { "type": "string", "required": true },
    "history": { "type": "array", "default": [] }
  },
  "steps": [
    {
      "id": "triage",
      "action": "invoke-agent",
      "agent": "support-triage",
      "inputs": {
        "message": "${inputs.message}",
        "platform": "${inputs.platform}",
        "history": "${inputs.history}"
      }
    },
    {
      "id": "route-billing",
      "action": "conditional",
      "condition": "${triage.category} == 'billing'",
      "depends_on": ["triage"],
      "then": [
        {
          "id": "handle-billing",
          "action": "invoke-agent",
          "agent": "billing-support",
          "inputs": { "summary": "${triage.summary}", "message": "${inputs.message}" }
        }
      ],
      "else": []
    },
    {
      "id": "route-technical",
      "action": "conditional",
      "condition": "${triage.category} == 'technical'",
      "depends_on": ["triage"],
      "then": [
        {
          "id": "handle-technical",
          "action": "invoke-agent",
          "agent": "tech-support",
          "inputs": { "summary": "${triage.summary}", "message": "${inputs.message}", "history": "${inputs.history}" }
        }
      ],
      "else": []
    },
    {
      "id": "route-general",
      "action": "conditional",
      "condition": "${triage.category} == 'general'",
      "depends_on": ["triage"],
      "then": [
        {
          "id": "handle-general",
          "action": "invoke-agent",
          "agent": "general-support",
          "inputs": { "summary": "${triage.summary}", "message": "${inputs.message}" }
        }
      ],
      "else": []
    }
  ],
  "execution": { "mode": "sequential" }
}
```

### Configuration

```env
TELEGRAM_BOT_TOKEN=your-telegram-token
DISCORD_BOT_TOKEN=your-discord-token
SLACK_BOT_TOKEN=xoxb-your-slack-token
REDIS_URL=redis://redis:6379/0
OLLAMA_DEFAULT_MODEL=llama3.2
```

Each messaging adapter implements the `MessagingAdapter` protocol with `start()`, `receive()`, and `send()` methods. Run all three adapters concurrently, feeding received messages into the workflow and sending responses back via `adapter.send(channel_id, response)`.

### Expected Outcome

- Messages from any platform are automatically classified by category and priority
- Each category is handled by a specialized agent with domain-specific knowledge
- Responses are sent back on the originating platform
- High-priority or escalation-flagged issues can trigger alerts for human agents
- Session memory maintains conversation context across multiple messages

---

## 4. Content Generation Factory

### Description

An orchestrator coordinates a team of agents to produce high-quality content: a researcher gathers information, a writer drafts the article, an editor refines it, and a publisher formats and delivers the final output.

### Components Used

- **Agents**: `content-orchestrator` (orchestrator), `topic-researcher` (researcher), `content-writer` (worker), `content-editor` (reviewer), `content-publisher` (worker)
- **Workflows**: Dependency-aware execution with reviewer feedback loop
- **Memory**: RAG pipeline for research context

### Agent Definitions

**content-orchestrator.json**

```json
{
  "name": "content-orchestrator",
  "version": "1.0.0",
  "role": "orchestrator",
  "description": "Plan content creation by determining research queries, outline structure, and quality criteria",
  "capabilities": ["orchestration"],
  "inputs": {
    "topic": { "type": "string", "required": true },
    "format": { "type": "string", "enum": ["blog", "whitepaper", "tutorial"], "default": "blog" },
    "word_count": { "type": "number", "default": 1500 }
  },
  "outputs": {
    "research_queries": { "type": "array", "description": "Queries for the researcher" },
    "outline": { "type": "array", "description": "Section headings and descriptions" },
    "quality_criteria": { "type": "array", "description": "Criteria for the editor to check" }
  },
  "dependencies": [
    { "agent": "topic-researcher", "purpose": "Gather source material" },
    { "agent": "content-writer", "purpose": "Draft sections" },
    { "agent": "content-editor", "purpose": "Review and refine" },
    { "agent": "content-publisher", "optional": true, "purpose": "Format and deliver" }
  ],
  "constraints": { "max_tokens": 2048, "timeout_seconds": 60 }
}
```

**content-editor.json**

```json
{
  "name": "content-editor",
  "version": "1.0.0",
  "role": "reviewer",
  "description": "Review drafted content for clarity, accuracy, grammar, and adherence to quality criteria. Provide specific feedback or approve.",
  "capabilities": ["validation", "refinement"],
  "inputs": {
    "draft": { "type": "string", "required": true },
    "criteria": { "type": "array", "description": "Quality criteria to evaluate against" }
  },
  "outputs": {
    "approved": { "type": "boolean" },
    "feedback": { "type": "string", "description": "Specific improvement suggestions" },
    "score": { "type": "number", "description": "Quality score 0-10" }
  },
  "constraints": { "max_tokens": 2048, "timeout_seconds": 90 }
}
```

### Workflow Definition

```json
{
  "name": "content-factory",
  "version": "1.0.0",
  "description": "End-to-end content generation with research, writing, editing, and publishing",
  "inputs": {
    "topic": { "type": "string", "required": true },
    "format": { "type": "string", "default": "blog" },
    "word_count": { "type": "number", "default": 1500 }
  },
  "steps": [
    {
      "id": "plan",
      "action": "invoke-agent",
      "agent": "content-orchestrator",
      "inputs": {
        "topic": "${inputs.topic}",
        "format": "${inputs.format}",
        "word_count": "${inputs.word_count}"
      }
    },
    {
      "id": "research",
      "action": "invoke-agent",
      "agent": "topic-researcher",
      "inputs": { "query": "${plan.research_queries}" },
      "depends_on": ["plan"]
    },
    {
      "id": "write",
      "action": "invoke-agent",
      "agent": "content-writer",
      "inputs": {
        "outline": "${plan.outline}",
        "research": "${research.summary}",
        "word_count": "${inputs.word_count}"
      },
      "depends_on": ["research"]
    },
    {
      "id": "edit",
      "action": "invoke-agent",
      "agent": "content-editor",
      "inputs": {
        "draft": "${write.content}",
        "criteria": "${plan.quality_criteria}"
      },
      "depends_on": ["write"]
    },
    {
      "id": "check-quality",
      "action": "conditional",
      "condition": "${edit.approved} == true",
      "depends_on": ["edit"],
      "then": [
        {
          "id": "publish",
          "action": "invoke-agent",
          "agent": "content-publisher",
          "inputs": {
            "content": "${write.content}",
            "format": "${inputs.format}"
          }
        }
      ],
      "else": [
        {
          "id": "revise",
          "action": "invoke-agent",
          "agent": "content-writer",
          "inputs": {
            "outline": "${plan.outline}",
            "research": "${research.summary}",
            "feedback": "${edit.feedback}",
            "word_count": "${inputs.word_count}"
          }
        }
      ]
    }
  ],
  "execution": {
    "mode": "dependency-aware",
    "timeout_seconds": 600,
    "continue_on_error": false
  }
}
```

### Configuration

```env
# Use a capable model for writing tasks
OPENAI_API_KEY=sk-...
# Use a local model for planning and editing (cheaper)
OLLAMA_DEFAULT_MODEL=llama3.2
```

Invoke the writer agent with `model: "gpt-4o"` and the orchestrator/editor with `model: "llama3.2"` to balance cost and quality.

### Expected Outcome

A complete content pipeline that produces publication-ready articles:
- The orchestrator creates a structured plan
- The researcher gathers relevant context
- The writer produces a draft following the outline
- The editor reviews against quality criteria
- If approved, the publisher formats the final output
- If rejected, the writer revises incorporating feedback

---

## 5. Automated DevOps

### Description

Cron-scheduled health checks monitor infrastructure, auto-remediation workflows fix common issues, and alert-driven responses handle incidents. The scheduler triggers workflows on a cadence, and webhook endpoints accept alerts from monitoring systems.

### Components Used

- **Agents**: `health-checker` (validator), `remediation-agent` (worker), `incident-reporter` (worker)
- **Automation**: `WorkflowScheduler` with cron triggers, webhook endpoints
- **Workflows**: Conditional remediation based on health check results
- **Tools**: `run-command` for executing shell commands

### Agent Definitions

**health-checker.json**

```json
{
  "name": "health-checker",
  "version": "1.0.0",
  "role": "validator",
  "description": "Analyze system health metrics and identify issues requiring remediation",
  "capabilities": ["validation", "api-calls"],
  "inputs": {
    "metrics": { "type": "object", "description": "System metrics (CPU, memory, disk, etc.)", "required": true },
    "thresholds": { "type": "object", "description": "Alert thresholds" }
  },
  "outputs": {
    "healthy": { "type": "boolean" },
    "issues": { "type": "array", "description": "List of identified issues" },
    "severity": { "type": "string", "enum": ["ok", "warning", "critical"] },
    "recommended_actions": { "type": "array", "description": "Suggested remediation steps" }
  },
  "constraints": { "max_tokens": 1024, "timeout_seconds": 30, "max_retries": 1 }
}
```

**remediation-agent.json**

```json
{
  "name": "remediation-agent",
  "version": "1.0.0",
  "role": "worker",
  "description": "Generate and validate safe remediation commands for identified infrastructure issues",
  "capabilities": ["code-execution", "api-calls"],
  "inputs": {
    "issues": { "type": "array", "required": true },
    "recommended_actions": { "type": "array", "required": true }
  },
  "outputs": {
    "commands": { "type": "array", "description": "Shell commands to execute" },
    "safe": { "type": "boolean", "description": "Whether the commands are safe to auto-execute" },
    "explanation": { "type": "string" }
  },
  "constraints": { "max_tokens": 1024, "timeout_seconds": 60, "max_retries": 0 }
}
```

### Workflow Definition

```json
{
  "name": "devops-health-check",
  "version": "1.0.0",
  "description": "Scheduled health check with auto-remediation",
  "triggers": {
    "schedule": "*/5 * * * *",
    "manual": true
  },
  "steps": [
    {
      "id": "collect-metrics",
      "action": "run-command",
      "command": "python scripts/collect_metrics.py --format json"
    },
    {
      "id": "check-health",
      "action": "invoke-agent",
      "agent": "health-checker",
      "inputs": {
        "metrics": "${collect-metrics.stdout}",
        "thresholds": { "cpu_percent": 90, "memory_percent": 85, "disk_percent": 90 }
      },
      "depends_on": ["collect-metrics"]
    },
    {
      "id": "needs-remediation",
      "action": "conditional",
      "condition": "${check-health.healthy} == false",
      "depends_on": ["check-health"],
      "then": [
        {
          "id": "plan-fix",
          "action": "invoke-agent",
          "agent": "remediation-agent",
          "inputs": {
            "issues": "${check-health.issues}",
            "recommended_actions": "${check-health.recommended_actions}"
          }
        },
        {
          "id": "apply-fix",
          "action": "conditional",
          "condition": "${plan-fix.safe} == true",
          "then": [
            {
              "id": "execute-fix",
              "action": "run-command",
              "command": "${plan-fix.commands[0]}",
              "timeout_seconds": 120
            }
          ],
          "else": [
            {
              "id": "alert-human",
              "action": "invoke-agent",
              "agent": "incident-reporter",
              "inputs": {
                "issues": "${check-health.issues}",
                "explanation": "${plan-fix.explanation}"
              }
            }
          ]
        }
      ],
      "else": []
    }
  ],
  "execution": {
    "mode": "sequential",
    "fail_fast": true,
    "timeout_seconds": 300
  }
}
```

### Scheduler Setup

```python
from agent33.automation.scheduler import WorkflowScheduler

scheduler = WorkflowScheduler(on_trigger=execute_workflow_callback)
scheduler.start()

# Run health check every 5 minutes
scheduler.schedule_cron("devops-health-check", "*/5 * * * *")

# Run full audit daily at 2 AM
scheduler.schedule_cron("full-system-audit", "0 2 * * *")
```

### Configuration

```env
OLLAMA_DEFAULT_MODEL=llama3.2
REDIS_URL=redis://redis:6379/0
```

### Expected Outcome

- Health checks run every 5 minutes automatically
- Issues are identified and classified by severity
- Safe remediations are applied automatically (e.g., clearing caches, restarting services)
- Unsafe or complex issues alert human operators with full context
- All actions are logged for audit trails

---

## 6. Data Processing Pipeline

### Description

A pipeline that ingests data from multiple sources, transforms it through agent-powered enrichment, validates the output, and stores results. Uses parallel processing for independent transformation steps.

### Components Used

- **Agents**: `data-enricher` (worker), `data-validator` (validator), `schema-mapper` (worker)
- **Workflows**: Parallel processing with validation gate
- **Actions**: `transform`, `validate`, `parallel-group`, `invoke-agent`

### Agent Definitions

**data-enricher.json**

```json
{
  "name": "data-enricher",
  "version": "1.0.0",
  "role": "worker",
  "description": "Enrich raw data records by extracting entities, classifying content, and adding computed fields",
  "capabilities": ["api-calls"],
  "inputs": {
    "records": { "type": "array", "description": "Raw data records", "required": true },
    "enrichment_rules": { "type": "object", "description": "Rules for enrichment" }
  },
  "outputs": {
    "enriched_records": { "type": "array", "description": "Records with added fields" },
    "stats": { "type": "object", "description": "Processing statistics" }
  },
  "constraints": { "max_tokens": 8192, "timeout_seconds": 180, "max_retries": 2 }
}
```

**data-validator.json**

```json
{
  "name": "data-validator",
  "version": "1.0.0",
  "role": "validator",
  "description": "Validate enriched data against schema rules and business logic constraints",
  "capabilities": ["validation"],
  "inputs": {
    "records": { "type": "array", "required": true },
    "schema_rules": { "type": "object", "description": "Validation rules" }
  },
  "outputs": {
    "valid_records": { "type": "array" },
    "invalid_records": { "type": "array" },
    "validation_report": { "type": "object" }
  },
  "constraints": { "max_tokens": 4096, "timeout_seconds": 120 }
}
```

### Workflow Definition

```json
{
  "name": "data-processing-pipeline",
  "version": "1.0.0",
  "description": "Ingest, enrich, validate, and store data with parallel processing",
  "inputs": {
    "source_url": { "type": "string", "required": true },
    "schema_rules": { "type": "object", "required": true }
  },
  "steps": [
    {
      "id": "ingest",
      "action": "run-command",
      "command": "python scripts/fetch_data.py --url ${inputs.source_url} --format json"
    },
    {
      "id": "split-batches",
      "action": "transform",
      "inputs": { "data": "${ingest.stdout}", "operation": "split_batches", "batch_size": 100 },
      "depends_on": ["ingest"]
    },
    {
      "id": "enrich-parallel",
      "action": "parallel-group",
      "depends_on": ["split-batches"],
      "steps": [
        {
          "id": "enrich-batch-1",
          "action": "invoke-agent",
          "agent": "data-enricher",
          "inputs": { "records": "${split-batches.batch_0}" }
        },
        {
          "id": "enrich-batch-2",
          "action": "invoke-agent",
          "agent": "data-enricher",
          "inputs": { "records": "${split-batches.batch_1}" }
        }
      ]
    },
    {
      "id": "merge",
      "action": "transform",
      "inputs": {
        "data": ["${enrich-parallel.results.enrich-batch-1.enriched_records}", "${enrich-parallel.results.enrich-batch-2.enriched_records}"],
        "operation": "merge_arrays"
      },
      "depends_on": ["enrich-parallel"]
    },
    {
      "id": "validate",
      "action": "invoke-agent",
      "agent": "data-validator",
      "inputs": {
        "records": "${merge.result}",
        "schema_rules": "${inputs.schema_rules}"
      },
      "depends_on": ["merge"]
    },
    {
      "id": "store",
      "action": "run-command",
      "command": "python scripts/store_data.py --input-json -",
      "inputs": { "stdin": "${validate.valid_records}" },
      "depends_on": ["validate"]
    }
  ],
  "execution": {
    "mode": "dependency-aware",
    "parallel_limit": 4,
    "timeout_seconds": 600
  }
}
```

### Configuration

```env
DATABASE_URL=postgresql+asyncpg://agent33:agent33@postgres:5432/agent33
OLLAMA_DEFAULT_MODEL=llama3.2
```

### Expected Outcome

- Data is fetched from the source URL
- Records are split into batches for parallel processing
- Each batch is enriched by an AI agent (entity extraction, classification)
- Results are merged and validated against schema rules
- Valid records are stored; invalid records are reported separately
- Processing statistics provide visibility into throughput and quality

---

## 7. Security Audit Automation

### Description

Scheduled security scans run against infrastructure and codebases, an AI agent assesses vulnerabilities for severity and exploitability, and a report is generated with prioritized remediation recommendations.

### Components Used

- **Agents**: `vuln-assessor` (researcher), `report-generator` (worker)
- **Automation**: `WorkflowScheduler` for daily/weekly scans
- **Workflows**: Sequential scan, assess, report pipeline
- **Tools**: `run-command` for running security scanners

### Agent Definitions

**vuln-assessor.json**

```json
{
  "name": "vuln-assessor",
  "version": "1.0.0",
  "role": "researcher",
  "description": "Analyze security scan results, assess vulnerability severity, determine exploitability, and prioritize remediation",
  "capabilities": ["research", "validation"],
  "inputs": {
    "scan_results": { "type": "object", "description": "Raw scanner output", "required": true },
    "context": { "type": "object", "description": "Environment context (production, staging, etc.)" }
  },
  "outputs": {
    "vulnerabilities": { "type": "array", "description": "Assessed vulnerabilities with severity scores" },
    "critical_count": { "type": "number" },
    "high_count": { "type": "number" },
    "recommendations": { "type": "array", "description": "Prioritized remediation steps" }
  },
  "constraints": { "max_tokens": 8192, "timeout_seconds": 180, "max_retries": 2 }
}
```

**report-generator.json**

```json
{
  "name": "security-report-generator",
  "version": "1.0.0",
  "role": "worker",
  "description": "Generate a formatted security audit report from vulnerability assessments",
  "capabilities": ["file-write"],
  "inputs": {
    "vulnerabilities": { "type": "array", "required": true },
    "recommendations": { "type": "array", "required": true },
    "scan_metadata": { "type": "object" }
  },
  "outputs": {
    "report_markdown": { "type": "string", "description": "Full report in Markdown format" },
    "executive_summary": { "type": "string", "description": "Brief summary for leadership" }
  },
  "constraints": { "max_tokens": 16384, "timeout_seconds": 120 }
}
```

### Workflow Definition

```json
{
  "name": "security-audit",
  "version": "1.0.0",
  "description": "Automated security scan, assessment, and report generation",
  "triggers": {
    "schedule": "0 3 * * 1",
    "manual": true
  },
  "steps": [
    {
      "id": "scan-deps",
      "action": "run-command",
      "command": "safety check --json",
      "timeout_seconds": 300
    },
    {
      "id": "scan-code",
      "action": "run-command",
      "command": "bandit -r src/ --format json",
      "timeout_seconds": 300
    },
    {
      "id": "scan-infra",
      "action": "run-command",
      "command": "trivy fs --format json .",
      "timeout_seconds": 600
    },
    {
      "id": "assess",
      "action": "invoke-agent",
      "agent": "vuln-assessor",
      "inputs": {
        "scan_results": {
          "dependencies": "${scan-deps.stdout}",
          "code": "${scan-code.stdout}",
          "infrastructure": "${scan-infra.stdout}"
        },
        "context": { "environment": "production" }
      },
      "depends_on": ["scan-deps", "scan-code", "scan-infra"]
    },
    {
      "id": "report",
      "action": "invoke-agent",
      "agent": "security-report-generator",
      "inputs": {
        "vulnerabilities": "${assess.vulnerabilities}",
        "recommendations": "${assess.recommendations}",
        "scan_metadata": { "date": "auto", "scans": ["safety", "bandit", "trivy"] }
      },
      "depends_on": ["assess"]
    },
    {
      "id": "save-report",
      "action": "run-command",
      "command": "python scripts/save_report.py --output reports/",
      "inputs": { "stdin": "${report.report_markdown}" },
      "depends_on": ["report"]
    }
  ],
  "execution": {
    "mode": "dependency-aware",
    "parallel_limit": 3,
    "timeout_seconds": 1800
  }
}
```

### Scheduler Setup

```python
scheduler = WorkflowScheduler(on_trigger=execute_workflow_callback)
scheduler.start()

# Weekly full audit on Monday at 3 AM
scheduler.schedule_cron("security-audit", "0 3 * * 1")

# Daily dependency check
scheduler.schedule_cron("dependency-check", "0 6 * * *")
```

### Configuration

```env
OLLAMA_DEFAULT_MODEL=llama3.2
# Use a larger model for accurate vulnerability assessment
OPENAI_API_KEY=sk-...
```

### Expected Outcome

- Three security scanners run in parallel (dependencies, code, infrastructure)
- An AI agent assesses all findings holistically, scoring severity and exploitability
- A formatted report is generated with executive summary and detailed findings
- Reports are saved to disk and can be emailed or posted to Slack
- Critical vulnerabilities trigger immediate alerts

---

## 8. Knowledge Base Builder

### Description

An automated system that ingests documents (Markdown, PDF, plain text), chunks them intelligently, generates embeddings, stores them in vector memory, and provides a semantic search and Q&A interface powered by RAG.

### Components Used

- **Memory**: `DocumentIngester`, `EmbeddingProvider`, `LongTermMemory`, `RAGPipeline`
- **Agents**: `qa-agent` (researcher), `summary-agent` (worker)
- **Automation**: File change sensor for auto-ingestion
- **Workflows**: Ingestion pipeline and query pipeline

### Agent Definitions

**qa-agent.json**

```json
{
  "name": "kb-qa-agent",
  "version": "1.0.0",
  "role": "researcher",
  "description": "Answer questions using knowledge base context. Always cite sources by [Source N] references. If the context does not contain enough information, say so.",
  "capabilities": ["research"],
  "inputs": {
    "augmented_question": { "type": "string", "description": "Question with RAG context prepended", "required": true }
  },
  "outputs": {
    "answer": { "type": "string", "description": "Detailed answer with citations" },
    "confidence": { "type": "number", "description": "0-1 confidence score" },
    "needs_more_info": { "type": "boolean", "description": "Whether the KB lacks sufficient info" }
  },
  "constraints": { "max_tokens": 4096, "timeout_seconds": 90, "max_retries": 2 }
}
```

**summary-agent.json**

```json
{
  "name": "doc-summarizer",
  "version": "1.0.0",
  "role": "worker",
  "description": "Generate a concise summary of a document for the knowledge base index",
  "capabilities": ["research"],
  "inputs": {
    "document_text": { "type": "string", "required": true },
    "document_title": { "type": "string" }
  },
  "outputs": {
    "summary": { "type": "string", "description": "2-3 paragraph summary" },
    "key_topics": { "type": "array", "description": "Main topics covered" },
    "suggested_questions": { "type": "array", "description": "Questions this document can answer" }
  },
  "constraints": { "max_tokens": 2048, "timeout_seconds": 60 }
}
```

### Ingestion Workflow

```json
{
  "name": "kb-ingest",
  "version": "1.0.0",
  "description": "Ingest a document into the knowledge base",
  "triggers": {
    "manual": true,
    "on_change": ["docs/**/*.md", "docs/**/*.txt"]
  },
  "inputs": {
    "file_path": { "type": "string", "required": true },
    "chunk_size": { "type": "number", "default": 500 },
    "overlap": { "type": "number", "default": 50 }
  },
  "steps": [
    {
      "id": "read-doc",
      "action": "run-command",
      "command": "cat ${inputs.file_path}"
    },
    {
      "id": "summarize",
      "action": "invoke-agent",
      "agent": "doc-summarizer",
      "inputs": {
        "document_text": "${read-doc.stdout}",
        "document_title": "${inputs.file_path}"
      },
      "depends_on": ["read-doc"]
    },
    {
      "id": "chunk-and-embed",
      "action": "run-command",
      "command": "python scripts/chunk_and_embed.py --input-stdin --chunk-size ${inputs.chunk_size} --overlap ${inputs.overlap}",
      "inputs": { "stdin": "${read-doc.stdout}" },
      "depends_on": ["read-doc"],
      "timeout_seconds": 300
    },
    {
      "id": "store-summary",
      "action": "run-command",
      "command": "python scripts/store_summary.py --file ${inputs.file_path}",
      "inputs": { "stdin": "${summarize}" },
      "depends_on": ["summarize"]
    }
  ],
  "execution": {
    "mode": "dependency-aware",
    "parallel_limit": 2
  }
}
```

### Query Workflow

```json
{
  "name": "kb-query",
  "version": "1.0.0",
  "description": "Answer a question from the knowledge base",
  "inputs": {
    "question": { "type": "string", "required": true },
    "top_k": { "type": "number", "default": 5 }
  },
  "steps": [
    {
      "id": "retrieve",
      "action": "run-command",
      "command": "python scripts/rag_query.py --question '${inputs.question}' --top-k ${inputs.top_k} --format json"
    },
    {
      "id": "answer",
      "action": "invoke-agent",
      "agent": "kb-qa-agent",
      "inputs": { "augmented_question": "${retrieve.stdout}" },
      "depends_on": ["retrieve"]
    }
  ],
  "execution": { "mode": "sequential" }
}
```

### Programmatic Setup

```python
from agent33.memory.ingestion import DocumentIngester
from agent33.memory.embeddings import EmbeddingProvider
from agent33.memory.long_term import LongTermMemory
from agent33.memory.rag import RAGPipeline

# Initialize components
ingester = DocumentIngester()
embedder = EmbeddingProvider(base_url="http://ollama:11434", model="nomic-embed-text")
memory = LongTermMemory(...)

# Ingest a document
chunks = ingester.ingest_markdown(doc_text, chunk_size=500, overlap=50)
for chunk in chunks:
    vec = await embedder.embed(chunk.text)
    await memory.store(text=chunk.text, embedding=vec, metadata=chunk.metadata)

# Query
rag = RAGPipeline(embedder, memory, top_k=5, similarity_threshold=0.3)
result = await rag.query("How do I configure agents?")
# result.augmented_prompt contains the question with retrieved context
# result.sources contains the matched chunks with similarity scores
```

### Configuration

```env
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_DEFAULT_MODEL=llama3.2
DATABASE_URL=postgresql+asyncpg://agent33:agent33@postgres:5432/agent33
```

Ensure `nomic-embed-text` (or your preferred embedding model) is available in Ollama.

### Expected Outcome

- Documents are automatically chunked respecting markdown structure (headings create natural boundaries)
- Each chunk is embedded and stored in vector memory with metadata
- Document summaries and suggested questions are generated for the index
- Users ask natural language questions and receive cited answers
- The system indicates when it lacks sufficient information rather than hallucinating
- New documents are automatically ingested when files change in watched directories
