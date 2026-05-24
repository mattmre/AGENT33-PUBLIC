import { describe, expect, it } from "vitest";

import { agentsDomain } from "./agents";

describe("agentsDomain", () => {
  it("keeps search filters in parity with the backend agents search route", () => {
    const search = agentsDomain.operations.find((operation) => operation.id === "agents-search");

    expect(search?.path).toBe("/v1/agents/search");
    expect(search?.schemaInfo?.parameters?.map((param) => param.name)).toEqual([
      "role",
      "spec_capability",
      "category",
      "status"
    ]);
    expect(search?.schemaInfo?.parameters?.map((param) => param.name)).not.toContain("tags");
    expect(search?.defaultQuery).toEqual({
      role: "orchestrator",
      spec_capability: "P-01",
      status: "active"
    });
  });

  it("uses canonical role and capability values in create-agent defaults", () => {
    const create = agentsDomain.operations.find((operation) => operation.id === "agents-create");
    const body = JSON.parse(create?.defaultBody ?? "{}") as {
      role?: string;
      capabilities?: string[];
      spec_capabilities?: string[];
    };

    expect(body.role).toBe("implementer");
    expect(body.capabilities).toEqual(["file-read"]);
    expect(body.spec_capabilities).toEqual(["I-01"]);
    expect(create?.schemaInfo?.body?.example).toContain('"role": "implementer"');
    expect(create?.schemaInfo?.body?.example).not.toContain('"role": "worker"');
  });
});
