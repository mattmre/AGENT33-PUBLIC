import { apiRequest } from "../../lib/api";
import type { OllamaQueryResponse, RagQueryResponse, RagUnavailableResult } from "./types";

/**
 * Call the engine's RAG pipeline via POST /v1/rag/query.
 *
 * Returns:
 *  - `RagQueryResponse` on success (HTTP 200)
 *  - `RagUnavailableResult` when the pipeline is not initialised (HTTP 503)
 *
 * Throws an `Error` for any other non-OK status so the caller can surface a
 * generic error rather than silently showing no results.
 */
export async function ragQuery(
  query: string,
  token?: string
): Promise<RagQueryResponse | RagUnavailableResult> {
  const result = await apiRequest({
    method: "POST",
    path: "/v1/rag/query",
    token,
    body: JSON.stringify({ query })
  });
  if (result.status === 503) {
    const body = result.data as { detail?: { detail?: string } } | null;
    const detail =
      body?.detail?.detail ?? "RAG pipeline not initialized";
    return { unavailable: true, detail } satisfies RagUnavailableResult;
  }
  if (!result.ok) {
    throw new Error(`RAG query failed: ${result.status}`);
  }
  return result.data as RagQueryResponse;
}

/**
 * Call a local Ollama-compatible server at *baseUrl* with *query*.
 * The default base URL matches the standard Ollama install path.
 */
export async function ollamaQuery(
  query: string,
  baseUrl = "http://localhost:11434",
  signal?: AbortSignal
): Promise<OllamaQueryResponse> {
  const response = await fetch(`${baseUrl}/v1/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "llama3.2",
      messages: [
        {
          role: "system",
          content: "You are a helpful assistant for AGENT33 setup and configuration."
        },
        { role: "user", content: query }
      ],
      stream: false
    }),
    signal
  });
  if (!response.ok) {
    throw new Error(`Ollama query failed: ${response.status}`);
  }
  const data = (await response.json()) as {
    choices?: { message?: { content?: string } }[];
  };
  return {
    text: data.choices?.[0]?.message?.content ?? "",
    sources: []
  };
}
