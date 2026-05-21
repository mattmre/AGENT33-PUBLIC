import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../lib/api";
import {
  filterOpenRouterModels,
  formatOpenRouterNumber,
  normalizeLikelyOpenRouterModelRef,
  parseOpenRouterModels,
  type OpenRouterModelEntry
} from "../../lib/openrouterModels";
import {
  asRecord,
  extractResultMessage,
  readNumber,
  readString,
  readStringArray
} from "../../lib/valueReaders";
import type { ApiResult } from "../../types";
import { ModelCapabilityBadges } from "./ModelCapabilityBadges";
import {
  ProviderModelHealthSummary,
  type LocalModelHealth,
  type LocalModelHealthState,
  type LocalProviderHealth,
  type LocalProviderHealthState
} from "./ProviderModelHealthSummary";
import { ProviderPresetSelector } from "./ProviderPresetSelector";
import {
  DEFAULT_LOCAL_RUNTIME_BASELINE,
  DEFAULT_MODEL_CONNECTION_BASELINE,
  buildModelConnectionConfigChanges,
  buildOpenRouterProbePayload,
  formatLocalRuntimeModelRef,
  formatLmStudioModelRef,
  formatOllamaModelRef,
  getLocalRuntimeFlavor,
  getModelReadinessLabel,
  normalizeLocalRuntimeBaseUrl,
  normalizeLmStudioBaseUrl,
  normalizeOllamaBaseUrl,
  normalizeConfiguredValue,
  stripLocalRuntimeModelRef,
  stripLmStudioModelRef,
  stripOllamaModelRef,
  type LocalRuntimeBaseline,
  type ModelConnectionBaseline,
  type ModelConnectionForm
} from "./helpers";
import {
  PROVIDER_PRESETS,
  applyProviderPresetToForm,
  getProviderPreset,
  inferProviderPresetId,
  type ProviderPreset,
  type ProviderPresetId
} from "./presets";

interface ModelConnectionWizardPanelProps {
  token: string;
  apiKey: string;
  onOpenSetup: () => void;
  onOpenWorkflowCatalog: () => void;
  onResult: (label: string, result: ApiResult) => void;
}

type StatusTone = "info" | "success" | "warning" | "error";

interface StatusMessage {
  tone: StatusTone;
  message: string;
}

interface ConfigSnapshot {
  baseline: ModelConnectionBaseline;
  localRuntimeConfig: LocalRuntimeBaseline;
  hasConfiguredLocalRuntime: boolean;
  hasStoredKey: boolean;
  storedKeyHint: string;
  localRuntimeBaseUrls: LocalRuntimeBaseUrls;
}

interface LocalRuntimeBaseUrls {
  ollama: string;
  lmStudio: string;
  localOrchestration: string;
}

interface OllamaModelEntry {
  name: string;
  size: number | null;
  parameterSize: string;
  quantizationLevel: string;
}

interface OllamaRuntimeStatus {
  state: "available" | "empty" | "unavailable" | "error";
  ok: boolean;
  baseUrl: string;
  message: string;
  models: OllamaModelEntry[];
}

interface LMStudioModelEntry {
  name: string;
  ownedBy: string;
  contextLength: number | null;
}

interface LMStudioRuntimeStatus {
  state: "available" | "empty" | "unavailable" | "error";
  ok: boolean;
  baseUrl: string;
  message: string;
  models: LMStudioModelEntry[];
}

interface LoadLocalModelHealthOptions {
  ollamaBaseUrl?: string;
  lmStudioBaseUrl?: string;
  localOrchestrationBaseUrl?: string;
}

function buildConfigSnapshot(data: unknown): ConfigSnapshot {
  const root = asRecord(data);
  const groups = asRecord(root.groups);
  const llm = asRecord(groups.llm);
  const ollama = asRecord(groups.ollama);
  const lmStudio = asRecord(groups.lm_studio);
  const localOrchestration = asRecord(groups.local_orchestration);
  const localOrchestrationModel = readString(localOrchestration.local_orchestration_model);
  const localOrchestrationEngine = readString(localOrchestration.local_orchestration_engine);
  const localOrchestrationBaseUrl = readString(localOrchestration.local_orchestration_base_url);
  const localRuntimeFlavor = getLocalRuntimeFlavor(localOrchestrationEngine);
  const effectiveLocalRuntimeBaseUrl =
    localRuntimeFlavor === "ollama"
      ? readString(ollama.ollama_base_url) || localOrchestrationBaseUrl
      : localRuntimeFlavor === "lm-studio"
        ? readString(lmStudio.lm_studio_base_url) || localOrchestrationBaseUrl
        : localOrchestrationBaseUrl;
  const effectiveLocalRuntimeModel =
    localOrchestrationModel ||
    (localRuntimeFlavor === "ollama"
      ? readString(ollama.ollama_default_model)
      : localRuntimeFlavor === "lm-studio"
        ? readString(lmStudio.lm_studio_default_model)
        : "");
  const hasConfiguredLocalRuntime =
    localOrchestrationModel.trim() !== "" ||
    localOrchestrationEngine.trim() !== "" ||
    effectiveLocalRuntimeBaseUrl.trim() !== "";
  const effectiveDefaultModel =
    readString(llm.default_model) ||
    (localOrchestrationEngine && effectiveLocalRuntimeModel
      ? formatLocalRuntimeModelRef(effectiveLocalRuntimeModel, localOrchestrationEngine)
      : readString(ollama.ollama_default_model));
  const normalizedDefaultModel =
    hasConfiguredLocalRuntime &&
    effectiveLocalRuntimeModel.trim() !== "" &&
    (
      effectiveDefaultModel.trim().toLowerCase() === effectiveLocalRuntimeModel.trim().toLowerCase() ||
      effectiveDefaultModel.trim().toLowerCase() ===
        formatLocalRuntimeModelRef(effectiveLocalRuntimeModel, localOrchestrationEngine).trim().toLowerCase()
    )
      ? formatLocalRuntimeModelRef(effectiveLocalRuntimeModel, localOrchestrationEngine)
      : normalizeLikelyOpenRouterModelRef(effectiveDefaultModel);
  const storedKeyHint =
    readString(llm.openrouter_api_key) || readString(llm.openrouter_api_key_redacted);

  return {
    baseline: {
      defaultModel: normalizedDefaultModel || DEFAULT_MODEL_CONNECTION_BASELINE.defaultModel,
      baseUrl: readString(llm.openrouter_base_url) || DEFAULT_MODEL_CONNECTION_BASELINE.baseUrl,
      siteUrl: readString(llm.openrouter_site_url) || DEFAULT_MODEL_CONNECTION_BASELINE.siteUrl,
      appName: readString(llm.openrouter_app_name) || DEFAULT_MODEL_CONNECTION_BASELINE.appName,
      appCategory:
        readString(llm.openrouter_app_category) || DEFAULT_MODEL_CONNECTION_BASELINE.appCategory,
      localEngine:
        readString(localOrchestration.local_orchestration_engine) ||
        DEFAULT_MODEL_CONNECTION_BASELINE.localEngine
    },
    localRuntimeConfig: {
      baseUrl: effectiveLocalRuntimeBaseUrl || DEFAULT_LOCAL_RUNTIME_BASELINE.baseUrl,
      defaultModel: effectiveLocalRuntimeModel || DEFAULT_LOCAL_RUNTIME_BASELINE.defaultModel,
      engine: localOrchestrationEngine || DEFAULT_LOCAL_RUNTIME_BASELINE.engine
    },
    hasConfiguredLocalRuntime,
    hasStoredKey: storedKeyHint.trim() !== "",
    storedKeyHint,
    localRuntimeBaseUrls: {
      ollama: readString(ollama.ollama_base_url),
      lmStudio: readString(lmStudio.lm_studio_base_url),
      localOrchestration: effectiveLocalRuntimeBaseUrl
    }
  };
}

function inferPresetIdFromSnapshot(snapshot: ConfigSnapshot): ProviderPresetId {
  const defaultModel = snapshot.baseline.defaultModel.trim().toLowerCase();
  const localRuntimeModel = snapshot.localRuntimeConfig.defaultModel.trim().toLowerCase();
  const localRuntimeModelRef = formatLocalRuntimeModelRef(
    snapshot.localRuntimeConfig.defaultModel,
    snapshot.localRuntimeConfig.engine
  )
    .trim()
    .toLowerCase();
  if (
    snapshot.hasConfiguredLocalRuntime &&
    (
      defaultModel.startsWith("llamacpp/") ||
      defaultModel === localRuntimeModel ||
      defaultModel === localRuntimeModelRef
    )
  ) {
    return "local-runtime";
  }
  if (defaultModel.startsWith("ollama/")) {
    return "ollama";
  }
  if (defaultModel.startsWith("lmstudio/")) {
    return "lm-studio";
  }
  return inferProviderPresetId(snapshot.baseline.baseUrl, {
    localRuntimeBaseUrl: snapshot.localRuntimeConfig.baseUrl
  });
}

function renderStatus(status: StatusMessage | null): JSX.Element | null {
  if (status === null) {
    return null;
  }
  return (
    <div className={`model-wizard-status model-wizard-status--${status.tone}`} role={status.tone === "error" ? "alert" : "status"}>
      {status.message}
    </div>
  );
}

function parseOllamaRuntimeStatus(data: unknown): OllamaRuntimeStatus {
  const root = asRecord(data);
  const models = Array.isArray(root.models)
    ? root.models.map(parseOllamaModel).filter((model): model is OllamaModelEntry => model !== null)
    : [];
  const state = readString(root.state);
  const normalizedState =
    state === "available" || state === "empty" || state === "unavailable" || state === "error"
      ? state
      : "error";

  return {
    state: normalizedState,
    ok: root.ok === true,
    baseUrl: readString(root.base_url),
    message: readString(root.message) || "Could not read Ollama status.",
    models
  };
}

function parseOllamaModel(data: unknown): OllamaModelEntry | null {
  const root = asRecord(data);
  const name = readString(root.name);
  if (!name) {
    return null;
  }
  const details = asRecord(root.details);
  return {
    name,
    size: readNumber(root.size),
    parameterSize: readString(details.parameter_size),
    quantizationLevel: readString(details.quantization_level)
  };
}

function parseLMStudioRuntimeStatus(data: unknown): LMStudioRuntimeStatus {
  const root = asRecord(data);
  const models = Array.isArray(root.models)
    ? root.models
        .map(parseLMStudioModel)
        .filter((model): model is LMStudioModelEntry => model !== null)
    : [];
  const state = readString(root.state);
  const normalizedState =
    state === "available" || state === "empty" || state === "unavailable" || state === "error"
      ? state
      : "error";

  return {
    state: normalizedState,
    ok: root.ok === true,
    baseUrl: readString(root.base_url),
    message: readString(root.message) || "Could not read LM Studio status.",
    models
  };
}

function parseLMStudioModel(data: unknown): LMStudioModelEntry | null {
  const root = asRecord(data);
  const name = readString(root.name) || readString(root.id);
  if (!name) {
    return null;
  }
  return {
    name,
    ownedBy: readString(root.owned_by),
    contextLength: readNumber(root.context_length)
  };
}

function parseLocalModelHealth(data: unknown): LocalModelHealth {
  const root = asRecord(data);
  const providers = Array.isArray(root.providers)
    ? root.providers
        .map(parseLocalProviderHealth)
        .filter((provider): provider is LocalProviderHealth => provider !== null)
    : [];
  const state = readString(root.overall_state);
  const overallState: LocalModelHealthState =
    state === "ready" || state === "needs_attention" || state === "unavailable"
      ? state
      : "unavailable";

  return {
    overallState,
    summary: readString(root.summary) || "Local model health could not be summarized.",
    readyProviderCount: readNumber(root.ready_provider_count) ?? 0,
    attentionProviderCount: readNumber(root.attention_provider_count) ?? 0,
    totalModelCount: readNumber(root.total_model_count) ?? 0,
    providers
  };
}

function parseLocalProviderHealth(data: unknown): LocalProviderHealth | null {
  const root = asRecord(data);
  const provider = readString(root.provider);
  if (
    provider !== "ollama" &&
    provider !== "lm-studio" &&
    provider !== "local-orchestration"
  ) {
    return null;
  }
  const state = readString(root.state);
  const normalizedState: LocalProviderHealthState =
    state === "available" || state === "empty" || state === "unavailable" || state === "error"
      ? state
      : "error";

  return {
    provider,
    label:
      readString(root.label) ||
      (provider === "ollama"
        ? "Ollama"
        : provider === "lm-studio"
          ? "LM Studio"
          : "Startup runtime"),
    state: normalizedState,
    ok: root.ok === true,
    baseUrl: readString(root.base_url),
    defaultModel: readString(root.default_model),
    modelCount: readNumber(root.model_count) ?? 0,
    message: readString(root.message) || "Status unavailable.",
    action: readString(root.action) || "Refresh local health after checking this runtime."
  };
}

function formatModelSize(size: number | null): string {
  if (size === null || size <= 0) {
    return "size unknown";
  }
  const gib = size / 1024 ** 3;
  return `${gib.toFixed(gib >= 10 ? 0 : 1)} GB`;
}

export function ModelConnectionWizardPanel({
  token,
  apiKey,
  onOpenSetup,
  onOpenWorkflowCatalog,
  onResult
}: ModelConnectionWizardPanelProps): JSX.Element {
  const [form, setForm] = useState<ModelConnectionForm>({
    ...DEFAULT_MODEL_CONNECTION_BASELINE,
    apiKey: "",
    writeToEnvFile: true,
    removeStoredKey: false
  });
  const [baseline, setBaseline] = useState<ModelConnectionBaseline>(
    DEFAULT_MODEL_CONNECTION_BASELINE
  );
  const [localRuntimeConfig, setLocalRuntimeConfig] = useState<LocalRuntimeBaseline>(
    DEFAULT_LOCAL_RUNTIME_BASELINE
  );
  const [hasStoredKey, setHasStoredKey] = useState(false);
  const [storedKeyHint, setStoredKeyHint] = useState("");
  const [localRuntimeBaseUrls, setLocalRuntimeBaseUrls] = useState<LocalRuntimeBaseUrls>({
    ollama: "",
    lmStudio: "",
    localOrchestration: ""
  });
  const [models, setModels] = useState<OpenRouterModelEntry[]>([]);
  const [ollamaStatus, setOllamaStatus] = useState<OllamaRuntimeStatus | null>(null);
  const [lmStudioStatus, setLMStudioStatus] = useState<LMStudioRuntimeStatus | null>(null);
  const [localModelHealth, setLocalModelHealth] = useState<LocalModelHealth | null>(null);
  const [modelSearch, setModelSearch] = useState("");
  const [selectedPresetId, setSelectedPresetId] = useState<ProviderPresetId>("openrouter");
  const [loadStatus, setLoadStatus] = useState<StatusMessage>({
    tone: "info",
    message: "Loading model connection status..."
  });
  const [saveStatus, setSaveStatus] = useState<StatusMessage | null>(null);
  const [probeStatus, setProbeStatus] = useState<StatusMessage | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isProbing, setIsProbing] = useState(false);
  const [isLoadingOllama, setIsLoadingOllama] = useState(false);
  const [isLoadingLMStudio, setIsLoadingLMStudio] = useState(false);
  const [isLoadingLocalHealth, setIsLoadingLocalHealth] = useState(false);

  const hasCredentials = token.trim() !== "" || apiKey.trim() !== "";
  const effectiveHasKey = form.removeStoredKey ? false : hasStoredKey || form.apiKey.trim() !== "";
  const selectedPreset = getProviderPreset(selectedPresetId) ?? PROVIDER_PRESETS[0];
  const providerAccessReady = selectedPreset.needsApiKey ? effectiveHasKey : true;
  const probeSucceeded = probeStatus?.tone === "success";
  const readinessLabel = getModelReadinessLabel(
    hasCredentials,
    providerAccessReady,
    form.defaultModel,
    probeSucceeded
  );
  const freeOpenRouterModels = useMemo(
    () => models.filter((model) => model.isFree).slice(0, 4),
    [models]
  );
  const filteredModels = useMemo(
    () => filterOpenRouterModels(models, modelSearch).slice(0, 8),
    [modelSearch, models]
  );
  const ollamaModels = ollamaStatus?.models ?? [];
  const liveOllamaModelRefs = ollamaModels.map((model) => formatOllamaModelRef(model.name));
  const lmStudioModels = lmStudioStatus?.models ?? [];
  const liveLMStudioModelRefs = lmStudioModels.map((model) => formatLmStudioModelRef(model.name));
  const localRuntimeProvider =
    localModelHealth?.providers.find((provider) => provider.provider === "local-orchestration") ??
    null;
  const isOllamaSelected = selectedPresetId === "ollama";
  const isLMStudioSelected = selectedPresetId === "lm-studio";
  const isLocalRuntimeSelected = selectedPresetId === "local-runtime";
  const isLocalModelCatalog = isOllamaSelected || isLMStudioSelected || isLocalRuntimeSelected;

  useEffect(() => {
    if (!hasCredentials) {
      setLoadStatus({
        tone: "warning",
        message: "Connect an operator token or API key before inspecting model settings."
      });
      return;
    }

    let cancelled = false;

    async function load(): Promise<void> {
      setLoadStatus({ tone: "info", message: "Loading model settings and catalog..." });
      const [configResult, catalogResult] = await Promise.allSettled([
        apiRequest({ method: "GET", path: "/v1/operator/config", token, apiKey }),
        apiRequest({ method: "GET", path: "/v1/openrouter/models", token, apiKey })
      ]);
      if (cancelled) {
        return;
      }

      if (configResult.status === "fulfilled") {
        onResult("Model Wizard - Config", configResult.value);
        if (configResult.value.ok) {
          const snapshot = buildConfigSnapshot(configResult.value.data);
          const inferredPresetId = inferPresetIdFromSnapshot(snapshot);
          setBaseline(snapshot.baseline);
          setLocalRuntimeConfig(snapshot.localRuntimeConfig);
          setLocalRuntimeBaseUrls(snapshot.localRuntimeBaseUrls);
          setForm((current) => ({
            ...current,
            ...snapshot.baseline,
            baseUrl:
              inferredPresetId === "ollama"
                ? snapshot.localRuntimeBaseUrls.ollama ||
                  getProviderPreset("ollama")?.baseUrlDefault ||
                  current.baseUrl
                : inferredPresetId === "lm-studio"
                  ? snapshot.localRuntimeBaseUrls.lmStudio ||
                    getProviderPreset("lm-studio")?.baseUrlDefault ||
                    current.baseUrl
                  : inferredPresetId === "local-runtime"
                    ? snapshot.localRuntimeConfig.baseUrl
                    : snapshot.baseline.baseUrl,
            defaultModel:
              inferredPresetId === "local-runtime"
                ? formatLocalRuntimeModelRef(
                    snapshot.localRuntimeConfig.defaultModel,
                    snapshot.localRuntimeConfig.engine
                  )
                : snapshot.baseline.defaultModel,
            localEngine:
              inferredPresetId === "local-runtime"
                ? snapshot.localRuntimeConfig.engine
                : snapshot.baseline.localEngine,
            apiKey: ""
          }));
          setSelectedPresetId(inferredPresetId);
          setHasStoredKey(snapshot.hasStoredKey);
          setStoredKeyHint(snapshot.storedKeyHint);
        }
      }

      if (catalogResult.status === "fulfilled") {
        onResult("Model Wizard - Catalog", catalogResult.value);
        if (catalogResult.value.ok) {
          setModels(parseOpenRouterModels(catalogResult.value.data));
        }
      }

      setLoadStatus({
        tone:
          configResult.status === "fulfilled" && configResult.value.ok ? "success" : "warning",
        message:
          configResult.status === "fulfilled" && configResult.value.ok
            ? "Model settings loaded. Choose a default and test the connection."
            : "Could not load current model settings; you can still prepare local form values."
      });
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [apiKey, hasCredentials, onResult, token]);

  function updateField<K extends keyof ModelConnectionForm>(
    key: K,
    value: ModelConnectionForm[K]
  ): void {
    setForm((current) => {
      const next = { ...current, [key]: value };
      if (key === "apiKey" && String(value).trim() !== "") {
        next.removeStoredKey = false;
      }
      return next;
    });
  }

  function selectProviderPreset(preset: ProviderPreset): void {
    setSelectedPresetId(preset.id);
    setForm((current) => {
      const next = applyProviderPresetToForm(current, preset);
      if (preset.id === "ollama" && localRuntimeBaseUrls.ollama.trim()) {
        next.baseUrl = localRuntimeBaseUrls.ollama;
      }
      if (preset.id === "lm-studio" && localRuntimeBaseUrls.lmStudio.trim()) {
        next.baseUrl = localRuntimeBaseUrls.lmStudio;
      }
      if (preset.id === "local-runtime") {
        next.baseUrl = localRuntimeBaseUrls.localOrchestration.trim()
          ? localRuntimeBaseUrls.localOrchestration
          : localRuntimeConfig.baseUrl;
        next.defaultModel = formatLocalRuntimeModelRef(
          localRuntimeConfig.defaultModel,
          localRuntimeConfig.engine
        );
        next.localEngine = localRuntimeConfig.engine;
      }
      return next;
    });
    setSaveStatus(null);
    setProbeStatus(null);
    setOllamaStatus(null);
    setLMStudioStatus(null);
  }

  function getOllamaBaseUrlOverride(): string | undefined {
    const preset = getProviderPreset("ollama");
    const current = normalizeOllamaBaseUrl(form.baseUrl);
    const configured = normalizeOllamaBaseUrl(
      localRuntimeBaseUrls.ollama || preset?.baseUrlDefault || ""
    );
    return current && current !== configured ? form.baseUrl : undefined;
  }

  function getLMStudioBaseUrlOverride(): string | undefined {
    const preset = getProviderPreset("lm-studio");
    const current = normalizeLmStudioBaseUrl(form.baseUrl);
    const configured = normalizeLmStudioBaseUrl(
      localRuntimeBaseUrls.lmStudio || preset?.baseUrlDefault || ""
    );
    return current && current !== configured ? form.baseUrl : undefined;
  }

  function getLocalRuntimeBaseUrlOverride(): string | undefined {
    const preset = getProviderPreset("local-runtime");
    const current = normalizeLocalRuntimeBaseUrl(form.baseUrl, form.localEngine);
    const configured = normalizeLocalRuntimeBaseUrl(
      localRuntimeBaseUrls.localOrchestration || preset?.baseUrlDefault || "",
      form.localEngine
    );
    return current && current !== configured ? form.baseUrl : undefined;
  }

  async function loadOllamaStatus(baseUrl?: string): Promise<OllamaRuntimeStatus | null> {
    if (!hasCredentials) {
      setOllamaStatus(null);
      return null;
    }
    setIsLoadingOllama(true);
    try {
      const result = await apiRequest({
        method: "GET",
        path: "/v1/ollama/status",
        token,
        apiKey,
        query: baseUrl ? { base_url: normalizeOllamaBaseUrl(baseUrl) } : undefined
      });
      onResult("Model Wizard - Ollama Status", result);
      const status = parseOllamaRuntimeStatus(result.data);
      setOllamaStatus(status);
      return status;
    } catch (error) {
      const status: OllamaRuntimeStatus = {
        state: "error",
        ok: false,
        baseUrl: baseUrl ? normalizeOllamaBaseUrl(baseUrl) : ollamaStatus?.baseUrl ?? "",
        message: error instanceof Error ? error.message : "Could not check Ollama status.",
        models: []
      };
      setOllamaStatus(status);
      return status;
    } finally {
      setIsLoadingOllama(false);
    }
  }

  async function loadLMStudioStatus(baseUrl?: string): Promise<LMStudioRuntimeStatus | null> {
    if (!hasCredentials) {
      setLMStudioStatus(null);
      return null;
    }
    setIsLoadingLMStudio(true);
    try {
      const result = await apiRequest({
        method: "GET",
        path: "/v1/lm-studio/status",
        token,
        apiKey,
        query: baseUrl ? { base_url: normalizeLmStudioBaseUrl(baseUrl) } : undefined
      });
      onResult("Model Wizard - LM Studio Status", result);
      const status = parseLMStudioRuntimeStatus(result.data);
      setLMStudioStatus(status);
      return status;
    } catch (error) {
      const status: LMStudioRuntimeStatus = {
        state: "error",
        ok: false,
        baseUrl: baseUrl ? normalizeLmStudioBaseUrl(baseUrl) : lmStudioStatus?.baseUrl ?? "",
        message: error instanceof Error ? error.message : "Could not check LM Studio status.",
        models: []
      };
      setLMStudioStatus(status);
      return status;
    } finally {
      setIsLoadingLMStudio(false);
    }
  }

  async function loadLocalModelHealth(
    options: LoadLocalModelHealthOptions = {}
  ): Promise<LocalModelHealth | null> {
    if (!hasCredentials) {
      setLocalModelHealth(null);
      return null;
    }
    const query: Record<string, string> = {};
    if (options.ollamaBaseUrl) {
      query.ollama_base_url = normalizeOllamaBaseUrl(options.ollamaBaseUrl);
    }
    if (options.lmStudioBaseUrl) {
      query.lm_studio_base_url = normalizeLmStudioBaseUrl(options.lmStudioBaseUrl);
    }
    if (options.localOrchestrationBaseUrl) {
      query.local_orchestration_base_url = normalizeLocalRuntimeBaseUrl(
        options.localOrchestrationBaseUrl,
        form.localEngine
      );
    }

    setIsLoadingLocalHealth(true);
    try {
      const result = await apiRequest({
        method: "GET",
        path: "/v1/model-health",
        token,
        apiKey,
        query: Object.keys(query).length > 0 ? query : undefined
      });
      onResult("Model Wizard - Local Model Health", result);
      const health = parseLocalModelHealth(result.data);
      setLocalModelHealth(health);
      return health;
    } catch (error) {
      const health: LocalModelHealth = {
        overallState: "unavailable",
        summary:
          error instanceof Error
            ? `Could not check local model health: ${error.message}`
            : "Could not check local model health. Confirm the engine is reachable.",
        readyProviderCount: 0,
        attentionProviderCount: 0,
        totalModelCount: 0,
        providers: []
      };
      setLocalModelHealth(health);
      return health;
    } finally {
      setIsLoadingLocalHealth(false);
    }
  }

  useEffect(() => {
    if (!hasCredentials) {
      setLocalModelHealth(null);
      return;
    }
    void loadLocalModelHealth();
    // Run once when engine credentials become available; manual refresh handles URL edits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasCredentials, token, apiKey]);

  useEffect(() => {
    if (!hasCredentials) {
      return;
    }
    if (selectedPresetId === "ollama") {
      void loadOllamaStatus(getOllamaBaseUrlOverride());
    }
    if (selectedPresetId === "lm-studio") {
      void loadLMStudioStatus(getLMStudioBaseUrlOverride());
    }
    if (selectedPresetId === "local-runtime") {
      void loadLocalModelHealth({
        localOrchestrationBaseUrl: getLocalRuntimeBaseUrlOverride()
      });
    }
    // Run when the operator enters a local runtime path; manual refresh handles base URL edits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasCredentials, selectedPresetId]);

  async function saveSettings(): Promise<void> {
    const changes = buildModelConnectionConfigChanges(
      selectedPresetId,
      form,
      baseline,
      localRuntimeConfig
    );
    if (Object.keys(changes).length === 0) {
      setSaveStatus({ tone: "info", message: "No model settings changed yet." });
      return;
    }
    setIsSaving(true);
    setSaveStatus({ tone: "info", message: "Saving model settings..." });
    try {
      const result = await apiRequest({
        method: "POST",
        path: "/v1/config/apply",
        token,
        apiKey,
        body: JSON.stringify({ changes, write_to_env_file: form.writeToEnvFile })
      });
      onResult("Model Wizard - Save", result);
      const payload = asRecord(result.data);
      const validationErrors = readStringArray(payload.validation_errors);
      const rejected = Array.isArray(payload.rejected)
        ? payload.rejected
            .filter((item): item is [string, string] => Array.isArray(item) && item.length >= 2)
            .map(([field, reason]) => `${field}: ${reason}`)
        : [];
      if (!result.ok || validationErrors.length > 0 || rejected.length > 0) {
        setSaveStatus({
          tone: "error",
          message:
            [...validationErrors, ...rejected].join(" ") ||
            extractResultMessage(result.data, "Could not save model settings.")
        });
        return;
      }

      const nextDefaultModel =
        selectedPresetId === "local-runtime"
          ? formatLocalRuntimeModelRef(
              stripLocalRuntimeModelRef(form.defaultModel),
              form.localEngine
            )
          : normalizeLikelyOpenRouterModelRef(form.defaultModel);
      const nextBaseline: ModelConnectionBaseline = {
        defaultModel: nextDefaultModel,
        baseUrl:
          selectedPresetId === "local-runtime"
            ? baseline.baseUrl
            : normalizeConfiguredValue(form.baseUrl, DEFAULT_MODEL_CONNECTION_BASELINE.baseUrl),
        siteUrl: normalizeConfiguredValue(form.siteUrl, DEFAULT_MODEL_CONNECTION_BASELINE.siteUrl),
        appName: normalizeConfiguredValue(form.appName, DEFAULT_MODEL_CONNECTION_BASELINE.appName),
        appCategory: normalizeConfiguredValue(
          form.appCategory,
          DEFAULT_MODEL_CONNECTION_BASELINE.appCategory
        ),
        localEngine:
          selectedPresetId === "local-runtime"
            ? normalizeConfiguredValue(form.localEngine, DEFAULT_LOCAL_RUNTIME_BASELINE.engine)
            : baseline.localEngine
      };
      setBaseline(nextBaseline);
      if (selectedPresetId === "local-runtime") {
        const nextLocalRuntimeConfig: LocalRuntimeBaseline = {
          baseUrl: normalizeLocalRuntimeBaseUrl(
            normalizeConfiguredValue(form.baseUrl, DEFAULT_LOCAL_RUNTIME_BASELINE.baseUrl),
            form.localEngine
          ),
          defaultModel:
            stripLocalRuntimeModelRef(form.defaultModel) || DEFAULT_LOCAL_RUNTIME_BASELINE.defaultModel,
          engine: normalizeConfiguredValue(
            form.localEngine,
            DEFAULT_LOCAL_RUNTIME_BASELINE.engine
          )
        };
        setLocalRuntimeConfig(nextLocalRuntimeConfig);
        setLocalRuntimeBaseUrls((current) => ({
          ...current,
          ollama:
            getLocalRuntimeFlavor(nextLocalRuntimeConfig.engine) === "ollama"
              ? nextLocalRuntimeConfig.baseUrl
              : current.ollama,
          lmStudio:
            getLocalRuntimeFlavor(nextLocalRuntimeConfig.engine) === "lm-studio"
              ? nextLocalRuntimeConfig.baseUrl
              : current.lmStudio,
          localOrchestration: nextLocalRuntimeConfig.baseUrl
        }));
        setForm((current) => ({
          ...current,
          defaultModel: formatLocalRuntimeModelRef(
            nextLocalRuntimeConfig.defaultModel,
            nextLocalRuntimeConfig.engine
          ),
          baseUrl: nextLocalRuntimeConfig.baseUrl,
          localEngine: nextLocalRuntimeConfig.engine,
          apiKey: "",
          removeStoredKey: false
        }));
      } else {
        setForm((current) => ({ ...current, ...nextBaseline, apiKey: "", removeStoredKey: false }));
      }
      setHasStoredKey(form.removeStoredKey ? false : form.apiKey.trim() !== "" || hasStoredKey);
      setStoredKeyHint(form.removeStoredKey ? "" : form.apiKey.trim() ? "configured" : storedKeyHint);
      setSaveStatus({ tone: "success", message: "Model settings saved." });
    } catch (error) {
      setSaveStatus({
        tone: "error",
        message: error instanceof Error ? error.message : "Could not save model settings."
      });
    } finally {
      setIsSaving(false);
    }
  }

  async function probeConnection(): Promise<void> {
    setIsProbing(true);
    setProbeStatus({ tone: "info", message: "Testing model connection..." });
    try {
      if (selectedPresetId === "ollama") {
        const status = await loadOllamaStatus(getOllamaBaseUrlOverride());
        const selectedModel = stripOllamaModelRef(form.defaultModel);
        const hasSelectedModel =
          status?.models.some((model) => model.name === selectedModel) ?? false;
        const ok = status?.ok === true && hasSelectedModel;
        setProbeStatus({
          tone: ok ? "success" : "error",
          message: ok
            ? `Ollama is ready at ${status.baseUrl}. Model: ${form.defaultModel}.`
            : status?.ok
              ? `Ollama is running, but ${selectedModel || "the selected model"} is not installed.`
              : status?.message ?? "Ollama connection failed."
        });
        return;
      }

      if (selectedPresetId === "lm-studio") {
        const status = await loadLMStudioStatus(getLMStudioBaseUrlOverride());
        const selectedModel = stripLmStudioModelRef(form.defaultModel);
        const hasSelectedModel =
          status?.models.some((model) => model.name === selectedModel) ?? false;
        const ok = status?.ok === true && hasSelectedModel;
        setProbeStatus({
          tone: ok ? "success" : "error",
          message: ok
            ? `LM Studio is ready at ${status.baseUrl}. Model: ${form.defaultModel}.`
            : status?.ok
              ? `LM Studio is running, but ${selectedModel || "the selected model"} is not listed.`
              : status?.message ?? "LM Studio connection failed."
        });
        return;
      }

      if (selectedPresetId === "local-runtime") {
        const health = await loadLocalModelHealth({
          localOrchestrationBaseUrl: getLocalRuntimeBaseUrlOverride()
        });
        const provider =
          health?.providers.find((item) => item.provider === "local-orchestration") ?? null;
        const selectedModel = stripLocalRuntimeModelRef(form.defaultModel);
        const configuredModel = stripLocalRuntimeModelRef(provider?.defaultModel ?? "");
        const ok = provider?.ok === true;
        setProbeStatus({
          tone: ok ? "success" : "error",
          message: ok
            ? `${provider?.label ?? "Startup runtime"} is ready at ${provider?.baseUrl ?? form.baseUrl}. ${
                configuredModel && configuredModel !== selectedModel
                  ? `Save settings to switch the configured startup model from ${configuredModel} to ${selectedModel}.`
                  : `Model: ${configuredModel || selectedModel || "configured local default"}.`
              }`
            : provider?.message ?? "Startup runtime connection failed."
        });
        return;
      }

      const result = await apiRequest({
        method: "POST",
        path: "/v1/openrouter/probe",
        token,
        apiKey,
        body: JSON.stringify(buildOpenRouterProbePayload(form))
      });
      onResult("Model Wizard - Probe", result);
      const payload = asRecord(result.data);
      const ok = result.ok && payload.ok !== false && !readString(payload.error);
      const latency = readNumber(payload.latency_ms) ?? readNumber(payload.duration_ms);
      const model = readString(payload.model) || readString(payload.default_model) || form.defaultModel;
      setProbeStatus({
        tone: ok ? "success" : "error",
        message: `${extractResultMessage(result.data, ok ? "Connection succeeded." : "Connection failed.")} Model: ${model}.${latency !== null ? ` Latency: ${Math.round(latency)}ms.` : ""}`
      });
    } catch (error) {
      setProbeStatus({
        tone: "error",
        message: error instanceof Error ? error.message : "Connection test failed."
      });
    } finally {
      setIsProbing(false);
    }
  }

  return (
    <section className="model-wizard-panel" aria-labelledby="model-wizard-title">
      <header className="model-wizard-hero">
        <div>
          <p className="eyebrow">Model Connection Wizard</p>
          <h2 id="model-wizard-title">Connect a model before you build</h2>
          <p>
            Pick {selectedPreset.name}, save a recommended model, test the connection, then launch
            a workflow with confidence.
          </p>
        </div>
        <div className="model-wizard-score">
          <strong>{readinessLabel}</strong>
          <span>
            {selectedPreset.needsApiKey
              ? hasStoredKey
                ? "Stored provider key configured"
                : "Provider key needed"
              : "Local path can run without a key"}
          </span>
        </div>
      </header>

      {!hasCredentials ? (
        <article className="onboarding-callout onboarding-callout-error">
          <h3>Connect engine access first</h3>
          <p>Add an API key or operator token so AGENT-33 can inspect and save model settings.</p>
          <button type="button" onClick={onOpenSetup}>Open integrations</button>
        </article>
      ) : null}

      {renderStatus(loadStatus)}

      <ProviderPresetSelector
        presets={PROVIDER_PRESETS}
        selectedPresetId={selectedPresetId}
        onSelectPreset={selectProviderPreset}
      />

      <ProviderModelHealthSummary
        health={localModelHealth}
        isLoading={isLoadingLocalHealth}
        hasCredentials={hasCredentials}
        selectedPresetId={selectedPresetId}
        selectedProviderName={selectedPreset.name}
        onRefresh={() =>
          void loadLocalModelHealth({
            ollamaBaseUrl: isOllamaSelected ? getOllamaBaseUrlOverride() : undefined,
            lmStudioBaseUrl: isLMStudioSelected ? getLMStudioBaseUrlOverride() : undefined,
            localOrchestrationBaseUrl: isLocalRuntimeSelected
              ? getLocalRuntimeBaseUrlOverride()
              : undefined
          })
        }
      />

      <div className="model-wizard-grid">
        <section className="model-wizard-card">
          <span>Step 1</span>
          <h3>Choose a recommended default</h3>
          <p>{selectedPreset.bestFor}. These picks are safe defaults for this provider path.</p>
          <div className="model-recommendation-list" role="group" aria-label="Recommended default models">
            {selectedPreset.recommendedModels.map((model) => (
              <button
                type="button"
                key={model.id}
                className={normalizeLikelyOpenRouterModelRef(form.defaultModel) === model.id ? "active" : ""}
                aria-pressed={normalizeLikelyOpenRouterModelRef(form.defaultModel) === model.id}
                aria-label={`Use ${model.name} as the default model`}
                onClick={() => updateField("defaultModel", model.id)}
              >
                <strong>{model.name}</strong>
                <small>{model.badgeLabel} · {model.description}</small>
                <ModelCapabilityBadges model={model} />
              </button>
            ))}
          </div>
          {isOllamaSelected ? (
            <div className="local-runtime-panel">
              <div>
                <strong>Local Ollama status</strong>
                <p>
                  {isLoadingOllama
                    ? "Checking Ollama..."
                    : ollamaStatus?.message ??
                      "Check whether Ollama is running and which models are installed."}
                </p>
              </div>
              <button
                type="button"
                onClick={() => void loadOllamaStatus(getOllamaBaseUrlOverride())}
                disabled={!hasCredentials || isLoadingOllama}
              >
                {isLoadingOllama ? "Checking..." : "Refresh Ollama"}
              </button>
              {ollamaModels.length > 0 ? (
                <div className="local-runtime-models" role="group" aria-label="Detected Ollama models">
                  {ollamaModels.map((model) => {
                    const modelRef = formatOllamaModelRef(model.name);
                    const meta = [
                      model.parameterSize,
                      model.quantizationLevel,
                      formatModelSize(model.size)
                    ].filter(Boolean).join(" · ");
                    return (
                      <button
                        type="button"
                        key={model.name}
                        className={form.defaultModel === modelRef ? "active" : ""}
                        aria-pressed={form.defaultModel === modelRef}
                        onClick={() => updateField("defaultModel", modelRef)}
                      >
                        <strong>{model.name}</strong>
                        <small>{meta || "Local Ollama model"}</small>
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>
          ) : null}
          {isLMStudioSelected ? (
            <div className="local-runtime-panel">
              <div>
                <strong>Local LM Studio status</strong>
                <p>
                  {isLoadingLMStudio
                    ? "Checking LM Studio..."
                    : lmStudioStatus?.message ??
                      "Check whether the LM Studio local server is running and listing models."}
                </p>
              </div>
              <button
                type="button"
                onClick={() => void loadLMStudioStatus(getLMStudioBaseUrlOverride())}
                disabled={!hasCredentials || isLoadingLMStudio}
              >
                {isLoadingLMStudio ? "Checking..." : "Refresh LM Studio"}
              </button>
              {lmStudioModels.length > 0 ? (
                <div className="local-runtime-models" role="group" aria-label="Detected LM Studio models">
                  {lmStudioModels.map((model) => {
                    const modelRef = formatLmStudioModelRef(model.name);
                    const meta = [
                      model.ownedBy,
                      model.contextLength ? `${formatOpenRouterNumber(model.contextLength)} context` : ""
                    ].filter(Boolean).join(" · ");
                    return (
                      <button
                        type="button"
                        key={model.name}
                        className={form.defaultModel === modelRef ? "active" : ""}
                        aria-pressed={form.defaultModel === modelRef}
                        onClick={() => updateField("defaultModel", modelRef)}
                      >
                        <strong>{model.name}</strong>
                        <small>{meta || "LM Studio local model"}</small>
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>
          ) : null}
          {isLocalRuntimeSelected ? (
            <div className="local-runtime-panel">
              <div>
                <strong>{localRuntimeProvider?.label ?? "Startup runtime status"}</strong>
                <p>
                  {isLoadingLocalHealth
                    ? "Checking the startup runtime..."
                    : localRuntimeProvider?.message ??
                      "Check whether the local orchestration server is running and serving a model."}
                </p>
              </div>
              <button
                type="button"
                onClick={() =>
                  void loadLocalModelHealth({
                    localOrchestrationBaseUrl: getLocalRuntimeBaseUrlOverride()
                  })
                }
                disabled={!hasCredentials || isLoadingLocalHealth}
              >
                {isLoadingLocalHealth ? "Checking..." : "Refresh startup runtime"}
              </button>
              {localRuntimeProvider ? (
                <div className="local-runtime-summary">
                  <strong>Configured startup model</strong>
                  <small>
                    {stripLocalRuntimeModelRef(localRuntimeProvider.defaultModel) ||
                      stripLocalRuntimeModelRef(form.defaultModel) ||
                      "Use the saved local orchestration model."}
                  </small>
                </div>
              ) : null}
            </div>
          ) : null}
        </section>

        <section className="model-wizard-card">
          <span>Step 2</span>
          <h3>Add provider access</h3>
          {selectedPreset.needsApiKey ? (
            <>
              <label>
                {selectedPreset.apiKeyLabel}
                <input
                  type="password"
                  value={form.apiKey}
                  onChange={(event) => updateField("apiKey", event.target.value)}
                  placeholder={hasStoredKey ? "Stored key already configured" : selectedPreset.apiKeyPlaceholder}
                />
              </label>
              <p className="model-wizard-field-hint">{selectedPreset.apiKeyHint}</p>
            </>
          ) : (
            <p className="model-wizard-field-hint">{selectedPreset.apiKeyHint}</p>
          )}
          <label>
            Default model
            <input
              value={form.defaultModel}
              onChange={(event) => updateField("defaultModel", event.target.value)}
              list="model-wizard-model-options"
            />
          </label>
          <datalist id="model-wizard-model-options">
            {isOllamaSelected
              ? liveOllamaModelRefs.map((modelRef) => (
                  <option key={modelRef} value={modelRef}>{stripOllamaModelRef(modelRef)}</option>
                ))
              : isLMStudioSelected
                ? liveLMStudioModelRefs.map((modelRef) => (
                    <option key={modelRef} value={modelRef}>{stripLmStudioModelRef(modelRef)}</option>
                  ))
              : isLocalRuntimeSelected
                ? [
                    <option key={form.defaultModel} value={form.defaultModel}>
                      {stripLocalRuntimeModelRef(form.defaultModel)}
                    </option>
                  ]
              : models.slice(0, 80).map((model) => (
                  <option key={model.id} value={model.id}>{model.name}</option>
                ))}
          </datalist>
          <label>
            Base URL
            <input
              value={form.baseUrl}
              onChange={(event) => {
                const nextBaseUrl = event.target.value;
                updateField("baseUrl", nextBaseUrl);
                const inferredPreset = inferProviderPresetId(nextBaseUrl, {
                  localRuntimeBaseUrl: localRuntimeConfig.baseUrl
                });
                const localRuntimePresetId =
                  getLocalRuntimeFlavor(form.localEngine) === "ollama"
                    ? "ollama"
                    : getLocalRuntimeFlavor(form.localEngine) === "lm-studio"
                      ? "lm-studio"
                      : "local-runtime";
                setSelectedPresetId(
                  selectedPresetId === "local-runtime" &&
                    (inferredPreset === "custom-openai" || inferredPreset === localRuntimePresetId)
                    ? "local-runtime"
                    : inferredPreset
                );
              }}
            />
          </label>
          {isLocalRuntimeSelected ? (
            <label>
              Runtime engine
              <select
                value={form.localEngine}
                onChange={(event) => {
                  const nextEngine = event.target.value;
                  const runtimeFlavor = getLocalRuntimeFlavor(nextEngine);
                  const nextBaseUrl =
                    runtimeFlavor === "ollama"
                      ? localRuntimeBaseUrls.ollama || form.baseUrl
                      : runtimeFlavor === "lm-studio"
                        ? localRuntimeBaseUrls.lmStudio || form.baseUrl
                        : localRuntimeBaseUrls.localOrchestration || form.baseUrl;
                  setForm((current) => ({
                    ...current,
                    localEngine: nextEngine,
                    baseUrl: nextBaseUrl,
                    defaultModel: formatLocalRuntimeModelRef(
                      stripLocalRuntimeModelRef(current.defaultModel),
                      nextEngine
                    )
                  }));
                }}
              >
                <option value="ollama">Ollama</option>
                <option value="lm-studio">LM Studio</option>
                <option value="llama.cpp">llama.cpp</option>
                <option value="vLLM">vLLM</option>
                <option value="TGI">TGI</option>
                <option value="openai-compatible">OpenAI-compatible local server</option>
              </select>
            </label>
          ) : null}
          <label className="model-wizard-checkbox">
            <input
              type="checkbox"
              checked={form.writeToEnvFile}
              onChange={(event) => updateField("writeToEnvFile", event.target.checked)}
            />
            Save to env file when supported
          </label>
          {selectedPreset.needsApiKey && hasStoredKey ? (
            <label className="model-wizard-checkbox">
              <input
                type="checkbox"
                checked={form.removeStoredKey}
                disabled={form.apiKey.trim() !== ""}
                onChange={(event) => updateField("removeStoredKey", event.target.checked)}
              />
              Remove stored OpenRouter key
            </label>
          ) : null}
          <div className="model-wizard-actions">
            <button type="button" onClick={() => void saveSettings()} disabled={!hasCredentials || isSaving}>
              {isSaving ? "Saving..." : "Save model settings"}
            </button>
          </div>
          {renderStatus(saveStatus)}
        </section>

        <section className="model-wizard-card">
          <span>Step 3</span>
          <h3>Test and launch</h3>
          <p>
            {isLocalRuntimeSelected
              ? "Test whether the startup runtime is reachable from the engine container, then launch a workflow against that local model."
              : `Test ${selectedPreset.name}. If it succeeds, open the workflow catalog and start from a packaged outcome.`}
          </p>
          <div className="model-wizard-actions">
            <button type="button" onClick={() => void probeConnection()} disabled={!hasCredentials || isProbing}>
              {isProbing ? "Testing..." : "Test connection"}
            </button>
            <button type="button" onClick={onOpenWorkflowCatalog}>
              Open workflow catalog
            </button>
          </div>
          {renderStatus(probeStatus)}
        </section>
      </div>

      <section className="model-catalog-preview" aria-labelledby="model-catalog-preview-title">
        <div className="outcome-section-head">
          <div>
            <p className="eyebrow">Model catalog</p>
            <h3 id="model-catalog-preview-title">
              {isOllamaSelected
                ? "Detected Ollama models"
                : isLMStudioSelected
                  ? "Detected LM Studio models"
                  : isLocalRuntimeSelected
                    ? "Configured startup runtime"
                  : "Available OpenRouter models"}
            </h3>
            <p>
              {isOllamaSelected
                ? "Use detected local models after starting Ollama. No prompts or secrets are sent during this check."
                : isLMStudioSelected
                  ? "Use detected local models after starting the LM Studio server. No prompts or secrets are sent during this check."
                  : isLocalRuntimeSelected
                    ? "Use the machine's startup model through the local orchestration server. This check only asks the runtime for metadata."
                : "Use search to find coding, free, long-context, or moderated model options."}
            </p>
          </div>
          {!isLocalModelCatalog ? (
            <label>
            Search models
            <input
              value={modelSearch}
              onChange={(event) => setModelSearch(event.target.value)}
              placeholder="coder, qwen, free, long context..."
            />
            </label>
          ) : null}
        </div>
        {!isLocalModelCatalog && freeOpenRouterModels.length > 0 ? (
          <div className="model-free-cloud-strip" role="group" aria-label="Free cloud model picks">
            {freeOpenRouterModels.map((model) => (
              <button type="button" key={model.id} onClick={() => updateField("defaultModel", model.id)}>
                <strong>{model.name}</strong>
                <small>
                  {model.contextLength
                    ? `${formatOpenRouterNumber(model.contextLength)} context`
                    : "Context unknown"}{" "}
                  · Free cloud option
                </small>
              </button>
            ))}
          </div>
        ) : null}
        <div className="model-catalog-grid">
          {isOllamaSelected
            ? ollamaModels.map((model) => {
                const modelRef = formatOllamaModelRef(model.name);
                return (
                  <button type="button" key={model.name} onClick={() => updateField("defaultModel", modelRef)}>
                    <strong>{model.name}</strong>
                    <span>{modelRef}</span>
                    <small>
                      {[model.parameterSize, model.quantizationLevel, formatModelSize(model.size)]
                        .filter(Boolean)
                        .join(" · ") || "Local Ollama model"}
                    </small>
                  </button>
                );
              })
            : isLMStudioSelected
              ? lmStudioModels.map((model) => {
                  const modelRef = formatLmStudioModelRef(model.name);
                  return (
                    <button type="button" key={model.name} onClick={() => updateField("defaultModel", modelRef)}>
                      <strong>{model.name}</strong>
                      <span>{modelRef}</span>
                      <small>
                        {[model.ownedBy, model.contextLength ? `${formatOpenRouterNumber(model.contextLength)} context` : ""]
                          .filter(Boolean)
                          .join(" · ") || "LM Studio local model"}
                      </small>
                    </button>
                  );
                })
            : isLocalRuntimeSelected
              ? [
                  <button
                    type="button"
                    key={form.defaultModel || "local-runtime"}
                    onClick={() =>
                      updateField(
                        "defaultModel",
                        localRuntimeProvider?.defaultModel || form.defaultModel
                      )
                    }
                  >
                    <strong>
                      {stripLocalRuntimeModelRef(localRuntimeProvider?.defaultModel || form.defaultModel) ||
                        "Configured startup model"}
                    </strong>
                    <span>{localRuntimeProvider?.defaultModel || form.defaultModel || "llamacpp/local-model"}</span>
                    <small>
                      {[
                        localRuntimeProvider?.label || form.localEngine,
                        localRuntimeProvider?.baseUrl || form.baseUrl,
                        localRuntimeProvider?.state === "available" ? "Reachable" : "Needs attention"
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </small>
                  </button>
                ]
            : filteredModels.map((model) => (
                <button type="button" key={model.id} onClick={() => updateField("defaultModel", model.id)}>
                  <strong>{model.name}</strong>
                  <span>{model.id}</span>
                  <ModelCapabilityBadges model={model} />
                  <small>
                    {model.contextLength ? `${formatOpenRouterNumber(model.contextLength)} context` : "Context unknown"}
                    {model.promptPrice ? ` · ${model.promptPrice} input` : ""}
                    {model.isFree ? " · Free option" : ""}
                  </small>
                </button>
              ))}
        </div>
      </section>
    </section>
  );
}
