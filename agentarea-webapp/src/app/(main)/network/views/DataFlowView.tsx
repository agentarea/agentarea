"use client";

import { useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import LaneRail from "../components/LaneRail";
import DataFlowEdge from "../components/edges/DataFlowEdge";
import AgentNode from "../components/nodes/AgentNode";
import MCPNode from "../components/nodes/MCPNode";
import OpenAPINode from "../components/nodes/OpenAPINode";
import SkillNode from "../components/nodes/SkillNode";
import TriggerNode from "../components/nodes/TriggerNode";
import { computeHighlightSets } from "../utils/highlight";
import { layoutClusters, type Lane } from "../utils/clusterLayout";

interface NetworkNodeData {
  id: string;
  type: "agent" | "mcp_instance" | "openapi_connection" | "skill" | "trigger";
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
  highlightId?: string | null;
  onPaneClick?: () => void;
}

const nodeTypes = {
  agent: AgentNode,
  mcp_instance: MCPNode,
  openapi_connection: OpenAPINode,
  skill: SkillNode,
  trigger: TriggerNode,
  lane: LaneRail,
};

const edgeTypes = {
  dataflow: DataFlowEdge,
};

const LANE_X: Record<Lane, number> = {
  events: 0,
  agents: 420,
  external: 840,
};

const LANE_META: Record<Lane, { label: string; sublabel: string }> = {
  events: { label: "Events", sublabel: "Triggers · webhooks · schedules" },
  agents: { label: "Agents", sublabel: "Internal — governed" },
  external: { label: "External", sublabel: "MCP · OpenAPI · skills (egress)" },
};

const ROW_H = 150;
const CLUSTER_GAP = 90;
const NODE_HALF_W = 80;
const NODE_HALF_H = 60;
const LANE_PAD = 56;
const LANE_HEADER = 56;

export default function DataFlowView({
  topology,
  onNodeClick,
  highlightId,
  onPaneClick,
}: Props) {
  const { nodes, edges } = useMemo(() => {
    const visibleNodes = topology.nodes.filter(
      (n) =>
        n.type === "agent" ||
        n.type === "mcp_instance" ||
        n.type === "openapi_connection" ||
        n.type === "skill" ||
        n.type === "trigger"
    );
    const nodeIds = new Set(visibleNodes.map((n) => n.id));
    const validEdges = topology.edges.filter(
      (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
    );

    const { positions, clusters } = layoutClusters(
      visibleNodes.map((n) => ({ id: n.id, type: n.type, label: n.label })),
      validEdges,
      {
        laneX: LANE_X,
        rowHeight: ROW_H,
        clusterGap: CLUSTER_GAP,
      }
    );

    const highlight = computeHighlightSets(highlightId, topology.edges);

    const flowNodes: Node[] = [];

    // Lane rails: span full vertical extent of the canvas, sized to the
    // bounding box of the nodes in that lane (plus padding).
    if (clusters.length > 0) {
      const totalYMin = clusters[0].yStart - LANE_HEADER;
      const totalYMax = clusters[clusters.length - 1].yEnd;
      const totalH = totalYMax - totalYMin + LANE_PAD;
      for (const lane of Object.keys(LANE_META) as Lane[]) {
        flowNodes.push({
          id: `lane-${lane}`,
          type: "lane",
          position: {
            x: LANE_X[lane] - NODE_HALF_W - LANE_PAD,
            y: totalYMin - LANE_PAD / 2,
          },
          data: { ...LANE_META[lane] },
          style: {
            width: NODE_HALF_W * 2 + LANE_PAD * 2,
            height: totalH,
          },
          selectable: false,
          draggable: false,
          zIndex: -2,
        });
      }
    }

    for (const n of visibleNodes) {
      const isHighlighted = !!highlight?.nodes.has(n.id);
      const isDimmed = !!highlight && !isHighlighted;
      flowNodes.push({
        id: n.id,
        type: n.type,
        position: positions[n.id] ?? { x: 0, y: 0 },
        data: {
          ...n,
          _dimmed: isDimmed,
          _highlighted: isHighlighted && n.id === highlightId,
        },
        zIndex: isHighlighted ? 2 : 1,
      });
    }

    const flowEdges: Edge[] = validEdges.map((e) => {
      const isHighlightedEdge = !!highlight?.edges.has(e.id);
      const isDimmedEdge = !!highlight && !isHighlightedEdge;
      // Visual flow: events → agents → external. The topology stores the
      // has_trigger edge as agent→trigger (ownership), but the data flow
      // is trigger→agent — swap endpoints so the arrow points the right way.
      const visualSource = e.relation === "has_trigger" ? e.target : e.source;
      const visualTarget = e.relation === "has_trigger" ? e.source : e.target;
      return {
        id: e.id,
        source: visualSource,
        target: visualTarget,
        type: "dataflow",
        data: {
          relation: e.relation,
          highlighted: isHighlightedEdge,
          dimmed: isDimmedEdge,
        },
        zIndex: isHighlightedEdge ? 2 : 0,
      };
    });

    return { nodes: flowNodes, edges: flowEdges };
  }, [topology, highlightId]);

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        nodesConnectable={false}
        elementsSelectable
        fitView
        fitViewOptions={{ padding: 0.18 }}
        minZoom={0.1}
        maxZoom={2}
        onPaneClick={onPaneClick}
        onNodeClick={(_, node) => {
          if (node.type === "lane") return;
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
