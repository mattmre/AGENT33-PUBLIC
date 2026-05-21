import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

function mockFetchResponse(data: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    headers: new Headers({ "content-type": "application/json" }),
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
    body: null
  } as unknown as Response;
}

describe("App route state guardrails", () => {
  beforeAll(() => {
    Element.prototype.scrollIntoView = vi.fn();
  });

  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    window.sessionStorage.clear();
    window.localStorage.clear();

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(mockFetchResponse({ status: "ok", services: {} }))
    );
    vi.stubGlobal("speechSynthesis", {
      getVoices: vi.fn().mockReturnValue([]),
      speak: vi.fn(),
      cancel: vi.fn(),
      speaking: false,
      onvoiceschanged: null
    });
    window.__AGENT33_CONFIG__ = {
      API_BASE_URL: "http://localhost:8000"
    };
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("opens design-kit deep links and preserves route context when jumping to live surfaces", async () => {
    window.history.replaceState(
      null,
      "",
      "/?view=design-kit&workspace=shipyard&permission=pr-first&operatorMode=beginner"
    );

    const { default: App } = await import("./App");
    const user = userEvent.setup();

    render(<App />);

    expect(screen.getByRole("heading", { name: "Design Kit Surfaces" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Active project template" })).toHaveValue("shipyard");
    expect(screen.getByRole("combobox", { name: "Permission mode" })).toHaveValue("pr-first");
    expect(screen.getByRole("button", { name: "Prioritize live controls" })).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "Open Operations Cockpit" })[0]);

    await waitFor(() => {
      expect(window.location.search).toContain("view=operations");
      expect(window.location.search).toContain("workspace=shipyard");
      expect(window.location.search).toContain("permission=pr-first");
      expect(window.location.search).toContain("operatorMode=beginner");
      expect(window.location.search).not.toContain("tab=");
    });
  });

  it("migrates legacy tab links, clears drawer outside operations, and stores popstate operator mode", async () => {
    window.history.replaceState(
      null,
      "",
      "/?tab=operations&sub=activity&workspace=shipyard&permission=pr-first&drawer=activity&operatorMode=beginner"
    );

    const { default: App } = await import("./App");
    const user = userEvent.setup();

    render(<App />);

    expect(screen.getByRole("button", { name: /Sessions & Runs/ })).toHaveAttribute("aria-current", "page");

    await waitFor(() => {
      expect(window.location.search).toContain("view=operations");
      expect(window.location.search).not.toContain("tab=");
      expect(window.location.search).not.toContain("sub=");
    });

    await user.click(screen.getByRole("button", { name: /Safety & Approvals/ }));

    await waitFor(() => {
      expect(window.location.search).toContain("view=safety");
      expect(window.location.search).toContain("operatorMode=beginner");
      expect(window.location.search).not.toContain("drawer=");
    });

    window.history.pushState(null, "", "/?view=advanced&operatorMode=pro");
    window.dispatchEvent(new PopStateEvent("popstate"));

    await waitFor(() => {
      expect(window.sessionStorage.getItem("agent33:operator-mode")).toBe("pro");
      expect(screen.getAllByRole("button", { name: "Prioritize guided routes" }).length).toBeGreaterThan(0);
    });
  });
});
