export type HelperRuntimeModeId = "static-search" | "browser-semantic" | "ollama-sidecar";
export type HelperRuntimeStatus = "available" | "pilot-ready" | "requires-setup";

export interface HelperRuntimeMode {
  id: HelperRuntimeModeId;
  title: string;
  status: HelperRuntimeStatus;
  privacy: string;
  description: string;
  setup: string[];
}

export const HELPER_RUNTIME_MODES: HelperRuntimeMode[] = [
  {
    id: "static-search",
    title: "Static cited search",
    status: "available",
    privacy: "Runs in this browser with built-in docs only.",
    description: "Searches curated setup recipes and feature docs without model calls.",
    setup: ["No setup required", "No secrets sent", "Works without WebGPU or local models"]
  },
  {
    id: "browser-semantic",
    title: "Browser semantic search",
    status: "pilot-ready",
    privacy: "Planned local embeddings in the browser; no external calls by default.",
    description: "Future mode for meaning-based search when bundle size and CPU cost are acceptable.",
    setup: ["Keep static search as fallback", "Ask before downloading model assets", "Show CPU/WebGPU readiness first"]
  },
  {
    id: "ollama-sidecar",
    title: "Ollama sidecar helper",
    status: "requires-setup",
    privacy: "Uses a local Ollama server you start and control.",
    description: "Future local RAG helper for users who already run Ollama or another OpenAI-compatible local server.",
    setup: ["Start Ollama locally", "Connect Models to http://localhost:11434/v1", "Keep secrets out of prompts"]
  }
];

export function getHelperRuntimeMode(id: string): HelperRuntimeMode {
  return HELPER_RUNTIME_MODES.find((mode) => mode.id === id) ?? HELPER_RUNTIME_MODES[0];
}

export function getRuntimeStatusLabel(status: HelperRuntimeStatus): string {
  if (status === "available") {
    return "Available now";
  }
  if (status === "pilot-ready") {
    return "Pilot path";
  }
  return "Needs local setup";
}
