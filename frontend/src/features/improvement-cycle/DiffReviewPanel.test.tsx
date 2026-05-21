import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DiffReviewPanel, isHtmlContent, parseDiffHunks } from "./DiffReviewPanel";

describe("isHtmlContent", () => {
  it("detects HTML doctype", () => {
    expect(isHtmlContent("<!DOCTYPE html><html></html>")).toBe(true);
  });

  it("detects html tag", () => {
    expect(isHtmlContent("<html><body>test</body></html>")).toBe(true);
  });

  it("detects body tag", () => {
    expect(isHtmlContent("<body>content</body>")).toBe(true);
  });

  it("rejects plain text", () => {
    expect(isHtmlContent("This is plain text.")).toBe(false);
  });

  it("rejects diff content", () => {
    expect(isHtmlContent("@@ -1,3 +1,4 @@\n+added line")).toBe(false);
  });
});

describe("parseDiffHunks", () => {
  const SAMPLE_DIFF = `@@ -1,3 +1,4 @@
 context line
-removed line
+added line
+another added
@@ -10,2 +11,2 @@
 more context
-old
+new`;

  it("parses hunks from unified diff format", () => {
    const hunks = parseDiffHunks(SAMPLE_DIFF);
    expect(hunks).toHaveLength(2);
    expect(hunks[0].oldStart).toBe(1);
    expect(hunks[0].newStart).toBe(1);
    expect(hunks[1].oldStart).toBe(10);
    expect(hunks[1].newStart).toBe(11);
  });

  it("categorizes line types correctly", () => {
    const hunks = parseDiffHunks(SAMPLE_DIFF);
    const firstHunk = hunks[0];
    expect(firstHunk.lines[0].type).toBe("context");
    expect(firstHunk.lines[1].type).toBe("removed");
    expect(firstHunk.lines[2].type).toBe("added");
    expect(firstHunk.lines[3].type).toBe("added");
  });

  it("strips leading +/- from line content", () => {
    const hunks = parseDiffHunks(SAMPLE_DIFF);
    expect(hunks[0].lines[1].content).toBe("removed line");
    expect(hunks[0].lines[2].content).toBe("added line");
  });

  it("initializes hunks with pending decision", () => {
    const hunks = parseDiffHunks(SAMPLE_DIFF);
    expect(hunks[0].decision).toBe("pending");
    expect(hunks[1].decision).toBe("pending");
  });

  it("returns empty array for non-diff content", () => {
    expect(parseDiffHunks("plain text without hunks")).toEqual([]);
  });
});

describe("DiffReviewPanel", () => {
  it("renders HTML content in an iframe", () => {
    render(
      <DiffReviewPanel content="<html><body>Hello</body></html>" isHtml={true} />
    );
    const iframe = document.querySelector("iframe");
    expect(iframe).not.toBeNull();
    expect(iframe?.title).toBe("Diff review content");
  });

  it("renders diff hunks for non-HTML content", () => {
    const diff = "@@ -1,2 +1,2 @@\n-old\n+new";
    render(<DiffReviewPanel content={diff} isHtml={false} />);
    expect(screen.getByText("@@ -1,2 +1,2 @@")).toBeInTheDocument();
    expect(screen.getByText("Accept")).toBeInTheDocument();
    expect(screen.getByText("Reject")).toBeInTheDocument();
  });

  it("allows accepting a hunk", async () => {
    const diff = "@@ -1,1 +1,1 @@\n-old\n+new";
    render(<DiffReviewPanel content={diff} isHtml={false} />);
    await userEvent.click(screen.getByText("Accept"));
    // After accepting, the Accept button should be disabled
    expect(screen.getByText("Accept")).toBeDisabled();
  });

  it("allows rejecting a hunk", async () => {
    const diff = "@@ -1,1 +1,1 @@\n-old\n+new";
    render(<DiffReviewPanel content={diff} isHtml={false} />);
    await userEvent.click(screen.getByText("Reject"));
    expect(screen.getByText("Reject")).toBeDisabled();
  });

  it("renders annotation textarea", () => {
    render(<DiffReviewPanel content="test" isHtml={false} />);
    expect(screen.getByLabelText("Annotation")).toBeInTheDocument();
  });

  it("submits annotation via callback", async () => {
    const onSubmit = vi.fn();
    render(
      <DiffReviewPanel content="test" isHtml={false} onAnnotationSubmit={onSubmit} />
    );
    await userEvent.type(screen.getByLabelText("Annotation"), "My comment");
    await userEvent.click(screen.getByText("Submit annotation"));
    expect(onSubmit).toHaveBeenCalledWith("My comment");
  });

  it("disables submit annotation when empty", () => {
    render(<DiffReviewPanel content="test" isHtml={false} />);
    expect(screen.getByText("Submit annotation")).toBeDisabled();
  });

  it("renders raw content when no hunks detected", () => {
    render(<DiffReviewPanel content="plain text" isHtml={false} />);
    expect(screen.getByText("plain text")).toBeInTheDocument();
  });
});
