import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import type { DomainConfig } from "../types"

const { apiRequestMock } = vi.hoisted(() => ({
  apiRequestMock: vi.fn()
}))

vi.mock("../lib/api", () => ({
  apiRequest: apiRequestMock,
  getRuntimeConfig: () => ({ API_BASE_URL: "http://localhost:8000" })
}))

vi.mock("../features/security-dashboard/SecurityDashboard", () => ({
  SecurityDashboard: ({ token }: { token: string }) => (
    <div data-testid="security-dashboard">Security: {token}</div>
  )
}))

vi.mock("../features/improvement-cycle/ImprovementCycleWizard", () => ({
  ImprovementCycleWizard: () => (
    <div data-testid="improvement-wizard">Wizard</div>
  )
}))

vi.mock("./OperationCard", () => ({
  OperationCard: ({ operation }: { operation: { id: string; title: string } }) => (
    <div data-testid={`op-${operation.id}`}>{operation.title}</div>
  )
}))

import { DomainPanel } from "./DomainPanel"

function buildDomain(overrides: Partial<DomainConfig> = {}): DomainConfig {
  return {
    id: "test-domain",
    title: "Test Domain",
    description: "Domain for testing",
    operations: [
      {
        id: "op-a",
        title: "Create Widget",
        method: "POST",
        path: "/v1/widgets",
        description: "Creates a new widget"
      },
      {
        id: "op-b",
        title: "List Agents",
        method: "GET",
        path: "/v1/agents",
        description: "List all agents"
      },
      {
        id: "op-c",
        title: "Delete Session",
        method: "DELETE",
        path: "/v1/sessions/{id}",
        description: "Deletes a session by id"
      }
    ],
    ...overrides
  }
}

describe("DomainPanel", () => {
  it("renders domain title and description", () => {
    const domain = buildDomain()

    render(
      <DomainPanel domain={domain} token="jwt" apiKey="" onResult={vi.fn()} />
    )

    expect(screen.getByText("Test Domain")).toBeInTheDocument()
    expect(screen.getByText("Domain for testing")).toBeInTheDocument()
  })

  it("renders all operation cards", () => {
    const domain = buildDomain()

    render(
      <DomainPanel domain={domain} token="jwt" apiKey="" onResult={vi.fn()} />
    )

    expect(screen.getByTestId("op-op-a")).toHaveTextContent("Create Widget")
    expect(screen.getByTestId("op-op-b")).toHaveTextContent("List Agents")
    expect(screen.getByTestId("op-op-c")).toHaveTextContent("Delete Session")
  })

  it("filters operations by title", async () => {
    const user = userEvent.setup()
    const domain = buildDomain()

    render(
      <DomainPanel domain={domain} token="jwt" apiKey="" onResult={vi.fn()} />
    )

    const filterInput = screen.getByPlaceholderText("Filter operations")
    await user.type(filterInput, "agent")

    expect(screen.getByTestId("op-op-b")).toBeInTheDocument()
    expect(screen.queryByTestId("op-op-a")).not.toBeInTheDocument()
    expect(screen.queryByTestId("op-op-c")).not.toBeInTheDocument()
  })

  it("filters operations by path", async () => {
    const user = userEvent.setup()
    const domain = buildDomain()

    render(
      <DomainPanel domain={domain} token="jwt" apiKey="" onResult={vi.fn()} />
    )

    const filterInput = screen.getByPlaceholderText("Filter operations")
    await user.type(filterInput, "widgets")

    expect(screen.getByTestId("op-op-a")).toBeInTheDocument()
    expect(screen.queryByTestId("op-op-b")).not.toBeInTheDocument()
  })

  it("filters operations by description", async () => {
    const user = userEvent.setup()
    const domain = buildDomain()

    render(
      <DomainPanel domain={domain} token="jwt" apiKey="" onResult={vi.fn()} />
    )

    const filterInput = screen.getByPlaceholderText("Filter operations")
    await user.type(filterInput, "deletes")

    expect(screen.getByTestId("op-op-c")).toBeInTheDocument()
    expect(screen.queryByTestId("op-op-a")).not.toBeInTheDocument()
  })

  it("shows all operations when filter is cleared", async () => {
    const user = userEvent.setup()
    const domain = buildDomain()

    render(
      <DomainPanel domain={domain} token="jwt" apiKey="" onResult={vi.fn()} />
    )

    const filterInput = screen.getByPlaceholderText("Filter operations")
    await user.type(filterInput, "agent")
    expect(screen.queryByTestId("op-op-a")).not.toBeInTheDocument()

    await user.clear(filterInput)
    expect(screen.getByTestId("op-op-a")).toBeInTheDocument()
    expect(screen.getByTestId("op-op-b")).toBeInTheDocument()
    expect(screen.getByTestId("op-op-c")).toBeInTheDocument()
  })

  it("renders SecurityDashboard for component-security domain", () => {
    const domain = buildDomain({ id: "component-security" })

    render(
      <DomainPanel domain={domain} token="my-jwt" apiKey="" onResult={vi.fn()} />
    )

    expect(screen.getByTestId("security-dashboard")).toHaveTextContent("Security: my-jwt")
  })

  it("does not render SecurityDashboard for non-security domains", () => {
    const domain = buildDomain({ id: "agents" })

    render(
      <DomainPanel domain={domain} token="jwt" apiKey="" onResult={vi.fn()} />
    )

    expect(screen.queryByTestId("security-dashboard")).not.toBeInTheDocument()
  })

  it("renders ImprovementCycleWizard for workflows domain", () => {
    const domain = buildDomain({ id: "workflows" })

    render(
      <DomainPanel domain={domain} token="jwt" apiKey="" onResult={vi.fn()} />
    )

    expect(screen.getByTestId("improvement-wizard")).toBeInTheDocument()
  })

  it("does not render ImprovementCycleWizard for non-workflow domains", () => {
    const domain = buildDomain({ id: "agents" })

    render(
      <DomainPanel domain={domain} token="jwt" apiKey="" onResult={vi.fn()} />
    )

    expect(screen.queryByTestId("improvement-wizard")).not.toBeInTheDocument()
  })

  it("filter is case-insensitive", async () => {
    const user = userEvent.setup()
    const domain = buildDomain()

    render(
      <DomainPanel domain={domain} token="jwt" apiKey="" onResult={vi.fn()} />
    )

    const filterInput = screen.getByPlaceholderText("Filter operations")
    await user.type(filterInput, "WIDGET")

    expect(screen.getByTestId("op-op-a")).toBeInTheDocument()
    expect(screen.queryByTestId("op-op-b")).not.toBeInTheDocument()
  })

  it("applies and clears the external pro search filter", () => {
    const domain = buildDomain()

    const { rerender } = render(
      <DomainPanel
        domain={domain}
        token="jwt"
        apiKey=""
        externalFilter="sessions"
        onResult={vi.fn()}
      />
    )

    expect(screen.getByText("Pro search applied: sessions")).toBeInTheDocument()
    expect(screen.getByTestId("op-op-c")).toBeInTheDocument()
    expect(screen.queryByTestId("op-op-a")).not.toBeInTheDocument()

    rerender(
      <DomainPanel domain={domain} token="jwt" apiKey="" externalFilter="" onResult={vi.fn()} />
    )

    expect(screen.queryByText(/Pro search applied:/)).not.toBeInTheDocument()
    expect(screen.getByTestId("op-op-a")).toBeInTheDocument()
    expect(screen.getByTestId("op-op-b")).toBeInTheDocument()
    expect(screen.getByTestId("op-op-c")).toBeInTheDocument()
  })
})
