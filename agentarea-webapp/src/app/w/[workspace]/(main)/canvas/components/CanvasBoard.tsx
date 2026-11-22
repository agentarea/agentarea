"use client";

import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useRef, type RefObject } from "react";
import { useTheme } from "next-themes";
import {
  Background,
  BackgroundVariant,
  ConnectionMode,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type NodeChange,
  type NodeChangeset,
} from "@xyflow/react";
import type { Canvas, Link, Point, TileFrame } from "../utils/canvasState";
import { EDGE_TYPES, type CanvasEdge } from "./CanvasEdge";
import { NODE_TYPES, type CanvasNode } from "./CanvasTiles";

export type BoardApi = {
  /** The canvas point under the middle of the visible board. */
  centre: () => Point;
  focus: (tileId: string) => void;
};

function toNodes(
  tiles: Canvas["tiles"],
  selected: ReadonlySet<string>
): CanvasNode[] {
  return tiles.map((tile) => ({
    id: tile.id,
    type: tile.kind,
    data: tile,
    position: { x: tile.frame.x, y: tile.frame.y },
    width: tile.frame.width,
    height: tile.frame.height,
    selected: selected.has(tile.id),
    dragHandle: ".canvas-tile-handle",
  }));
}

function toEdges(links: Link[], selected: ReadonlySet<string>): CanvasEdge[] {
  return links.map((link) => ({
    id: link.id,
    type: "floating",
    source: link.from,
    target: link.to,
    data: { label: link.label },
    selected: selected.has(link.id),
    markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
  }));
}

function selectedIds(items: { id: string; selected?: boolean }[]) {
  return new Set(items.filter((item) => item.selected).map((item) => item.id));
}

function frameOf(node: CanvasNode): TileFrame {
  return {
    x: node.position.x,
    y: node.position.y,
    width: node.width ?? node.measured?.width ?? node.data.frame.width,
    height: node.height ?? node.measured?.height ?? node.data.frame.height,
  };
}

// A drag or a resize reports its last change with the flag off; only those
// are worth writing back, the in-between ones would rewrite the store per frame.
function settles(change: NodeChange<CanvasNode>): boolean {
  return (
    (change.type === "position" && change.dragging === false) ||
    (change.type === "dimensions" && change.resizing === false)
  );
}

export default function CanvasBoard({
  canvas,
  apiRef,
  onFrames,
  onLink,
  children,
}: {
  canvas: Canvas;
  apiRef: RefObject<BoardApi | null>;
  onFrames: (frames: Record<string, TileFrame>) => void;
  onLink: (from: string, to: string) => void;
  children?: React.ReactNode;
}) {
  const { resolvedTheme } = useTheme();
  const { fitView, screenToFlowPosition } = useReactFlow();
  const containerRef = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasNode>(
    toNodes(canvas.tiles, new Set())
  );
  const [edges, setEdges, onEdgesChange] = useEdgesState<CanvasEdge>(
    toEdges(canvas.links, new Set())
  );
  const settled = useRef(false);

  useEffect(() => {
    setNodes((current) => toNodes(canvas.tiles, selectedIds(current)));
  }, [canvas.tiles, setNodes]);

  useEffect(() => {
    setEdges((current) => toEdges(canvas.links, selectedIds(current)));
  }, [canvas.links, setEdges]);

  const handleNodesChange = useCallback(
    (changes: NodeChangeset<CanvasNode>) => {
      if (changes.toArray().some(settles)) settled.current = true;
      onNodesChange(changes);
    },
    [onNodesChange]
  );

  useEffect(() => {
    if (!settled.current) return;
    settled.current = false;
    onFrames(Object.fromEntries(nodes.map((node) => [node.id, frameOf(node)])));
  }, [nodes, onFrames]);

  const onConnect = useCallback(
    (connection: Connection) => onLink(connection.source, connection.target),
    [onLink]
  );

  const focus = useCallback(
    (tileId: string) =>
      void fitView({ nodes: [{ id: tileId }], padding: 0.04, duration: 400 }),
    [fitView]
  );

  useEffect(() => {
    apiRef.current = {
      centre: () => {
        const rect = containerRef.current?.getBoundingClientRect();
        if (!rect) return { x: 0, y: 0 };
        return screenToFlowPosition({
          x: rect.left + rect.width / 2,
          y: rect.top + rect.height / 2,
        });
      },
      focus,
    };
    return () => {
      apiRef.current = null;
    };
  }, [apiRef, focus, screenToFlowPosition]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setNodes((current) =>
        current.map((node) => ({ ...node, selected: false }))
      );
      void fitView({ padding: 0.1, maxZoom: 1, duration: 400 });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fitView, setNodes]);

  return (
    <div ref={containerRef} className="relative h-full min-h-0 w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={handleNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        connectionMode={ConnectionMode.Loose}
        onNodeDoubleClick={(_event, node) => focus(node.id)}
        forceColorMode={resolvedTheme === "dark" ? "dark" : "light"}
        deleteKeyCode={null}
        zoomOnDoubleClick={false}
        minZoom={0.05}
        maxZoom={2}
        fitView
        fitViewOptions={{ padding: 0.08, maxZoom: 1 }}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1.5} />
        <Controls showInteractive={false} position="bottom-left" />
        <MiniMap pannable zoomable position="bottom-right" />
      </ReactFlow>
      {children}
    </div>
  );
}
