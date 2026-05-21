import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

vi.mock("../../lib/api", () => ({
  getRuntimeConfig: () => ({ API_BASE_URL: "http://localhost:8000" })
}))

import { EvolutionDashboard } from "./Dashboard"

const PROPOSALS_URL = "http://localhost:8000/v1/improvements/proposals"
const GENERATE_URL = "http://localhost:8000/v1/improvements/proposals/generate"

const MOCK_PROPOSALS_RESPONSE = {
  proposals: [
    {
      id: "abc123",
      status: "proposal_only",
      proposal_type: "config-calibration",
      summary: "Proposal-only sandbox; production mutation is disabled.",
      created_at: "2026-05-16T10:00:00Z",
      completed_at: "2026-05-16T10:00:01Z",
      approved_at: null,
      approved_by: null,
      sample_size: 15,
      before_values: { auto_intake_min_quality: 0.45 },
      after_values: { auto_intake_min_quality: 0.6 },
      deltas: { auto_intake_min_quality: 0.15 }
    }
  ],
  count: 1,
  type: "tuning-calibration"
}

describe("EvolutionDashboard", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it("renders the dashboard heading", () => {
    render(<EvolutionDashboard token={null} />)

    expect(
      screen.getByText("Self-Evolution & Security Engine")
    ).toBeInTheDocument()
  })

  it("renders action buttons", () => {
    render(<EvolutionDashboard token="jwt" />)

    expect(
      screen.getByRole("button", { name: "Generate Improvement Proposal" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Refresh Proposals" })
    ).toBeInTheDocument()
  })

  it("shows empty proposals state initially", () => {
    render(<EvolutionDashboard token="jwt" />)

    expect(
      screen.getByText(/No proposals yet/)
    ).toBeInTheDocument()
  })

  it("loads and displays real proposals when Refresh button is clicked", async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(MOCK_PROPOSALS_RESPONSE)
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<EvolutionDashboard token="my-jwt" />)

    await user.click(
      screen.getByRole("button", { name: "Refresh Proposals" })
    )

    await waitFor(() => {
      expect(
        screen.getByText(/config-calibration: proposal_only/)
      ).toBeInTheDocument()
    })

    expect(fetchMock).toHaveBeenCalledWith(
      PROPOSALS_URL,
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer my-jwt"
        })
      })
    )

    expect(
      screen.queryByText(/No proposals yet/)
    ).not.toBeInTheDocument()
  })

  it("shows error when proposals fetch fails", async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 503
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<EvolutionDashboard token="my-jwt" />)

    await user.click(
      screen.getByRole("button", { name: "Refresh Proposals" })
    )

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument()
    })
  })

  it("calls generate endpoint then reloads proposals", async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn()
      // First call: POST to generate
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ proposal_id: "new-1", status: "generated" }) })
      // Second call: GET to reload list
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(MOCK_PROPOSALS_RESPONSE) })
    vi.stubGlobal("fetch", fetchMock)

    render(<EvolutionDashboard token="my-jwt" />)

    await user.click(
      screen.getByRole("button", { name: "Generate Improvement Proposal" })
    )

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      GENERATE_URL,
      expect.objectContaining({ method: "POST" })
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      PROPOSALS_URL,
      expect.anything()
    )
  })

  it("does not fetch when token is null", async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)

    render(<EvolutionDashboard token={null} />)

    await user.click(
      screen.getByRole("button", { name: "Refresh Proposals" })
    )

    expect(fetchMock).not.toHaveBeenCalled()
  })
})
