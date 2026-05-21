import { describe, expect, it } from "vitest";

import { buildUrl, interpolatePath } from "./api";

describe("interpolatePath", () => {
  it("replaces path params", () => {
    expect(interpolatePath("/v1/reviews/{review_id}", { review_id: "abc-123" })).toBe(
      "/v1/reviews/abc-123"
    );
  });

  it("url-encodes path params", () => {
    expect(interpolatePath("/v1/files/{name}", { name: "a b.txt" })).toBe("/v1/files/a%20b.txt");
  });

  it("keeps raw placeholder for missing params", () => {
    expect(interpolatePath("/v1/items/{item_id}/sub/{sub_id}", { item_id: "123" })).toBe(
      "/v1/items/123/sub/{sub_id}"
    );
  });

  it("keeps raw placeholder when no params provided", () => {
    expect(interpolatePath("/v1/resource/{id}")).toBe("/v1/resource/{id}");
  });
});

describe("buildUrl", () => {
  it("builds full url with query", () => {
    const url = buildUrl(
      "http://localhost:8000",
      "/v1/agents/search",
      {},
      { role: "orchestrator", q: "alpha beta" }
    );
    expect(url).toBe("http://localhost:8000/v1/agents/search?role=orchestrator&q=alpha+beta");
  });

  it("omits blank query values", () => {
    const url = buildUrl("http://localhost:8000", "/health", {}, { q: "" });
    expect(url).toBe("http://localhost:8000/health");
  });
});
