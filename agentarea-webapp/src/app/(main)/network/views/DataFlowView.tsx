"use client";

import { useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Position,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import DataFlowEdge from "../components/edges/DataFlowEdge";
import AgentNode from "../components/nodes/AgentNode";
import MCPNode from "../components/nodes/MCPNode";
import SkillNode from "../components/nodes/SkillNode";
import TriggerNode from "../components/nodes/TriggerNode";
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
const ZONE_PADDING = 50;
const NODE_W = 320;
const NODE_H = 120;
const NODE_GAP_X = 40;
const NODE_GAP_Y = 30;
const SIDE_ZONE_W = 360;
const INTERNAL_ZONE_W = 1200;
const ZONE_GAP = 80;

const COLS_INTERNAL = 4;
type ZoneKey = "gateway" | "internal" | "egress";
const ZONE_X: Record<ZoneKey, number> = {
  gateway: 0,
  internal: SIDE_ZONE_W + ZONE_GAP,
  egress: SIDE_ZONE_W + ZONE_GAP + INTERNAL_ZONE_W + ZONE_GAP,
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
    const agentNodes = topology.nodes.filter((n) => n.type === "agent");
    const zoneNodes: Record<ZoneKey, NetworkNodeData[]> = {
      gateway: [],
      internal: [],
      egress: [],
    };
    for (const n of agentNodes) {
      zoneNodes[getZone(n)].push(n);
    }
    const flowNodes: Node[] = [];
    const flowEdges: Edge[] = [];
    const nodeZoneMap: Record<string, ZoneKey> = {};
    for (const n of agentNodes) nodeZoneMap[n.id] = getZone(n);
    const nodeIds = new Set(agentNodes.map((n) => n.id));
    const sourceToTargets: Record<string, string[]> = {};
    const targetToSources: Record<string, string[]> = {};
    for (const e of topology.edges) {
      if (!nodeIds.has(e.source) || !nodeIds.has(e.target)) continue;
      if (!sourceToTargets[e.source]) sourceToTargets[e.source] = [];
      if (!targetToSources[e.target]) targetToSources[e.target] = [];
      sourceToTargets[e.source].push(e.target);
      targetToSources[e.target].push(e.source);
    }
    const nodePositions: Record<string, { x: number; y: number }> = {};
    const zoneHeights: Record<ZoneKey, number> = {
      gateway: 200,
      internal: 200,
      egress: 200,
    };
    const zoneWidths: Record<ZoneKey, number> = {
      gateway: SIDE_ZONE_W,
      internal: INTERNAL_ZONE_W,
      egress: SIDE_ZONE_W,
    };
    for (const zone of Object.keys(ZONE_META) as ZoneKey[]) {
      const members = zoneNodes[zone];
      members.sort((a, b) => {
        const aTargets = sourceToTargets[a.id] || [];
        const bTargets = sourceToTargets[b.id] || [];
        const aSources = targetToSources[a.id] || [];
        const bSources = targetToSources[b.id] || [];
        const aHasEgress = aTargets.some((t) => nodeZoneMap[t] === "egress");
        const bHasEgress = bTargets.some((t) => nodeZoneMap[t] === "egress");
        if (aHasEgress && !bHasEgress) return -1;
        if (!aHasEgress && bHasEgress) return 1;
        const aFromGateway = aSources.some((s) => nodeZoneMap[s] === "gateway");
        const bFromGateway = bSources.some((s) => nodeZoneMap[s] === "gateway");
        if (aFromGateway && !bFromGateway) return -1;
        if (!aFromGateway && bFromGateway) return 1;
        return 0;
      });
      if (zone === "internal") {
        const cols = Math.min(COLS_INTERNAL, Math.max(1, members.length));
        const rows = Math.ceil(members.length / cols);
        const gridWidth = cols * NODE_W + (cols - 1) * NODE_GAP_X;
        const zoneWidth = Math.max(
          gridWidth + ZONE_PADDING * 2,
          INTERNAL_ZONE_W
        );
        const zoneHeight =
          rows * NODE_H + (rows - 1) * NODE_GAP_Y + ZONE_PADDING * 2;
        zoneHeights[zone] = Math.max(200, zoneHeight);
        zoneWidths[zone] = zoneWidth;
        members.forEach((n, i) => {
          const col = i % cols;
          const row = Math.floor(i / cols);
          const x = ZONE_X[zone] + ZONE_PADDING + col * (NODE_W + NODE_GAP_X);
          const y = ZONE_PADDING + row * (NODE_H + NODE_GAP_Y);
          nodePositions[n.id] = { x, y };
        });
      } else {
        const zoneHeight =
          members.length * NODE_H +
          (members.length - 1) * NODE_GAP_Y +
          ZONE_PADDING * 2;
        zoneHeights[zone] = Math.max(200, zoneHeight);
        members.forEach((n, i) => {
          const y = ZONE_PADDING + i * (NODE_H + NODE_GAP_Y);
          nodePositions[n.id] = {
            x: ZONE_X[zone] + ZONE_PADDING,
            y,
          };
        });
      }
    }
    const maxZoneHeight = Math.max(...Object.values(zoneHeights));
    const egressX = SIDE_ZONE_W + ZONE_GAP + zoneWidths.internal + ZONE_GAP;
    for (const n of zoneNodes.egress) {
      if (nodePositions[n.id]) {
        nodePositions[n.id].x = egressX + ZONE_PADDING;
      }
    }
    for (const [zone, zoneData] of Object.entries(ZONE_META) as [
      ZoneKey,
      (typeof ZONE_META)[ZoneKey],
    ][]) {
      const members = zoneNodes[zone];
      const zoneWidth = zoneWidths[zone];
      const zoneX = zone === "egress" ? egressX : ZONE_X[zone];
      flowNodes.push({
        id: `zone-${zone}`,
        type: "zone",
        position: { x: zoneX, y: 0 },
        data: { label: zoneData.label, color: zoneData.color },
        style: { width: zoneWidth, height: maxZoneHeight },
        selectable: false,
        draggable: false,
        zIndex: -1,
      });
      members.forEach((n) => {
        const pos = nodePositions[n.id];
        if (pos) {
          flowNodes.push({
            id: n.id,
            type: n.type,
            position: pos,
            data: { ...n },
            zIndex: 1,
          });
        }
      });
    }
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
        data: {
          isRisk: crossesBoundary && targetZone === "egress",
          relation: e.relation,
        },
        zIndex: 0,
      });
    }
    return { nodes: flowNodes, edges: flowEdges };
  }, [topology]);
  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.1}
        maxZoom={2}
        onNodeClick={(_, node) => {
          if (node.type === "zone") return;
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
