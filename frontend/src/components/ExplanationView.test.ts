import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ExplanationView, type ExplanationData } from "./ExplanationView";

describe("ExplanationView", () => {
  const mockExplanation: ExplanationData = {
    id: "expl-abc123",
    entity_type: "workflow",
    entity_id: "hello-flow",
    content: "This workflow processes greetings and generates responses.",
    mode: "plan_review",
    fact_check_status: "verified",
    created_at: "2024-01-16T12:00:00Z",
    metadata: {
      model: "llama3.1"
    },
    claims: [
      {
        id: "claim-1",
        claim_type: "metadata_equals",
        target: "model",
        status: "verified",
        message: "Metadata value matches expected value"
      }
    ]
  };

  it("renders core explanation fields", () => {
    const html = renderToStaticMarkup(
      createElement(ExplanationView, { explanation: mockExplanation })
    );
    expect(html).toContain("expl-abc123");
    expect(html).toContain("workflow / hello-flow");
    expect(html).toContain("This workflow processes greetings and generates responses.");
    expect(html).toContain("verified");
  });

  it("renders metadata section when metadata exists", () => {
    const html = renderToStaticMarkup(
      createElement(ExplanationView, { explanation: mockExplanation })
    );
    expect(html).toContain("Metadata");
    expect(html).toContain("llama3.1");
  });

  it("renders fact-check claims when present", () => {
    const html = renderToStaticMarkup(
      createElement(ExplanationView, { explanation: mockExplanation })
    );
    expect(html).toContain("Fact-check claims");
    expect(html).toContain("metadata_equals");
    expect(html).toContain("Metadata value matches expected value");
  });

  it("hides metadata section when metadata is absent", () => {
    const withoutMetadata: ExplanationData = {
      id: "expl-no-meta",
      entity_type: "workflow",
      entity_id: "flow",
      content: "test",
      fact_check_status: "pending",
      created_at: "2024-01-16T12:00:00Z"
    };
    const html = renderToStaticMarkup(
      createElement(ExplanationView, { explanation: withoutMetadata })
    );
    expect(html).not.toContain("Metadata");
  });

  it("renders plain text content in a <p> tag", () => {
    const html = renderToStaticMarkup(
      createElement(ExplanationView, { explanation: mockExplanation })
    );
    expect(html).toContain("<p>This workflow processes greetings");
    expect(html).not.toContain("<iframe");
  });

  it("renders HTML content starting with <!DOCTYPE in an iframe", () => {
    const htmlExplanation: ExplanationData = {
      ...mockExplanation,
      content: "<!DOCTYPE html><html><body><h1>Review</h1></body></html>"
    };
    const markup = renderToStaticMarkup(
      createElement(ExplanationView, { explanation: htmlExplanation })
    );
    expect(markup).toContain("<iframe");
    expect(markup).toContain('sandbox="allow-same-origin"');
    expect(markup).toContain('title="Explanation content"');
    expect(markup).not.toContain("<p><!DOCTYPE");
  });

  it("renders HTML content starting with <html in an iframe", () => {
    const htmlExplanation: ExplanationData = {
      ...mockExplanation,
      content: "<html><body><p>Plan summary</p></body></html>"
    };
    const markup = renderToStaticMarkup(
      createElement(ExplanationView, { explanation: htmlExplanation })
    );
    expect(markup).toContain("<iframe");
    expect(markup).not.toContain("<p><html>");
  });

  it("renders HTML content starting with <div in an iframe", () => {
    const htmlExplanation: ExplanationData = {
      ...mockExplanation,
      content: "<div class=\"recap\"><h2>Recap</h2></div>"
    };
    const markup = renderToStaticMarkup(
      createElement(ExplanationView, { explanation: htmlExplanation })
    );
    expect(markup).toContain("<iframe");
  });

  it("renders claims list below content when claims are present", () => {
    const html = renderToStaticMarkup(
      createElement(ExplanationView, { explanation: mockExplanation })
    );
    expect(html).toContain("Fact-check claims");
    expect(html).toContain("metadata_equals");
    expect(html).toContain("verified");
  });

  it("omits claims section when claims array is empty", () => {
    const noClaims: ExplanationData = {
      ...mockExplanation,
      claims: []
    };
    const html = renderToStaticMarkup(
      createElement(ExplanationView, { explanation: noClaims })
    );
    expect(html).not.toContain("Fact-check claims");
  });
});
