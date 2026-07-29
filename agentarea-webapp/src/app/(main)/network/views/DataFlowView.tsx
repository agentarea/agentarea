"use client";

import { useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import DataFlowEdge from "../components/edges/DataFlowEdge";
import LaneRail from "../components/LaneRail";
import AgentNode from "../components/nodes/AgentNode";
import MCPNode from "../components/nodes/MCPNode";
import OpenAPINode from "../components/nodes/OpenAPINode";
import SkillNode from "../components/nodes/SkillNode";
import TriggerNode from "../components/nodes/TriggerNode";
import type { NetworkNodeData, TopologyResponse } from "../types";
import { layoutClusters, type Lane } from "../utils/clusterLayout";
import { computeHighlightSets } from "../utils/highlight";

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

type LaneTone = "blue" | "neutral" | "rose";

const LANE_META: Record<
  Lane,
  { label: string; sublabel: string; tone: LaneTone; iconKey: Lane }
> = {
  events: {
    label: "Ingress",
    sublabel: "Events entering the workspace",
    tone: "blue",
    iconKey: "events",
  },
  agents: {
    label: "Agent fabric",
    sublabel: "Governed execution boundary",
    tone: "neutral",
    iconKey: "agents",
  },
  external: {
    label: "Capabilities",
    sublabel: "MCP, APIs and reusable skills",
    tone: "rose",
    iconKey: "external",
  },
};

const ROW_H = 144;
const CLUSTER_GAP = 80;
const NODE_HALF_W = 104;
const LANE_PAD = 64;
const LANE_HEADER = 76;

export default function DataFlowView({
  topology,
  onNodeClick,
  highlightId,
  onPaneClick,
}: Props) {
  const { nodes, edges, visibleCount } = useMemo(() => {
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

    return {
      nodes: flowNodes,
      edges: flowEdges,
      visibleCount: visibleNodes.length,
    };
  }, [topology, highlightId]);

  return (
    <div className="relative h-full w-full overflow-hidden bg-[#f4f7fb] dark:bg-zinc-950">
      <div
        className="pointer-events-none absolute inset-0 opacity-90 dark:opacity-20"
        style={{
          backgroundImage:
            "linear-gradient(rgba(148,163,184,0.10) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,0.10) 1px, transparent 1px)",
          backgroundSize: "24px 24px, 24px 24px",
        }}
      />
      <ReactFlow
        className="relative z-0 !bg-transparent"
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        nodesConnectable={false}
        elementsSelectable
        fitView
        fitViewOptions={{ padding: 0.08 }}
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
          gap={24}
          size={1}
          color="#cbd5e1"
          className="opacity-60 dark:opacity-20"
        />
        {visibleCount > 18 && (
          <MiniMap
            position="bottom-right"
            pannable
            zoomable
            nodeStrokeWidth={3}
            nodeColor={(node) => {
              if (node.type === "agent") return "#4f67e8";
              if (node.type === "trigger") return "#f0a53b";
              if (node.type === "lane") return "transparent";
              return "#18a37a";
            }}
            maskColor="rgba(244,247,251,0.72)"
            className="!right-3 !bottom-3 !h-[82px] !w-[132px] !rounded-lg !border !border-slate-200 !bg-white/90 !shadow-sm dark:!border-zinc-800 dark:!bg-zinc-950/90"
          />
        )}
        <Controls
          position="bottom-left"
          className="!bottom-3 !left-3 !overflow-hidden !rounded-lg !border !border-slate-200 !bg-white/90 !shadow-sm dark:!border-zinc-800 dark:!bg-zinc-950/90"
        />
      </ReactFlow>
    </div>
  );
}
