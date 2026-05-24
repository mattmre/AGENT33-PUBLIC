import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiRequestMock } = vi.hoisted(() => ({
  apiRequestMock: vi.fn()
}));

vi.mock("../../lib/api", () => ({
  apiRequest: apiRequestMock
}));

import { SandboxingPanel } from "./SandboxingPanel";

describe("SandboxingPanel", () => {
  beforeEach(() => {
    apiRequestMock.mockReset();
  });

  it("posts the backend sandbox review contract", async () => {
    apiRequestMock.mockResolvedValue({
      ok: true,
      data: {
        surface: "code-interpreter",
        requires_review: true,
        risk: "high",
        blockers: ["missing safe mount"],
        safe_mounts_required: true,
        recommendation: "Require docker sandbox"
      }
    });

    render(<SandboxingPanel token="token-1" />);

    fireEvent.change(screen.getByPlaceholderText("Surface (e.g., code-interpreter)"), {
      target: { value: " code-interpreter " }
    });
    fireEvent.change(screen.getByLabelText("Risk"), { target: { value: "high" } });
    fireEvent.change(screen.getByPlaceholderText("Recommendation"), {
      target: { value: "Require docker sandbox" }
    });
    fireEvent.change(screen.getByPlaceholderText("Blockers, comma separated"), {
      target: { value: "missing safe mount, " }
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit for Review" }));

    await waitFor(() => expect(apiRequestMock).toHaveBeenCalledTimes(1));
    expect(apiRequestMock).toHaveBeenCalledWith({
      method: "POST",
      path: "/v1/sandboxing/review",
      token: "token-1",
      body: JSON.stringify({
        surface: "code-interpreter",
        risk: "high",
        recommendation: "Require docker sandbox",
        blockers: ["missing safe mount"],
        safe_mounts_required: true
      })
    });
    expect(await screen.findByText("REVIEW REQUIRED")).toBeInTheDocument();
    expect(screen.getByText("Blockers: missing safe mount")).toBeInTheDocument();
  });
});
