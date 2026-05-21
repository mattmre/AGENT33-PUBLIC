import { render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ObservationStream } from "./ObservationStream"

function buildSseResponse(bodyText: string): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(bodyText))
      controller.close()
    }
  })
  return new Response(body, {
    status: 200,
    headers: { "content-type": "text/event-stream" }
  })
}

function encodeEvent(event: Record<string, unknown>): string {
  return `data: ${JSON.stringify(event)}\n\n`
}

function buildMockStreamResponse(chunks: string[]) {
  const encoder = new TextEncoder()
  let index = 0
  const reader = {
    read: vi.fn().mockImplementation(async () => {
      if (index < chunks.length) {
        const value = encoder.encode(chunks[index])
        index += 1
        return { done: false, value }
      }
      return { done: true, value: undefined }
    }),
    cancel: vi.fn().mockResolvedValue(undefined)
  }

  return {
    reader,
    response: {
      ok: true,
      body: {
        getReader: () => reader
      }
    }
  }
}

describe("ObservationStream", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders nothing when no token is provided", () => {
    const { container } = render(<ObservationStream token={null} />)

    expect(container.innerHTML).toBe("")
  })

  it("connects to the stream with bearer auth", async () => {
    const fetchMock = vi.fn().mockResolvedValue(buildSseResponse(""))
    vi.stubGlobal("fetch", fetchMock)

    render(<ObservationStream token="my-jwt" />)

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(fetchMock.mock.calls[0][0]).toContain("/v1/operations/stream")
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      headers: { Authorization: "Bearer my-jwt" }
    })
  })

  it("renders allowed core-mechanics events", async () => {
    const event = {
      id: "ev-1",
      agent_name: "orchestrator",
      event_type: "handoff_context_wipe",
      content: "Context wiped for handoff",
      timestamp: new Date().toISOString()
    }

    const fetchMock = vi
      .fn()
      .mockResolvedValue(buildSseResponse(`data: ${JSON.stringify(event)}\n\n`))
    vi.stubGlobal("fetch", fetchMock)

    render(<ObservationStream token="tok" />)

    await waitFor(() => {
      expect(screen.getByText("Live Core Mechanics")).toBeInTheDocument()
    })
    expect(screen.getByText("Context wiped for handoff")).toBeInTheDocument()
    expect(screen.getByText("orchestrator")).toBeInTheDocument()
  })

  it("filters irrelevant events out of the stream", async () => {
    const irrelevantEvent = {
      id: "ev-2",
      agent_name: "worker",
      event_type: "generic_event",
      content: "Something irrelevant",
      timestamp: new Date().toISOString()
    }

    const { reader, response } = buildMockStreamResponse([encodeEvent(irrelevantEvent)])
    const fetchMock = vi.fn().mockResolvedValue(response)
    vi.stubGlobal("fetch", fetchMock)

    const { container } = render(<ObservationStream token="tok" />)

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    await waitFor(() => expect(reader.read).toHaveBeenCalledTimes(2))

    expect(container.querySelector(".observation-stream")).toBeNull()
  })

  it("keeps at most ten events in newest-first order", async () => {
    const events = Array.from({ length: 12 }, (_, index) => ({
      id: `ev-${index}`,
      agent_name: "orch",
      event_type: "handoff_context_wipe",
      content: `Wipe ${index}`,
      timestamp: new Date().toISOString()
    }))

    const { response } = buildMockStreamResponse(events.map((event) => encodeEvent(event)))
    const fetchMock = vi.fn().mockResolvedValue(response)
    vi.stubGlobal("fetch", fetchMock)

    const { container } = render(<ObservationStream token="tok" />)

    await waitFor(() => {
      expect(screen.getByText("Wipe 11")).toBeInTheDocument()
    })

    await waitFor(() => {
      expect(container.querySelectorAll(".observation-item")).toHaveLength(10)
    })

    const contents = Array.from(
      container.querySelectorAll<HTMLElement>(".observation-item .observation-content")
    )
    expect(contents[0]).toHaveTextContent("Wipe 11")
    expect(contents[9]).toHaveTextContent("Wipe 2")
  })

  it("cancels the stream reader on unmount", async () => {
    const cancelMock = vi.fn().mockResolvedValue(undefined)
    let resolveRead: (value: { done: boolean; value: undefined }) => void = () => {}
    const mockReader = {
      read: vi.fn().mockImplementation(
        () =>
          new Promise<{ done: boolean; value: undefined }>((resolve) => {
            resolveRead = resolve
          })
      ),
      cancel: cancelMock
    }

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: { getReader: () => mockReader }
    })
    vi.stubGlobal("fetch", fetchMock)

    const { unmount } = render(<ObservationStream token="tok" />)
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    await waitFor(() => expect(mockReader.read).toHaveBeenCalledTimes(1))

    unmount()

    await waitFor(() => expect(cancelMock).toHaveBeenCalled())
    resolveRead({ done: true, value: undefined })
  })

  it("renders a2a subordinate events with the correct type label", async () => {
    const event = {
      id: "ev-a2a",
      agent_name: "director",
      event_type: "tool_call",
      content: "Invoking deploy_a2a_subordinate for task-42",
      timestamp: new Date().toISOString()
    }

    const fetchMock = vi
      .fn()
      .mockResolvedValue(buildSseResponse(`data: ${JSON.stringify(event)}\n\n`))
    vi.stubGlobal("fetch", fetchMock)

    render(<ObservationStream token="tok" />)

    await waitFor(() => {
      expect(screen.getByText("Invoking deploy_a2a_subordinate for task-42")).toBeInTheDocument()
    })
    expect(screen.getByText("director")).toBeInTheDocument()
  })

  it("renders AST extraction events with the correct type label", async () => {
    const event = {
      id: "ev-ast",
      agent_name: "code-worker",
      event_type: "tool_call",
      content: "Running tldr_read_enforcer on module.py",
      timestamp: new Date().toISOString()
    }

    const fetchMock = vi
      .fn()
      .mockResolvedValue(buildSseResponse(`data: ${JSON.stringify(event)}\n\n`))
    vi.stubGlobal("fetch", fetchMock)

    render(<ObservationStream token="tok" />)

    await waitFor(() => {
      expect(screen.getByText("Running tldr_read_enforcer on module.py")).toBeInTheDocument()
    })
    expect(screen.getByText("code-worker")).toBeInTheDocument()
  })

  it("does not crash when fetch rejects with a network error", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("Connection refused"))
    vi.stubGlobal("fetch", fetchMock)

    const { container } = render(<ObservationStream token="tok" />)

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())

    expect(container.innerHTML).toBe("")
  })

  it("does not connect when response.ok is false", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      body: null
    })
    vi.stubGlobal("fetch", fetchMock)

    const { container } = render(<ObservationStream token="tok" />)

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())

    expect(container.innerHTML).toBe("")
  })

  it("displays formatted timestamps on events", async () => {
    const timestamp = "2026-03-15T14:30:00.000Z"
    const event = {
      id: "ev-ts",
      agent_name: "orch",
      event_type: "handoff_context_wipe",
      content: "Context wiped",
      timestamp
    }

    const fetchMock = vi
      .fn()
      .mockResolvedValue(buildSseResponse(`data: ${JSON.stringify(event)}\n\n`))
    vi.stubGlobal("fetch", fetchMock)

    render(<ObservationStream token="tok" />)

    await waitFor(() => {
      expect(screen.getByText("Context wiped")).toBeInTheDocument()
    })

    const timeEl = document.querySelector(".observation-time")
    expect(timeEl).not.toBeNull()
    expect(timeEl?.textContent).toBeTruthy()
  })
})
