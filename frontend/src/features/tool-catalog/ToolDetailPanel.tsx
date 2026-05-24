/**
 * ToolDetailPanel: displays tool detail with schema when available.
 */

import { SchemaViewer } from "./SchemaViewer";
import type { CatalogEntry } from "./types";

interface ToolDetailPanelProps {
  tool: CatalogEntry;
  onClose: () => void;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.length > 0);
}

export function ToolDetailPanel({ tool, onClose }: ToolDetailPanelProps): JSX.Element {
  const requiredScope = stringValue(tool.governance.required_scope);
  const commandAllowlist = stringList(tool.governance.command_allowlist);
  const pathAllowlist = stringList(tool.governance.path_allowlist);
  const domainAllowlist = stringList(tool.governance.domain_allowlist);
  const provenanceLicense = stringValue(tool.provenance.license);
  const provenanceRepo = stringValue(tool.provenance.repo_url);

  return (
    <div className="tool-detail-panel" role="complementary" aria-label={`Details for ${tool.name}`}>
      <header className="tool-detail-header">
        <h2>{tool.name}</h2>
        <button onClick={onClose} aria-label="Close detail panel">
          Close
        </button>
      </header>

      <div className="tool-detail-body">
        <p className="tool-description">{tool.description || "No description available."}</p>

        <dl className="tool-metadata">
          <dt>Provider</dt>
          <dd>{tool.provider}{tool.provider_name ? ` (${tool.provider_name})` : ""}</dd>

          <dt>Category</dt>
          <dd>{tool.category}</dd>

          <dt>Version</dt>
          <dd>{tool.version || "N/A"}</dd>

          <dt>Status</dt>
          <dd>{tool.status || (tool.enabled ? "enabled" : "disabled")}</dd>

          {tool.owner && (
            <>
              <dt>Owner</dt>
              <dd>{tool.owner}</dd>
            </>
          )}

          {requiredScope && (
            <>
              <dt>Required scope</dt>
              <dd>{requiredScope}</dd>
            </>
          )}

          {provenanceLicense && (
            <>
              <dt>License</dt>
              <dd>{provenanceLicense}</dd>
            </>
          )}

          {provenanceRepo && (
            <>
              <dt>Source</dt>
              <dd>{provenanceRepo}</dd>
            </>
          )}

          {commandAllowlist.length > 0 && (
            <>
              <dt>Command allowlist</dt>
              <dd>{commandAllowlist.join(", ")}</dd>
            </>
          )}

          {pathAllowlist.length > 0 && (
            <>
              <dt>Path allowlist</dt>
              <dd>{pathAllowlist.join(", ")}</dd>
            </>
          )}

          {domainAllowlist.length > 0 && (
            <>
              <dt>Domain allowlist</dt>
              <dd>{domainAllowlist.join(", ")}</dd>
            </>
          )}

          {tool.last_review && (
            <>
              <dt>Last review</dt>
              <dd>{tool.last_review}</dd>
            </>
          )}

          {tool.next_review && (
            <>
              <dt>Next review</dt>
              <dd>{tool.next_review}</dd>
            </>
          )}

          {tool.deprecation_message && (
            <>
              <dt>Deprecation</dt>
              <dd>{tool.deprecation_message}</dd>
            </>
          )}

          {tool.tags.length > 0 && (
            <>
              <dt>Tags</dt>
              <dd>
                {tool.tags.map((tag) => (
                  <span key={tag} className="tool-tag">
                    {tag}
                  </span>
                ))}
              </dd>
            </>
          )}
        </dl>

        {tool.has_schema && Object.keys(tool.parameters_schema).length > 0 && (
          <section className="tool-schema-section">
            <h3>Parameters Schema</h3>
            <SchemaViewer schema={tool.parameters_schema} />
          </section>
        )}

        {Object.keys(tool.result_schema).length > 0 && (
          <section className="tool-schema-section">
            <h3>Result Schema</h3>
            <SchemaViewer schema={tool.result_schema} />
          </section>
        )}

        {!tool.has_schema && (
          <p className="tool-no-schema">No parameter schema declared for this tool.</p>
        )}
      </div>
    </div>
  );
}
