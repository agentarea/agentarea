"use client";

import { useMemo } from "react";
import dagre from "@dagrejs/dagre";
import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import DataFlowEdge from "../components/edges/DataFlowEdge";
import AgentNode from "../components/nodes/AgentNode";
import MCPNode from "../components/nodes/MCPNode";
import OpenAPINode from "../components/nodes/OpenAPINode";
import SkillNode from "../components/nodes/SkillNode";
import TriggerNode from "../components/nodes/TriggerNode";
import type { NetworkNodeData, TopologyResponse } from "../types";
import { computeHighlightSets } from "../utils/highlight";

interface Props {
  topology: TopologyResponse;
  onNodeClick?: (node: NetworkNodeData) => void;
  highlightId?: string | null;
  onPaneClick?: () => void;
}

const NODE_W: Record<string, number> = {
  agent: 128,
  mcp_instance: 128,
  openapi_connection: 128,
  skill: 128,
  trigger: 128,
};
const NODE_H = 110;

const nodeTypes = {
  agent: AgentNode,
  mcp_instance: MCPNode,
  openapi_connection: OpenAPINode,
  skill: SkillNode,
  trigger: TriggerNode,
};

const edgeTypes = {
  dataflow: DataFlowEdge,
};

function layout(
  nodes: Node[],
  edges: Edge[]
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 28, ranksep: 60 });

  nodes.forEach((n) => {
    g.setNode(n.id, {
      width: NODE_W[n.type ?? "agent"] ?? 200,
      height: NODE_H,
    });
  });
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);

  return {
    nodes: nodes.map((n) => {
      const pos = g.node(n.id);
      const w = NODE_W[n.type ?? "agent"] ?? 200;
      return { ...n, position: { x: pos.x - w / 2, y: pos.y - NODE_H / 2 } };
    }),
    edges,
  };
}

export default function OrgChartView({
  topology,
  onNodeClick,
  highlightId,
  onPaneClick,
}: Props) {
  const { nodes, edges } = useMemo(() => {
    const nodeIds = new Set(topology.nodes.map((n) => n.id));
    const highlight = computeHighlightSets(highlightId, topology.edges);

    const flowNodes: Node[] = topology.nodes.map((n) => {
      const isHighlighted = !!highlight?.nodes.has(n.id);
      const isDimmed = !!highlight && !isHighlighted;
      return {
        id: n.id,
        type: n.type,
        position: { x: 0, y: 0 },
        data: {
          ...n,
          _dimmed: isDimmed,
          _highlighted: isHighlighted && n.id === highlightId,
        },
      };
    });

    const flowEdges: Edge[] = topology.edges
      .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
      .map((e) => {
        const isHighlightedEdge = !!highlight?.edges.has(e.id);
        const isDimmedEdge = !!highlight && !isHighlightedEdge;
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          type: "dataflow",
          data: {
            relation: e.relation,
            highlighted: isHighlightedEdge,
            dimmed: isDimmedEdge,
          },
          zIndex: isHighlightedEdge ? 2 : 0,
        };
      });

    return layout(flowNodes, flowEdges);
  }, [topology, highlightId]);

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        nodesConnectable={false}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.2}
        maxZoom={2}
        onPaneClick={onPaneClick}
        onNodeClick={(_, node) => {
          const networkNode = topology.nodes.find((n) => n.id === node.id);
          if (networkNode) onNodeClick?.(networkNode);
        }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color="#e4e4e7"
          className="dark:!bg-zinc-900"
        />
        <Controls className="!shadow-sm !border !border-zinc-200 dark:!border-zinc-700 !rounded-xl overflow-hidden" />
      </ReactFlow>
    </div>
  );
}
