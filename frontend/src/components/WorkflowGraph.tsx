import { useCallback, useEffect, useMemo, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  type Edge,
  type Node,
  type NodeTypes,
  Panel,
  ReactFlowProvider,
  useEdgesState,
  useNodesState
} from "reactflow";
import "reactflow/dist/style.css";

import { WorkflowStatusNode } from "./WorkflowStatusNode";

export interface WorkflowNode {
  id: string;
  name: string;
  action: string;
  x?: number;
  y?: number;
  position?: { x: number; y: number };
  metadata?: Record<string, unknown>;
  status?: string;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
}

export interface WorkflowGraphData {
  workflow_id: string;
  workflow_version?: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  layout?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

interface WorkflowGraphProps {
  data: WorkflowGraphData;
  /** Optional callback invoked every polling tick to refresh graph data. */
  onRefresh?: () => void;
  /** Polling interval in milliseconds when active nodes exist. @default 2000 */
  pollIntervalMs?: number;
}

/** Custom node type registry — must be defined outside of render to avoid remounts. */
const nodeTypes: NodeTypes = {
  workflowStatus: WorkflowStatusNode
};

const EDGE_ANIMATION_STATUSES = new Set(["running", "retrying"]);
const ACTIVE_POLLING_STATUSES = new Set(["running", "pending", "retrying"]);

/**
 * Maps backend WorkflowNode to ReactFlow Node format.
 * All nodes use the custom `workflowStatus` type.
 */
export function mapWorkflowNodesToReactFlow(nodes: WorkflowNode[]): Node[] {
  return nodes.map((node) => {
    const position = node.position ?? { x: node.x ?? 0, y: node.y ?? 0 };
    return {
      id: node.id,
      type: "workflowStatus",
      position,
      data: {
        label: node.name || node.id,
        action: node.action,
        status: node.status,
        metadata: node.metadata
      }
    };
  });
}

/**
 * Build a Set of node IDs whose status is actively executing.
 */
export function getRunningNodeIds(nodes: WorkflowNode[]): Set<string> {
  const ids = new Set<string>();
  for (const node of nodes) {
    if (node.status && EDGE_ANIMATION_STATUSES.has(node.status)) {
      ids.add(node.id);
    }
  }
  return ids;
}

/**
 * Returns true when at least one node has an active status (`running`, `pending`,
 * or `retrying`) that warrants automatic polling.
 */
export function hasActiveNodes(nodes: WorkflowNode[]): boolean {
  return nodes.some((node) => node.status !== undefined && ACTIVE_POLLING_STATUSES.has(node.status));
}

/**
 * Maps backend WorkflowEdge to ReactFlow Edge format.
 *
 * Edges whose source **or** target is an actively executing node are animated
 * to visually indicate in-progress data flow.
 */
export function mapWorkflowEdgesToReactFlow(
  edges: WorkflowEdge[],
  runningNodeIds?: Set<string>
): Edge[] {
  const running = runningNodeIds ?? new Set<string>();
  return edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    type: "smoothstep",
    animated: running.has(edge.source) || running.has(edge.target)
  }));
}

function WorkflowGraphInner({
  data,
  onRefresh,
  pollIntervalMs = 2000
}: WorkflowGraphProps): JSX.Element {
  const runningIds = useMemo(() => getRunningNodeIds(data.nodes), [data.nodes]);
  const initialNodes = useMemo(() => mapWorkflowNodesToReactFlow(data.nodes), [data.nodes]);
  const initialEdges = useMemo(
    () => mapWorkflowEdgesToReactFlow(data.edges, runningIds),
    [data.edges, runningIds]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);

  useEffect(() => {
    setNodes(initialNodes);
  }, [initialNodes, setNodes]);

  useEffect(() => {
    setEdges(initialEdges);
  }, [initialEdges, setEdges]);

  useEffect(() => {
    setSelectedNode((currentNode) => {
      if (currentNode === null) {
        return null;
      }
      return initialNodes.find((node) => node.id === currentNode.id) ?? null;
    });
  }, [initialNodes]);

  // ---- Polling: auto-refresh while any node is active or retrying ----
  const shouldPoll = useMemo(() => hasActiveNodes(data.nodes), [data.nodes]);

  useEffect(() => {
    if (!shouldPoll || !onRefresh) return;

    const id = setInterval(() => {
      onRefresh();
    }, pollIntervalMs);

    return () => clearInterval(id);
  }, [shouldPoll, onRefresh, pollIntervalMs]);

  const onNodeClick = useCallback((_event: unknown, node: Node) => {
    setSelectedNode(node);
  }, []);

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
  }, []);

  const selectedNodeData = selectedNode
    ? (selectedNode.data as {
        label: string;
        action?: string;
        status?: string;
        metadata?: Record<string, unknown>;
      })
    : null;

  return (
    <div className="workflow-graph-container">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        fitView
        minZoom={0.1}
        maxZoom={2}
      >
        <Background />
        <Controls />
        <Panel position="top-left" className="workflow-graph-header">
          <div>
            <strong>{data.workflow_id}</strong>
            {data.workflow_version ? <span> v{data.workflow_version}</span> : null}
          </div>
          <div className="workflow-graph-stats">
            {data.nodes.length} nodes · {data.edges.length} edges
          </div>
        </Panel>
      </ReactFlow>
      {selectedNode ? (
        <aside className="workflow-graph-detail">
          <h4>Node Details</h4>
          <div className="detail-row">
            <span className="detail-label">ID:</span>
            <span className="detail-value">{selectedNode.id}</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">Name:</span>
            <span className="detail-value">{selectedNodeData?.label}</span>
          </div>
          {selectedNodeData?.action ? (
            <div className="detail-row">
              <span className="detail-label">Action:</span>
              <span className="detail-value">{selectedNodeData.action}</span>
            </div>
          ) : null}
          {selectedNodeData?.status ? (
            <div className="detail-row">
              <span className="detail-label">Status:</span>
              <span className="detail-value">{selectedNodeData.status}</span>
            </div>
          ) : null}
          {selectedNodeData?.metadata ? (
            <div className="detail-row">
              <span className="detail-label">Metadata:</span>
              <pre className="detail-metadata">
                {JSON.stringify(selectedNodeData.metadata, null, 2)}
              </pre>
            </div>
          ) : null}
        </aside>
      ) : null}
    </div>
  );
}

export function WorkflowGraph(props: WorkflowGraphProps): JSX.Element {
  return (
    <ReactFlowProvider>
      <WorkflowGraphInner {...props} />
    </ReactFlowProvider>
  );
}
