import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", () => ({
  apiRequest: vi.fn()
}));

import { apiRequest } from "../../lib/api";
import { ResourceCatalogPanel } from "./ResourceCatalogPanel";

const apiRequestMock = vi.mocked(apiRequest);

describe("ResourceCatalogPanel", () => {
  afterEach(() => {
    apiRequestMock.mockReset();
  });

  it("prompts for authentication before loading resources", () => {
    render(<ResourceCatalogPanel token={null} apiKey={null} />);

    expect(screen.getByText("Resource Catalog")).toBeInTheDocument();
    expect(screen.getByText("Connect with a session token or API key to load resources.")).toBeInTheDocument();
    expect(apiRequestMock).not.toHaveBeenCalled();
  });

  it("loads and renders unified resource manifests", async () => {
    apiRequestMock.mockResolvedValue({
      ok: true,
      status: 200,
      durationMs: 4,
      url: "http://localhost:8000/v1/resources/search",
      data: {
        total: 1,
        items: [
          {
            id: "pack.core-ops",
            name: "Core Ops Pack",
            version: "1.0.0",
            kind: "pack",
            description: "Built-in operational workflows and guardrails.",
            tags: ["ops"],
            permissions: [{ scope: "workflows:read" }],
            trust: { verified: true },
            rollback: { supported: true }
          }
        ]
      }
    });

    render(<ResourceCatalogPanel token="jwt" apiKey={null} />);

    await waitFor(() => {
      expect(screen.getByText("Core Ops Pack")).toBeInTheDocument();
    });
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(screen.getByText("workflows:read")).toBeInTheDocument();
  });

  it("applies query and kind filters", async () => {
    const user = userEvent.setup();
    apiRequestMock.mockResolvedValue({
      ok: true,
      status: 200,
      durationMs: 4,
      url: "http://localhost:8000/v1/resources/search",
      data: { total: 0, items: [] }
    });

    render(<ResourceCatalogPanel token="jwt" apiKey={null} />);
    await user.type(screen.getByLabelText("Search"), "review");
    await user.selectOptions(screen.getByLabelText("Type"), "skill");
    await user.click(screen.getByRole("button", { name: "Apply" }));

    expect(apiRequestMock).toHaveBeenLastCalledWith(
      expect.objectContaining({
        query: { query: "review", kind: "skill", limit: "50" }
      })
    );
  });
});
