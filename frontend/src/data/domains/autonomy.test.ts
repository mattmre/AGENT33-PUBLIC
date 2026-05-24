import { describe, expect, it } from "vitest";

import { autonomyDomain } from "./autonomy";

function getOperation(id: string) {
  const operation = autonomyDomain.operations.find((entry) => entry.id === id);
  expect(operation).toBeDefined();
  return operation!;
}

describe("autonomyDomain", () => {
  it("keeps create-budget defaults fail-closed and backend-shaped", () => {
    const body = JSON.parse(getOperation("autonomy-create").defaultBody ?? "{}");

    expect(body.files.read).toContain("engine/src/**");
    expect(body.files.write).toContain("engine/tests/**");
    expect(body.allowed_commands[0]).toMatchObject({
      command: "python",
      args_pattern: "^-m (pytest|ruff)\\b.*"
    });
    expect(body.network).toMatchObject({
      enabled: false,
      allowed_domains: []
    });
    expect(body.stop_conditions[0].action).toBe("stop");
  });

  it("uses backend request fields for file and network enforcement", () => {
    const fileBody = JSON.parse(getOperation("autonomy-enforce-file").defaultBody ?? "{}");
    expect(fileBody).toEqual({
      path: "engine/src/agent33/main.py",
      mode: "read"
    });

    const networkBody = JSON.parse(getOperation("autonomy-enforce-network").defaultBody ?? "{}");
    expect(networkBody).toEqual({
      domain: "api.github.com"
    });
  });
});
