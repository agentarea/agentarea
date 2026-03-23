"use client";

import { useMemo } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  type Node,
  type Edge,
} from "@xyflow/react";
import dagre from "@dagrejs/dagre";
import "@xyflow/react/dist/style.css";
import AgentNode from "../components/nodes/AgentNode";
import MCPNode from "../components/nodes/MCPNode";
import SkillNode from "../components/nodes/SkillNode";
import TriggerNode from "../components/nodes/TriggerNode";
import DataFlowEdge from "../components/edges/DataFlowEdge";

interface NetworkNodeData {
  id: string;
  type: "agent" | "mcp_instance" | "skill" | "trigger";
  label: string;
  status?: string | null;
  metadata: Record<string, any>;
}

interface NetworkEdgeData {
  id: string;
  source: string;
  target: string;
  relation: string;
}

interface TopologyResponse {
  nodes: NetworkNodeData[];
  edges: NetworkEdgeData[];
  governance: any[];
  deployment_mode: string;
}

interface Props {
  topology: TopologyResponse;
  onNodeClick?: (node: NetworkNodeData) => void;
}

const NODE_W: Record<string, number> = {
  agent: 240,
  mcp_instance: 200,
  skill: 200,
  trigger: 200,
};
const NODE_H = 90;

const nodeTypes = {
  agent: AgentNode,
  mcp_instance: MCPNode,
  skill: SkillNode,
  trigger: TriggerNode,
};

const edgeTypes = {
  dataflow: DataFlowEdge,
};

function layout(nodes: Node[], edges: Edge[]): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 40, ranksep: 80 });

  nodes.forEach((n) => {
    g.setNode(n.id, { width: NODE_W[n.type ?? "agent"] ?? 200, height: NODE_H });
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

export default function OrgChartView({ topology, onNodeClick }: Props) {
  const { nodes, edges } = useMemo(() => {
    const nodeIds = new Set(topology.nodes.map((n) => n.id));

    const flowNodes: Node[] = topology.nodes.map((n) => ({
      id: n.id,
      type: n.type,
      position: { x: 0, y: 0 },
      data: { ...n },
    }));

    const flowEdges: Edge[] = topology.edges
      .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
      .map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        type: "dataflow",
        data: { relation: e.relation },
      }));

    return layout(flowNodes, flowEdges);
  }, [topology]);

  return (
    <div className="h-[calc(100vh-16rem)] w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.2}
        maxZoom={2}
        onNodeClick={(_, node) => {
          const networkNode = topology.nodes.find((n) => n.id === node.id);
          if (networkNode) onNodeClick?.(networkNode);
        }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#e4e4e7" className="dark:!bg-zinc-900" />
        <Controls className="!shadow-sm !border !border-zinc-200 dark:!border-zinc-700 !rounded-xl overflow-hidden" />
      </ReactFlow>
    </div>
  );
}
