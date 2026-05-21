export interface OpenRouterModelEntry {
  id: string
  name: string
  description: string
  provider: string
  vendor: string
  contextLength: number | null
  maxCompletionTokens: number | null
  promptPrice: string | null
  completionPrice: string | null
  requestPrice: string | null
  imagePrice: string | null
  capabilities: string[]
  moderated: boolean
  isFree: boolean
  detailsPath: string
}

export interface OpenRouterRecommendedModel {
  id: string
  name: string
  description: string
  badgeLabel: string
  isStableDefault: boolean
}

export const OPENROUTER_STABLE_DEFAULT_MODEL = "openrouter/qwen/qwen3-coder-flash"

export const OPENROUTER_RECOMMENDED_MODELS: OpenRouterRecommendedModel[] = [
  {
    id: OPENROUTER_STABLE_DEFAULT_MODEL,
    name: "Qwen3 Coder Flash",
    description: "Current stable default and fastest verified recovery pick.",
    badgeLabel: "Stable default",
    isStableDefault: true
  },
  {
    id: "openrouter/qwen/qwen3-coder-30b-a3b-instruct",
    name: "Qwen3 Coder 30B A3B Instruct",
    description: "Known-working larger instruct model for higher-capacity turns.",
    badgeLabel: "Known working",
    isStableDefault: false
  },
  {
    id: "openrouter/qwen/qwen3-32b",
    name: "Qwen3 32B",
    description: "Known-working Qwen option for general chat and coding tasks.",
    badgeLabel: "Known working",
    isStableDefault: false
  }
]

const EXPLICIT_PROVIDER_MODEL_PREFIXES = new Set([
  "airllm",
  "llamacpp",
  "lmstudio",
  "ollama",
  "openai",
  "openrouter"
])

export function toOpenRouterModelRef(modelId: string): string {
  const normalized = modelId.trim()
  if (!normalized) {
    return ""
  }
  return normalized.startsWith("openrouter/") ? normalized : `openrouter/${normalized}`
}

export function normalizeLikelyOpenRouterModelRef(modelId: string): string {
  const normalized = modelId.trim()
  if (!normalized) {
    return ""
  }
  if (normalized === "auto") {
    return "openrouter/auto"
  }
  if (!normalized.includes("/") || normalized.startsWith("openrouter/")) {
    return normalized
  }

  const [prefix] = normalized.split("/", 1)
  return EXPLICIT_PROVIDER_MODEL_PREFIXES.has(prefix) ? normalized : `openrouter/${normalized}`
}

const OPENROUTER_RECOMMENDED_MODELS_BY_ID = new Map(
  OPENROUTER_RECOMMENDED_MODELS.map((model) => [toOpenRouterModelRef(model.id), model])
)

export function getOpenRouterRecommendedModel(modelId: string): OpenRouterRecommendedModel | null {
  const normalized = toOpenRouterModelRef(modelId)
  if (!normalized) {
    return null
  }

  return OPENROUTER_RECOMMENDED_MODELS_BY_ID.get(normalized) ?? null
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {}
}

function readString(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function readNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value
  }

  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) {
      return parsed
    }
  }

  return null
}

function readStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === "string" && item.trim() !== "")
  }

  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .filter(([, enabled]) => enabled === true)
      .map(([key]) => key)
  }

  return []
}

function uniqueStrings(values: Array<string | null | undefined>): string[] {
  return Array.from(
    new Set(
      values
        .flatMap((value) => (value ? [value] : []))
        .map((value) => value.trim())
        .filter(Boolean)
    )
  )
}

function formatPerMillionPrice(value: unknown): string | null {
  const numericValue = readNumber(value)
  if (numericValue === null) {
    return null
  }

  if (numericValue === 0) {
    return "Free"
  }

  const scaledValue = numericValue * 1_000_000
  const fractionDigits = scaledValue >= 1 ? 2 : scaledValue >= 0.01 ? 4 : 6
  return `$${scaledValue.toFixed(fractionDigits)}/M`
}

function formatUnitPrice(value: unknown, unit: string): string | null {
  const numericValue = readNumber(value)
  if (numericValue === null) {
    return null
  }

  if (numericValue === 0) {
    return "Free"
  }

  return `$${numericValue.toFixed(numericValue >= 1 ? 2 : 4)}/${unit}`
}

function inferVendor(modelId: string): string {
  const segments = modelId.split("/").filter(Boolean)
  if (segments.length >= 2 && segments[0] === "openrouter") {
    return segments[1]
  }
  return ""
}

export function formatOpenRouterNumber(value: number | null): string | null {
  if (value === null) {
    return null
  }

  return new Intl.NumberFormat().format(value)
}

export function parseOpenRouterModels(data: unknown): OpenRouterModelEntry[] {
  const root = asRecord(data)
  const models = Array.isArray(root.data)
    ? root.data
    : Array.isArray(root.models)
      ? root.models
      : Array.isArray(data)
        ? data
        : []

  return models
    .map((model) => {
      const rawModel = asRecord(model)
      const architecture = asRecord(rawModel.architecture)
      const topProvider = asRecord(rawModel.top_provider)
      const pricing = asRecord(rawModel.pricing)
      const rawModelId = readString(rawModel.id) || readString(rawModel.slug)
      if (!rawModelId) {
        return null
      }
      const modelId = toOpenRouterModelRef(rawModelId)

      const moderated = rawModel.moderated === true || topProvider.is_moderated === true
      const promptPrice = formatPerMillionPrice(pricing.prompt)
      const completionPrice = formatPerMillionPrice(pricing.completion)
      const requestPrice = formatUnitPrice(pricing.request, "request")
      const imagePrice = formatUnitPrice(pricing.image, "image")

      return {
        id: modelId,
        name: readString(rawModel.name) || rawModelId,
        description: readString(rawModel.description),
        provider:
          readString(rawModel.provider) ||
          readString(topProvider.provider) ||
          readString(topProvider.slug) ||
          readString(topProvider.name),
        vendor: readString(rawModel.vendor) || inferVendor(modelId),
        contextLength:
          readNumber(rawModel.context_length) ?? readNumber(topProvider.context_length),
        maxCompletionTokens:
          readNumber(rawModel.max_completion_tokens) ??
          readNumber(topProvider.max_completion_tokens),
        promptPrice,
        completionPrice,
        requestPrice,
        imagePrice,
        capabilities: uniqueStrings([
          ...readStringList(rawModel.capabilities),
          ...readStringList(rawModel.supported_parameters),
          ...readStringList(rawModel.input_modalities).map((value) => `input:${value}`),
          ...readStringList(rawModel.output_modalities).map((value) => `output:${value}`),
          readString(architecture.modality),
          readString(architecture.instruct_type),
          moderated ? "moderated" : null
        ]).slice(0, 8),
        moderated,
        isFree:
          rawModel.is_free === true ||
          promptPrice === "Free" ||
          completionPrice === "Free" ||
          requestPrice === "Free" ||
          imagePrice === "Free",
        detailsPath: readString(rawModel.details_path)
      }
    })
    .filter((model): model is OpenRouterModelEntry => model !== null)
}

export function filterOpenRouterModels(
  models: OpenRouterModelEntry[],
  query: string
): OpenRouterModelEntry[] {
  const normalizedQuery = query.trim().toLowerCase()
  if (!normalizedQuery) {
    return models
  }

  return models.filter((model) => {
    const haystack = [
      model.id,
      model.name,
      model.description,
      model.vendor,
      model.provider,
      ...model.capabilities
    ]
      .join(" ")
      .toLowerCase()

    return haystack.includes(normalizedQuery)
  })
}
