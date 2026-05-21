import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SchemaViewer } from "./SchemaViewer";

describe("SchemaViewer", () => {
  it("renders tree and treeitem semantics for nested schemas", () => {
    render(
      <SchemaViewer
        schema={{
          type: "object",
          properties: {
            command: { type: "string" },
            options: {
              type: "object",
              properties: {
                recursive: { type: "boolean" },
              },
            },
          },
          required: ["command"],
        }}
      />
    );

    expect(screen.getByRole("tree", { name: "JSON Schema" })).toBeInTheDocument();
    expect(screen.getAllByRole("treeitem")).toHaveLength(3);
  });
});
