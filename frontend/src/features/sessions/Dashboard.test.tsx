import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

vi.mock("../../lib/api", () => ({
  getRuntimeConfig: () => ({ API_BASE_URL: "http://localhost:8000" })
}))

import { SessionsDashboard } from "./Dashboard"

describe("SessionsDashboard", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders the dashboard heading and description", () => {
    render(<SessionsDashboard token={null} />)

    expect(screen.getByText("Agent runs, outcomes, and artifacts")).toBeInTheDocument()
    expect(
      screen.getByText("Review what ran, what happened, what artifacts exist, and what to do next.")
    ).toBeInTheDocument()
  })

  it("shows empty state message when no sessions are loaded", () => {
    render(<SessionsDashboard token={null} />)

    expect(
      screen.getByText("No run history found yet")
    ).toBeInTheDocument()
  })

  it("does not fetch sessions when token is null", () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)

    render(<SessionsDashboard token={null} />)

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("fetches and displays sessions when token is provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
        json: () =>
          Promise.resolve([
            {
              id: "session-001",
              status: "completed",
              agent: "researcher",
              evidence: [{ title: "Validation summary" }],
              verifications: ["pytest"]
            },
            { id: "session-002", status: "running", agent: "implementer" },
            { id: "session-003", status: "failed", agent: "qa" }
          ])
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<SessionsDashboard token="my-jwt" />)

    await waitFor(() => {
      expect(screen.getByText("session-001")).toBeInTheDocument()
    })
    expect(screen.getByText("session-002")).toBeInTheDocument()
    expect(screen.getByText("session-003")).toBeInTheDocument()
    expect(screen.getByText("Review artifacts")).toBeInTheDocument()
    expect(screen.getByText("Evidence")).toBeInTheDocument()
    expect(screen.getAllByText("Validation summary")).toHaveLength(2)
    expect(screen.getByText("Verification")).toBeInTheDocument()

    expect(fetchMock.mock.calls[0][0]).toContain("/v1/sessions")
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      headers: { Authorization: "Bearer my-jwt" }
    })
  })

  it("refreshes sessions on button click", async () => {
    const user = userEvent.setup()
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve([{ id: "session-old" }])
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve([{ id: "session-old" }, { id: "session-new" }])
      })
    vi.stubGlobal("fetch", fetchMock)

    render(<SessionsDashboard token="jwt" />)

    await waitFor(() => {
      expect(screen.getByText("session-old")).toBeInTheDocument()
    })

    await user.click(screen.getByRole("button", { name: "Refresh runs" }))

    await waitFor(() => {
      expect(screen.getByText("session-new")).toBeInTheDocument()
    })

    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it("shows loading state on the refresh button", async () => {
    let resolveReq: (value: unknown) => void = () => {}
    const fetchMock = vi.fn().mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveReq = resolve
        })
    )
    vi.stubGlobal("fetch", fetchMock)

    render(<SessionsDashboard token="jwt" />)

    expect(screen.getByRole("button", { name: "Loading..." })).toBeDisabled()

    resolveReq({
      ok: true,
      json: () => Promise.resolve([])
    })

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Refresh runs" })
      ).toBeEnabled()
    })
  })

  it("handles fetch errors gracefully without crashing", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("Network error"))
    vi.stubGlobal("fetch", fetchMock)

    render(<SessionsDashboard token="jwt" />)

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Refresh runs" })
      ).toBeEnabled()
    })

    expect(
      screen.getByText("Network error")
    ).toBeInTheDocument()
  })

  it("renders session IDs inside run cards", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([{ id: "ses-42" }])
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<SessionsDashboard token="jwt" />)

    await waitFor(() => {
      expect(screen.getByText("ses-42")).toBeInTheDocument()
    })

    expect(screen.getByText("Run ID")).toBeInTheDocument()
  })

  it("handles session objects without an id property", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([{ status: "completed" }])
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<SessionsDashboard token="jwt" />)

    await waitFor(() => {
      expect(screen.getByText("Run session-1")).toBeInTheDocument()
      expect(screen.getByText("Unassigned agent")).toBeInTheDocument()
    })
  })
})
