import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PluginManagerPanel } from "./PluginManagerPanel";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

const pluginList = [
  {
    name: "alpha-plugin",
    version: "1.0.0",
    description: "Alpha extension",
    state: "active",
    author: "AGENT-33",
    tags: ["infra"],
    contributions_summary: { skills: 1, tools: 1, agents: 0, hooks: 0 }
  },
  {
    name: "beta-plugin",
    version: "0.8.0",
    description: "Beta extension",
    state: "loaded",
    author: "AGENT-33",
    tags: ["testing"],
    contributions_summary: { skills: 0, tools: 1, agents: 0, hooks: 1 }
  }
];

const alphaDetail = {
  name: "alpha-plugin",
  version: "1.0.0",
  description: "Alpha extension",
  author: "AGENT-33",
  license: "MIT",
  homepage: "",
  repository: "",
  state: "active",
  status: "stable",
  permissions: ["network"],
  granted_permissions: ["network"],
  denied_permissions: [],
  contributions: {
    skills: ["alpha/skill"],
    tools: ["alpha.tool"],
    agents: [],
    hooks: []
  },
  dependencies: [{ name: "base-plugin", version_constraint: "^1.0.0", optional: true }],
  tags: ["infra"],
  tenant_config: null,
  error: null
};

const alphaDoctor = {
  plugin_name: "alpha-plugin",
  state: "active",
  overall_status: "healthy",
  install_source: "local",
  installed_path: "plugins/alpha-plugin",
  permissions: {
    plugin_name: "alpha-plugin",
    requested: ["network"],
    granted: ["network"],
    denied: []
  },
  checks: [
    {
      name: "manifest_valid",
      status: "ok",
      message: "Manifest is valid.",
      remediation: ""
    }
  ]
};

function installPluginFetchMock(fetchMock: ReturnType<typeof vi.fn>): void {
  fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);

    if (url === "http://localhost:8000/v1/plugins") {
      expect(init).toEqual(
        expect.objectContaining({
          headers: expect.objectContaining({
            Accept: "application/json",
            "X-API-Key": "plugin-key"
          })
        })
      );
      return jsonResponse(pluginList);
    }

    if (url === "http://localhost:8000/v1/plugins/search?q=beta") {
      return jsonResponse({ query: "beta", count: 1, plugins: [pluginList[1]] });
    }

    if (url === "http://localhost:8000/v1/plugins/doctor") {
      return jsonResponse({ count: 1, reports: [alphaDoctor] });
    }

    if (url === "http://localhost:8000/v1/plugins/alpha-plugin") {
      return jsonResponse(alphaDetail);
    }

    if (url === "http://localhost:8000/v1/plugins/alpha-plugin/config") {
      if (init?.method === "PUT") {
        expect(init.body).toBe(
          JSON.stringify({
            config: { threshold: 2 },
            enabled: false,
            permission_overrides: { network: false }
          })
        );
        return jsonResponse({
          plugin_name: "alpha-plugin",
          updated: true,
          config: { threshold: 2 },
          enabled: false,
          permission_overrides: { network: false },
          tenant_id: "tenant-a"
        });
      }

      return jsonResponse({
        plugin_name: "alpha-plugin",
        enabled: true,
        config_overrides: { threshold: 1 },
        permission_overrides: { network: true },
        tenant_id: "tenant-a"
      });
    }

    if (url === "http://localhost:8000/v1/plugins/alpha-plugin/health") {
      return jsonResponse({
        plugin_name: "alpha-plugin",
        healthy: true,
        details: { state: "active", version: "1.0.0" }
      });
    }

    if (url === "http://localhost:8000/v1/plugins/alpha-plugin/permissions") {
      return jsonResponse({
        plugin_name: "alpha-plugin",
        requested: ["network"],
        granted: ["network"],
        denied: []
      });
    }

    if (url === "http://localhost:8000/v1/plugins/alpha-plugin/doctor") {
      return jsonResponse(alphaDoctor);
    }

    if (url === "http://localhost:8000/v1/plugins/alpha-plugin/events") {
      return jsonResponse({
        plugin_name: "alpha-plugin",
        count: 1,
        events: [
          {
            event_type: "config_updated",
            plugin_name: "alpha-plugin",
            version: "1.0.0",
            timestamp: "2026-05-24T12:00:00Z",
            details: { tenant_id: "tenant-a" }
          }
        ]
      });
    }

    if (url === "http://localhost:8000/v1/plugins/alpha-plugin/disable") {
      expect(init?.method).toBe("POST");
      return jsonResponse({ ...pluginList[0], state: "disabled" });
    }

    if (url === "http://localhost:8000/v1/plugins/beta-plugin/link") {
      expect(init).toEqual(
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            source_path: "D:/plugins/beta",
            mode: "link",
            enable: false
          })
        })
      );
      return jsonResponse({
        success: true,
        plugin_name: "beta-plugin",
        version: "0.8.0",
        mode: "link",
        linked: true,
        installed_path: "plugins/beta-plugin",
        source_path: "D:/plugins/beta",
        warnings: [],
        errors: []
      });
    }

    throw new Error(`Unhandled fetch: ${url}`);
  });
}

describe("PluginManagerPanel", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    window.__AGENT33_CONFIG__ = { API_BASE_URL: "http://localhost:8000" };
  });

  afterEach(() => {
    delete window.__AGENT33_CONFIG__;
    vi.unstubAllGlobals();
  });

  it("loads plugin inventory with API-key auth and renders detail diagnostics", async () => {
    installPluginFetchMock(fetchMock);

    render(<PluginManagerPanel token={null} apiKey="plugin-key" onOpenSetup={vi.fn()} />);

    expect(await screen.findByRole("heading", { name: "Plugins and Extensions" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /alpha-plugin/i })).toBeInTheDocument();
    expect(await screen.findByText("Alpha extension")).toBeInTheDocument();
    expect(screen.getAllByText("Doctor healthy").length).toBeGreaterThan(0);
    expect(screen.getAllByText("network").length).toBeGreaterThan(0);
    expect(screen.getByText("config updated")).toBeInTheDocument();
    expect(screen.getByLabelText("Config JSON")).toHaveValue('{\n  "threshold": 1\n}');
  });

  it("disables a plugin and saves tenant configuration through /v1/plugins", async () => {
    installPluginFetchMock(fetchMock);
    const user = userEvent.setup();

    render(<PluginManagerPanel token={null} apiKey="plugin-key" onOpenSetup={vi.fn()} />);

    await screen.findByText("Alpha extension");
    await user.click(screen.getByRole("button", { name: "Disable" }));

    expect(await screen.findByText("Disable plugin completed for alpha-plugin.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Config JSON"), {
      target: { value: '{"threshold":2}' }
    });
    fireEvent.change(screen.getByLabelText("Permission overrides JSON"), {
      target: { value: '{"network":false}' }
    });
    await user.selectOptions(screen.getByLabelText("Enabled setting"), "false");
    await user.click(screen.getByRole("button", { name: "Save configuration" }));

    expect(await screen.findByText("Configuration saved for alpha-plugin.")).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://localhost:8000/v1/plugins/alpha-plugin/config",
        expect.objectContaining({ method: "PUT" })
      )
    );
  });

  it("searches plugins and links a local extension source", async () => {
    installPluginFetchMock(fetchMock);
    const user = userEvent.setup();

    render(<PluginManagerPanel token={null} apiKey="plugin-key" onOpenSetup={vi.fn()} />);

    await screen.findByText("Alpha extension");
    await user.type(screen.getByLabelText("Search plugins"), "beta");
    await user.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://localhost:8000/v1/plugins/search?q=beta",
        expect.any(Object)
      )
    );

    await user.type(screen.getByLabelText("Source path"), "D:/plugins/beta");
    await user.type(screen.getByLabelText("Expected name"), "beta-plugin");
    await user.selectOptions(screen.getByLabelText("Mode"), "link");
    await user.click(screen.getByLabelText("Enable after install"));
    await user.click(screen.getByRole("button", { name: "Install plugin" }));

    expect(await screen.findByText("Linked beta-plugin 0.8.0.")).toBeInTheDocument();
  });

  it("exposes an accessible setup path when credentials are missing", () => {
    const onOpenSetup = vi.fn();

    render(<PluginManagerPanel token={null} apiKey={null} onOpenSetup={onOpenSetup} />);

    expect(screen.getByRole("region", { name: "Plugin and extension manager" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open API access" })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
