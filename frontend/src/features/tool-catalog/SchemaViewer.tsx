/**
 * SchemaViewer: renders a JSON Schema in a human-readable tree format.
 *
 * Supports nested objects, arrays, required markers, and descriptions.
 */

import { useMemo } from "react";

interface SchemaViewerProps {
  schema: Record<string, unknown>;
}

interface SchemaNode {
  key: string;
  type: string;
  description?: string;
  required: boolean;
  children: SchemaNode[];
  enumValues?: string[];
  defaultValue?: unknown;
}

function parseSchemaProperties(
  schema: Record<string, unknown>,
  requiredSet: Set<string>
): SchemaNode[] {
  const properties = (schema.properties ?? {}) as Record<string, Record<string, unknown>>;
  const nodes: SchemaNode[] = [];

  for (const [key, prop] of Object.entries(properties)) {
    const type = String(prop.type ?? "any");
    const description = prop.description ? String(prop.description) : undefined;
    const enumValues = Array.isArray(prop.enum)
      ? prop.enum.map((v: unknown) => String(v))
      : undefined;
    const defaultValue = prop.default;

    let children: SchemaNode[] = [];
    if (type === "object" && prop.properties) {
      const childRequired = new Set(
        Array.isArray(prop.required) ? (prop.required as string[]) : []
      );
      children = parseSchemaProperties(prop as Record<string, unknown>, childRequired);
    }
    if (type === "array" && prop.items && typeof prop.items === "object") {
      const items = prop.items as Record<string, unknown>;
      if (items.properties) {
        const childRequired = new Set(
          Array.isArray(items.required) ? (items.required as string[]) : []
        );
        children = parseSchemaProperties(items as Record<string, unknown>, childRequired);
      }
    }

    nodes.push({
      key,
      type,
      description,
      required: requiredSet.has(key),
      children,
      enumValues,
      defaultValue,
    });
  }

  return nodes;
}

function SchemaNodeRow({ node, depth }: { node: SchemaNode; depth: number }): JSX.Element {
  return (
    <div
      role="treeitem"
      aria-level={depth + 1}
      aria-expanded={node.children.length > 0 ? true : undefined}
    >
      <div
        className="schema-node"
        style={{ paddingLeft: `${depth * 1.2}rem` }}
      >
        <span className="schema-key">{node.key}</span>
        <span className="schema-type">{node.type}</span>
        {node.required && <span className="schema-required">required</span>}
        {node.defaultValue !== undefined && (
          <span className="schema-default">= {JSON.stringify(node.defaultValue)}</span>
        )}
        {node.enumValues && (
          <span className="schema-enum">[{node.enumValues.join(" | ")}]</span>
        )}
        {node.description && (
          <span className="schema-desc">{node.description}</span>
        )}
      </div>
      {node.children.length > 0 && (
        <div role="group">
          {node.children.map((child) => (
            <SchemaNodeRow key={child.key} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

export function SchemaViewer({ schema }: SchemaViewerProps): JSX.Element {
  const nodes = useMemo(() => {
    const required = new Set(
      Array.isArray(schema.required) ? (schema.required as string[]) : []
    );
    return parseSchemaProperties(schema, required);
  }, [schema]);

  if (nodes.length === 0) {
    return <p className="schema-empty">No parameters defined.</p>;
  }

  return (
    <div className="schema-viewer" role="tree" aria-label="JSON Schema">
      {nodes.map((node) => (
        <SchemaNodeRow key={node.key} node={node} depth={0} />
      ))}
    </div>
  );
}
