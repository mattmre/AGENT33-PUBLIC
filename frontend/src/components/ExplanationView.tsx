/**
 * ExplanationView component - renders explanation content.
 *
 * Supports two content modes:
 * - Plain text: rendered inside a &lt;p&gt; tag
 * - HTML content: rendered inside a sandboxed &lt;iframe&gt; via srcDoc
 *
 * HTML detection: content starting with `<!DOCTYPE`, `<html`, or `<div`
 * (case-insensitive, ignoring leading whitespace).
 */

import React from "react";

export interface ExplanationData {
  id: string;
  entity_type: string;
  entity_id: string;
  content: string;
  mode?: "generic" | "diff_review" | "plan_review" | "project_recap";
  fact_check_status: "pending" | "verified" | "flagged" | "skipped";
  created_at: string;
  metadata?: Record<string, unknown>;
  claims?: ExplanationClaimData[];
}

export interface ExplanationClaimData {
  id: string;
  claim_type: string;
  target: string;
  expected?: string;
  actual?: string;
  description?: string;
  message?: string;
  status: "pending" | "verified" | "flagged" | "skipped";
}

export interface ExplanationViewProps {
  explanation: ExplanationData;
}

/** Returns true when `content` looks like an HTML document or fragment. */
function isHtmlContent(content: string): boolean {
  const trimmed = content.trimStart().toLowerCase();
  return (
    trimmed.startsWith("<!doctype") ||
    trimmed.startsWith("<html") ||
    trimmed.startsWith("<div")
  );
}

export const ExplanationView: React.FC<ExplanationViewProps> = ({
  explanation
}) => {
  const htmlMode = isHtmlContent(explanation.content);

  return (
    <div data-testid="explanation-view" className="explanation-view">
      <div className="explanation-header">
        <h3>Explanation: {explanation.id}</h3>
        <span
          className={`fact-check-badge fact-check-${explanation.fact_check_status}`}
          data-testid="fact-check-status"
          role="status"
          aria-label={`Fact check status: ${explanation.fact_check_status}`}
        >
          {explanation.fact_check_status}
        </span>
      </div>

      <div className="explanation-meta">
        <span>
          Entity: {explanation.entity_type} / {explanation.entity_id}
        </span>
        <span>Created: {new Date(explanation.created_at).toLocaleString()}</span>
      </div>

      <div className="explanation-content" data-testid="explanation-content">
        {htmlMode ? (
          <iframe
            srcDoc={explanation.content}
            sandbox="allow-same-origin"
            style={{ width: "100%", minHeight: "400px", border: "1px solid #e5e7eb" }}
            title="Explanation content"
            data-testid="explanation-iframe"
          />
        ) : (
          <p>{explanation.content}</p>
        )}
      </div>

      {explanation.claims && explanation.claims.length > 0 && (
        <div className="explanation-claims" data-testid="explanation-claims">
          <h4>Fact-check claims</h4>
          <ul>
            {explanation.claims.map((claim) => (
              <li key={claim.id}>
                <strong>{claim.claim_type}</strong>: {claim.description || claim.target} (
                {claim.status})
                {claim.message ? <span> - {claim.message}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      )}

      {explanation.metadata && Object.keys(explanation.metadata).length > 0 && (
        <div className="explanation-metadata">
          <h4>Metadata</h4>
          <pre>{JSON.stringify(explanation.metadata, null, 2)}</pre>
        </div>
      )}
    </div>
  );
};
