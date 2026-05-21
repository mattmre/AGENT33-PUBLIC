import { waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { connectWorkflowLiveTransport } from "./workflowLiveTransport";

function buildSseResponse(bodyText: string): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(bodyText));
      controller.close();
    }
  });
  return new Response(body, {
    status: 200,
    headers: { "content-type": "text/event-stream" }
  });
}

describe("workflowLiveTransport", () => {
  afterEach(() => {
    delete window.__AGENT33_CONFIG__;
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("uses authenticated SSE when a bearer token is available", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      buildSseResponse(
        'data: {"type":"sync","run_id":"run-ws","workflow_name":"wf-live","timestamp":1}\n\n'
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    const webSocketSpy = vi.fn();
    vi.stubGlobal("WebSocket", webSocketSpy);
    const onEvent = vi.fn().mockName("onEvent");

    const connection = connectWorkflowLiveTransport({
      runId: "run-ws",
      token: "jwt-token",
      onEvent
    });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(webSocketSpy).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      headers: {
        Accept: "text/event-stream",
        Authorization: "Bearer jwt-token"
      }
    });
    await waitFor(() =>
      expect(onEvent).toHaveBeenCalledWith(
        expect.objectContaining({ type: "sync", run_id: "run-ws" })
      )
    );
    connection.close();
  });

  it("uses SSE directly for api-key-only workflow live updates", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      buildSseResponse(
        'data: {"type":"sync","run_id":"run-sse","workflow_name":"wf-live","timestamp":1}\n\n'
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    const webSocketSpy = vi.fn();
    vi.stubGlobal("WebSocket", webSocketSpy);
    const onEvent = vi.fn();

    const connection = connectWorkflowLiveTransport({
      runId: "run-sse",
      apiKey: "api-key",
      onEvent
    });

    expect(webSocketSpy).not.toHaveBeenCalled();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      headers: {
        Accept: "text/event-stream",
        "X-API-Key": "api-key"
      }
    });
    await waitFor(() =>
      expect(onEvent).toHaveBeenCalledWith(
        expect.objectContaining({ type: "sync", run_id: "run-sse" })
      )
    );
    connection.close();
  });

  it("reconnects with Last-Event-ID after a transient SSE disconnect", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        buildSseResponse(
          'id: 1\ndata: {"type":"step_started","run_id":"run-reconnect","workflow_name":"wf-live","timestamp":1,"step_id":"step-a"}\n\n'
        )
      )
      .mockResolvedValueOnce(
        buildSseResponse(
          'id: 2\ndata: {"type":"workflow_completed","run_id":"run-reconnect","workflow_name":"wf-live","timestamp":2}\n\n'
        )
      );
    vi.stubGlobal("fetch", fetchMock);
    const onEvent = vi.fn();
    const onError = vi.fn();

    const connection = connectWorkflowLiveTransport({
      runId: "run-reconnect",
      token: "jwt-token",
      onEvent,
      onError,
      reconnectBaseDelayMs: 1,
      reconnectMaxDelayMs: 1
    });

    await waitFor(() =>
      expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ type: "step_started" }))
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      headers: {
        Accept: "text/event-stream",
        Authorization: "Bearer jwt-token",
        "Last-Event-ID": "1"
      }
    });
    await waitFor(() =>
      expect(onEvent).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "workflow_completed",
          event_id: "2"
        })
      )
    );
    expect(onError).not.toHaveBeenCalled();
    connection.close();
  });

  it("does not retry permanent SSE failures", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(null, {
        status: 404,
        headers: { "content-type": "text/event-stream" }
      })
    );
    vi.stubGlobal("fetch", fetchMock);
    const onError = vi.fn();

    const connection = connectWorkflowLiveTransport({
      runId: "run-missing",
      token: "jwt-token",
      onEvent: vi.fn(),
      onError,
      reconnectBaseDelayMs: 1,
      reconnectMaxDelayMs: 1
    });

    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        message: "Workflow SSE request failed with status 404"
      })
    );
    connection.close();
  });
});
