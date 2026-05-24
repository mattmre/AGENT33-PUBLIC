import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ollamaQuery, ragQuery } from "./ragApi";

// Mock the lib/api apiRequest so tests do not need a real HTTP server
vi.mock("../../lib/api", () => ({
  apiRequest: vi.fn(),
  getRuntimeConfig: () => ({ API_BASE_URL: "http://localhost:8000" })
}));

import { apiRequest } from "../../lib/api";
const mockApiRequest = vi.mocked(apiRequest);

function makeFetchResponse(
  ok: boolean,
  status: number,
  body: unknown = {}
): Response {
  return {
    ok,
    status,
    headers: new Headers({ "content-type": "application/json" }),
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
    body: null
  } as unknown as Response;
}

const mockFetch = vi.fn<typeof fetch>();

describe("ragQuery", () => {
  beforeEach(() => {
    mockApiRequest.mockReset();
  });

  it("returns augmented_prompt and sources on success", async () => {
    mockApiRequest.mockResolvedValueOnce({
      ok: true,
      status: 200,
      durationMs: 5,
      url: "http://localhost:8000/v1/rag/query",
      data: {
        augmented_prompt: "Context: hello world",
        sources: [{ text: "hello world", score: 0.9, metadata: {}, retrieval_method: "vector" }]
      }
    });

    const result = await ragQuery("hello");
    if ("unavailable" in result) {
      throw new Error("Expected successful RAG query result");
    }
    expect(result.augmented_prompt).toBe("Context: hello world");
    expect(result.sources).toHaveLength(1);
    expect(result.sources[0]?.score).toBe(0.9);
  });

  it("returns RagUnavailableResult when the backend returns 503", async () => {
    mockApiRequest.mockResolvedValueOnce({
      ok: false,
      status: 503,
      durationMs: 1,
      url: "http://localhost:8000/v1/rag/query",
      data: { detail: { error: "rag_unavailable", detail: "RAG pipeline not initialized" } }
    });

    const result = await ragQuery("fail");
    expect(result).toMatchObject({ unavailable: true, detail: "RAG pipeline not initialized" });
  });

  it("throws when the backend returns a non-503 error status", async () => {
    mockApiRequest.mockResolvedValueOnce({
      ok: false,
      status: 500,
      durationMs: 1,
      url: "http://localhost:8000/v1/rag/query",
      data: null
    });

    await expect(ragQuery("fail")).rejects.toThrow("RAG query failed: 500");
  });

  it("passes the bearer token in the request", async () => {
    mockApiRequest.mockResolvedValueOnce({
      ok: true,
      status: 200,
      durationMs: 1,
      url: "",
      data: { augmented_prompt: "", sources: [] }
    });

    await ragQuery("test", "tok-abc");
    expect(mockApiRequest).toHaveBeenCalledWith(
      expect.objectContaining({ token: "tok-abc" })
    );
  });
});

describe("ollamaQuery", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch);
    mockFetch.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns text from the Ollama response", async () => {
    mockFetch.mockResolvedValueOnce(
      makeFetchResponse(true, 200, {
        choices: [{ message: { content: "Ollama answer" } }]
      })
    );

    const result = await ollamaQuery("what is mcp?");
    expect(result.text).toBe("Ollama answer");
    expect(result.sources).toEqual([]);
  });

  it("uses the provided baseUrl", async () => {
    mockFetch.mockResolvedValueOnce(
      makeFetchResponse(true, 200, { choices: [{ message: { content: "ok" } }] })
    );

    await ollamaQuery("q", "http://127.0.0.1:9999");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://127.0.0.1:9999/v1/chat/completions",
      expect.any(Object)
    );
  });

  it("throws when Ollama is unreachable", async () => {
    mockFetch.mockResolvedValueOnce(makeFetchResponse(false, 500));
    await expect(ollamaQuery("q")).rejects.toThrow("Ollama query failed: 500");
  });
});
