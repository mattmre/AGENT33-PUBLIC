import type { DomainConfig } from "../../types";

export const agentsDomain: DomainConfig = {
  id: "agents",
  title: "Agents",
  description: "Agent registry, search, details, invoke.",
  operations: [
    {
      id: "agents-catalog",
      title: "Capabilities Catalog",
      method: "GET",
      path: "/v1/agents/capabilities/catalog",
      description: "Agent capabilities catalog.",
      instructionalText: "View a master index of all specific skills, tools, and actions that registered agents are currently capable of performing."
    },
    {
      id: "agents-search",
      title: "Search Agents",
      method: "GET",
      path: "/v1/agents/search",
      description: "Search by role/tags.",
      instructionalText: "Find specific agents based on their assigned roles (like 'orchestrator' or 'worker') or specific capability tags.",
      schemaInfo: {
        parameters: [
          { name: "role", type: "string", description: "Filter the agent registry to only return agents possessing this exact role.", required: false },
          { name: "tags", type: "string", description: "Comma-separated list of capabilities to filter by.", required: false }
        ]
      },
      defaultQuery: {
        role: "orchestrator"
      }
    },
    {
      id: "agents-by-id",
      title: "Get Agent by ID",
      method: "GET",
      path: "/v1/agents/by-id/{agent_id}",
      description: "Fetch agent by identifier.",
      instructionalText: "Retrieve the exact configuration, assigned tools, and current behavioral parameters for a specific agent using its unique ID.",
      schemaInfo: {
        parameters: [
          { name: "agent_id", type: "string", description: "The precise unqiue identifier of the agent.", required: true }
        ]
      },
      defaultPathParams: {
        agent_id: "AGT-001"
      }
    },
    {
      id: "agents-list",
      title: "List Agents",
      method: "GET",
      path: "/v1/agents/",
      description: "List all registered agents.",
      instructionalText: "Fetch a complete roster of every intelligent agent currently registered and active within the engine ecosystem."
    },
    {
      id: "agents-get",
      title: "Get Agent by Name",
      method: "GET",
      path: "/v1/agents/{name}",
      description: "Fetch agent definition by name.",
      instructionalText: "Retrieve the full configuration and capabilities for an agent by providing its human-readable name, like 'orchestrator'.",
      schemaInfo: {
        parameters: [
          { name: "name", type: "string", description: "The registered human-readable name of the agent.", required: true }
        ]
      },
      defaultPathParams: {
        name: "orchestrator"
      }
    },
    {
      id: "agents-create",
      title: "Create Agent",
      method: "POST",
      path: "/v1/agents/",
      description: "Register a new agent definition.",
      instructionalText: "Programmatically deploy a brand new agent personality into the engine, supplying its behavioral constraints, toolset, and core identity description.",
      schemaInfo: {
        body: {
          description: "A complete agent definition specifying its context, system prompt, tool constraints, and overarching role within the engine.",
          example: '{\n  "name": "demo-worker",\n  "role": "worker",\n  "description": "A demo agent for performing simple calculations.",\n  "capabilities": ["math", "logic"],\n  "constraints": {\n    "max_tokens": 1024,\n    "timeout_seconds": 60\n  }\n}'
        }
      },
      defaultBody: JSON.stringify(
        {
          name: "demo-agent",
          version: "1.0.0",
          role: "worker",
          description: "Demo worker",
          capabilities: [],
          inputs: {},
          outputs: {},
          constraints: {
            max_tokens: 2048,
            timeout_seconds: 120,
            max_retries: 2,
            parallel_allowed: true
          }
        },
        null,
        2
      )
    },
    {
      id: "agents-invoke",
      title: "Invoke Agent",
      method: "POST",
      path: "/v1/agents/{name}/invoke",
      description: "Run an agent by name.",
      instructionalText: "Command an agent to perform a specific one-off task. The agent will process your request, use necessary tools immediately, and return a single final conclusive answer.",
      schemaInfo: {
        parameters: [
          { name: "name", type: "string", description: "The registered name of the agent to invoke.", required: true }
        ],
        body: {
          description: "A JSON specifying the task inputs and optionally overriding the model constraints.",
          example: '{\n  "inputs": {\n    "task": "Quickly research the weather in Tokyo."\n  },\n  "model": "openrouter/auto",\n  "temperature": 0.4\n}'
        }
      },
      defaultPathParams: {
        name: "orchestrator"
      },
      defaultBody: JSON.stringify(
        {
          inputs: {
            task: "Generate a short implementation plan."
          },
          model: "openrouter/auto",
          temperature: 0.2
        },
        null,
        2
      )
    },
    {
      id: "agents-invoke-iterative",
      title: "Invoke Agent (Iterative)",
      method: "POST",
      path: "/v1/agents/{name}/invoke-iterative",
      description: "Iterative tool-use loop invocation for autonomous problem solving.",
      instructionalText: "Unleash an agent with deep autonomy. Instead of returning right away, the agent will enter a cognitive loop—thinking, testing, reflecting, and adapting tools—until it successfully solves the complex objective provided.",
      schemaInfo: {
        parameters: [
          { name: "name", type: "string", description: "The registered name of the agent to unleash.", required: true }
        ],
        body: {
          description: "A JSON specifying the complex task and the absolute limits on how long the agent is allowed to think/loop.",
          example: '{\n  "inputs": {\n    "task": "Fully refactor the frontend css stylesheet."\n  },\n  "max_iterations": 15,\n  "max_tool_calls_per_iteration": 4,\n  "enable_double_confirmation": true\n}'
        }
      },
      defaultPathParams: {
        name: "orchestrator"
      },
      defaultBody: JSON.stringify(
        {
          inputs: {
            task: "Iteratively solve and validate a workflow execution plan."
          },
          model: "openrouter/auto",
          temperature: 0.2,
          max_iterations: 8,
          max_tool_calls_per_iteration: 4,
          enable_double_confirmation: true
        },
        null,
        2
      ),
      uxHint: "agent-iterative"
    }
  ]
};
