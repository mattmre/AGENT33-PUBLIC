import { describe, expect, it } from "vitest";

import {
  asMcpStatus,
  asProxyReloadResponse,
  asProxyServersResponse,
  asProxyToolsResponse,
  asProxyValidateResponse,
  asSyncPushResponse,
  asSyncDiffResponse
} from "./api";

describe("mcp health api parsers", () => {
  it("parses MCP status with optional bridge fields", () => {
    const parsed = asMcpStatus({
      available: true,
      mcp_sdk_installed: true,
      transport_available: true,
      status: "operational",
      tools_loaded: 12
    });

    expect(parsed?.available).toBe(true);
    expect(parsed?.tools_loaded).toBe(12);
  });

  it("parses proxy fleet and tools responses", () => {
    const servers = asProxyServersResponse({
      servers: [
        {
          id: "evokore",
          name: "EVOKORE",
          state: "healthy",
          transport: "stdio",
          tool_count: 4,
          uptime_seconds: 11,
          consecutive_failures: 0,
          circuit_state: "closed",
          last_health_check: null,
          last_error: null
        }
      ],
      total: 1,
      healthy: 1,
      degraded: 0,
      unhealthy: 0,
      stopped: 0
    });
    const tools = asProxyToolsResponse({
      tools: [
        {
          name: "evokore.search_skills",
          description: "Search skills",
          proxy_server_id: "evokore",
          original_name: "search_skills"
        }
      ],
      count: 1
    });

    expect(servers?.servers[0]?.state).toBe("healthy");
    expect(tools?.tools[0]?.name).toBe("evokore.search_skills");
  });

  it("parses CLI sync drift entries", () => {
    const diff = asSyncDiffResponse({
      entries: [
        {
          target: "claude_code",
          config_path: "/home/operator/.claude.json",
          present: true,
          matches: false,
          current: { command: "old" },
          expected: { command: "uvx" },
          error: ""
        }
      ]
    });

    expect(diff?.entries[0]?.target).toBe("claude_code");
    expect(diff?.entries[0]?.matches).toBe(false);
  });

  it("parses MCP action responses", () => {
    const pushed = asSyncPushResponse({
      results: [
        {
          target: "claude_code",
          config_path: "/home/operator/.claude.json",
          status: "updated",
          message: "Updated agent33 entry",
          existing_entry: { command: "old" }
        }
      ]
    });
    const validated = asProxyValidateResponse({
      valid: true,
      server_count: 1,
      errors: [],
      diff: { added: ["evokore"] }
    });
    const reloaded = asProxyReloadResponse({
      added: ["evokore"],
      restarted: [],
      removed: [],
      unchanged: [],
      errors: []
    });

    expect(pushed?.results[0]?.status).toBe("updated");
    expect(validated?.server_count).toBe(1);
    expect(reloaded?.added).toEqual(["evokore"]);
  });
});
