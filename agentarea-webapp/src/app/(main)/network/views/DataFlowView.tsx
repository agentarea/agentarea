"use client";

import { useMemo } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  type Node,
  type Edge,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import AgentNode from "../components/nodes/AgentNode";
import MCPNode from "../components/nodes/MCPNode";
import SkillNode from "../components/nodes/SkillNode";
import TriggerNode from "../components/nodes/TriggerNode";
import DataFlowEdge from "../components/edges/DataFlowEdge";
import ZoneContainer from "../components/ZoneContainer";

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

const nodeTypes = {
  agent: AgentNode,
  mcp_instance: MCPNode,
  skill: SkillNode,
  trigger: TriggerNode,
  zone: ZoneContainer,
};

const edgeTypes = {
  dataflow: DataFlowEdge,
};

// Zone x-ranges (left edge of zone)
const ZONE_PADDING = 40;
const NODE_W = 240;
const NODE_H = 90;
const NODE_GAP = 24;
const ZONE_W = 320;
const ZONE_H_MIN = 160;

type ZoneKey = "gateway" | "internal" | "egress";

const ZONE_X: Record<ZoneKey, number> = {
  gateway: 0,
  internal: ZONE_W + 60,
  egress: (ZONE_W + 60) * 2,
};

const ZONE_META: Record<ZoneKey, { label: string; color: string }> = {
  gateway: { label: "Gateway — Ingress", color: "amber" },
  internal: { label: "VPC Internal — Governed", color: "blue" },
  egress: { label: "Egress", color: "orange" },
};

function getZone(node: NetworkNodeData): ZoneKey {
  if (node.type === "trigger") {
    return node.metadata?.trigger_type === "webhook" ? "gateway" : "internal";
  }
  if (node.type === "mcp_instance" || node.type === "skill") {
    return node.metadata?.network_scope === "egress" ? "egress" : "internal";
  }
  return "internal";
}

export default function DataFlowView({ topology, onNodeClick }: Props) {
  const { nodes, edges } = useMemo(() => {
    const zoneNodes: Record<ZoneKey, NetworkNodeData[]> = {
      gateway: [],
      internal: [],
      egress: [],
    };

    for (const n of topology.nodes) {
      zoneNodes[getZone(n)].push(n);
    }

    const flowNodes: Node[] = [];
    const flowEdges: Edge[] = [];

    // Place zone containers + entity nodes
    for (const [zone, zoneData] of Object.entries(ZONE_META) as [ZoneKey, typeof ZONE_META[ZoneKey]][]) {
      const members = zoneNodes[zone];
      const zoneHeight = Math.max(
        ZONE_H_MIN,
        members.length * (NODE_H + NODE_GAP) + ZONE_PADDING * 2
      );

      flowNodes.push({
        id: `zone-${zone}`,
        type: "zone",
        position: { x: ZONE_X[zone], y: 0 },
        data: { label: zoneData.label, color: zoneData.color },
        style: { width: ZONE_W, height: zoneHeight },
        selectable: false,
        draggable: false,
        zIndex: -1,
      });

      members.forEach((n, i) => {
        flowNodes.push({
          id: n.id,
          type: n.type,
          position: {
            x: ZONE_X[zone] + ZONE_PADDING,
            y: ZONE_PADDING + i * (NODE_H + NODE_GAP),
          },
          data: { ...n },
          zIndex: 1,
        });
      });
    }

    // Build edges with risk detection
    const nodeZoneMap: Record<string, ZoneKey> = {};
    for (const n of topology.nodes) nodeZoneMap[n.id] = getZone(n);

    const nodeIds = new Set(topology.nodes.map((n) => n.id));

    for (const e of topology.edges) {
      if (!nodeIds.has(e.source) || !nodeIds.has(e.target)) continue;

      const sourceZone = nodeZoneMap[e.source];
      const targetZone = nodeZoneMap[e.target];
      const crossesBoundary =
        (sourceZone === "internal" && targetZone === "egress") ||
        (sourceZone === "gateway" && targetZone === "internal");

      flowEdges.push({
        id: e.id,
        source: e.source,
        target: e.target,
        type: "dataflow",
        data: { isRisk: crossesBoundary && targetZone === "egress", relation: e.relation },
        zIndex: 2,
      });
    }

    return { nodes: flowNodes, edges: flowEdges };
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
        minZoom={0.3}
        maxZoom={2}
        onNodeClick={(_, node) => {
          if (node.type === "zone") return;
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
