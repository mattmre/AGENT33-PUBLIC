# AGENT-33 Agent Guide

This guide covers everything you need to know about creating, configuring, running, and testing agents in the AGENT-33 engine.

---

## Table of Contents

1. [What are Agents](#1-what-are-agents)
2. [Agent Definition Format](#2-agent-definition-format)
3. [Creating Agents](#3-creating-agents)
4. [Agent Runtime](#4-agent-runtime)
5. [Agent Registry](#5-agent-registry)
6. [LLM Routing](#6-llm-routing)
7. [Multi-Model Strategies](#7-multi-model-strategies)
8. [Agent Interaction Patterns](#8-agent-interaction-patterns)
9. [Testing Agents](#9-testing-agents)
10. [Best Practices](#10-best-practices)

---

## 1. What are Agents

An **agent** in AGENT-33 is a declarative unit of AI capability defined as a JSON file. Each agent has a name, a role, a set of capabilities, typed inputs and outputs, prompt templates, and execution constraints. The engine loads these definitions, constructs prompts automatically, calls an LLM, and parses the response into structured output.

### Role Types

| Role | Purpose |
|------|---------|
| `orchestrator` | Coordinates multiple agents, delegates sub-tasks, aggregates results |
| `director` | Makes high-level decisions about which agents to invoke and in what order |
| `worker` | Performs a focused task (code generation, summarization, translation, etc.) |
| `reviewer` | Evaluates outputs from other agents and provides feedback or approval |
| `researcher` | Gathers information, performs searches, synthesizes findings |
| `validator` | Checks outputs against rules, schemas, or quality criteria |

### Capabilities

Agents declare what they are allowed to do. The engine uses these declarations for security enforcement and tooling access.

| Capability | Description |
|------------|-------------|
| `file-read` | Read files from the filesystem |
| `file-write` | Write or modify files |
| `code-execution` | Execute code in a sandbox |
| `web-search` | Query external search APIs |
| `api-calls` | Make HTTP requests to external services |
| `orchestration` | Invoke other agents |
| `validation` | Validate data against schemas or rules |
| `research` | Perform research and information gathering |
| `refinement` | Iteratively improve outputs |

---

## 2. Agent Definition Format

Every agent is defined as a JSON file that conforms to the `AgentDefinition` Pydantic model. Below is the full schema with annotations.

### Complete Schema

```json
{
  "$schema": "agent.schema.json",
  "name": "my-agent",
  "version": "1.0.0",
  "role": "worker",
  "description": "A short description of what this agent does (max 500 chars)",
  "capabilities": ["file-read", "code-execution"],
  "inputs": {
    "source_code": {
      "type": "string",
      "description": "The source code to analyze",
      "required": true,
      "default": null,
      "enum": null
    }
  },
  "outputs": {
    "analysis": {
      "type": "string",
      "description": "The analysis result",
      "required": true,
      "default": null,
      "enum": null
    }
  },
  "dependencies": [
    {
      "agent": "linter-agent",
      "optional": true,
      "purpose": "Pre-lint before analysis"
    }
  ],
  "prompts": {
    "system": "path/to/system-prompt.txt",
    "user": "path/to/user-prompt.txt",
    "examples": ["path/to/example1.txt"]
  },
  "constraints": {
    "max_tokens": 4096,
    "timeout_seconds": 120,
    "max_retries": 2,
    "parallel_allowed": true
  },
  "metadata": {
    "author": "team-name",
    "created": "2026-01-30",
    "updated": "2026-01-30",
    "tags": ["code", "analysis"]
  }
}
```

### Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique identifier. Pattern: `^[a-z][a-z0-9-]*$`, 2-64 chars |
| `version` | string | Yes | Semantic version. Pattern: `^\d+\.\d+\.\d+$` |
| `role` | enum | Yes | One of: `orchestrator`, `director`, `worker`, `reviewer`, `researcher`, `validator` |
| `description` | string | No | Human-readable description, max 500 characters |
| `capabilities` | array | No | List of capability enums the agent declares |
| `inputs` | object | No | Map of parameter name to `AgentParameter` objects |
| `outputs` | object | No | Map of parameter name to `AgentParameter` objects |
| `dependencies` | array | No | List of `AgentDependency` objects |
| `prompts` | object | No | Paths to prompt template files |
| `constraints` | object | No | Execution limits (tokens, timeout, retries) |
| `metadata` | object | No | Author, dates, tags |

### AgentParameter Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | string | (required) | Data type: `string`, `number`, `boolean`, `object`, `array` |
| `description` | string | `""` | What this parameter represents |
| `required` | bool | `false` | Whether the parameter must be provided |
| `default` | any | `null` | Default value if not provided |
| `enum` | array | `null` | Allowed values (if constrained) |

### AgentConstraints Fields

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `max_tokens` | int | 4096 | 100-200000 | Maximum tokens for LLM response |
| `timeout_seconds` | int | 120 | 10-3600 | Maximum execution time |
| `max_retries` | int | 2 | 0-10 | Retry attempts on failure |
| `parallel_allowed` | bool | `true` | -- | Whether this agent can run concurrently |

---

## 3. Creating Agents

### Step 1: Choose a Role

Decide what your agent does. A focused worker is the most common starting point.

### Step 2: Define Inputs and Outputs

Be explicit about what data flows in and out. Use typed parameters with descriptions.

### Step 3: Write the JSON File

Save to your agent definitions directory (any folder of `.json` files that you point the registry at).

### Example: Simple Worker Agent

```json
{
  "name": "code-reviewer",
  "version": "1.0.0",
  "role": "worker",
  "description": "Reviews source code for bugs, style issues, and improvements",
  "capabilities": ["file-read"],
  "inputs": {
    "code": {
      "type": "string",
      "description": "Source code to review",
      "required": true
    },
    "language": {
      "type": "string",
      "description": "Programming language",
      "required": false,
      "default": "python"
    }
  },
  "outputs": {
    "review": {
      "type": "string",
      "description": "Detailed code review"
    },
    "score": {
      "type": "number",
      "description": "Quality score from 0 to 10"
    }
  },
  "constraints": {
    "max_tokens": 2048,
    "timeout_seconds": 60,
    "max_retries": 1
  },
  "metadata": {
    "author": "dev-team",
    "tags": ["code", "review"]
  }
}
```

### Example: Orchestrator Agent

```json
{
  "name": "pipeline-orchestrator",
  "version": "1.0.0",
  "role": "orchestrator",
  "description": "Coordinates research, drafting, and review agents for content creation",
  "capabilities": ["orchestration"],
  "inputs": {
    "topic": {
      "type": "string",
      "description": "The topic to create content about",
      "required": true
    }
  },
  "outputs": {
    "final_content": {
      "type": "string",
      "description": "The finished, reviewed content"
    }
  },
  "dependencies": [
    { "agent": "researcher", "optional": false, "purpose": "Gather source material" },
    { "agent": "writer", "optional": false, "purpose": "Draft content" },
    { "agent": "editor", "optional": true, "purpose": "Polish final output" }
  ],
  "constraints": {
    "max_tokens": 8192,
    "timeout_seconds": 300,
    "max_retries": 2
  }
}
```

### Example: Reviewer Agent

```json
{
  "name": "quality-reviewer",
  "version": "1.0.0",
  "role": "reviewer",
  "description": "Evaluates generated content against quality criteria",
  "capabilities": ["validation", "refinement"],
  "inputs": {
    "content": {
      "type": "string",
      "description": "Content to review",
      "required": true
    },
    "criteria": {
      "type": "array",
      "description": "List of quality criteria to check",
      "required": false,
      "default": ["accuracy", "clarity", "completeness"]
    }
  },
  "outputs": {
    "approved": {
      "type": "boolean",
      "description": "Whether the content passes review"
    },
    "feedback": {
      "type": "string",
      "description": "Detailed feedback"
    }
  },
  "constraints": {
    "max_tokens": 2048,
    "timeout_seconds": 90,
    "max_retries": 1
  }
}
```

### Example: Researcher Agent

```json
{
  "name": "topic-researcher",
  "version": "1.0.0",
  "role": "researcher",
  "description": "Researches a topic and produces a structured summary with citations",
  "capabilities": ["research", "web-search"],
  "inputs": {
    "query": {
      "type": "string",
      "description": "Research question",
      "required": true
    },
    "depth": {
      "type": "string",
      "description": "How deep to research",
      "enum": ["shallow", "medium", "deep"],
      "default": "medium"
    }
  },
  "outputs": {
    "summary": { "type": "string", "description": "Research summary" },
    "sources": { "type": "array", "description": "List of sources found" }
  },
  "constraints": {
    "max_tokens": 4096,
    "timeout_seconds": 180
  }
}
```

---

## 4. Agent Runtime

The `AgentRuntime` class in `agent33.agents.runtime` is responsible for executing an agent definition against an LLM. Here is the full flow:

### Prompt Construction

When `invoke()` is called, the runtime builds a system prompt automatically from the definition:

1. **Identity line**: `"You are '{name}', an AI agent with role '{role}'."`
2. **Purpose**: The agent's `description` field
3. **Capabilities**: Comma-separated list of declared capabilities
4. **Expected inputs**: Each input parameter with its name, type, and description
5. **Required outputs**: Each output parameter with its name, type, and description
6. **Constraints**: Token limit, timeout, and retry count
7. **Format instruction**: `"Respond with valid JSON containing the output fields."`

The user message is the `inputs` dictionary serialized as pretty-printed JSON.

### Input Validation

Before calling the LLM, the runtime checks every parameter in `definition.inputs` that has `required: true`. If any required input is missing from the provided data, a `ValueError` is raised immediately.

### LLM Call Flow

```
invoke(inputs)
  |
  v
_build_system_prompt(definition)
  |
  v
Validate required inputs
  |
  v
Build messages: [system_prompt, user_content_json]
  |
  v
Loop up to (max_retries + 1) attempts:
  |-- router.complete(messages, model, temperature, max_tokens)
  |-- On success: break
  |-- On exception: log warning, continue to next attempt
  |
  v
If all attempts fail: raise RuntimeError
  |
  v
_parse_output(raw_response, definition)
  |
  v
Return AgentResult(output, raw_response, tokens_used, model)
```

### Output Parsing

The `_parse_output` function handles several response formats:

1. **Markdown code fences**: Strips `` ```json ... ``` `` wrappers
2. **Valid JSON object**: Returned directly as a dict
3. **Valid JSON non-object**: Wrapped as `{"result": value}`
4. **Non-JSON text with single output**: Uses the single output key name as the dict key
5. **Non-JSON text with multiple outputs**: Falls back to `{"result": raw_text}`

### AgentResult

The return value is a frozen dataclass with:

| Field | Type | Description |
|-------|------|-------------|
| `output` | `dict[str, Any]` | Parsed output dictionary |
| `raw_response` | `str` | Raw LLM response text |
| `tokens_used` | `int` | Total tokens (prompt + completion) |
| `model` | `str` | Model identifier that was used |

---

## 5. Agent Registry

The `AgentRegistry` class provides in-memory storage and discovery of agent definitions.

### Auto-Discovery from Directory

Point the registry at a folder containing `.json` files:

```python
from agent33.agents.registry import AgentRegistry

registry = AgentRegistry()
count = registry.discover("/path/to/agent-definitions/")
print(f"Loaded {count} agents")
```

The `discover()` method:
- Scans the directory for all `*.json` files (sorted alphabetically)
- Loads each file via `AgentDefinition.load_from_file()`
- Registers successfully loaded definitions by name
- Logs errors for any files that fail validation
- Returns the count of definitions loaded

### Registering via API

**POST** `/v1/agents/` with a full agent definition JSON body:

```bash
curl -X POST http://localhost:8000/v1/agents/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-agent",
    "version": "1.0.0",
    "role": "worker",
    "description": "Example agent"
  }'
```

Response:
```json
{"status": "registered", "name": "my-agent"}
```

### Programmatic Registration

```python
registry.register(definition)
```

### Listing Agents

**GET** `/v1/agents/` returns a summary of all registered agents:

```json
[
  {
    "name": "code-reviewer",
    "version": "1.0.0",
    "role": "worker",
    "description": "Reviews source code"
  }
]
```

Programmatically:

```python
all_agents = registry.list_all()       # sorted by name
agent = registry.get("code-reviewer")  # returns None if not found
exists = "code-reviewer" in registry   # boolean check
count = len(registry)                  # total count
registry.remove("old-agent")           # returns True if existed
```

### Retrieving a Single Agent

**GET** `/v1/agents/{name}` returns the full definition as JSON. Returns 404 if not found.

---

## 6. LLM Routing

The `ModelRouter` class dispatches LLM requests to the correct provider based on model name prefixes.

### How Model Selection Works

When you invoke an agent, you specify (or default to) a model name like `gpt-4o`, `llama3.2`, or `claude-3.5-sonnet`. The router checks the model name against a prefix map in order:

| Prefix | Provider |
|--------|----------|
| `gpt-` | `openai` |
| `o1` | `openai` |
| `o3` | `openai` |
| `claude-` | `openai` (via OpenAI-compatible proxy) |
| `ft:gpt-` | `openai` |
| *(no match)* | `ollama` (default) |

The first matching prefix wins. If no prefix matches, the default provider (`ollama`) is used.

### Provider Prefixes

You can customize the prefix map when constructing the router:

```python
router = ModelRouter(
    prefix_map=[
        ("gpt-", "openai"),
        ("claude-", "anthropic"),
        ("mistral-", "ollama"),
    ],
    default_provider="ollama",
)
```

### Fallback Behavior

If the model name matches a prefix but the mapped provider is not registered, a `ValueError` is raised. If no prefix matches and the default provider is not registered, a `ValueError` is raised. There is no automatic fallback to a different provider -- you must ensure the required providers are registered.

### Registering Providers

```python
from agent33.llm.router import ModelRouter
from agent33.llm.ollama import OllamaProvider
from agent33.llm.openai import OpenAIProvider

router = ModelRouter()
router.register("ollama", OllamaProvider(base_url="http://localhost:11434"))
router.register("openai", OpenAIProvider(api_key="sk-..."))
```

### Supported Providers

| Provider | Class | Backend |
|----------|-------|---------|
| `ollama` | `OllamaProvider` | Local Ollama instance (default `http://localhost:11434`) |
| `openai` | `OpenAIProvider` | OpenAI API or any OpenAI-compatible endpoint |

Both providers implement the `LLMProvider` protocol and include automatic exponential-backoff retry (3 attempts).

---

## 7. Multi-Model Strategies

Different agents can use different models to balance cost, speed, and capability.

### Assigning Models per Agent

When invoking an agent via the API, pass the `model` field:

```bash
curl -X POST http://localhost:8000/v1/agents/code-reviewer/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {"code": "def hello(): pass"},
    "model": "gpt-4o",
    "temperature": 0.3
  }'
```

When using the runtime directly:

```python
runtime = AgentRuntime(
    definition=definition,
    router=router,
    model="gpt-4o",        # override model per agent
    temperature=0.3,
)
result = await runtime.invoke({"code": "..."})
```

### Cost Optimization Strategy

| Task Complexity | Recommended Models | Rationale |
|----------------|-------------------|-----------|
| Simple extraction, formatting | `llama3.2`, `gpt-4o-mini` | Low cost, fast, sufficient quality |
| Standard generation, summarization | `gpt-4o`, `llama3.1:70b` | Good balance of quality and cost |
| Complex reasoning, code review | `gpt-4o`, `o3` | Higher capability needed |
| Creative writing, nuanced analysis | `claude-3.5-sonnet`, `gpt-4o` | Best quality for subjective tasks |
| Validation, simple checks | `llama3.2`, `gpt-4o-mini` | Deterministic tasks need minimal model power |

### Workflow-Level Model Assignment

In a workflow, each `invoke-agent` step can use a different model by configuring the agent runtime accordingly. This means your orchestrator can use a small, fast model while delegating complex work to a larger model.

### Token Budget Management

Use the `constraints.max_tokens` field in agent definitions to cap response size per agent. For a pipeline, plan your total token budget across all agents:

```
Total budget = sum(agent.constraints.max_tokens for each agent in pipeline)
```

Monitor actual usage via the `tokens_used` field returned in every `AgentResult`.

---

## 8. Agent Interaction Patterns

### Single Agent Invocation

The simplest pattern: call one agent with inputs, get outputs.

```python
runtime = AgentRuntime(definition=agent_def, router=router, model="llama3.2")
result = await runtime.invoke({"query": "Explain async/await"})
print(result.output)
```

Or via API:

```bash
curl -X POST http://localhost:8000/v1/agents/my-agent/invoke \
  -d '{"inputs": {"query": "Explain async/await"}}'
```

### Chained Agents in Workflows

Use a sequential workflow to pipe one agent's output into the next:

```json
{
  "name": "research-and-write",
  "version": "1.0.0",
  "steps": [
    {
      "id": "research",
      "action": "invoke-agent",
      "agent": "topic-researcher",
      "inputs": { "query": "${inputs.topic}" }
    },
    {
      "id": "write",
      "action": "invoke-agent",
      "agent": "content-writer",
      "inputs": { "context": "${research.summary}" },
      "depends_on": ["research"]
    }
  ],
  "execution": { "mode": "sequential" }
}
```

The expression syntax `${step_id.field}` passes data between steps.

### Orchestrator-Worker Delegation

An orchestrator agent decides what to do, then a workflow invokes worker agents based on its output:

```json
{
  "name": "smart-pipeline",
  "version": "1.0.0",
  "steps": [
    {
      "id": "plan",
      "action": "invoke-agent",
      "agent": "pipeline-orchestrator",
      "inputs": { "topic": "${inputs.topic}" }
    },
    {
      "id": "execute-workers",
      "action": "parallel-group",
      "steps": [
        {
          "id": "research-task",
          "action": "invoke-agent",
          "agent": "topic-researcher",
          "inputs": { "query": "${plan.research_query}" }
        },
        {
          "id": "outline-task",
          "action": "invoke-agent",
          "agent": "content-writer",
          "inputs": { "prompt": "${plan.outline_prompt}" }
        }
      ],
      "depends_on": ["plan"]
    }
  ],
  "execution": { "mode": "dependency-aware" }
}
```

### Reviewer Feedback Loops

Use a conditional step to re-invoke a worker if the reviewer rejects the output:

```json
{
  "name": "review-loop",
  "version": "1.0.0",
  "steps": [
    {
      "id": "draft",
      "action": "invoke-agent",
      "agent": "content-writer",
      "inputs": { "topic": "${inputs.topic}" }
    },
    {
      "id": "review",
      "action": "invoke-agent",
      "agent": "quality-reviewer",
      "inputs": { "content": "${draft.content}" },
      "depends_on": ["draft"]
    },
    {
      "id": "check-approval",
      "action": "conditional",
      "condition": "${review.approved} == true",
      "then": [
        {
          "id": "publish",
          "action": "invoke-agent",
          "agent": "publisher",
          "inputs": { "content": "${draft.content}" }
        }
      ],
      "else": [
        {
          "id": "revise",
          "action": "invoke-agent",
          "agent": "content-writer",
          "inputs": {
            "topic": "${inputs.topic}",
            "feedback": "${review.feedback}"
          }
        }
      ],
      "depends_on": ["review"]
    }
  ],
  "execution": { "mode": "sequential" }
}
```

---

## 9. Testing Agents

AGENT-33 provides two testing utilities: `AgentTestHarness` for agent-level tests and `MockLLMProvider` for deterministic LLM behavior.

### AgentTestHarness

The harness lets you test agent definitions with canned inputs and outputs without calling a real LLM.

```python
import asyncio
from agent33.testing.agent_harness import AgentTestHarness

harness = AgentTestHarness()

# Load from file
harness.load_agent("/path/to/code-reviewer.json")

# Or load a definition object directly
# harness.load_definition(my_definition)

# Test with a single input
result = asyncio.run(harness.test_with_input(
    input_data={"code": "def foo(): pass", "language": "python"},
    responses={
        # Map the exact user message content to a canned LLM response
        '{\n  "code": "def foo(): pass",\n  "language": "python"\n}':
            '{"review": "Looks good", "score": 8}'
    },
))

print(result.output)   # {"review": "Looks good", "score": 8}
print(result.model)    # "mock"
```

### Canned Input/Output Pairs for Regression

Register multiple test cases and run them all at once:

```python
harness.add_canned_pair(
    input_data={"code": "x = 1"},
    expected_output={"review": "Simple assignment", "score": 5},
)
harness.add_canned_pair(
    input_data={"code": "import os; os.system('rm -rf /')"},
    expected_output={"review": "Dangerous code", "score": 0},
)

results = asyncio.run(harness.run_regression(responses={...}))
for pair, result in results:
    assert result.output == pair.expected_output
```

### MockLLMProvider

For more fine-grained control, use `MockLLMProvider` directly. It implements the `LLMProvider` protocol and returns responses from a configurable map.

```python
from agent33.testing.mock_llm import MockLLMProvider
from agent33.llm.router import ModelRouter
from agent33.agents.runtime import AgentRuntime

mock = MockLLMProvider()
mock.set_response(
    '{\n  "query": "test"\n}',
    '{"summary": "Test result", "sources": []}'
)

router = ModelRouter(default_provider="mock")
router.register("mock", mock)

runtime = AgentRuntime(definition=my_agent, router=router, model="mock-model")
result = asyncio.run(runtime.invoke({"query": "test"}))
```

**Key behaviors of MockLLMProvider:**

- Matches on the exact content of the last user message
- If no match is found, echoes the user message back as the response
- Reports token counts as character lengths (for testing purposes)
- Returns `["mock-model"]` from `list_models()`

### Writing Regression Tests

A recommended pattern using pytest:

```python
import pytest
from agent33.testing.agent_harness import AgentTestHarness

@pytest.fixture
def harness():
    h = AgentTestHarness()
    h.load_agent("/path/to/my-agent.json")
    return h

@pytest.mark.asyncio
async def test_basic_invocation(harness):
    result = await harness.test_with_input(
        {"code": "print('hello')"},
        responses={
            '{\n  "code": "print(\'hello\')"\n}':
                '{"review": "Simple print statement", "score": 7}'
        },
    )
    assert result.output["score"] == 7

@pytest.mark.asyncio
async def test_missing_required_input(harness):
    with pytest.raises(ValueError, match="Missing required input"):
        await harness.test_with_input({})
```

---

## 10. Best Practices

### Prompt Engineering for Agents

- **Be specific in descriptions**: The `description` field becomes part of the system prompt. Write it as an instruction, not a label.
- **Name outputs precisely**: Output parameter names and descriptions guide the LLM on what JSON keys to produce.
- **Use enum constraints**: When an input or output has a fixed set of values, use the `enum` field to communicate that to the LLM.
- **Keep agents focused**: One agent should do one thing well. Split complex tasks across multiple agents.

### Constraining Outputs

- Always define explicit `outputs` with types and descriptions. The runtime tells the LLM to respond with valid JSON matching these fields.
- For boolean decisions, use a single output with `type: "boolean"`.
- For structured data, describe the expected JSON shape in the output description.
- The output parser handles markdown code fences, so the LLM can wrap responses in `` ```json ``` `` blocks.

### Retry Strategies

- Set `max_retries` to 1-2 for most agents. The runtime retries on any exception.
- For critical agents, use `max_retries: 3` with a generous `timeout_seconds`.
- For quick, cheap agents, `max_retries: 0` is fine -- fail fast and let the workflow handle it.
- At the workflow level, each step has its own `retry` configuration with `max_attempts` and `delay_seconds`.

### Token Budget Management

- Set `max_tokens` based on expected output size, not input size. The LLM response is what gets capped.
- Monitor `tokens_used` in `AgentResult` to track actual consumption.
- For pipelines, estimate total cost: `sum(agent_tokens * price_per_token * invocations)`.
- Use smaller models for simple tasks (validation, extraction) and larger models for generation.

### General Guidelines

- **Version your agents**: Use semantic versioning. Bump the version when you change inputs, outputs, or behavior.
- **Tag agents**: Use `metadata.tags` to categorize agents for discovery and filtering.
- **Test with MockLLMProvider**: Always write regression tests for agent definitions before deploying.
- **Set timeouts**: Every agent should have a reasonable `timeout_seconds` to prevent runaway LLM calls.
- **Declare capabilities honestly**: The security layer uses capabilities to enforce permissions. Only declare what the agent actually needs.
