import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LiveVoicePanel } from "./LiveVoicePanel";

const API_BASE_URL = "http://agent33.test";

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: {
      "Content-Type": "application/json"
    },
    ...init
  });
}

describe("LiveVoicePanel", () => {
  beforeEach(() => {
    window.__AGENT33_CONFIG__ = { API_BASE_URL };
  });

  it("prompts for sign-in when no token is present", () => {
    render(<LiveVoicePanel token={null} />);

    expect(screen.getByText("Sign in first to enable live voice sessions.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Connect microphone/i })).toBeDisabled();
  });

  it("hydrates an existing active voice session", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse([
        {
          id: "vcs-existing",
          room_name: "agent33-voice-tenant-a",
          state: "active",
          transport: "stub",
          daemon_health: true,
          started_at: "2026-03-09T18:00:00Z",
          last_error: ""
        }
      ])
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<LiveVoicePanel token="test-token" />);

    expect(await screen.findByText("Disconnect")).toBeInTheDocument();
    expect(screen.getByText("Room: agent33-voice-tenant-a")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE_URL}/v1/multimodal/voice/sessions?state=active&limit=1`,
      {
        method: "GET",
        headers: {
          Accept: "application/json",
          Authorization: "Bearer test-token"
        },
        body: undefined
      }
    );
  });

  it("starts and stops a live voice session through the backend", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        jsonResponse({
          id: "vcs-123",
          room_name: "agent33-voice-tenant-a",
          state: "active",
          transport: "stub",
          daemon_health: true,
          started_at: "2026-03-09T18:00:00Z",
          last_error: ""
        }, { status: 201 })
      )
      .mockResolvedValueOnce(
        jsonResponse({
          id: "vcs-123",
          room_name: "agent33-voice-tenant-a",
          state: "stopped",
          transport: "stub",
          daemon_health: false,
          started_at: "2026-03-09T18:00:00Z",
          last_error: ""
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<LiveVoicePanel token="test-token" />);

    await user.click(await screen.findByRole("button", { name: /Connect microphone/i }));
    expect(await screen.findByText("Disconnect")).toBeInTheDocument();
    expect(screen.getByText("Health: healthy")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Disconnect/i }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Connect microphone/i })).toBeInTheDocument();
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `${API_BASE_URL}/v1/multimodal/voice/sessions`,
      {
        method: "POST",
        headers: {
          Accept: "application/json",
          Authorization: "Bearer test-token",
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ requested_by: "frontend-live-voice" })
      }
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `${API_BASE_URL}/v1/multimodal/voice/sessions/vcs-123/stop`,
      {
        method: "POST",
        headers: {
          Accept: "application/json",
          Authorization: "Bearer test-token"
        },
        body: undefined
      }
    );
  });

  it("renders backend errors when voice session creation fails", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "voice runtime is disabled" }, { status: 503 })
      );
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<LiveVoicePanel token="test-token" />);

    await user.click(await screen.findByRole("button", { name: /Connect microphone/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("voice runtime is disabled");
  });

  it("surfaces hydration request failures and clears loading state", async () => {
    const fetchMock = vi.fn().mockRejectedValueOnce(new Error("voice backend offline"));
    vi.stubGlobal("fetch", fetchMock);

    render(<LiveVoicePanel token="test-token" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("voice backend offline");
    expect(screen.getByText("Ready to start")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Connect microphone/i })).toBeEnabled();
  });

  it("renders thrown start errors and clears the busy state", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockRejectedValueOnce(new Error("network dropped during start"));
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<LiveVoicePanel token="test-token" />);

    await user.click(await screen.findByRole("button", { name: /Connect microphone/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("network dropped during start");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Connect microphone/i })).toBeEnabled();
    });
  });

  it("renders thrown stop errors and clears the busy state", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse([
          {
            id: "vcs-existing",
            room_name: "agent33-voice-tenant-a",
            state: "active",
            transport: "stub",
            daemon_health: true,
            started_at: "2026-03-09T18:00:00Z",
            last_error: ""
          }
        ])
      )
      .mockRejectedValueOnce(new Error("stop request failed"));
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<LiveVoicePanel token="test-token" />);

    await user.click(await screen.findByRole("button", { name: /Disconnect/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("stop request failed");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Disconnect/i })).toBeEnabled();
    });
  });
});
