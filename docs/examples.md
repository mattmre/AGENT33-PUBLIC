# Examples

This document walks through realistic scenarios using AGENT-33. Each
example is end-to-end: what you are trying to accomplish, the commands
or configuration you write, what the system does, and how to verify it
worked.

Examples assume you have a running engine. If you do not yet, follow
[`QUICKSTART.md`](../QUICKSTART.md) first.

---

## Example 1: Run a single agent against a goal

The simplest useful interaction: ask one of the reference agents to do
one thing.

### Setup

```bash
# Confirm the engine is reachable
agent33 status
```

You should see `status: ok` and a list of subsystems.

### Invoke the researcher

```bash
agent33 sessions create --name "weather lookup"
# returns: session_id=sess_01H...

agent33 sessions send sess_01H... \
  --agent researcher \
  --message "What was the high temperature in Tokyo yesterday?"
```

### What happens

1. The CLI sends the message to the engine through `/v1/sessions/{id}/messages`.
2. The engine resolves the `researcher` agent from the registry.
3. The agent runtime constructs the prompt. The `web_fetch` and shell
   tools are in the researcher's allowlist, so they appear in the
   tool list.
4. The model decides to call `web_fetch` against a weather source.
5. The runtime validates the call against the tool's schema, runs it,
   and feeds the result back into the next iteration.
6. The model summarizes the result and returns a final answer.

### Verify

```bash
# Read the transcript
agent33 sessions show sess_01H...

# Read the trace tree
agent33 traces show --session sess_01H...
```

The trace shows each LLM call, each tool call, and the timing for each
step.

---

## Example 2: Compose a multi-step workflow

When a goal requires more than one agent, define a workflow.

### Define the workflow

Create `my-workflow.yaml`:

```yaml
name: research-and-summarize
version: 1
inputs:
  topic:
    type: string
    required: true
steps:
  - id: research
    action: invoke_agent
    agent: researcher
    input:
      message: "Find three recent sources about ${inputs.topic}."

  - id: summarize
    action: invoke_agent
    agent: code-worker
    depends_on: [research]
    input:
      message: |
        Write a 200-word summary from these sources:
        ${steps.research.output}

  - id: review
    action: invoke_agent
    agent: qa
    depends_on: [summarize]
    input:
      message: |
        Review this summary for accuracy and clarity:
        ${steps.summarize.output}

outputs:
  summary: ${steps.summarize.output}
  review: ${steps.review.output}
```

### Run it

```bash
agent33 workflows register my-workflow.yaml
# returns: workflow_id=wf_01H...

agent33 workflows run wf_01H... \
  --input topic="post-quantum cryptography"
# returns: run_id=run_01H...
```

### What happens

1. The workflow engine validates the DAG.
2. `research` starts. There are no unresolved dependencies, so it runs
   immediately.
3. When `research` completes, the engine checkpoints its output.
4. `summarize` becomes runnable. The expression
   `${steps.research.output}` is resolved from the checkpoint and fed
   into the agent invocation.
5. `summarize` completes, and `review` runs.
6. The run ends. The outputs declared in the workflow are available
   through the API.

### Verify

```bash
agent33 workflows runs show run_01H...
```

If the engine crashes mid-run, the next start picks up from the last
checkpoint — no work is lost.

---

## Example 3: Install and use a pack

Packs are how capability is shared between installations.

### Find a pack

```bash
agent33 packs search "code review"
# returns: a list of matching packs from PackHub
```

### Install it

```bash
agent33 packs install code-review-pack@1.2.0
```

The CLI:

1. Downloads the pack from PackHub.
2. Verifies the SHA-256 integrity hash against the manifest.
3. Loads the pack into the local registry.

### Use the new capability

The pack typically ships one or more agents, skills, or tools. List
what was added:

```bash
agent33 packs show code-review-pack
```

You might see an agent like `code-reviewer-pro` and a skill like
`unit-test-coverage`. Invoke the new agent the same way as a built-in
one:

```bash
agent33 sessions send sess_01H... \
  --agent code-reviewer-pro \
  --message "Review the diff in branch feat/login-flow."
```

The runtime auto-loads the pack's skills and exposes the pack's tools
according to the active tool governance policy.

### Verify

```bash
agent33 packs status code-review-pack
```

You can see when it was installed, what version, and which agents,
skills, and tools it contributed.

---

## Example 4: Add a custom tool

Custom tools let an agent call into your own code.

### Author the tool

Create `tools/my_tool.py` inside the engine:

```python
from agent33.tools.registry import register_tool
from agent33.tools.types import ToolResult

@register_tool(
    name="ticker_lookup",
    description="Look up a stock ticker symbol from a company name.",
    schema={
        "type": "object",
        "properties": {
            "company": {"type": "string", "description": "Company name"},
        },
        "required": ["company"],
    },
)
async def ticker_lookup(company: str) -> ToolResult:
    # Your implementation here. Could call an API, look up a local
    # CSV, etc.
    ticker = await my_data_source.lookup(company)
    return ToolResult(output={"company": company, "ticker": ticker})
```

### Make it available

Add the tool's name to the relevant agent's `allowed_tools` list in its
JSON definition:

```json
{
  "name": "finance-researcher",
  "allowed_tools": ["web_fetch", "ticker_lookup"],
  "...": "..."
}
```

Restart the engine. The new tool appears in the tool registry, and
agents whose allowlist includes it can call it.

### Verify

```bash
agent33 tools list --tenant default | grep ticker_lookup
```

Then ask the agent:

```bash
agent33 sessions send sess_01H... \
  --agent finance-researcher \
  --message "What is the ticker for SpaceX?"
```

The trace shows the `ticker_lookup` call with the input the LLM
provided and the output your handler returned.

---

## Example 5: Run an agent under an autonomy budget

When you want to give an agent latitude without unbounded access,
define a budget.

### Define the budget

```yaml
# budgets/code-fix-budget.yaml
name: code-fix-budget
file_scope:
  read: ["src/**", "tests/**"]
  write: ["src/**", "tests/**"]
command_scope:
  allow: ["pytest", "ruff", "mypy"]
  deny: ["rm -rf", "*sudo*"]
network_scope:
  allow: []
stop_conditions:
  max_steps: 30
  max_wall_clock_seconds: 600
```

### Apply the budget

```bash
agent33 autonomy budgets register budgets/code-fix-budget.yaml
agent33 sessions send sess_01H... \
  --agent code-worker \
  --budget code-fix-budget \
  --message "Fix the failing tests in tests/test_payment.py."
```

### What happens

- Preflight: the runtime checks the budget for the requested agent. If
  the agent's allowed tools step outside the budget, the request is
  rejected before any step runs.
- Runtime: every tool call is checked against the active budget. A
  command outside the allowlist is rejected. A file write outside the
  write scope is rejected. A network call to a host outside the
  network allowlist is rejected.
- Stop conditions: if the agent uses 30 steps without finishing, the
  run is terminated and the budget records the reason.

### Verify

```bash
agent33 autonomy budgets show code-fix-budget
```

You can see how many runs have used it, how often a stop condition was
hit, and whether any preflight rejections occurred.

---

## Example 6: Set up scheduled knowledge ingestion

When you want to keep a tenant's knowledge base current without writing
a cron job yourself.

### Configure the source

```yaml
# knowledge/sources.yaml
sources:
  - id: hn-frontpage
    type: rss
    url: https://news.ycombinator.com/rss
    schedule: "0 */4 * * *"   # every 4 hours
    tenant: default

  - id: kubernetes-blog
    type: web
    url: https://kubernetes.io/blog/
    schedule: "0 9 * * *"     # daily at 09:00
    tenant: default
    selectors:
      article: "article.post"
      title: "h1.post-title"
      body: "div.post-content"
```

### Register sources

```bash
agent33 knowledge sources register knowledge/sources.yaml
```

APScheduler picks them up. At each scheduled tick, the ingestion
service fetches the source, chunks the content, computes embeddings,
and writes them into the tenant's long-term memory.

### Verify

```bash
agent33 knowledge sources list
agent33 knowledge runs --source hn-frontpage --tail 5
```

Future agent invocations on the same tenant can now retrieve the
ingested content through the RAG pipeline without any change to the
agent itself.

---

## What to do next

- Browse [`docs/use-cases.md`](use-cases.md) for higher-level
  scenarios.
- Read [`docs/walkthroughs.md`](walkthroughs.md) for guided
  step-by-step tours.
- Read [`docs/architecture/`](architecture/) when you want to know how
  the engine handles what each example just did.
