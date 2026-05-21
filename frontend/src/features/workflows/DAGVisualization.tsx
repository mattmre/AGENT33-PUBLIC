import { useCallback, useMemo, useRef, useState } from "react";

import type { DAGEdge, DAGLayout, DAGNode } from "./DAGTypes";
import { dagStatusLabel, dagStatusToColor } from "./DAGTypes";

/** Dimensions for each node rectangle in the SVG. */
const NODE_W = 180;
const NODE_H = 60;
const NODE_RX = 10;
const ARROW_SIZE = 8;

interface DAGVisualizationProps {
  dagLayout: DAGLayout;
  onNodeClick?: (nodeId: string) => void;
  /** Called when the user requests an artifact download for the current run. */
  onDownloadArtifacts?: (runId: string) => void;
  /** Called when the user requests a per-step retry. */
  onRetryStep?: (runId: string, stepId: string) => void;
}

// ---------------------------------------------------------------------------
// Tooltip state
// ---------------------------------------------------------------------------

interface TooltipInfo {
  node: DAGNode;
  screenX: number;
  screenY: number;
}

// ---------------------------------------------------------------------------
// Edge rendering
// ---------------------------------------------------------------------------

function edgePath(
  source: DAGNode,
  target: DAGNode
): { d: string; markerX: number; markerY: number; angle: number } {
  const sx = source.x + NODE_W;
  const sy = source.y + NODE_H / 2;
  const tx = target.x;
  const ty = target.y + NODE_H / 2;

  const midX = (sx + tx) / 2;
  const d = `M ${sx} ${sy} C ${midX} ${sy}, ${midX} ${ty}, ${tx} ${ty}`;

  const angle = Math.atan2(ty - sy, tx - midX) * (180 / Math.PI);

  return { d, markerX: tx, markerY: ty, angle };
}

function DAGEdgeElement({
  edge,
  nodeMap
}: {
  edge: DAGEdge;
  nodeMap: Map<string, DAGNode>;
}): JSX.Element | null {
  const source = nodeMap.get(edge.source);
  const target = nodeMap.get(edge.target);
  if (!source || !target) return null;

  const { d, markerX, markerY, angle } = edgePath(source, target);
  const sourceColor = dagStatusToColor(source.status);

  return (
    <g data-testid={`edge-${edge.source}-${edge.target}`}>
      <path d={d} fill="none" stroke={sourceColor} strokeWidth={2} strokeOpacity={0.6} />
      <polygon
        points={`0,${-ARROW_SIZE / 2} ${ARROW_SIZE},0 0,${ARROW_SIZE / 2}`}
        fill={sourceColor}
        fillOpacity={0.6}
        transform={`translate(${markerX},${markerY}) rotate(${angle})`}
      />
      {edge.label ? (
        <text
          x={(source.x + NODE_W + target.x) / 2}
          y={(source.y + NODE_H / 2 + target.y + NODE_H / 2) / 2 - 6}
          textAnchor="middle"
          fontSize={11}
          fill="#94a3b8"
        >
          {edge.label}
        </text>
      ) : null}
    </g>
  );
}

// ---------------------------------------------------------------------------
// Node rendering
// ---------------------------------------------------------------------------

function DAGNodeElement({
  node,
  onClick,
  onHoverStart,
  onHoverEnd
}: {
  node: DAGNode;
  onClick?: (nodeId: string) => void;
  onHoverStart: (node: DAGNode, e: React.MouseEvent) => void;
  onHoverEnd: () => void;
}): JSX.Element {
  const color = dagStatusToColor(node.status);
  const isRunning = node.status === "running" || node.status === "retrying";

  return (
    <g
      data-testid={`node-${node.id}`}
      role="button"
      aria-label={`${node.label}: ${dagStatusLabel(node.status)}`}
      tabIndex={0}
      style={{ cursor: "pointer" }}
      onClick={() => onClick?.(node.id)}
      onMouseEnter={(e) => onHoverStart(node, e)}
      onMouseLeave={onHoverEnd}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick?.(node.id);
        }
      }}
    >
      {/* Background rect */}
      <rect
        x={node.x}
        y={node.y}
        width={NODE_W}
        height={NODE_H}
        rx={NODE_RX}
        ry={NODE_RX}
        fill="rgba(15, 23, 42, 0.9)"
        stroke={color}
        strokeWidth={2}
      >
        {isRunning ? (
          <animate attributeName="stroke-opacity" values="1;0.4;1" dur="1.5s" repeatCount="indefinite" />
        ) : null}
      </rect>

      {/* Node label */}
      <text
        x={node.x + NODE_W / 2}
        y={node.y + 24}
        textAnchor="middle"
        fill="#e2e8f0"
        fontSize={13}
        fontWeight={600}
        fontFamily="'Space Grotesk', 'Segoe UI', sans-serif"
      >
        {node.label.length > 20 ? node.label.slice(0, 18) + "..." : node.label}
      </text>

      {/* Status badge */}
      <rect
        x={node.x + NODE_W / 2 - 30}
        y={node.y + 34}
        width={60}
        height={18}
        rx={4}
        ry={4}
        fill={`${color}20`}
      />
      <text
        x={node.x + NODE_W / 2}
        y={node.y + 47}
        textAnchor="middle"
        fill={color}
        fontSize={10}
        fontWeight={600}
        fontFamily="'Space Grotesk', 'Segoe UI', sans-serif"
        letterSpacing={0.5}
        style={{ textTransform: "uppercase" }}
      >
        {dagStatusLabel(node.status)}
      </text>
    </g>
  );
}

// ---------------------------------------------------------------------------
// Tooltip overlay
// ---------------------------------------------------------------------------

function DAGTooltip({
  info,
  containerRef,
  onRetryStep,
  runId
}: {
  info: TooltipInfo;
  containerRef: React.RefObject<HTMLDivElement | null>;
  onRetryStep?: (runId: string, stepId: string) => void;
  runId: string | null;
}): JSX.Element {
  const containerRect = containerRef.current?.getBoundingClientRect();
  const left = info.screenX - (containerRect?.left ?? 0) + 12;
  const top = info.screenY - (containerRect?.top ?? 0) - 10;

  return (
    <div
      data-testid="dag-tooltip"
      role="tooltip"
      style={{
        position: "absolute",
        left,
        top,
        background: "rgba(15, 23, 42, 0.95)",
        border: "1px solid #334155",
        borderRadius: 8,
        padding: "8px 12px",
        color: "#e2e8f0",
        fontSize: "0.8rem",
        fontFamily: "'Space Grotesk', 'Segoe UI', sans-serif",
        pointerEvents: "none",
        zIndex: 10,
        maxWidth: 240,
        whiteSpace: "nowrap"
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{info.node.label}</div>
      <div>Type: {info.node.type}</div>
      <div>Status: {dagStatusLabel(info.node.status)}</div>
      {info.node.agent_id ? <div>Agent: {info.node.agent_id}</div> : null}
      {info.node.duration_ms != null ? (
        <div>Duration: {info.node.duration_ms.toFixed(1)}ms</div>
      ) : null}
      {info.node.status === "failed" && onRetryStep && runId ? (
        <button
          data-testid={`retry-step-${info.node.id}`}
          onClick={() => onRetryStep(runId, info.node.id)}
          style={{
            marginTop: 8,
            padding: "3px 10px",
            background: "rgba(239, 68, 68, 0.15)",
            border: "1px solid #ef4444",
            color: "#ef4444",
            borderRadius: 4,
            cursor: "pointer",
            fontSize: "0.75rem",
            fontWeight: 600,
            pointerEvents: "auto"
          }}
        >
          Retry step
        </button>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function DAGVisualization({
  dagLayout,
  onNodeClick,
  onDownloadArtifacts,
  onRetryStep
}: DAGVisualizationProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [tooltip, setTooltip] = useState<TooltipInfo | null>(null);
  const [scale, setScale] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const panStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 });

  const nodeMap = useMemo(() => {
    const map = new Map<string, DAGNode>();
    for (const node of dagLayout.nodes) {
      map.set(node.id, node);
    }
    return map;
  }, [dagLayout.nodes]);

  const handleHoverStart = useCallback((node: DAGNode, e: React.MouseEvent) => {
    setTooltip({ node, screenX: e.clientX, screenY: e.clientY });
  }, []);

  const handleHoverEnd = useCallback(() => {
    setTooltip(null);
  }, []);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    setScale((prev) => Math.min(3, Math.max(0.2, prev * delta)));
  }, []);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (e.button !== 0) return;
      setIsPanning(true);
      panStart.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y };
    },
    [pan]
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!isPanning) return;
      const dx = e.clientX - panStart.current.x;
      const dy = e.clientY - panStart.current.y;
      setPan({ x: panStart.current.panX + dx, y: panStart.current.panY + dy });
    },
    [isPanning]
  );

  const handleMouseUp = useCallback(() => {
    setIsPanning(false);
  }, []);

  const svgWidth = Math.max(dagLayout.width, 400);
  const svgHeight = Math.max(dagLayout.height, 300);

  return (
    <div
      ref={containerRef}
      data-testid="dag-visualization"
      style={{ position: "relative", width: "100%", height: "100%", overflow: "hidden" }}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      <svg
        width="100%"
        height="100%"
        viewBox={`0 0 ${svgWidth} ${svgHeight}`}
        style={{ display: "block" }}
      >
        <g transform={`translate(${pan.x},${pan.y}) scale(${scale})`}>
          {/* Render edges first (behind nodes) */}
          {dagLayout.edges.map((edge) => (
            <DAGEdgeElement
              key={`${edge.source}-${edge.target}`}
              edge={edge}
              nodeMap={nodeMap}
            />
          ))}

          {/* Render nodes */}
          {dagLayout.nodes.map((node) => (
            <DAGNodeElement
              key={node.id}
              node={node}
              onClick={onNodeClick}
              onHoverStart={handleHoverStart}
              onHoverEnd={handleHoverEnd}
            />
          ))}
        </g>
      </svg>

      {tooltip ? (
        <DAGTooltip
          info={tooltip}
          containerRef={containerRef}
          onRetryStep={onRetryStep}
          runId={dagLayout.run_id}
        />
      ) : null}

      {/* Download artifacts button */}
      {onDownloadArtifacts && dagLayout.run_id ? (
        <button
          data-testid="dag-download-artifacts"
          onClick={() => onDownloadArtifacts(dagLayout.run_id!)}
          style={{
            position: "absolute",
            bottom: 12,
            left: 12,
            background: "rgba(15, 23, 42, 0.8)",
            border: "1px solid #334155",
            color: "#94a3b8",
            borderRadius: 6,
            padding: "4px 10px",
            cursor: "pointer",
            fontSize: 12,
            fontFamily: "'Space Grotesk', 'Segoe UI', sans-serif"
          }}
          aria-label="Download artifacts"
        >
          ↓ Artifacts
        </button>
      ) : null}

      {/* Zoom controls */}
      <div
        style={{
          position: "absolute",
          bottom: 12,
          right: 12,
          display: "flex",
          gap: 4,
          background: "rgba(15, 23, 42, 0.8)",
          borderRadius: 6,
          padding: 4
        }}
      >
        <button
          data-testid="dag-zoom-in"
          onClick={() => setScale((s) => Math.min(3, s * 1.2))}
          style={{
            background: "transparent",
            border: "1px solid #334155",
            color: "#e2e8f0",
            borderRadius: 4,
            width: 28,
            height: 28,
            cursor: "pointer",
            fontSize: 16
          }}
          aria-label="Zoom in"
        >
          +
        </button>
        <button
          data-testid="dag-zoom-out"
          onClick={() => setScale((s) => Math.max(0.2, s / 1.2))}
          style={{
            background: "transparent",
            border: "1px solid #334155",
            color: "#e2e8f0",
            borderRadius: 4,
            width: 28,
            height: 28,
            cursor: "pointer",
            fontSize: 16
          }}
          aria-label="Zoom out"
        >
          -
        </button>
        <button
          data-testid="dag-zoom-reset"
          onClick={() => {
            setScale(1);
            setPan({ x: 0, y: 0 });
          }}
          style={{
            background: "transparent",
            border: "1px solid #334155",
            color: "#e2e8f0",
            borderRadius: 4,
            width: 28,
            height: 28,
            cursor: "pointer",
            fontSize: 11
          }}
          aria-label="Reset zoom"
        >
          1:1
        </button>
      </div>
    </div>
  );
}
