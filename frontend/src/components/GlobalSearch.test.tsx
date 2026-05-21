import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

vi.mock("../lib/api", () => ({
  getRuntimeConfig: () => ({ API_BASE_URL: "http://localhost:8000" })
}))

import { GlobalSearch } from "./GlobalSearch"

describe("GlobalSearch", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function getSearchInput() {
    return screen.getByRole("searchbox", { name: "Search semantic memory" })
  }

  it("renders a disabled input without a token", () => {
    render(<GlobalSearch token={null} />)

    expect(getSearchInput()).toBeDisabled()
    expect(getSearchInput()).toHaveAttribute("placeholder", "Sign in to use memory search")
  })

  it("renders an enabled input with a token", () => {
    render(<GlobalSearch token="jwt-token" />)

    expect(getSearchInput()).not.toBeDisabled()
    expect(getSearchInput()).toHaveAttribute(
      "placeholder",
      "Search semantic memory, workflows, and notes..."
    )
  })

  it("submits a memory-search request with auth", async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ results: [] })
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<GlobalSearch token="my-jwt" />)
    await user.type(getSearchInput(), "test query{enter}")

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(fetchMock.mock.calls[0][0]).toContain("/v1/memory/search")
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: "POST",
      headers: expect.objectContaining({
        Authorization: "Bearer my-jwt",
        "Content-Type": "application/json"
      })
    })
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toMatchObject({
      query: "test query",
      level: "full",
      top_k: 3
    })
  })

  it("renders returned search results", async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          results: [
            {
              content: "Result one content here that is important",
              token_estimate: 42,
              level: "full"
            },
            {
              content: "Result two content here that is also important",
              token_estimate: 20,
              level: "summary"
            }
          ]
        })
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<GlobalSearch token="tok" />)
    await user.type(getSearchInput(), "search{enter}")

    await waitFor(() => {
      expect(screen.getByText("Memory Results")).toBeInTheDocument()
    })
    expect(screen.getByText(/Result one content/)).toBeInTheDocument()
    expect(screen.getByText(/Result two content/)).toBeInTheDocument()
  })

  it("closes the result panel", async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ results: [] })
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<GlobalSearch token="tok" />)
    await user.type(getSearchInput(), "test{enter}")

    await waitFor(() => {
      expect(screen.getByText("No results found.")).toBeInTheDocument()
    })

    await user.click(screen.getByRole("button", { name: "Close search results" }))

    expect(screen.queryByText("No results found.")).not.toBeInTheDocument()
  })

  it("does not submit when query is empty", async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)

    render(<GlobalSearch token="tok" />)
    await user.type(getSearchInput(), "{enter}")

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("shows sign-in message in results panel when token is null and form submitted", async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)

    render(<GlobalSearch token={null} />)

    expect(getSearchInput()).toBeDisabled()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("displays loading state while search is in flight", async () => {
    const user = userEvent.setup()
    let resolveSearch: (value: unknown) => void = () => {}
    const fetchMock = vi.fn().mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveSearch = resolve
        })
    )
    vi.stubGlobal("fetch", fetchMock)

    render(<GlobalSearch token="tok" />)
    await user.type(getSearchInput(), "query{enter}")

    await waitFor(() => {
      expect(screen.getByText("Searching...")).toBeInTheDocument()
    })

    resolveSearch({
      ok: true,
      json: () => Promise.resolve({ results: [] })
    })

    await waitFor(() => {
      expect(screen.getByText("No results found.")).toBeInTheDocument()
    })
    expect(screen.queryByText("Searching...")).not.toBeInTheDocument()
  })

  it("renders result token and match metadata", async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          results: [
            {
              content: "Semantic memory result about agent orchestration workflow",
              token_estimate: 128,
              level: "summary"
            }
          ]
        })
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<GlobalSearch token="tok" />)
    await user.type(getSearchInput(), "search{enter}")

    await waitFor(() => {
      expect(screen.getByText(/Tokens: 128/)).toBeInTheDocument()
    })
    expect(screen.getByText(/Match: summary/)).toBeInTheDocument()
  })
})
