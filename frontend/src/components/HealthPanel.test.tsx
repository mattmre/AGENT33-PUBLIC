import { render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

const { apiRequestMock } = vi.hoisted(() => ({
  apiRequestMock: vi.fn()
}))

vi.mock("../lib/api", () => ({
  apiRequest: apiRequestMock,
  getRuntimeConfig: () => ({ API_BASE_URL: "http://localhost:8000" })
}))

import { HealthPanel } from "./HealthPanel"

describe("HealthPanel", () => {
  afterEach(() => {
    vi.clearAllMocks()
    vi.useRealTimers()
  })

  it("renders the loading state initially", () => {
    apiRequestMock.mockReturnValue(new Promise(() => {}))

    render(<HealthPanel />)

    expect(screen.getByText("Loading health...")).toBeInTheDocument()
  })

  it("renders health status with service details", async () => {
    apiRequestMock.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        status: "healthy",
        services: {
          postgres: "ok",
          redis: "ok",
          nats: "configured"
        }
      }
    })

    render(<HealthPanel />)

    await waitFor(() => {
      expect(screen.getByText("healthy")).toBeInTheDocument()
    })
    expect(screen.getByText("POSTGRES")).toBeInTheDocument()
    expect(screen.getByText("REDIS")).toBeInTheDocument()
    expect(screen.getByText("NATS")).toBeInTheDocument()
    expect(screen.getByText("configured")).toBeInTheDocument()
  })

  it("shows an error when the health request fails", async () => {
    apiRequestMock.mockResolvedValue({
      ok: false,
      status: 503,
      data: null
    })

    render(<HealthPanel />)

    await waitFor(() => {
      expect(screen.getByText("Health check failed (503)")).toBeInTheDocument()
    })
  })

  it("shows thrown network errors", async () => {
    apiRequestMock.mockRejectedValue(new Error("Network unreachable"))

    render(<HealthPanel />)

    await waitFor(() => {
      expect(screen.getByText("Network unreachable")).toBeInTheDocument()
    })
  })

  it("maps overall and service status classes correctly", async () => {
    apiRequestMock.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        status: "ok",
        services: {
          redis: "degraded",
          nats: "unconfigured"
        }
      }
    })

    render(<HealthPanel />)

    await waitFor(() => {
      expect(screen.getByText("ok")).toBeInTheDocument()
    })

    expect(document.querySelectorAll(".rh-icon.connected")).toHaveLength(1)
    expect(document.querySelectorAll(".rh-icon.error")).toHaveLength(1)
    expect(document.querySelectorAll(".rh-icon.inactive")).toHaveLength(1)
  })

  it("maps configured status to pending icon", async () => {
    apiRequestMock.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        status: "healthy",
        services: {
          nats: "configured"
        }
      }
    })

    render(<HealthPanel />)

    await waitFor(() => {
      expect(screen.getByText("healthy")).toBeInTheDocument()
    })

    expect(document.querySelectorAll(".rh-icon.pending")).toHaveLength(1)
  })

  it("renders the OVERALL card with the top-level status", async () => {
    apiRequestMock.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        status: "degraded",
        services: {}
      }
    })

    render(<HealthPanel />)

    await waitFor(() => {
      expect(screen.getByText("OVERALL")).toBeInTheDocument()
    })
    expect(screen.getByText("degraded")).toBeInTheDocument()
    expect(document.querySelectorAll(".runtime-health-card")).toHaveLength(1)
  })

  it("renders health with no services gracefully", async () => {
    apiRequestMock.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        status: "ok"
      }
    })

    render(<HealthPanel />)

    await waitFor(() => {
      expect(screen.getByText("ok")).toBeInTheDocument()
    })

    expect(screen.getByText("OVERALL")).toBeInTheDocument()
    expect(document.querySelectorAll(".runtime-health-card")).toHaveLength(1)
  })

  it("calls apiRequest on the /health endpoint", async () => {
    apiRequestMock.mockResolvedValue({
      ok: true,
      status: 200,
      data: { status: "ok", services: {} }
    })

    render(<HealthPanel />)

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledTimes(1)
    })

    expect(apiRequestMock).toHaveBeenCalledWith(
      expect.objectContaining({
        method: "GET",
        path: "/health"
      })
    )
  })
})
