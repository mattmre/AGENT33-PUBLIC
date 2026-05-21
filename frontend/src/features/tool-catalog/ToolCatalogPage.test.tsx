import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToolCatalogPage } from "./ToolCatalogPage";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("ToolCatalogPage", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    window.__AGENT33_CONFIG__ = { API_BASE_URL: "http://localhost:8000" };
  });

  afterEach(() => {
    delete window.__AGENT33_CONFIG__;
  });

  it("uses the API key when loading tool catalog data", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ tools: [], total: 0, limit: 20, offset: 0 })
      )
      .mockResolvedValueOnce(jsonResponse([]));

    render(<ToolCatalogPage token={null} apiKey="catalog-key" />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/v1/catalog/tools?limit=20&offset=0",
      expect.objectContaining({
        headers: expect.objectContaining({
          Accept: "application/json",
          "X-API-Key": "catalog-key",
        }),
      })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/v1/catalog/categories",
      expect.objectContaining({
        headers: expect.objectContaining({
          Accept: "application/json",
          "X-API-Key": "catalog-key",
        }),
      })
    );
  });
});
