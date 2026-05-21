export const HELP_ASSISTANT_TARGETS = [
  "guide",
  "start",
  "connect",
  "demo",
  "models",
  "setup",
  "catalog",
  "starter",
  "operations",
  "safety",
  "mcp",
  "advanced"
] as const;

export type HelpAssistantTarget = (typeof HELP_ASSISTANT_TARGETS)[number];

export interface HelpSource {
  label: string;
  path: string;
}

export interface HelpAction {
  label: string;
  target: HelpAssistantTarget;
}

export interface HelpArticle {
  id: string;
  title: string;
  audience: string;
  summary: string;
  body: string[];
  steps: string[];
  keywords: string[];
  sources: HelpSource[];
  actions: HelpAction[];
}

export interface HelpSearchResult {
  article: HelpArticle;
  score: number;
  matchedTerms: string[];
}

export interface RagSource {
  text: string;
  score: number;
  metadata: Record<string, unknown>;
  retrieval_method: string;
}

export interface RagQueryResponse {
  augmented_prompt: string;
  sources: RagSource[];
  citations: string[];
}

export interface OllamaQueryResponse {
  text: string;
  sources: RagSource[];
}

/** Typed sentinel returned by ragQuery when the backend is unavailable (HTTP 503). */
export interface RagUnavailableResult {
  unavailable: true;
  detail: string;
}
