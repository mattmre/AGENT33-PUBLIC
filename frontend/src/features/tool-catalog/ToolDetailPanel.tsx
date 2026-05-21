/**
 * ToolDetailPanel: displays tool detail with schema when available.
 */

import { SchemaViewer } from "./SchemaViewer";
import type { CatalogEntry } from "./types";

interface ToolDetailPanelProps {
  tool: CatalogEntry;
  onClose: () => void;
}

export function ToolDetailPanel({ tool, onClose }: ToolDetailPanelProps): JSX.Element {
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
          <dd>{tool.enabled ? "Enabled" : "Disabled"}</dd>

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
