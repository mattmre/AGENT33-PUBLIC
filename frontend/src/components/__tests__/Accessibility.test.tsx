/**
 * Accessibility test suite for AGENT-33 frontend.
 *
 * Tests the new a11y utility components (SkipLink, VisuallyHidden) and
 * spot-checks key components for proper ARIA attributes, keyboard
 * accessibility, form labels, and heading hierarchy.
 */

import { render, screen, fireEvent, cleanup, within, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, beforeAll, afterEach } from "vitest";

import { SkipLink } from "../SkipLink";
import { VisuallyHidden } from "../VisuallyHidden";

// jsdom does not implement scrollIntoView; stub it globally for all tests
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  cleanup();
  delete (window as any).__AGENT33_CONFIG__;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/**
 * Helper: build a mock Response that satisfies both direct fetch callers
 * and the apiRequest helper (which reads response.headers.get()).
 */
function mockFetchResponse(data: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    headers: new Headers({ "content-type": "application/json" }),
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
    body: null,
  } as unknown as Response;
}

// ---- SkipLink ----

describe("SkipLink", () => {
  it("renders an anchor linking to #main-content", () => {
    render(<SkipLink />);
    const link = screen.getByText("Skip to main content");
    expect(link).toBeInTheDocument();
    expect(link.tagName).toBe("A");
    expect(link).toHaveAttribute("href", "#main-content");
  });

  it("has the skip-link CSS class", () => {
    render(<SkipLink />);
    const link = screen.getByText("Skip to main content");
    expect(link).toHaveClass("skip-link");
  });
});

// ---- VisuallyHidden ----

describe("VisuallyHidden", () => {
  it("renders its children in the DOM", () => {
    render(<VisuallyHidden>Screen reader only text</VisuallyHidden>);
    const element = screen.getByText("Screen reader only text");
    expect(element).toBeInTheDocument();
  });

  it("applies the sr-only CSS class", () => {
    render(<VisuallyHidden>Hidden label</VisuallyHidden>);
    const element = screen.getByText("Hidden label");
    expect(element).toHaveClass("sr-only");
  });

  it("renders as a span element", () => {
    render(<VisuallyHidden>Test content</VisuallyHidden>);
    const element = screen.getByText("Test content");
    expect(element.tagName).toBe("SPAN");
  });
});

// ---- App-level ARIA checks ----

describe("App accessibility", () => {
  // Mock dependencies that App uses
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    window.sessionStorage.clear();

    // Mock localStorage for auth
    vi.stubGlobal("localStorage", {
      getItem: vi.fn().mockReturnValue(null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
      clear: vi.fn(),
      length: 0,
      key: vi.fn(),
    });

    // Mock fetch for HealthPanel and other API calls
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockFetchResponse({ status: "ok", services: {} })
      )
    );

    // Mock speechSynthesis for ChatInterface
    vi.stubGlobal("speechSynthesis", {
      getVoices: vi.fn().mockReturnValue([]),
      speak: vi.fn(),
      cancel: vi.fn(),
      speaking: false,
      onvoiceschanged: null,
    });

    // Mock window.__AGENT33_CONFIG__
    (window as any).__AGENT33_CONFIG__ = {
      API_BASE_URL: "http://localhost:8000",
    };
  });

  it("renders SkipLink at the top of the app", async () => {
    // Dynamically import App to avoid import-order issues with mocks
    const { default: App } = await import("../../App");
    render(<App />);
    const skipLink = screen.getByText("Skip to main content");
    expect(skipLink).toBeInTheDocument();
    expect(skipLink).toHaveAttribute("href", "#main-content");
  }, 10000);

  it("has a main-content landmark", async () => {
    const { default: App } = await import("../../App");
    render(<App />);
    const mainContent = document.getElementById("main-content");
    expect(mainContent).toBeTruthy();
    expect(mainContent).toHaveAttribute("role", "main");
  });

  it("has labeled main navigation", async () => {
    const { default: App } = await import("../../App");
    render(<App />);
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(nav).toBeInTheDocument();
  });

  it("marks the active tab with aria-current", async () => {
    const { default: App } = await import("../../App");
    render(<App />);
    const buttons = screen.getAllByRole("button");
    const guideTabButton = buttons.find(
      (btn) => btn.textContent?.includes("Guide / Intake")
    );
    expect(guideTabButton).toBeTruthy();
    expect(guideTabButton).toHaveAttribute("aria-current", "page");
  });

  it("non-active tabs do not have aria-current", async () => {
    const { default: App } = await import("../../App");
    render(<App />);
    const buttons = screen.getAllByRole("button");
    const sessionsTabButton = buttons.find(
      (btn) => btn.textContent?.includes("Sessions & Runs")
    );
    expect(sessionsTabButton).toBeTruthy();
    expect(sessionsTabButton).not.toHaveAttribute("aria-current");
  });

  it("decorative logo orb has aria-hidden", async () => {
    const { default: App } = await import("../../App");
    render(<App />);
    const orb = document.querySelector(".logo-orb");
    expect(orb).toBeTruthy();
    expect(orb).toHaveAttribute("aria-hidden", "true");
  });

  it("keeps permission mode visible and changeable in the cockpit context", async () => {
    const { default: App } = await import("../../App");
    render(<App />);

    const permissionRegion = screen.getByRole("region", { name: "Permission mode" });
    expect(permissionRegion).toBeInTheDocument();

    const permissionSelect = screen.getByRole("combobox", { name: "Permission mode" });
    expect(permissionSelect).toHaveValue("ask");

    fireEvent.change(permissionSelect, { target: { value: "pr-first" } });

    expect(permissionSelect).toHaveValue("pr-first");
    expect(within(permissionRegion).getByText("Prefer reviewable branches and pull requests.")).toBeInTheDocument();
  });

  it("renders the cockpit dashboard and artifact drawer landmarks", async () => {
    const { default: App } = await import("../../App");
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /Sessions & Runs/ }));

    expect(screen.getByRole("region", { name: "Project cockpit dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Shipyard lanes" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Artifact and review drawer" })).toBeInTheDocument();
  });

  it("opens major cockpit destinations from URL state and keeps shareable links updated", async () => {
    window.history.replaceState(
      null,
      "",
      "/?view=operations&workspace=shipyard&permission=pr-first&drawer=activity"
    );

    const { default: App } = await import("../../App");
    render(<App />);

    expect(screen.getByRole("button", { name: /Sessions & Runs/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("combobox", { name: "Permission mode" })).toHaveValue("pr-first");
    expect(screen.getByRole("combobox", { name: "Active project template" })).toHaveValue("shipyard");
    expect(screen.getByRole("tab", { name: "Activity / Mailbox" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Agent mailbox")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Safety & Approvals/ }));

    await waitFor(() => {
      expect(window.location.search).toContain("view=safety");
      expect(window.location.search).toContain("workspace=shipyard");
      expect(window.location.search).toContain("permission=pr-first");
      expect(window.location.search).not.toContain("drawer=");
    });
  });
});

// ---- GlobalSearch ARIA checks ----

describe("GlobalSearch accessibility", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(mockFetchResponse({ results: [] }))
    );
    (window as any).__AGENT33_CONFIG__ = {
      API_BASE_URL: "http://localhost:8000",
    };
  });

  it("search input has aria-label", async () => {
    const { GlobalSearch } = await import("../GlobalSearch");
    render(<GlobalSearch token="test-token" />);
    const input = screen.getByRole("searchbox");
    expect(input).toHaveAttribute("aria-label", "Search semantic memory");
  });

  it("wrapping div has role='search'", async () => {
    const { GlobalSearch } = await import("../GlobalSearch");
    render(<GlobalSearch token="test-token" />);
    const searchRegion = screen.getByRole("search");
    expect(searchRegion).toBeInTheDocument();
  });
});

// ---- ChatInterface ARIA checks ----

describe("ChatInterface accessibility", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(mockFetchResponse({ choices: [] }))
    );
    vi.stubGlobal("speechSynthesis", {
      getVoices: vi.fn().mockReturnValue([]),
      speak: vi.fn(),
      cancel: vi.fn(),
      speaking: false,
      onvoiceschanged: null,
    });
    (window as any).__AGENT33_CONFIG__ = {
      API_BASE_URL: "http://localhost:8000",
    };
  });

  it("message log region has role='log' and aria-label", async () => {
    const { ChatInterface } = await import("../../features/chat/ChatInterface");
    render(<ChatInterface token="test" apiKey="test" />);
    const log = screen.getByRole("log");
    expect(log).toHaveAttribute("aria-label", "Chat messages");
  });

  it("textarea has aria-label", async () => {
    const { ChatInterface } = await import("../../features/chat/ChatInterface");
    render(<ChatInterface token="test" apiKey="test" />);
    const textarea = screen.getByRole("textbox", { name: "Message input" });
    expect(textarea).toBeInTheDocument();
  });

  it("send button has aria-label", async () => {
    const { ChatInterface } = await import("../../features/chat/ChatInterface");
    render(<ChatInterface token="test" apiKey="test" />);
    const sendBtn = screen.getByRole("button", { name: "Send message" });
    expect(sendBtn).toBeInTheDocument();
  });

  it("mic button has aria-label and aria-pressed", async () => {
    const { ChatInterface } = await import("../../features/chat/ChatInterface");
    render(<ChatInterface token="test" apiKey="test" />);
    const micBtn = screen.getByRole("button", { name: "Start dictation" });
    expect(micBtn).toBeInTheDocument();
    expect(micBtn).toHaveAttribute("aria-pressed", "false");
  });

  it("settings button has aria-expanded", async () => {
    const { ChatInterface } = await import("../../features/chat/ChatInterface");
    render(<ChatInterface token="test" apiKey="test" />);
    const settingsBtn = screen.getByRole("button", { name: "Chat settings" });
    expect(settingsBtn).toHaveAttribute("aria-expanded", "false");
  });

  it("settings popover opens with dialog role on click", async () => {
    const { ChatInterface } = await import("../../features/chat/ChatInterface");
    render(<ChatInterface token="test" apiKey="test" />);
    const settingsBtn = screen.getByRole("button", { name: "Chat settings" });
    fireEvent.click(settingsBtn);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-label", "Chat settings");
  });

  it("model picker controls remain labeled when the settings tab is opened", async () => {
    const { ChatInterface } = await import("../../features/chat/ChatInterface");
    render(<ChatInterface token="test" apiKey="test" />);

    fireEvent.click(screen.getByRole("button", { name: "Chat settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Model & Provider" }));

    expect(screen.getByLabelText("Model override")).toBeInTheDocument();
    expect(screen.getByLabelText("Search model catalog")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Use server default" })
    ).toBeInTheDocument();
  });
});

// ---- HealthPanel ARIA checks ----

describe("HealthPanel accessibility", () => {
  beforeEach(() => {
    (window as any).__AGENT33_CONFIG__ = {
      API_BASE_URL: "http://localhost:8000",
    };
  });

  it("status icons have role='img' with aria-label", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockFetchResponse({
          status: "ok",
          services: { postgres: "ok", redis: "error" },
        })
      )
    );

    const { HealthPanel } = await import("../HealthPanel");
    render(<HealthPanel />);

    // Wait for the async data load. There may be multiple "ok" icons
    // (OVERALL + postgres), so use findAllByRole.
    const connectedIcons = await screen.findAllByRole("img", {
      name: "Connected and working",
    });
    expect(connectedIcons.length).toBeGreaterThanOrEqual(1);

    const errorIcon = await screen.findByRole("img", {
      name: "Not working",
    });
    expect(errorIcon).toBeInTheDocument();
  });

  it("error messages have role='alert'", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("Network error"))
    );

    const { HealthPanel } = await import("../HealthPanel");
    render(<HealthPanel />);

    const alert = await screen.findByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).toContain("Network error");
  });
});

// ---- OperationsHubPanel keyboard accessibility ----

describe("OperationsHubPanel accessibility", () => {
  beforeEach(() => {
    (window as any).__AGENT33_CONFIG__ = {
      API_BASE_URL: "http://localhost:8000",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockFetchResponse({
          timestamp: new Date().toISOString(),
          active_count: 1,
          processes: [
            {
              id: "proc-1",
              name: "Test Process",
              type: "workflow",
              status: "running",
              started_at: new Date().toISOString(),
            },
          ],
        })
      )
    );
  });

  it("process items are keyboard-focusable with role='button'", async () => {
    const { OperationsHubPanel } = await import(
      "../../features/operations-hub/OperationsHubPanel"
    );
    render(
      <OperationsHubPanel
        token="test"
        apiKey="test"
        onResult={() => {}}
      />
    );

    const processItem = await screen.findByRole("button", {
      name: /Test Process/,
    });
    expect(processItem).toBeInTheDocument();
    expect(processItem).toHaveAttribute("tabindex", "0");
  });

  it("process items respond to Enter key", async () => {
    const { OperationsHubPanel } = await import(
      "../../features/operations-hub/OperationsHubPanel"
    );
    render(
      <OperationsHubPanel
        token="test"
        apiKey="test"
        onResult={() => {}}
      />
    );

    const processItem = await screen.findByRole("button", {
      name: /Test Process/,
    });
    fireEvent.keyDown(processItem, { key: "Enter" });
    // After selection, aria-pressed should be true
    expect(processItem).toHaveAttribute("aria-pressed", "true");
  });
});

// ---- MessagingSetup icon a11y ----

describe("MessagingSetup accessibility", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/v1/operator/config")) {
          return Promise.resolve(
            mockFetchResponse({
              groups: {
                llm: {
                  openrouter_api_key: "***",
                  openrouter_base_url: "https://openrouter.ai/api/v1",
                  openrouter_site_url: "https://agent33.example",
                  openrouter_app_name: "Agent Console",
                  openrouter_app_category: "ops-console",
                },
                ollama: {
                  default_model: "openrouter/auto",
                },
              },
            })
          );
        }

        if (url.includes("/v1/openrouter/models")) {
          return Promise.resolve(
            mockFetchResponse({
              data: [
                {
                  id: "openrouter/auto",
                  name: "Auto Router",
                  context_length: 128000,
                  pricing: { prompt: "0.000001", completion: "0.000002" },
                },
              ],
            })
          );
        }

        return Promise.resolve(mockFetchResponse({}));
      })
    );
    (window as any).__AGENT33_CONFIG__ = {
      API_BASE_URL: "http://localhost:8000",
    };
  });

  it("decorative card icons have aria-hidden", async () => {
    const { MessagingSetup } = await import(
      "../../features/integrations/MessagingSetup"
    );
    render(<MessagingSetup />);
    const icons = document.querySelectorAll(".card-icon");
    expect(icons.length).toBeGreaterThan(0);
    icons.forEach((icon) => {
      expect(icon).toHaveAttribute("aria-hidden", "true");
    });
  });

  it("OpenRouter form controls expose accessible labels", async () => {
    const { MessagingSetup } = await import(
      "../../features/integrations/MessagingSetup"
    );
    render(<MessagingSetup />);

    expect(await screen.findByLabelText("API key")).toBeInTheDocument();
    expect(screen.getByLabelText("Default model")).toBeInTheDocument();
    expect(screen.getByLabelText("Search catalog")).toBeInTheDocument();
  });

  it("status updates are announced via aria-live regions", async () => {
    const { MessagingSetup } = await import(
      "../../features/integrations/MessagingSetup"
    );
    render(<MessagingSetup />);

    const setupStatus = await screen.findByText(
      /Loaded OpenRouter settings from the server/
    );
    expect(setupStatus).toHaveAttribute("aria-live", "polite");
  });
});

// ---- Heading hierarchy check ----

describe("Heading hierarchy", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn().mockReturnValue(null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
      clear: vi.fn(),
      length: 0,
      key: vi.fn(),
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockFetchResponse({ status: "ok", services: {} })
      )
    );
    vi.stubGlobal("speechSynthesis", {
      getVoices: vi.fn().mockReturnValue([]),
      speak: vi.fn(),
      cancel: vi.fn(),
      speaking: false,
      onvoiceschanged: null,
    });
    (window as any).__AGENT33_CONFIG__ = {
      API_BASE_URL: "http://localhost:8000",
    };
  });

  it("has exactly one h1 element", async () => {
    const { default: App } = await import("../../App");
    render(<App />);
    const h1Elements = document.querySelectorAll("h1");
    expect(h1Elements.length).toBe(1);
    expect(h1Elements[0].textContent).toBe("AGENT-33");
  });
});

// ---- FindingsTable keyboard accessibility ----

describe("FindingsTable accessibility", () => {
  it("sortable headers are keyboard-focusable with aria-sort", async () => {
    const { FindingsTable } = await import(
      "../../features/security-dashboard/FindingsTable"
    );
    const findings = [
      {
        id: "f1",
        run_id: "r1",
        severity: "high",
        category: "xss",
        title: "XSS in input",
        description: "Found XSS",
        tool: "bandit",
        file_path: "src/app.py",
        line_number: 42,
        remediation: "Escape input",
        cwe_id: "CWE-79",
      },
    ];

    render(<FindingsTable findings={findings} />);

    const table = screen.getByRole("table", { name: "Security findings" });
    expect(table).toBeInTheDocument();

    // Check that th elements have aria-sort
    const headers = table.querySelectorAll("th.sortable");
    expect(headers.length).toBe(5);
    headers.forEach((header) => {
      expect(header).toHaveAttribute("tabindex", "0");
      expect(header).toHaveAttribute("aria-sort");
    });
  });

  it("finding rows are keyboard-focusable with aria-expanded", async () => {
    const { FindingsTable } = await import(
      "../../features/security-dashboard/FindingsTable"
    );
    const findings = [
      {
        id: "f1",
        run_id: "r1",
        severity: "high",
        category: "xss",
        title: "XSS in input",
        description: "Found XSS",
        tool: "bandit",
        file_path: "src/app.py",
        line_number: 42,
        remediation: "Escape input",
        cwe_id: "CWE-79",
      },
    ];

    render(<FindingsTable findings={findings} />);

    const rows = document.querySelectorAll("tr.finding-row");
    expect(rows.length).toBe(1);
    const row = rows[0];
    expect(row).toHaveAttribute("tabindex", "0");
    expect(row).toHaveAttribute("aria-expanded", "false");

    // Press Enter to expand
    fireEvent.keyDown(row, { key: "Enter" });
    expect(row).toHaveAttribute("aria-expanded", "true");
  });
});

// ---- CitationCard a11y ----

describe("CitationCard accessibility", () => {
  it("expand toggle has aria-expanded attribute", async () => {
    const { CitationCard } = await import(
      "../../features/research/CitationCard"
    );
    const citation = {
      url: "https://example.com",
      title: "Test Citation",
      display_url: "example.com",
      provider_id: "google",
      domain: "example.com",
      trust_level: "fetch-verified" as const,
      trust_reason: "Well-known domain",
    };

    render(<CitationCard citation={citation} snippet="A test snippet" />);

    const toggleBtn = screen.getByTestId("expand-toggle");
    expect(toggleBtn).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(toggleBtn);
    expect(toggleBtn).toHaveAttribute("aria-expanded", "true");
  });

  it("trust color dot is aria-hidden", async () => {
    const { CitationCard } = await import(
      "../../features/research/CitationCard"
    );
    const citation = {
      url: "https://example.com",
      title: "Test Citation",
      display_url: "example.com",
      provider_id: "google",
      domain: "example.com",
      trust_level: "fetch-verified" as const,
      trust_reason: "Well-known domain",
    };

    render(<CitationCard citation={citation} snippet="A test snippet" />);

    const indicator = screen.getByTestId("trust-indicator");
    const colorDot = indicator.querySelector("[aria-hidden='true']");
    expect(colorDot).toBeTruthy();
  });
});
