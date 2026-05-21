import { buildUrl, getRuntimeConfig } from "./api";
import type { WorkflowLiveEvent, WorkflowLiveTransportConnection } from "../types";

export interface WorkflowLiveTransportOptions {
  runId: string;
  token?: string;
  apiKey?: string;
  onEvent: (event: WorkflowLiveEvent) => void;
  onError?: (error: Error) => void;
  closeOnTerminal?: boolean;
  reconnectBaseDelayMs?: number;
  reconnectMaxDelayMs?: number;
  maxReconnectAttempts?: number;
}

const WORKFLOW_GRAPH_REFRESH_EVENT_TYPES = new Set([
  "sync",
  "step_started",
  "step_completed",
  "step_failed",
  "step_skipped",
  "step_retrying",
  "workflow_completed",
  "workflow_failed"
]);

const WORKFLOW_TERMINAL_EVENT_TYPES = new Set(["workflow_completed", "workflow_failed"]);
const PERMANENT_FAILURE_STATUSES = new Set([401, 403, 404]);
const DEFAULT_RECONNECT_BASE_DELAY_MS = 250;
const DEFAULT_RECONNECT_MAX_DELAY_MS = 4_000;
const DEFAULT_MAX_RECONNECT_ATTEMPTS = 5;

export function shouldRefreshWorkflowGraph(event: WorkflowLiveEvent): boolean {
  return WORKFLOW_GRAPH_REFRESH_EVENT_TYPES.has(event.type);
}

export function isWorkflowTerminalEvent(event: WorkflowLiveEvent): boolean {
  return WORKFLOW_TERMINAL_EVENT_TYPES.has(event.type);
}

export function connectWorkflowLiveTransport(
  options: WorkflowLiveTransportOptions
): WorkflowLiveTransportConnection {
  const { API_BASE_URL } = getRuntimeConfig();

  let abortController: AbortController | null = null;
  abortController = new AbortController();
  void streamWorkflowEventsOverSse(API_BASE_URL, options, abortController.signal).catch((error) => {
    if (abortController?.signal.aborted || isAbortError(error)) {
      return;
    }
    options.onError?.(toError(error, "Workflow live SSE connection failed"));
  });

  return {
    close: () => {
      abortController?.abort();
    }
  };
}

export function buildWorkflowWebSocketUrl(baseUrl: string, runId: string, _token: string): string {
  void _token;
  const httpUrl = buildUrl(baseUrl, "/v1/workflows/{run_id}/ws", { run_id: runId });
  const url = new URL(httpUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

async function streamWorkflowEventsOverSse(
  baseUrl: string,
  options: WorkflowLiveTransportOptions,
  signal: AbortSignal
): Promise<void> {
  let lastEventId: string | null = null;
  let reconnectAttempts = 0;

  while (!signal.aborted) {
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
    try {
      const response = await fetch(
        buildUrl(baseUrl, "/v1/workflows/{run_id}/events", { run_id: options.runId }),
        {
          headers: buildWorkflowLiveHeaders(options, lastEventId),
          signal
        }
      );

      if (!response.ok || !response.body) {
        throw buildWorkflowTransportError(response.status);
      }

      reader = response.body.getReader();
      const streamState = await readWorkflowSseStream(reader, options, signal, lastEventId);
      lastEventId = streamState.lastEventId;

      if (streamState.terminalReached || signal.aborted) {
        return;
      }

      if (streamState.eventCount > 0) {
        reconnectAttempts = 0;
      }

      throw new RetryableWorkflowTransportError(
        "Workflow live SSE stream ended before a terminal event"
      );
    } catch (error) {
      if (signal.aborted || isAbortError(error)) {
        return;
      }
      if (error instanceof FatalWorkflowTransportError) {
        options.onError?.(error);
        return;
      }

      const maxReconnectAttempts = Math.max(
        0,
        options.maxReconnectAttempts ?? DEFAULT_MAX_RECONNECT_ATTEMPTS
      );
      if (reconnectAttempts >= maxReconnectAttempts) {
        const message =
          reconnectAttempts === 0
            ? "Workflow live SSE connection failed"
            : `Workflow live SSE connection failed after ${reconnectAttempts} retries`;
        options.onError?.(toError(error, message));
        return;
      }

      const delayMs = computeReconnectDelayMs(reconnectAttempts, options);
      reconnectAttempts += 1;
      await waitForReconnect(delayMs, signal);
    } finally {
      await reader?.cancel().catch(() => undefined);
    }
  }
}

function buildWorkflowLiveHeaders(
  options: Pick<WorkflowLiveTransportOptions, "token" | "apiKey">,
  lastEventId?: string | null
): HeadersInit {
  const headers: Record<string, string> = {
    Accept: "text/event-stream"
  };
  if (options.token?.trim()) {
    headers.Authorization = `Bearer ${options.token.trim()}`;
  }
  if (options.apiKey?.trim()) {
    headers["X-API-Key"] = options.apiKey.trim();
  }
  if (lastEventId?.trim()) {
    headers["Last-Event-ID"] = lastEventId.trim();
  }
  return headers;
}

async function readWorkflowSseStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  options: WorkflowLiveTransportOptions,
  signal: AbortSignal,
  initialLastEventId: string | null
): Promise<{ eventCount: number; lastEventId: string | null; terminalReached: boolean }> {
  const decoder = new TextDecoder();
  let buffer = "";
  let eventCount = 0;
  let lastEventId = initialLastEventId;
  let terminalReached = false;

  while (!signal.aborted) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.replace(/\r/g, "").split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const parsed = parseWorkflowSseChunk(part);
      if (!parsed?.event) {
        continue;
      }
      if (parsed.eventId) {
        lastEventId = parsed.eventId;
        parsed.event.event_id = parsed.eventId;
      }
      eventCount += 1;
      options.onEvent(parsed.event);
      if (isWorkflowTerminalEvent(parsed.event) && options.closeOnTerminal !== false) {
        terminalReached = true;
        return { eventCount, lastEventId, terminalReached };
      }
    }
  }

  if (buffer.trim()) {
    const parsed = parseWorkflowSseChunk(buffer);
    if (parsed?.event) {
      if (parsed.eventId) {
        lastEventId = parsed.eventId;
        parsed.event.event_id = parsed.eventId;
      }
      eventCount += 1;
      options.onEvent(parsed.event);
      if (isWorkflowTerminalEvent(parsed.event) && options.closeOnTerminal !== false) {
        terminalReached = true;
      }
    }
  }

  return { eventCount, lastEventId, terminalReached };
}

function parseWorkflowSseChunk(
  chunk: string
): { event: WorkflowLiveEvent | null; eventId: string | null } | null {
  const dataLines: string[] = [];
  let eventId: string | null = null;

  for (const line of chunk.replace(/\r/g, "").split("\n")) {
    if (line.startsWith("id:")) {
      eventId = line.slice(3).trim() || null;
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  if (dataLines.length === 0) {
    return { event: null, eventId };
  }

  return {
    event: JSON.parse(dataLines.join("\n")) as WorkflowLiveEvent,
    eventId
  };
}

function computeReconnectDelayMs(
  reconnectAttempts: number,
  options: Pick<
    WorkflowLiveTransportOptions,
    "reconnectBaseDelayMs" | "reconnectMaxDelayMs"
  >
): number {
  const baseDelayMs = Math.max(
    1,
    options.reconnectBaseDelayMs ?? DEFAULT_RECONNECT_BASE_DELAY_MS
  );
  const maxDelayMs = Math.max(
    baseDelayMs,
    options.reconnectMaxDelayMs ?? DEFAULT_RECONNECT_MAX_DELAY_MS
  );
  return Math.min(baseDelayMs * 2 ** reconnectAttempts, maxDelayMs);
}

async function waitForReconnect(delayMs: number, signal: AbortSignal): Promise<void> {
  if (delayMs <= 0 || signal.aborted) {
    return;
  }
  await new Promise<void>((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      cleanup();
      resolve();
    }, delayMs);
    const onAbort = () => {
      cleanup();
      reject(new Error("Workflow live SSE reconnect aborted"));
    };
    const cleanup = () => {
      window.clearTimeout(timeout);
      signal.removeEventListener("abort", onAbort);
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function buildWorkflowTransportError(status: number): Error {
  const message = `Workflow SSE request failed with status ${status}`;
  if (PERMANENT_FAILURE_STATUSES.has(status)) {
    return new FatalWorkflowTransportError(message);
  }
  return new RetryableWorkflowTransportError(message);
}

function toError(error: unknown, fallbackMessage: string): Error {
  if (error instanceof Error) {
    return error;
  }
  return new Error(fallbackMessage);
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.message === "Workflow live SSE reconnect aborted";
}

class RetryableWorkflowTransportError extends Error {}

class FatalWorkflowTransportError extends Error {}
