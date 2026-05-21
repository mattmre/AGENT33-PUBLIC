import { useState } from "react";

export interface DiffHunk {
  index: number;
  header: string;
  oldStart: number;
  newStart: number;
  lines: DiffLine[];
  decision: "pending" | "accepted" | "rejected";
}

export interface DiffLine {
  type: "context" | "added" | "removed";
  content: string;
}

interface DiffReviewPanelProps {
  content: string;
  isHtml: boolean;
  onAnnotationSubmit?: (comment: string) => void;
}

export function isHtmlContent(content: string): boolean {
  const trimmed = content.trimStart();
  return (
    trimmed.startsWith("<!DOCTYPE") ||
    trimmed.startsWith("<html") ||
    trimmed.startsWith("<HTML") ||
    trimmed.startsWith("<body") ||
    trimmed.startsWith("<div")
  );
}

export function parseDiffHunks(content: string): DiffHunk[] {
  const hunks: DiffHunk[] = [];
  const lines = content.split("\n");
  let current: DiffHunk | null = null;
  let index = 0;

  const hunkHeaderRegex = /^@@\s*-(\d+)(?:,\d+)?\s*\+(\d+)(?:,\d+)?\s*@@/;

  for (const line of lines) {
    const match = hunkHeaderRegex.exec(line);
    if (match) {
      if (current) hunks.push(current);
      current = {
        index: index++,
        header: line,
        oldStart: parseInt(match[1], 10),
        newStart: parseInt(match[2], 10),
        lines: [],
        decision: "pending"
      };
      continue;
    }

    if (current) {
      if (line.startsWith("+")) {
        current.lines.push({ type: "added", content: line.slice(1) });
      } else if (line.startsWith("-")) {
        current.lines.push({ type: "removed", content: line.slice(1) });
      } else {
        current.lines.push({ type: "context", content: line.startsWith(" ") ? line.slice(1) : line });
      }
    }
  }

  if (current) hunks.push(current);
  return hunks;
}

export function DiffReviewPanel({
  content,
  isHtml,
  onAnnotationSubmit
}: DiffReviewPanelProps): JSX.Element {
  const [annotation, setAnnotation] = useState("");
  const [hunks, setHunks] = useState<DiffHunk[]>(() =>
    !isHtml ? parseDiffHunks(content) : []
  );

  function handleHunkDecision(
    hunkIndex: number,
    decision: "accepted" | "rejected"
  ): void {
    setHunks((prev) =>
      prev.map((h) => (h.index === hunkIndex ? { ...h, decision } : h))
    );
  }

  function handleAnnotationSubmit(): void {
    if (annotation.trim() && onAnnotationSubmit) {
      onAnnotationSubmit(annotation.trim());
      setAnnotation("");
    }
  }

  return (
    <section className="diff-review-panel">
      {isHtml ? (
        <div className="diff-review-html">
          <iframe
            className="wizard-preview-frame"
            title="Diff review content"
            srcDoc={content}
            sandbox="allow-same-origin"
          />
        </div>
      ) : hunks.length > 0 ? (
        <div className="diff-review-hunks">
          {hunks.map((hunk) => (
            <div key={hunk.index} className="diff-hunk">
              <div className="diff-hunk-header">
                <code>{hunk.header}</code>
                <span className="diff-hunk-decision" data-decision={hunk.decision}>
                  {hunk.decision}
                </span>
              </div>
              <pre className="diff-hunk-lines">
                {hunk.lines.map((line, i) => (
                  <span key={i} className={`diff-line diff-line-${line.type}`}>
                    {line.type === "added" ? "+" : line.type === "removed" ? "-" : " "}
                    {line.content}
                    {"\n"}
                  </span>
                ))}
              </pre>
              <div className="diff-hunk-actions">
                <button
                  disabled={hunk.decision === "accepted"}
                  onClick={() => handleHunkDecision(hunk.index, "accepted")}
                >
                  Accept
                </button>
                <button
                  disabled={hunk.decision === "rejected"}
                  className="wizard-danger"
                  onClick={() => handleHunkDecision(hunk.index, "rejected")}
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <pre className="diff-review-raw">{content}</pre>
      )}

      <div className="diff-review-annotation">
        <label className="wizard-textarea">
          Annotation
          <textarea
            aria-label="Annotation"
            rows={3}
            value={annotation}
            onChange={(e) => setAnnotation(e.target.value)}
            placeholder="Add a comment or annotation..."
          />
        </label>
        <div className="wizard-actions">
          <button
            disabled={!annotation.trim()}
            onClick={handleAnnotationSubmit}
          >
            Submit annotation
          </button>
        </div>
      </div>
    </section>
  );
}
