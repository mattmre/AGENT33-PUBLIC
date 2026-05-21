import {
  OPENROUTER_STABLE_DEFAULT_MODEL,
  normalizeLikelyOpenRouterModelRef
} from "../../lib/openrouterModels";

export interface ModelConnectionBaseline {
  defaultModel: string;
  baseUrl: string;
  siteUrl: string;
  appName: string;
  appCategory: string;
  localEngine: string;
}

export interface ModelConnectionForm extends ModelConnectionBaseline {
  apiKey: string;
  writeToEnvFile: boolean;
  removeStoredKey: boolean;
}

export interface LocalRuntimeBaseline {
  baseUrl: string;
  defaultModel: string;
  engine: string;
}

export type LocalRuntimeFlavor = "ollama" | "lm-studio" | "local-orchestration";

export const DEFAULT_MODEL_CONNECTION_BASELINE: ModelConnectionBaseline = {
  defaultModel: OPENROUTER_STABLE_DEFAULT_MODEL,
  baseUrl: "https://openrouter.ai/api/v1",
  siteUrl: "http://localhost",
  appName: "AGENT-33",
  appCategory: "cli-agent",
  localEngine: "llama.cpp"
};

export const DEFAULT_LOCAL_RUNTIME_BASELINE: LocalRuntimeBaseline = {
  baseUrl: "http://host.docker.internal:8033/v1",
  defaultModel: "qwen3-coder-next",
  engine: "llama.cpp"
};

function normalizeLocalRuntimeEngine(engine: string): string {
  return engine.trim().toLowerCase().replace(/\s+/g, "").replace(/_/g, "-");
}

export function getLocalRuntimeFlavor(engine: string): LocalRuntimeFlavor {
  const normalizedEngine = normalizeLocalRuntimeEngine(engine);
  if (normalizedEngine === "ollama") {
    return "ollama";
  }
  if (normalizedEngine === "lmstudio" || normalizedEngine === "lm-studio") {
    return "lm-studio";
  }
  return "local-orchestration";
}

export function normalizeConfiguredValue(value: string, fallback: string): string {
  return value.trim() || fallback;
}

export function buildOpenRouterConfigChanges(
  form: ModelConnectionForm,
  baseline: ModelConnectionBaseline
): Record<string, unknown> {
  const normalizedForm = {
    defaultModel: normalizeLikelyOpenRouterModelRef(form.defaultModel),
    baseUrl: normalizeConfiguredValue(form.baseUrl, DEFAULT_MODEL_CONNECTION_BASELINE.baseUrl),
    siteUrl: normalizeConfiguredValue(form.siteUrl, DEFAULT_MODEL_CONNECTION_BASELINE.siteUrl),
    appName: normalizeConfiguredValue(form.appName, DEFAULT_MODEL_CONNECTION_BASELINE.appName),
    appCategory: normalizeConfiguredValue(
      form.appCategory,
      DEFAULT_MODEL_CONNECTION_BASELINE.appCategory
    )
  };
  const normalizedBaseline = {
    defaultModel: normalizeLikelyOpenRouterModelRef(baseline.defaultModel),
    baseUrl: normalizeConfiguredValue(baseline.baseUrl, DEFAULT_MODEL_CONNECTION_BASELINE.baseUrl),
    siteUrl: normalizeConfiguredValue(baseline.siteUrl, DEFAULT_MODEL_CONNECTION_BASELINE.siteUrl),
    appName: normalizeConfiguredValue(baseline.appName, DEFAULT_MODEL_CONNECTION_BASELINE.appName),
    appCategory: normalizeConfiguredValue(
      baseline.appCategory,
      DEFAULT_MODEL_CONNECTION_BASELINE.appCategory
    )
  };

  const changes: Record<string, unknown> = {};
  if (normalizedForm.defaultModel !== normalizedBaseline.defaultModel) {
    changes.default_model = normalizedForm.defaultModel;
  }
  if (normalizedForm.baseUrl !== normalizedBaseline.baseUrl) {
    changes.openrouter_base_url = normalizedForm.baseUrl;
  }
  if (normalizedForm.siteUrl !== normalizedBaseline.siteUrl) {
    changes.openrouter_site_url = normalizedForm.siteUrl;
  }
  if (normalizedForm.appName !== normalizedBaseline.appName) {
    changes.openrouter_app_name = normalizedForm.appName;
  }
  if (normalizedForm.appCategory !== normalizedBaseline.appCategory) {
    changes.openrouter_app_category = normalizedForm.appCategory;
  }

  const trimmedApiKey = form.apiKey.trim();
  if (trimmedApiKey) {
    changes.openrouter_api_key = trimmedApiKey;
  } else if (form.removeStoredKey) {
    changes.openrouter_api_key = "";
  }

  return changes;
}

export function buildOpenRouterProbePayload(form: ModelConnectionForm): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    openrouter_base_url: normalizeConfiguredValue(
      form.baseUrl,
      DEFAULT_MODEL_CONNECTION_BASELINE.baseUrl
    ),
    openrouter_site_url: normalizeConfiguredValue(
      form.siteUrl,
      DEFAULT_MODEL_CONNECTION_BASELINE.siteUrl
    ),
    openrouter_app_name: normalizeConfiguredValue(
      form.appName,
      DEFAULT_MODEL_CONNECTION_BASELINE.appName
    ),
    openrouter_app_category: normalizeConfiguredValue(
      form.appCategory,
      DEFAULT_MODEL_CONNECTION_BASELINE.appCategory
    )
  };

  const model = normalizeLikelyOpenRouterModelRef(form.defaultModel);
  if (model) {
    payload.default_model = model;
  }
  if (form.apiKey.trim()) {
    payload.openrouter_api_key = form.apiKey.trim();
  } else if (form.removeStoredKey) {
    payload.openrouter_api_key = "";
  }

  return payload;
}

export function buildLocalRuntimeConfigChanges(
  form: ModelConnectionForm,
  baseline: ModelConnectionBaseline,
  localBaseline: LocalRuntimeBaseline
): Record<string, unknown> {
  const normalizedEngine = normalizeConfiguredValue(
    form.localEngine,
    DEFAULT_LOCAL_RUNTIME_BASELINE.engine
  );
  const runtimeFlavor = getLocalRuntimeFlavor(normalizedEngine);
  const normalizedBaseUrl = normalizeLocalRuntimeBaseUrl(
    normalizeConfiguredValue(form.baseUrl, DEFAULT_LOCAL_RUNTIME_BASELINE.baseUrl),
    normalizedEngine
  );
  const normalizedDefaultModel = formatLocalRuntimeModelRef(
    stripLocalRuntimeModelRef(form.defaultModel),
    normalizedEngine
  );
  const normalizedLocalBaselineBaseUrl = normalizeLocalRuntimeBaseUrl(
    normalizeConfiguredValue(localBaseline.baseUrl, DEFAULT_LOCAL_RUNTIME_BASELINE.baseUrl),
    localBaseline.engine
  );
  const normalizedLocalBaselineModel = stripLocalRuntimeModelRef(localBaseline.defaultModel);
  const normalizedBaselineDefaultModel = normalizeConfiguredValue(
    baseline.defaultModel,
    formatLocalRuntimeModelRef(normalizedLocalBaselineModel, localBaseline.engine)
  );
  const normalizedBaselineEngine = normalizeConfiguredValue(localBaseline.engine, DEFAULT_LOCAL_RUNTIME_BASELINE.engine);

  const changes: Record<string, unknown> = {};
  if (normalizedDefaultModel !== normalizedBaselineDefaultModel) {
    changes.default_model = normalizedDefaultModel;
  }
  if (runtimeFlavor === "local-orchestration" && normalizedBaseUrl !== normalizedLocalBaselineBaseUrl) {
    changes.local_orchestration_base_url = normalizedBaseUrl;
  }
  if (stripLocalRuntimeModelRef(normalizedDefaultModel) !== normalizedLocalBaselineModel) {
    changes.local_orchestration_model = stripLocalRuntimeModelRef(normalizedDefaultModel);
  }
  if (runtimeFlavor === "ollama") {
    if (normalizedBaseUrl !== normalizedLocalBaselineBaseUrl) {
      changes.ollama_base_url = normalizedBaseUrl;
    }
    if (stripLocalRuntimeModelRef(normalizedDefaultModel) !== normalizedLocalBaselineModel) {
      changes.ollama_default_model = stripLocalRuntimeModelRef(normalizedDefaultModel);
    }
  }
  if (runtimeFlavor === "lm-studio") {
    if (normalizedBaseUrl !== normalizedLocalBaselineBaseUrl) {
      changes.lm_studio_base_url = normalizedBaseUrl;
    }
    if (stripLocalRuntimeModelRef(normalizedDefaultModel) !== normalizedLocalBaselineModel) {
      changes.lm_studio_default_model = stripLocalRuntimeModelRef(normalizedDefaultModel);
    }
  }
  if (normalizedEngine !== normalizedBaselineEngine) {
    changes.local_orchestration_engine = normalizedEngine;
  }
  return changes;
}

export function buildModelConnectionConfigChanges(
  selectedPresetId: string,
  form: ModelConnectionForm,
  baseline: ModelConnectionBaseline,
  localBaseline: LocalRuntimeBaseline
): Record<string, unknown> {
  if (selectedPresetId === "local-runtime") {
    return buildLocalRuntimeConfigChanges(form, baseline, localBaseline);
  }
  return buildOpenRouterConfigChanges(form, baseline);
}

export function normalizeOllamaBaseUrl(baseUrl: string): string {
  const trimmed = baseUrl.trim().replace(/\/+$/, "");
  return trimmed.toLowerCase().endsWith("/v1") ? trimmed.slice(0, -3).replace(/\/+$/, "") : trimmed;
}

export function normalizeLmStudioBaseUrl(baseUrl: string): string {
  const trimmed = baseUrl.trim().replace(/\/+$/, "");
  if (!trimmed || trimmed.toLowerCase().endsWith("/v1")) {
    return trimmed;
  }
  return `${trimmed}/v1`;
}

export function normalizeLocalRuntimeBaseUrl(baseUrl: string, engine = DEFAULT_LOCAL_RUNTIME_BASELINE.engine): string {
  const runtimeFlavor = getLocalRuntimeFlavor(engine);
  if (runtimeFlavor === "ollama") {
    return normalizeOllamaBaseUrl(baseUrl);
  }
  if (runtimeFlavor === "lm-studio") {
    return normalizeLmStudioBaseUrl(baseUrl);
  }
  const trimmed = baseUrl.trim().replace(/\/+$/, "");
  if (!trimmed || trimmed.toLowerCase().endsWith("/v1")) {
    return trimmed;
  }
  return `${trimmed}/v1`;
}

export function formatOllamaModelRef(modelName: string): string {
  const trimmed = modelName.trim();
  return trimmed.startsWith("ollama/") ? trimmed : `ollama/${trimmed}`;
}

export function stripOllamaModelRef(modelRef: string): string {
  const trimmed = modelRef.trim();
  return trimmed.startsWith("ollama/") ? trimmed.slice("ollama/".length) : trimmed;
}

export function formatLmStudioModelRef(modelName: string): string {
  const trimmed = modelName.trim();
  return trimmed.startsWith("lmstudio/") ? trimmed : `lmstudio/${trimmed}`;
}

export function stripLmStudioModelRef(modelRef: string): string {
  const trimmed = modelRef.trim();
  return trimmed.startsWith("lmstudio/") ? trimmed.slice("lmstudio/".length) : trimmed;
}

export function formatLocalRuntimeModelRef(
  modelName: string,
  engine = DEFAULT_LOCAL_RUNTIME_BASELINE.engine
): string {
  const trimmed = modelName.trim();
  if (!trimmed) {
    return trimmed;
  }
  const runtimeFlavor = getLocalRuntimeFlavor(engine);
  if (runtimeFlavor === "ollama") {
    return formatOllamaModelRef(stripLocalRuntimeModelRef(trimmed));
  }
  if (runtimeFlavor === "lm-studio") {
    return formatLmStudioModelRef(stripLocalRuntimeModelRef(trimmed));
  }
  return trimmed.startsWith("llamacpp/") ? trimmed : `llamacpp/${stripLocalRuntimeModelRef(trimmed)}`;
}

export function stripLocalRuntimeModelRef(modelRef: string): string {
  const trimmed = modelRef.trim();
  if (trimmed.startsWith("llamacpp/")) {
    return trimmed.slice("llamacpp/".length);
  }
  if (trimmed.startsWith("ollama/")) {
    return trimmed.slice("ollama/".length);
  }
  if (trimmed.startsWith("lmstudio/")) {
    return trimmed.slice("lmstudio/".length);
  }
  return trimmed;
}

export function getModelReadinessLabel(
  hasCredentials: boolean,
  hasStoredKey: boolean,
  defaultModel: string,
  probeSucceeded: boolean
): string {
  if (!hasCredentials) {
    return "Connect engine access";
  }
  if (!hasStoredKey) {
    return "Add provider key";
  }
  if (!defaultModel.trim()) {
    return "Choose a model";
  }
  return probeSucceeded ? "Ready for workflows" : "Test connection";
}
