import type { HelpArticle } from "./types";

export const HELP_ARTICLES: HelpArticle[] = [
  {
    id: "helper-runtime-modes",
    title: "Choose a helper runtime",
    audience: "New user deciding whether setup help should stay local",
    summary:
      "The Help Assistant defaults to static cited search. Browser semantic search and Ollama sidecar modes are pilot paths that must stay opt-in and privacy-explicit.",
    body: [
      "Static cited search is available now and uses only built-in help articles.",
      "Browser semantic search should ask before downloading model or embedding assets and must keep static search as the fallback.",
      "Ollama sidecar help should only run when a user starts a local server and chooses that runtime."
    ],
    steps: [
      'Click "Ask AGENT33".',
      "Keep Static cited search selected for no-setup help.",
      "Use Browser semantic search only when the UI says the browser is ready.",
      "Use Ollama sidecar only after starting a local Ollama server and connecting Models."
    ],
    keywords: [
      "helper",
      "runtime",
      "browser",
      "semantic",
      "ollama",
      "local",
      "privacy",
      "assistant"
    ],
    sources: [
      { label: "Helper runtime modes", path: "frontend/src/features/help-assistant/helperModes.ts" },
      { label: "Help Assistant drawer", path: "frontend/src/features/help-assistant/HelpAssistantDrawer.tsx" },
      { label: "Wave 2 helper architecture", path: "docs/research/wave2-r10-helper-llm-pilot.md" }
    ],
    actions: [
      { label: "Open Models", target: "models" },
      { label: "Open Connect Center", target: "connect" }
    ]
  },
  {
    id: "connect-center",
    title: "Use Connect Center for setup",
    audience: "New user who needs to connect models, tools, and safety",
    summary:
      "Connect Center turns setup into a readable checklist for engine access, models, runtime memory, MCP tools, tool catalog visibility, and safety approvals.",
    body: [
      "Use Connect Center when you are not sure whether you need Models, Integrations, MCP Health, Tools, or Safety Center.",
      "It reuses existing readiness checks when credentials are available and otherwise gives safe next actions.",
      "The center does not store secrets or auto-fix settings; each action opens the deeper setup page for review."
    ],
    steps: [
      "Open Start > Connect.",
      "Review the recommended next connection.",
      "Use Refresh connection scan after adding an operator token or API key.",
      "Open the suggested setup page and return to Connect when done."
    ],
    keywords: [
      "connect",
      "setup",
      "models",
      "integrations",
      "mcp",
      "tools",
      "safety",
      "readiness"
    ],
    sources: [
      { label: "Connect Center panel", path: "frontend/src/features/connect-center/UnifiedConnectCenterPanel.tsx" },
      { label: "Connect card helpers", path: "frontend/src/features/connect-center/helpers.ts" },
      { label: "Wave 2 Round 4 research", path: "docs/research/wave2-r4-unified-connect-center.md" }
    ],
    actions: [
      { label: "Open Connect Center", target: "connect" },
      { label: "Open model setup", target: "models" }
    ]
  },
  {
    id: "choose-role-path",
    title: "Choose a role-based start path",
    audience: "New user who is not sure where to begin",
    summary:
      "The Guide Me page asks what kind of user you are, recommends workflows and demos, and turns a plain-language idea into a Workflow Starter draft.",
    body: [
      "Use Guide Me before opening settings if you are unsure what model, tool, or workflow you need.",
      "Role paths are advisory: they change the recommended workflows and demos, but they do not hide the full catalog.",
      "The guided brief stays local and plan-only until you choose to connect a model and run a workflow."
    ],
    steps: [
      "Open Guide Me.",
      "Choose Founder, Developer, Agency, Enterprise, or Operator.",
      "Review the recommended workflows and demos.",
      "Fill in the guided brief and create a Workflow Starter draft."
    ],
    keywords: [
      "guide",
      "role",
      "persona",
      "beginner",
      "idea intake",
      "product brief",
      "guided start"
    ],
    sources: [
      { label: "Role Intake panel", path: "frontend/src/features/role-intake/RoleIntakePanel.tsx" },
      { label: "Role profiles", path: "frontend/src/features/role-intake/data.ts" },
      { label: "Wave 2 Round 3 research", path: "docs/research/wave2-r3-role-intake-guided-brief.md" }
    ],
    actions: [
      { label: "Open Guide Me", target: "guide" },
      { label: "Try Demo Mode", target: "demo" }
    ]
  },
  {
    id: "try-demo-mode",
    title: "Try Demo Mode before setup",
    audience: "New user who wants to see value before connecting credentials",
    summary:
      "Demo Mode shows sample outcomes, a simulated run timeline, and reviewable artifacts without calling a model or requiring API keys.",
    body: [
      "Use Demo Mode when you want to understand the product loop before configuring providers.",
      "The demo is static and offline: it does not create files, call models, or pretend that a backend run succeeded.",
      "When you are ready, you can send a sample into Workflow Starter as an editable draft or connect a model from the Models page."
    ],
    steps: [
      "Open Start > Demo Mode.",
      "Pick a sample outcome such as support dashboard, landing page, or repo triage.",
      "Review the simulated timeline and artifacts.",
      "Use Customize this demo after connecting credentials, or open Models to make the workflow real."
    ],
    keywords: [
      "demo",
      "sample",
      "first success",
      "no setup",
      "no credentials",
      "offline",
      "preview",
      "artifacts"
    ],
    sources: [
      { label: "Demo Mode panel", path: "frontend/src/features/demo-mode/DemoModePanel.tsx" },
      { label: "Demo scenarios", path: "frontend/src/features/demo-mode/demoScenarios.ts" },
      { label: "Wave 2 Round 2 research", path: "docs/research/wave2-r2-demo-mode-first-success.md" }
    ],
    actions: [
      { label: "Open Demo Mode", target: "demo" },
      { label: "Connect model when ready", target: "models" }
    ]
  },
  {
    id: "connect-openrouter",
    title: "Connect OpenRouter",
    audience: "New user setting up the first cloud model",
    summary:
      "Use the Models page to save an OpenRouter key, keep the base URL on the standard endpoint, choose a default model, and run the probe before launching workflows.",
    body: [
      "OpenRouter is the recommended cloud-model starting path because one key can route to many model providers.",
      "AGENT33 stores provider settings through the existing operator config flow. The UI never needs to show a stored secret back to you.",
      "For environment-based setup, use OPENROUTER_API_KEY for the key, OPENROUTER_BASE_URL=https://openrouter.ai/api/v1 for the endpoint, and DEFAULT_MODEL=openrouter/auto or the recommended stable default shown in Models."
    ],
    steps: [
      "Open Start > Models.",
      "Pick the OpenRouter provider path.",
      "Paste your OpenRouter API key into the provider key field.",
      "Keep the base URL as https://openrouter.ai/api/v1 unless you are using a compatible gateway.",
      "Choose the recommended default model or enter DEFAULT_MODEL=openrouter/auto.",
      "Save settings, then run Test connection before using Workflow Catalog."
    ],
    keywords: [
      "openrouter",
      "model",
      "provider",
      "api key",
      "openrouter_api_key",
      "openrouter_base_url",
      "default_model",
      "connect",
      "setup"
    ],
    sources: [
      { label: "Model Connection Wizard", path: "frontend/src/features/model-connection/ModelConnectionWizardPanel.tsx" },
      { label: "OpenRouter config helpers", path: "frontend/src/features/model-connection/helpers.ts" },
      { label: "Engine environment example", path: "engine/.env.example" },
      { label: "Setup guide", path: "docs/setup-guide.md" }
    ],
    actions: [
      { label: "Open Models", target: "models" },
      { label: "Browse workflows after setup", target: "catalog" }
    ]
  },
  {
    id: "connect-local-model-provider",
    title: "Connect Ollama or LM Studio",
    audience: "Local user who wants a private model path",
    summary:
      "Use the Models page provider cards to choose Ollama or LM Studio, fill the local endpoint automatically, leave the key blank unless your local server requires one, then test the connection.",
    body: [
      "Ollama and LM Studio are local provider paths. AGENT33 does not download a model in this step; your local model server needs to be running first.",
      "Ollama usually uses http://localhost:11434/v1. LM Studio usually uses http://localhost:1234/v1 after you start its local server.",
      "Local paths are useful for privacy and setup practice, but smaller local models may be slower or less capable than cloud models."
    ],
    steps: [
      "Open Start > Models.",
      "Pick Ollama or LM Studio from the provider path cards.",
      "Confirm the Base URL matches the local server you started.",
      "Choose the recommended local model or type the model name your local server exposes.",
      "Save settings, then run Test connection before using Workflow Catalog."
    ],
    keywords: [
      "ollama",
      "lm studio",
      "local model",
      "localhost",
      "openai compatible",
      "provider",
      "models",
      "setup"
    ],
    sources: [
      { label: "Provider presets", path: "frontend/src/features/model-connection/presets.ts" },
      { label: "Model Connection Wizard", path: "frontend/src/features/model-connection/ModelConnectionWizardPanel.tsx" },
      { label: "Round 5 research", path: "docs/research/wave2-r5-provider-setup-v2.md" }
    ],
    actions: [
      { label: "Open Models", target: "models" },
      { label: "Browse workflows after setup", target: "catalog" }
    ]
  },
  {
    id: "start-docker",
    title: "Start or refresh Docker",
    audience: "Local user running AGENT33 with Docker Desktop",
    summary:
      "Run Docker Compose from the engine folder, rebuild when code changes, then open the frontend and verify API health.",
    body: [
      "The AGENT33 stack is launched from engine/docker-compose.yml, not the repository root.",
      "The frontend is exposed on http://localhost:3000 and the API health check is exposed on http://localhost:8000/health.",
      "When updating to the latest code, rebuild the api and frontend images and recreate containers so the browser sees the new UI."
    ],
    steps: [
      "Open a terminal in the repo worktree.",
      "Run cd engine.",
      "Run docker compose -p engine up -d --build --remove-orphans.",
      "Open http://localhost:3000.",
      "Verify http://localhost:8000/health returns a 200 response."
    ],
    keywords: [
      "docker",
      "docker desktop",
      "compose",
      "localhost",
      "frontend",
      "health",
      "refresh",
      "rebuild"
    ],
    sources: [
      { label: "Setup guide", path: "docs/setup-guide.md" },
      { label: "Docker compose", path: "engine/docker-compose.yml" },
      { label: "Frontend Dockerfile", path: "frontend/Dockerfile" }
    ],
    actions: [
      { label: "Open Start", target: "start" },
      { label: "Open Operations Hub", target: "operations" }
    ]
  },
  {
    id: "first-workflow",
    title: "Run a first workflow",
    audience: "Beginner trying to get a useful outcome",
    summary:
      "Start with Workflow Catalog, pick a review-gated workflow, and let Workflow Starter turn it into an editable plan before anything runs.",
    body: [
      "Workflow Catalog is the beginner-safe path for prebuilt outcomes. It shows audience, deliverables, expected time, prerequisites, and safety posture.",
      "Workflow Starter receives an editable draft from catalog cards so you can adjust the goal and output before launching.",
      "Review-gated workflows are safer for first use because they ask for confirmation before moving from planning into action."
    ],
    steps: [
      "Open Build > Workflow Catalog.",
      "Search for an outcome like landing page, repo analysis, competitive research, or SaaS scaffold.",
      "Choose Use this workflow.",
      "Review the drafted goal and expected output in Workflow Starter.",
      "Launch only after model readiness and safety expectations are clear."
    ],
    keywords: [
      "workflow",
      "catalog",
      "starter",
      "first run",
      "prebuilt",
      "template",
      "outcome",
      "beginner"
    ],
    sources: [
      { label: "Workflow Catalog", path: "frontend/src/features/workflow-catalog/WorkflowCatalogPanel.tsx" },
      { label: "Outcome workflow catalog", path: "frontend/src/features/outcome-home/catalog.ts" },
      { label: "UX backlog workflow items", path: "docs/research/ux-overhaul-backlog-2026-04-27.md" }
    ],
    actions: [
      { label: "Open Workflow Catalog", target: "catalog" },
      { label: "Open Workflow Starter", target: "starter" }
    ]
  },
  {
    id: "what-is-safe-mode",
    title: "Beginner mode vs Pro mode",
    audience: "User worried about destructive controls",
    summary:
      "Beginner mode keeps raw API/domain controls quarantined and routes you to safer pages for models, workflows, safety, and operations.",
    body: [
      "Beginner mode is the default. It hides raw endpoint forms because they are powerful and easy to misuse.",
      "Pro mode is still available for operators who need direct domain operations, endpoint search, and raw request tools.",
      "If a page shows raw JSON or endpoint language, use the safer route cards first unless you know exactly what the operation changes."
    ],
    steps: [
      "Keep Mode set to Beginner for normal setup and workflow work.",
      "Use Models, Workflow Catalog, Safety Center, and Operations Hub for guided actions.",
      "Only unlock Pro mode when you need raw domain operations.",
      "Return to Beginner mode after technical inspection."
    ],
    keywords: [
      "beginner",
      "pro",
      "advanced",
      "raw",
      "safe",
      "destructive",
      "control plane",
      "endpoint"
    ],
    sources: [
      { label: "Advanced quarantine", path: "frontend/src/features/advanced/AdvancedControlPlanePanel.tsx" },
      { label: "UX session log", path: "docs/sessions/session-133-2026-04-27-ux-overhaul.md" }
    ],
    actions: [
      { label: "Open Safety Center", target: "safety" },
      { label: "Open Advanced", target: "advanced" }
    ]
  },
  {
    id: "mcp-tools-skills",
    title: "Understand MCP, tools, and skills",
    audience: "User confused by platform vocabulary",
    summary:
      "Think of models as the brain, tools as actions, MCP as external tool connections, skills as packaged know-how, and workflows as the step-by-step plan.",
    body: [
      "A model generates reasoning and text. A tool performs a specific action. MCP connects AGENT33 to external tool servers.",
      "A skill packages instructions, workflows, and reusable operating knowledge. A workflow combines goals, tools, skills, safety gates, and outputs.",
      "If you are not sure where to start, pick a workflow first. AGENT33 should tell you which model, tools, and skills that workflow needs."
    ],
    steps: [
      "Open Workflow Catalog if you know your desired outcome.",
      "Open MCP Health if a tool server is not available.",
      "Open Tool Fabric to discover or sync tools.",
      "Open Skill Wizard only when you want to author or install a reusable skill."
    ],
    keywords: [
      "mcp",
      "tool",
      "skills",
      "skill",
      "workflow",
      "model",
      "fabric",
      "glossary"
    ],
    sources: [
      { label: "MCP Health", path: "frontend/src/features/mcp-health/McpHealthPanel.tsx" },
      { label: "Tool Fabric", path: "frontend/src/features/tool-fabric/ToolFabricPanel.tsx" },
      { label: "Skill Wizard", path: "frontend/src/features/skill-wizard/SkillWizardPanel.tsx" }
    ],
    actions: [
      { label: "Open MCP Health", target: "mcp" },
      { label: "Open Workflow Catalog", target: "catalog" }
    ]
  }
];
