import type { OpenRouterModelEntry } from "../../lib/openrouterModels";
import type { ProviderModelRecommendation } from "./presets";

export type ModelCapabilityKind = "coding" | "speed" | "free" | "context" | "local" | "easy";

export interface ModelCapabilityTag {
  kind: ModelCapabilityKind;
  label: string;
}

type CapabilitySource =
  | OpenRouterModelEntry
  | ProviderModelRecommendation
  | {
      id: string;
      name: string;
      description?: string;
      capabilities?: string[];
      contextLength?: number | null;
      promptPrice?: string | null;
      isFree?: boolean;
    };

function includesAny(value: string, needles: string[]): boolean {
  return needles.some((needle) => value.includes(needle));
}

function pushUnique(tags: ModelCapabilityTag[], tag: ModelCapabilityTag): void {
  if (!tags.some((existing) => existing.kind === tag.kind || existing.label === tag.label)) {
    tags.push(tag);
  }
}

export function getModelCapabilityTags(model: CapabilitySource): ModelCapabilityTag[] {
  const searchable = [
    model.id,
    model.name,
    "description" in model ? model.description : "",
    ...("capabilities" in model && Array.isArray(model.capabilities) ? model.capabilities : [])
  ]
    .join(" ")
    .toLowerCase();
  const tags: ModelCapabilityTag[] = [];

  if (includesAny(searchable, ["coder", "coding", "code"])) {
    pushUnique(tags, { kind: "coding", label: "Best for coding" });
  }
  if (includesAny(searchable, ["flash", "fast", "turbo", "mini"])) {
    pushUnique(tags, { kind: "speed", label: "Fast start" });
  }
  if (model.isFree === true || ("promptPrice" in model && model.promptPrice === "Free")) {
    pushUnique(tags, { kind: "free", label: "Free option" });
  }
  if (typeof model.contextLength === "number" && model.contextLength >= 100_000) {
    pushUnique(tags, { kind: "context", label: "Long context" });
  }
  if (includesAny(searchable, ["local", "ollama", "lm studio"])) {
    pushUnique(tags, { kind: "local", label: "Runs locally" });
  }
  if (includesAny(searchable, ["auto", "easy", "loaded"])) {
    pushUnique(tags, { kind: "easy", label: "Easy mode" });
  }

  return tags.slice(0, 3);
}
