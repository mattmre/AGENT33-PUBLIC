import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    fetchMock.mockReset();
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

  it("renders registry metadata in the tool detail panel", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          tools: [
            {
              name: "shell",
              description: "Run shell commands",
              provider: "builtin",
              provider_name: "tool-registry",
              category: "system",
              version: "1.0",
              enabled: true,
              has_schema: true,
              parameters_schema: { type: "object" },
              result_schema: {},
              tags: ["system"],
              governance: {
                required_scope: "tools:execute",
                command_allowlist: ["git", "python"],
              },
              owner: "agent33-core",
              status: "active",
              provenance: {
                repo_url: "https://github.com/agent-33/agent-33",
                license: "MIT",
              },
              scope: {
                commands: ["git", "python"],
              },
              approval: {},
              last_review: "2026-05-24",
              next_review: "2026-08-24",
              deprecation_message: "",
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
        })
      )
      .mockResolvedValueOnce(jsonResponse([{ category: "system", count: 1 }]));

    render(<ToolCatalogPage token={null} apiKey="catalog-key" />);

    const shellCard = await screen.findByText("shell");
    fireEvent.click(shellCard);

    expect(screen.getByText("agent33-core")).toBeInTheDocument();
    expect(screen.getByText("tools:execute")).toBeInTheDocument();
    expect(screen.getByText("git, python")).toBeInTheDocument();
    expect(screen.getByText("MIT")).toBeInTheDocument();
    expect(screen.getByText("2026-05-24")).toBeInTheDocument();
  });
});
